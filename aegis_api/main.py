"""Local WebSocket API for the AEGIS simulation engine."""

from __future__ import annotations

import asyncio
import json
import os
import secrets
import time
import urllib.error
import urllib.request
from dataclasses import dataclass, field
from typing import Literal

from fastapi import FastAPI, HTTPException, WebSocket, WebSocketDisconnect
from fastapi.middleware.cors import CORSMiddleware
from pydantic import BaseModel, Field

from aegis.building import BUILDING_PROFILES, build_generated_building, validate_building
from aegis.emergency import EMERGENCY_SERVICES, build_emergency_brief
from aegis.models import Person, SimulationState
from aegis.simulation import (
    HAZARD_OPTIONS,
    MOVEMENT_TICKS_PER_TRAVEL_UNIT,
    create_scenario,
    inject_sensor_alarm,
    set_running,
    step_simulation,
)


app = FastAPI(title="AEGIS Local Simulation API", version="0.2.0")
app.add_middleware(
    CORSMiddleware,
    allow_origins=["http://localhost:5173", "http://127.0.0.1:5173"],
    allow_origin_regex=(
        r"^http://(?:localhost|127\.0\.0\.1|10(?:\.\d{1,3}){3}|192\.168(?:\.\d{1,3}){2}|"
        r"172\.(?:1[6-9]|2\d|3[01])(?:\.\d{1,3}){2}):5173$"
    ),
    allow_credentials=False,
    allow_methods=["GET", "POST"],
    allow_headers=["Content-Type"],
)


@dataclass
class Runtime:
    state: SimulationState
    profile: str
    last_step_at: float = field(default_factory=time.monotonic)
    lock: asyncio.Lock = field(default_factory=asyncio.Lock)


sessions: dict[str, Runtime] = {}


class ScenarioRequest(BaseModel):
    person_count: int = Field(default=8, ge=1, le=20)
    seed: int | None = None
    incident_type: str = "Random incident"
    building_profile: str = "Office"
    floors: int | None = Field(default=None, ge=3, le=5)
    rooms_per_wing: int | None = Field(default=None, ge=2, le=6)


class CommandRequest(BaseModel):
    action: Literal["start", "pause", "step", "alarm"]
    sensor_id: str | None = None


class AIReviewRequest(BaseModel):
    session_id: str = Field(min_length=1, max_length=96)
    person_id: str = Field(min_length=1, max_length=32)


class EmergencyBriefRequest(BaseModel):
    site_address: str = Field(default="", max_length=500)
    callback_number: str = Field(default="", max_length=80)


def _runtime(session_id: str) -> Runtime:
    runtime = sessions.get(session_id)
    if runtime is None:
        raise HTTPException(status_code=404, detail="Scenario session not found")
    return runtime


def _ai_is_configured() -> bool:
    return bool(os.getenv("HF_TOKEN") and os.getenv("HF_MODEL"))


def _floor_name(floor: int) -> str:
    return "Ground" if floor == 0 else f"Floor {floor}"


def _assistance_diagnostics(state: SimulationState, person: Person) -> tuple[str | None, list[str]]:
    if person.status != "Needs Assistance":
        return None, []

    building = state.building
    current = building.nodes.get(person.current_node)
    if current is None:
        return "Current location is missing from the building graph; a route cannot be planned.", []

    def label(node_id: str) -> str:
        node = building.nodes[node_id]
        return f"{node.label} ({_floor_name(node.floor)})"

    def closure_cause(kind: str, target_id: str) -> str:
        for hazard in state.hazards:
            if (hazard.target_kind == kind and hazard.target_id == target_id) or (
                kind == "edge" and target_id in hazard.spread_edges
            ):
                return f"{hazard.incident_type} hazard"
        sensor = next((
            item for item in state.sensors
            if item.state == "Alarm" and item.target_kind == kind and item.target_id == target_id
        ), None)
        return "active sensor alarm" if sensor else "simulation closure"

    if current.id in state.blocked_nodes:
        blocker = f"{label(current.id)} is closed ({closure_cause('node', current.id)})"
        return f"No safe route can start from the person's current location. {blocker}.", [blocker]

    reachable = {current.id}
    pending = [current.id]
    blockers: set[str] = set()
    while pending:
        node_id = pending.pop()
        for neighbor, edge in building.neighbors(node_id):
            if edge.id in state.blocked_edges:
                blockers.add(
                    f"Passage {label(edge.a)} ↔ {label(edge.b)} is closed ({closure_cause('edge', edge.id)})"
                )
                continue
            if neighbor.id in state.blocked_nodes:
                blockers.add(
                    f"{label(neighbor.id)} is closed ({closure_cause('node', neighbor.id)})"
                )
                continue
            if neighbor.id not in reachable:
                reachable.add(neighbor.id)
                pending.append(neighbor.id)

    exits = {node_id for node_id, node in building.nodes.items() if node.kind == "exit"}
    if reachable & exits:
        return "A safe exit is connected now, but the person still needs a route update.", sorted(blockers)[:4]

    if blockers:
        details = "; ".join(sorted(blockers)[:3])
        return f"No open path from this location reaches an exit. Blocking points: {details}.", sorted(blockers)[:4]
    return "No connected safe path from this location to an exit is available in the current building graph.", []


def _snapshot(session_id: str, runtime: Runtime) -> dict:
    state = runtime.state
    floors = sorted({node.floor for node in state.building.nodes.values()})
    assistance_by_person = {
        person.id: _assistance_diagnostics(state, person)
        for person in state.people
        if person.status == "Needs Assistance"
    }
    return {
        "session_id": session_id,
        "seed": state.seed,
        "profile": runtime.profile,
        "tick": state.tick,
        "running": state.running,
        "rerouted_total": state.rerouted_total,
        "floors": [{"index": floor, "label": _floor_name(floor)} for floor in floors],
        "nodes": [
            {
                "id": node.id, "floor": node.floor, "x": node.x, "z": node.y,
                "kind": node.kind, "label": node.label, "exit_capacity": node.exit_capacity,
                "blocked": node.id in state.blocked_nodes,
                "caution": node.id in state.caution_nodes,
            }
            for node in state.building.nodes.values()
        ],
        "edges": [
            {
                "id": edge.id, "a": edge.a, "b": edge.b, "travel_time": edge.travel_time,
                "width_m": edge.width_m, "capacity": edge.capacity_per_step,
                "is_stair": edge.is_stair, "is_narrow": edge.is_narrow,
                "blocked": edge.id in state.blocked_edges,
                "caution": edge.id in state.caution_edges,
            }
            for edge in state.building.edges.values()
        ],
        "people": [
            {
                "id": person.id, "start_node": person.start_node,
                "current_node": person.current_node, "status": person.status,
                "priority": round(person.priority_score, 3), "route": list(person.route),
                "route_edges": list(person.route_edges), "assigned_exit": person.assigned_exit,
                "traversed_edges": list(person.traversed_edges),
                "reroutes": person.reroutes, "queued_edge": person.queued_edge,
                "movement_progress": person.movement_progress,
                "backtracking": person.backtracking,
                "assistance_reason": assistance_by_person.get(person.id, (None, []))[0],
                "assistance_blockers": assistance_by_person.get(person.id, (None, []))[1],
            }
            for person in state.people
        ],
        "sensors": [
            {
                "id": sensor.id, "target_id": sensor.target_id,
                "target_kind": sensor.target_kind, "metric": sensor.metric,
                "reading": sensor.reading, "unit": sensor.unit,
                "state": sensor.state, "label": sensor.label,
            }
            for sensor in state.sensors
        ],
        "hazards": [
            {
                "id": hazard.id, "incident_type": hazard.incident_type,
                "target_id": hazard.target_id, "target_kind": hazard.target_kind,
                "intensity": hazard.intensity, "level": hazard.level,
            }
            for hazard in state.hazards
        ],
        "events": [
            {"tick": event.tick, "kind": event.kind, "message": event.message}
            for event in state.event_log[-40:]
        ],
        "movement_ticks_per_unit": MOVEMENT_TICKS_PER_TRAVEL_UNIT,
    }


@app.get("/api/health")
def health() -> dict:
    return {"status": "ok", "ai_configured": _ai_is_configured()}


@app.get("/api/config")
def config() -> dict:
    return {
        "profiles": list(BUILDING_PROFILES),
        "incident_types": list(HAZARD_OPTIONS),
        "services": list(EMERGENCY_SERVICES),
        "ai_configured": _ai_is_configured(),
        "ai_provider": "Hugging Face Inference Providers",
    }


@app.post("/api/scenarios")
def create_session(request: ScenarioRequest) -> dict:
    if request.building_profile not in BUILDING_PROFILES:
        raise HTTPException(status_code=422, detail="Unknown building profile")
    if request.incident_type not in HAZARD_OPTIONS:
        raise HTTPException(status_code=422, detail="Unknown incident type")
    seed = request.seed if request.seed is not None else secrets.randbelow(2**31 - 1) + 1
    building = build_generated_building(
        seed, request.building_profile,
        floor_count=request.floors,
        rooms_per_wing=request.rooms_per_wing,
    )
    errors = validate_building(building)
    if errors:
        raise HTTPException(status_code=500, detail={"building_validation": errors})
    state = create_scenario(
        request.person_count, seed, request.incident_type, building=building,
    )
    session_id = secrets.token_urlsafe(12)
    runtime = Runtime(state=state, profile=request.building_profile)
    sessions[session_id] = runtime
    return _snapshot(session_id, runtime)


@app.get("/api/scenarios/{session_id}")
async def get_session(session_id: str) -> dict:
    runtime = _runtime(session_id)
    async with runtime.lock:
        return _snapshot(session_id, runtime)


@app.post("/api/scenarios/{session_id}/command")
async def command(session_id: str, request: CommandRequest) -> dict:
    runtime = _runtime(session_id)
    async with runtime.lock:
        state = runtime.state
        if request.action == "start":
            set_running(state, True)
            runtime.last_step_at = time.monotonic()
        elif request.action == "pause":
            set_running(state, False)
        elif request.action == "step":
            if state.running:
                raise HTTPException(status_code=409, detail="Pause before stepping one beat")
            step_simulation(state)
        elif request.action == "alarm":
            if not request.sensor_id:
                raise HTTPException(status_code=422, detail="sensor_id is required for an alarm")
            if not inject_sensor_alarm(state, request.sensor_id):
                raise HTTPException(status_code=409, detail="That sensor is already active or unavailable")
        return _snapshot(session_id, runtime)


@app.post("/api/scenarios/{session_id}/emergency-brief")
async def emergency_brief(session_id: str, request: EmergencyBriefRequest) -> dict:
    runtime = _runtime(session_id)
    async with runtime.lock:
        return {
            "draft_only": True,
            "sent": False,
            "text": build_emergency_brief(
                runtime.state,
                profile=runtime.profile,
                site_address=request.site_address,
                callback_number=request.callback_number,
            ),
        }


def _ai_review_context(runtime: Runtime, person_id: str) -> dict:
    state = runtime.state
    person = next((item for item in state.people if item.id == person_id), None)
    if person is None:
        raise HTTPException(status_code=404, detail="Selected person is not in this simulation")

    def node_label(node_id: str | None) -> str:
        node = state.building.nodes.get(node_id or "")
        return f"{node.label} ({_floor_name(node.floor)})" if node else (node_id or "Unknown location")

    def edge_label(edge_id: str) -> str:
        edge = state.building.edges.get(edge_id)
        if edge is None:
            return edge_id
        return f"{node_label(edge.a)} to {node_label(edge.b)}"

    facts: list[dict[str, str]] = []

    def add_fact(fact_id: str, statement: str) -> None:
        facts.append({"id": fact_id, "statement": statement})

    status_names = ("Waiting", "Moving", "Queued", "Needs Assistance", "Evacuated")
    counts = {name: sum(person.status == name for person in state.people) for name in status_names}
    for status, count in counts.items():
        add_fact(f"people:{status.lower().replace(' ', '-')}", f"{count} people are {status.lower()}.")

    hazards = []
    for hazard in state.hazards:
        location = node_label(hazard.target_id) if hazard.target_kind == "node" else edge_label(hazard.target_id)
        hazards.append({
            "id": hazard.id,
            "type": hazard.incident_type,
            "location": location,
            "intensity": round(hazard.intensity),
            "level": hazard.level,
        })
        add_fact(
            f"hazard:{hazard.id}",
            f"{hazard.id} is a simulated {hazard.incident_type} at {location}, intensity {round(hazard.intensity)}/100 ({hazard.level}).",
        )

    blocked_passages = []
    for edge_id in sorted(state.blocked_edges)[:8]:
        label = edge_label(edge_id)
        blocked_passages.append({"id": edge_id, "label": label})
        add_fact(f"blocked:{edge_id}", f"Passage {label} is blocked.")
    blocked_locations = []
    for node_id in sorted(state.blocked_nodes)[:8]:
        label = node_label(node_id)
        blocked_locations.append({"id": node_id, "label": label})
        add_fact(f"blocked-node:{node_id}", f"Location {label} is blocked.")

    caution_areas = []
    for edge_id in sorted(state.caution_edges)[:8]:
        label = edge_label(edge_id)
        caution_areas.append({"id": edge_id, "label": label})
        add_fact(f"caution:{edge_id}", f"Passage {label} is marked caution.")
    for node_id in sorted(state.caution_nodes)[:8]:
        label = node_label(node_id)
        caution_areas.append({"id": node_id, "label": label})
        add_fact(f"caution-node:{node_id}", f"Location {label} is marked caution.")

    queued: dict[str, list[str]] = {}
    for current_person in state.people:
        if current_person.status == "Queued" and current_person.queued_edge:
            queued.setdefault(current_person.queued_edge, []).append(current_person.id)
    queues = []
    for edge_id, waiting_people in sorted(queued.items(), key=lambda item: (-len(item[1]), item[0]))[:6]:
        label = edge_label(edge_id)
        queues.append({"passage": label, "people_waiting": len(waiting_people)})
        add_fact(f"queue:{edge_id}", f"{len(waiting_people)} people are queued at {label}.")

    assistance = [item for item in state.people if item.status == "Needs Assistance"]
    for assisted in assistance[:8]:
        add_fact(f"assistance:{assisted.id}", f"{assisted.id} needs assistance at {node_label(assisted.current_node)}.")

    alarms = [sensor for sensor in state.sensors if sensor.state == "Alarm"]
    for sensor in alarms[:8]:
        add_fact(f"alarm:{sensor.id}", f"Sensor {sensor.id} reports an alarm: {sensor.label} ({sensor.metric} {sensor.reading:g} {sensor.unit}).")

    route = [node_label(node_id) for node_id in person.route[:8]]
    selected_person = {
        "id": person.id,
        "status": person.status,
        "location": node_label(person.current_node),
        "assigned_exit": node_label(person.assigned_exit),
        "remaining_route": route,
        "progress_percent": round(person.movement_progress * 100),
        "reroutes": person.reroutes,
        "backtracking": person.backtracking,
    }
    add_fact(
        f"person:{person.id}",
        f"Selected person {person.id} is {person.status} at {selected_person['location']}, assigned exit {selected_person['assigned_exit']}, "
        f"progress {selected_person['progress_percent']}%, reroutes {person.reroutes}, "
        f"backtracking {str(person.backtracking).lower()}, remaining route: {' -> '.join(route) or 'none'}.",
    )
    add_fact("scenario:reroutes", f"The routing engine has recorded {state.rerouted_total} reroutes so far.")

    relevant_events = [
        event for event in state.event_log[-8:]
        if event.kind in {"reroute", "queue", "congestion", "assistance", "sensor", "hazard"}
    ]
    recent_events = []
    for index, event in enumerate(relevant_events):
        fact_id = f"event:{event.tick}:{event.kind}:{index}"
        message = event.message[:180]
        recent_events.append({"fact_id": fact_id, "tick": event.tick, "kind": event.kind, "message": message})
        add_fact(fact_id, f"At tick {event.tick}, {event.kind}: {message}")
    return {
        "source": "synthetic AEGIS simulation state; no real building, address, or contact data",
        "scenario": {
            "profile": runtime.profile,
            "seed": state.seed,
            "tick": state.tick,
            "running": state.running,
            "total_reroutes": state.rerouted_total,
        },
        "people_by_status": counts,
        "selected_person": selected_person,
        "hazards": hazards,
        "blocked_passages": blocked_passages,
        "blocked_locations": blocked_locations,
        "caution_areas": caution_areas,
        "queues": queues,
        "people_needing_assistance": len(assistance),
        "active_sensor_alarms": len(alarms),
        "recent_relevant_events": recent_events,
        "facts": facts,
    }


def _call_huggingface_review(token: str, model: str, context: dict) -> dict:
    payload = {
        "model": model,
        "messages": [
            {
                "role": "system",
                "content": (
                    "You review a synthetic evacuation simulation for its operator. Do not give real-world emergency advice, "
                    "change routes, or claim the model controlled the simulation. Analyze only the supplied JSON. "
                    "Return JSON with exactly two arrays: observations and operator_checks. Each array item must be an object "
                    "with text (under 220 characters) and evidence (one or more exact fact IDs copied from the supplied facts). "
                    "Return 1-3 concise observations and 1-3 checks. Every item must cite relevant supplied evidence; never invent IDs or facts. "
                    "If the snapshot has no meaningful issue, say so and cite the relevant count or status fact."
                ),
            },
            {"role": "user", "content": json.dumps(context, ensure_ascii=True)},
        ],
        "max_tokens": 500,
        "temperature": 0.1,
        "response_format": {"type": "json_object"},
    }
    request = urllib.request.Request(
        "https://router.huggingface.co/v1/chat/completions",
        data=json.dumps(payload).encode("utf-8"),
        headers={
            "Authorization": f"Bearer {token}",
            "Content-Type": "application/json",
        },
        method="POST",
    )
    try:
        with urllib.request.urlopen(request, timeout=45) as response:
            completion = json.loads(response.read().decode("utf-8"))
    except urllib.error.HTTPError as exc:
        detail = exc.read().decode("utf-8", errors="replace")[:500]
        raise RuntimeError(f"Hugging Face returned HTTP {exc.code}: {detail}") from exc
    except urllib.error.URLError as exc:
        raise RuntimeError(f"Could not reach Hugging Face Inference Providers: {exc.reason}") from exc

    choices = completion.get("choices")
    if not isinstance(choices, list) or not choices or not isinstance(choices[0], dict):
        raise ValueError("Hugging Face response did not contain a chat completion")
    message = choices[0].get("message")
    content = message.get("content") if isinstance(message, dict) else None
    if not isinstance(content, str) or not content:
        raise ValueError("Hugging Face response did not contain message text")
    start, end = content.find("{"), content.rfind("}")
    if start < 0 or end <= start:
        raise ValueError("Model response did not contain JSON")
    return json.loads(content[start:end + 1])


def _validated_ai_items(items: object, fact_labels: dict[str, str]) -> list[dict]:
    if not isinstance(items, list):
        return []
    result = []
    for item in items[:3]:
        if not isinstance(item, dict):
            continue
        text = str(item.get("text", "")).strip()[:220]
        raw_evidence = item.get("evidence", [])
        if not text or not isinstance(raw_evidence, list):
            continue
        evidence_ids = list(dict.fromkeys(str(value) for value in raw_evidence if str(value) in fact_labels))[:3]
        if not evidence_ids:
            continue
        result.append({
            "text": text,
            "evidence": [{"id": fact_id, "label": fact_labels[fact_id]} for fact_id in evidence_ids],
        })
    return result


@app.post("/api/ai/evacuation-review")
async def ai_evacuation_review(request: AIReviewRequest) -> dict:
    token = os.getenv("HF_TOKEN")
    model = os.getenv("HF_MODEL")
    if not _ai_is_configured():
        raise HTTPException(
            status_code=503,
            detail="AI review is not active. Configure HF_TOKEN and HF_MODEL in the local API terminal first.",
        )
    runtime = _runtime(request.session_id)
    async with runtime.lock:
        context = _ai_review_context(runtime, request.person_id)

    try:
        raw_review = await asyncio.to_thread(_call_huggingface_review, token, model, context)
        facts = {fact["id"]: fact["statement"] for fact in context["facts"]}
        observations = _validated_ai_items(raw_review.get("observations"), facts)
        checks = _validated_ai_items(raw_review.get("operator_checks"), facts)
        if not observations:
            raise ValueError("Model response had no evidence-linked observations")
        return {
            "provider": "Hugging Face Inference Providers",
            "model": model,
            "tick": context["scenario"]["tick"],
            "person_id": request.person_id,
            "observations": observations,
            "operator_checks": checks,
            "evidence_mode": "only supplied simulation facts are accepted",
        }
    except HTTPException:
        raise
    except Exception as exc:
        raise HTTPException(
            status_code=502,
            detail=f"AI review failed ({type(exc).__name__}). Check the selected Hugging Face model/provider and token permissions.",
        ) from exc


@app.websocket("/api/scenarios/{session_id}/stream")
async def stream_session(websocket: WebSocket, session_id: str) -> None:
    runtime = sessions.get(session_id)
    if runtime is None:
        await websocket.close(code=4404, reason="Scenario session not found")
        return
    await websocket.accept()
    last_sent_tick: int | None = None
    try:
        while True:
            now = time.monotonic()
            if runtime.state.running and now - runtime.last_step_at >= 1.0:
                async with runtime.lock:
                    now = time.monotonic()
                    if runtime.state.running and now - runtime.last_step_at >= 1.0:
                        step_simulation(runtime.state)
                        runtime.last_step_at = now
            if runtime.state.tick != last_sent_tick:
                await websocket.send_json(_snapshot(session_id, runtime))
                last_sent_tick = runtime.state.tick
            await asyncio.sleep(0.1 if runtime.state.running else 0.5)
    except WebSocketDisconnect:
        return
