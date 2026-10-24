"""Seeded scenarios, shared group routing, movement, and event history."""

from __future__ import annotations

import random
import secrets
import math
from collections import Counter
import heapq

from aegis.building import build_sample_building
from aegis.models import (
    INCLUSIVE_DEMO_PROFILES,
    PERSON_PROFILE_SPECS,
    Building,
    Event,
    Hazard,
    Person,
    SimulationState,
)
from aegis.routing import Route, find_route
from aegis.sensors import (
    create_sensor_network,
    metric_for_incident,
    reading_for_hazard,
    state_for_reading,
)


MAX_EVENTS = 200
MOVEMENT_TICKS_PER_TRAVEL_UNIT = 12
RANDOM_INCIDENT = "Random incident"
INCIDENT_TYPES = ("Fire / smoke", "Gas leak", "Blocked passage", "Earthquake")
HAZARD_OPTIONS = (RANDOM_INCIDENT, *INCIDENT_TYPES)
INTENSITY_STAGE_THRESHOLDS = (35.0, 60.0, 85.0)
ACTIVE_STATUSES = {"Waiting", "Moving", "Queued", "Needs Assistance"}


def _movement_ticks_for_edge(person: Person, edge) -> int:
    speed = PERSON_PROFILE_SPECS[person.accessibility_profile].movement_speed_factor
    return max(
        MOVEMENT_TICKS_PER_TRAVEL_UNIT,
        int(math.ceil(edge.travel_time * MOVEMENT_TICKS_PER_TRAVEL_UNIT / speed)),
    )


def log_event(state: SimulationState, kind: str, message: str) -> None:
    state.event_log.append(Event(state.tick, kind, message))
    if len(state.event_log) > MAX_EVENTS:
        del state.event_log[: len(state.event_log) - MAX_EVENTS]


def _hazard_distance(state: SimulationState, start: str) -> float:
    targets: list[str] = []
    for hazard in state.hazards:
        if hazard.target_kind == "node":
            targets.append(hazard.target_id)
        else:
            edge = state.building.edges[hazard.target_id]
            targets.extend((edge.a, edge.b))
    if not targets:
        return 1_000_000.0
    distances = {start: 0.0}
    queue = [(0.0, start)]
    target_set = set(targets)
    while queue:
        distance, node_id = heapq.heappop(queue)
        if distance != distances.get(node_id):
            continue
        if node_id in target_set:
            return distance
        for neighbor, edge in state.building.neighbors(node_id):
            candidate = distance + edge.travel_time
            if candidate < distances.get(neighbor.id, float("inf")):
                distances[neighbor.id] = candidate
                heapq.heappush(queue, (candidate, neighbor.id))
    return 1_000_000.0


def _refresh_priorities(state: SimulationState) -> None:
    for person in state.people:
        distance = _hazard_distance(state, person.current_node)
        profile = PERSON_PROFILE_SPECS[person.accessibility_profile]
        person.priority_score = profile.priority_bonus + 1.0 / (0.5 + distance)


def _route_for_person(
    state: SimulationState,
    person: Person,
    start: str,
    edge_load: Counter,
    exit_load: Counter,
) -> Route | None:
    return find_route(
        state.building,
        start,
        blocked_nodes=state.blocked_nodes,
        blocked_edges=state.blocked_edges,
        caution_nodes=state.caution_nodes,
        caution_edges=state.caution_edges,
        edge_load=edge_load,
        exit_load=exit_load,
        person_profile=person.accessibility_profile,
    )


def _spread_stage(intensity: float) -> int:
    return sum(intensity >= threshold for threshold in INTENSITY_STAGE_THRESHOLDS)


def _hazard_seed_nodes(state: SimulationState, hazard: Hazard) -> set[str]:
    if hazard.target_kind == "node":
        return {hazard.target_id}
    edge = state.building.edges[hazard.target_id]
    return {edge.a, edge.b}


def _apply_hazard_footprint(state: SimulationState, hazard: Hazard) -> None:
    """Expand a synthetic hazard footprint at its current intensity stage."""
    seeds = _hazard_seed_nodes(state, hazard)
    if hazard.target_kind == "node":
        state.blocked_nodes.add(hazard.target_id)
    else:
        state.blocked_edges.add(hazard.target_id)

    for node_id in seeds:
        for neighbor, _edge in state.building.neighbors(node_id):
            if neighbor.kind != "exit" and neighbor.id not in state.blocked_nodes:
                state.caution_nodes.add(neighbor.id)

    stage = _spread_stage(hazard.intensity)
    if stage >= 1:
        distances = {node_id: 0 for node_id in seeds}
        pending = list(sorted(seeds))
        while pending:
            node_id = pending.pop(0)
            if distances[node_id] >= 2:
                continue
            for neighbor, _edge in state.building.neighbors(node_id):
                if neighbor.id not in distances:
                    distances[neighbor.id] = distances[node_id] + 1
                    pending.append(neighbor.id)
        for node_id, distance in distances.items():
            node = state.building.nodes[node_id]
            if distance == 2 and node.kind != "exit" and node_id not in state.blocked_nodes:
                state.caution_nodes.add(node_id)

    hazard.spread_stage = stage
    if stage >= 2:
        # Close more nearby horizontal passages as the simulated intensity rises.
        candidate_edges = []
        region = {node_id for node_id, distance in distances.items() if distance <= 2} if stage >= 1 else seeds
        for edge in state.building.edges.values():
            if edge.id == hazard.target_id or edge.is_stair or edge.id in hazard.spread_edges:
                continue
            if state.building.nodes[edge.a].kind == "exit" or state.building.nodes[edge.b].kind == "exit":
                continue
            if edge.a in region or edge.b in region:
                candidate_edges.append(edge.id)
        candidate_edges.sort()
        needed = max(0, stage - 1 - len(hazard.spread_edges))
        added = 0
        if needed:
            for edge_id in candidate_edges:
                if edge_id in state.blocked_edges:
                    continue
                state.blocked_edges.add(edge_id)
                hazard.spread_edges.append(edge_id)
                added += 1
                if added >= needed:
                    break


def _update_hazard_sensor(state: SimulationState, hazard: Hazard) -> str | None:
    metric, unit, _threshold = metric_for_incident(hazard.incident_type)
    sensor = next((
        item for item in state.sensors
        if item.target_id == hazard.target_id and item.target_kind == hazard.target_kind
    ), None)
    if sensor is None:
        return None
    previous_state = sensor.state
    sensor.metric = metric
    sensor.unit = unit
    sensor.reading = reading_for_hazard(metric, hazard.intensity)
    sensor.state = state_for_reading(metric, sensor.reading)
    return sensor.id if previous_state != sensor.state else None


def _advance_hazards(state: SimulationState) -> bool:
    """Grow intensities and expand impacted areas at deterministic stage changes."""
    expanded = False
    for hazard in state.hazards:
        old_stage = hazard.spread_stage
        hazard.intensity = min(100.0, hazard.intensity + hazard.growth_per_tick)
        new_stage = _spread_stage(hazard.intensity)
        sensor_state_changed = _update_hazard_sensor(state, hazard)
        if new_stage > old_stage:
            _apply_hazard_footprint(state, hazard)
            log_event(
                state,
                "hazard",
                f"{hazard.incident_type} intensity increased to {hazard.intensity:.0f}/100 "
                f"({hazard.level}); affected area expanded.",
            )
            expanded = True
        if sensor_state_changed:
            sensor = next(item for item in state.sensors if item.id == sensor_state_changed)
            log_event(state, "sensor", f"{sensor.id}: {sensor.metric} entered {sensor.state.lower()} as intensity rose.")
    return expanded


def assign_group_routes(
    state: SimulationState,
    *,
    reason: str = "initial assignment",
    congestion_bias: Counter | None = None,
) -> None:
    """Plan in urgency order, reserving each planned corridor and exit."""
    _refresh_priorities(state)
    edge_load: Counter = Counter(congestion_bias or {})
    exit_load: Counter = Counter()
    people = sorted(
        (person for person in state.people if person.status in ACTIVE_STATUSES),
        key=lambda person: (-person.priority_score, person.id),
    )
    for person in people:
        previous_route = tuple(person.route)
        previous_edges = tuple(person.route_edges)
        was_assigned = bool(previous_route or person.assigned_exit)
        in_flight = (
            person.movement_progress > 0.0
            and len(person.route) > 1
            and bool(person.route_edges)
            and person.route[0] == person.current_node
        )
        current_edge_id = person.route_edges[0] if in_flight else None
        next_node = person.route[1] if in_flight else None

        if in_flight and next_node in state.blocked_nodes:
            if not person.backtracking:
                log_event(
                    state,
                    "reroute",
                    f"{person.id}: {next_node} closed while they were in the passage; turning back to {person.current_node}.",
                )
            person.backtracking = True
            person.queued_edge = None
            person.status = "Moving" if state.running else "Waiting"
            for edge_id in person.route_edges:
                edge_load[edge_id] += 1
            if person.assigned_exit:
                exit_load[person.assigned_exit] += 1
            continue

        # If a person is already on a passage, keep that segment as a fixed
        # prefix and plan the new route from its far end. This prevents a
        # closure or second alarm from moving them back to the previous node.
        plan_start = next_node if in_flight else person.current_node
        route = _route_for_person(state, person, plan_start, edge_load, exit_load)
        if route is None:
            if in_flight:
                person.route = [person.current_node, next_node]
                person.route_edges = [current_edge_id]
                person.assigned_exit = None
                person.queued_edge = None
                person.status = "Moving" if state.running else "Waiting"
                log_event(
                    state,
                    "assistance",
                    f"{person.id}: no safe continuation from {next_node}; finishing the occupied passage first.",
                )
                edge_load[current_edge_id] += 1
                continue
            person.route = []
            person.route_edges = []
            person.movement_progress = 0.0
            person.backtracking = False
            person.assigned_exit = None
            if person.status != "Needs Assistance":
                log_event(state, "assistance", f"{person.id}: no safe route is available; assistance needed.")
            person.status = "Needs Assistance"
            person.queued_edge = None
            continue

        new_route = (person.current_node, *route.nodes) if in_flight else route.nodes
        new_edges = (current_edge_id, *route.edges) if in_flight else route.edges
        changed = was_assigned and (
            new_route != previous_route
            or new_edges != previous_edges
            or route.exit_id != person.assigned_exit
            or (in_flight and current_edge_id in state.blocked_edges)
        )
        if changed and not in_flight:
            person.movement_progress = 0.0
        person.route = list(new_route)
        person.route_edges = list(new_edges)
        person.assigned_exit = route.exit_id
        person.queued_edge = None
        person.backtracking = False
        if state.running:
            person.status = "Moving"
        else:
            person.status = "Waiting"

        if changed:
            person.reroutes += 1
            state.rerouted_total += 1
            if in_flight:
                message = f"{person.id}: route recalculated after {reason}; continuing to {next_node}, then taking the route to {route.exit_id}."
            else:
                message = f"{person.id}: route recalculated after {reason}; now assigned to {route.exit_id}."
            log_event(state, "reroute", message)
        elif not was_assigned:
            log_event(state, "route", f"{person.id}: safe route assigned to {route.exit_id} (priority {person.priority_score:.2f}).")

        for edge_id in new_edges:
            edge_load[edge_id] += 1
        exit_load[route.exit_id] += 1
    state.last_replan_tick = state.tick


def create_scenario(
    person_count: int = 8,
    seed: int | None = None,
    incident_type: str | None = None,
    *,
    building: Building | None = None,
    include_accessibility_personas: bool = False,
) -> SimulationState:
    if not 1 <= person_count <= 20:
        raise ValueError("person_count must be between 1 and 20")
    scenario_seed = secrets.randbelow(2**31 - 1) + 1 if seed is None else int(seed)
    rng = random.Random(scenario_seed)
    building = building or build_sample_building()
    state = SimulationState(building=building, seed=scenario_seed)

    if incident_type in (None, RANDOM_INCIDENT):
        selected_incident = rng.choice(INCIDENT_TYPES)
    elif incident_type in INCIDENT_TYPES:
        selected_incident = incident_type
    else:
        raise ValueError(f"incident_type must be one of {', '.join(HAZARD_OPTIONS)}")

    intensity = float(rng.randint(12, 22))
    growth_per_tick = float(rng.randint(2, 4))
    if selected_incident in {"Blocked passage", "Earthquake"}:
        candidates = [
            edge for edge in building.edges.values()
            if not edge.is_stair and "EXIT" not in edge.id
        ]
        if selected_incident == "Earthquake" and rng.choice((True, False)):
            node_candidates = [node for node in building.nodes.values() if node.kind == "junction"]
            target_node = rng.choice(sorted(node_candidates, key=lambda node: node.id))
            hazard = Hazard(
                "H1", selected_incident, target_node.id, "node", "block",
                f"Simulated ground movement affects {target_node.label}.", intensity, growth_per_tick,
            )
        else:
            target_edge = rng.choice(sorted(candidates, key=lambda edge: edge.id))
            description = (
                f"Simulated earthquake damage affects passage {target_edge.id}."
                if selected_incident == "Earthquake"
                else f"Simulated obstruction closes passage {target_edge.id}."
            )
            hazard = Hazard(
                "H1", selected_incident, target_edge.id, "edge", "block",
                description, intensity, growth_per_tick,
            )
    else:
        candidates = [node for node in building.nodes.values() if node.kind == "room"]
        target_node = rng.choice(sorted(candidates, key=lambda node: node.id))
        hazard = Hazard(
            "H1", selected_incident, target_node.id, "node", "block",
            f"Simulated {selected_incident.lower()} affects {target_node.label}.",
            intensity, growth_per_tick,
        )
    state.hazards.append(hazard)
    _apply_hazard_footprint(state, hazard)
    state.sensors = create_sensor_network(building, rng, state.hazards)

    safe_rooms_by_floor = {
        floor: [
            node for node in building.nodes.values()
            if node.kind == "room" and node.floor == floor and node.id not in state.blocked_nodes
        ]
        for floor in sorted({node.floor for node in building.nodes.values()})
    }
    for rooms in safe_rooms_by_floor.values():
        rng.shuffle(rooms)
    floor_order = list(safe_rooms_by_floor)
    rng.shuffle(floor_order)

    # Interleave floors so small groups are not accidentally placed together.
    safe_rooms: list = []
    while any(safe_rooms_by_floor.values()):
        for floor in floor_order:
            if safe_rooms_by_floor[floor]:
                safe_rooms.append(safe_rooms_by_floor[floor].pop())

    for index in range(person_count):
        node = safe_rooms[index]
        person_id = f"P{index + 1:02d}"
        accessibility_profile = (
            INCLUSIVE_DEMO_PROFILES[index % len(INCLUSIVE_DEMO_PROFILES)]
            if include_accessibility_personas and index < len(INCLUSIVE_DEMO_PROFILES)
            else "Standard"
        )
        state.people.append(Person(
            person_id, node.id, node.id,
            accessibility_profile=accessibility_profile,
        ))

    log_event(
        state, "scenario",
        f"New seeded scenario created (seed {scenario_seed}); {selected_incident} incident detected "
        f"at intensity {hazard.intensity:.0f}/100.",
    )
    for sensor in state.sensors:
        if sensor.state == "Alarm":
            log_event(state, "sensor", f"{sensor.id}: {sensor.metric} {sensor.reading:g} {sensor.unit} — ALARM.")
    assign_group_routes(state)
    return state


def set_running(state: SimulationState, running: bool) -> None:
    state.running = running
    if running:
        for person in state.people:
            if person.status == "Waiting":
                person.status = "Moving"
        log_event(state, "control", "Evacuation simulation started.")
    else:
        for person in state.people:
            if person.status == "Moving":
                person.status = "Waiting"
        log_event(state, "control", "Evacuation simulation paused.")


def inject_sensor_alarm(state: SimulationState, sensor_id: str) -> bool:
    """Promote a normal/warning simulated sensor into a route-changing alarm."""
    sensor = next((item for item in state.sensors if item.id == sensor_id), None)
    if sensor is None or sensor.state == "Alarm":
        return False
    if any(
        hazard.target_id == sensor.target_id and hazard.target_kind == sensor.target_kind
        for hazard in state.hazards
    ):
        return False
    if sensor.target_kind == "node" and sensor.target_id in state.blocked_nodes:
        return False
    if sensor.target_kind == "edge" and sensor.target_id in state.blocked_edges:
        return False
    incident_by_metric = {
        "smoke": "Fire / smoke",
        "gas": "Gas leak",
        "heat": "Fire / smoke",
        "obstruction": "Blocked passage",
        "ground_motion": "Earthquake",
    }
    incident_type = incident_by_metric[sensor.metric]
    alarm_thresholds = {
        "smoke": (65.0, "ppm"),
        "gas": (40.0, "%"),
        "heat": (60.0, "°C"),
        "obstruction": (60.0, "%"),
        "ground_motion": (65.0, "index"),
    }
    threshold, unit = alarm_thresholds[sensor.metric]
    sensor.reading = round(threshold + 12.0, 1)
    sensor.unit = unit
    sensor.state = "Alarm"
    hazard = Hazard(
        f"H{len(state.hazards) + 1}", incident_type, sensor.target_id,
        sensor.target_kind, "block", f"Simulated sensor alarm at {sensor.label}.", 70.0, 3.0,
    )
    state.hazards.append(hazard)
    _apply_hazard_footprint(state, hazard)
    log_event(state, "sensor", f"{sensor.id}: {sensor.metric} {sensor.reading:g} {sensor.unit} — ALARM; routes recalculated.")
    assign_group_routes(state, reason="sensor alarm")
    return True


def _path_is_open(state: SimulationState, person: Person) -> bool:
    if not person.route or not person.route_edges:
        return False
    edge_id = person.route_edges[0]
    next_node = person.route[1] if len(person.route) > 1 else None
    if person.movement_progress > 0.0 and next_node is not None and next_node not in state.blocked_nodes:
        # Existing occupants can clear a newly closed passage if the far end is safe.
        return True
    return (
        edge_id not in state.blocked_edges
        and next_node is not None
        and next_node not in state.blocked_nodes
    )


def step_simulation(state: SimulationState) -> None:
    """Advance walkers gradually along an edge, respecting entry and exit capacity."""
    state.tick += 1
    if _advance_hazards(state):
        assign_group_routes(state, reason="hazard intensity increased")
    edge_use: Counter = Counter()
    exit_use: Counter = Counter()
    must_replan = False
    active = sorted(
        (person for person in state.people if person.status in {"Moving", "Queued", "Waiting"}),
        key=lambda person: (-person.priority_score, person.id),
    )

    for person in active:
        if not person.route or len(person.route) < 2 or not person.route_edges:
            if person.current_node in state.building.nodes and state.building.nodes[person.current_node].kind == "exit":
                person.status = "Evacuated"
            else:
                must_replan = True
            continue

        if person.backtracking:
            edge = state.building.edges[person.route_edges[0]]
            ticks_for_edge = _movement_ticks_for_edge(person, edge)
            person.movement_progress = max(0.0, person.movement_progress - 1.0 / ticks_for_edge)
            if person.movement_progress <= 1e-9:
                person.movement_progress = 0.0
                person.backtracking = False
                person.status = "Moving" if state.running else "Waiting"
                must_replan = True
                log_event(state, "reroute", f"{person.id}: back at {person.current_node}; planning a safe route again.")
            else:
                person.status = "Moving" if state.running else "Waiting"
            continue

        if not _path_is_open(state, person):
            must_replan = True
            continue

        edge_id = person.route_edges[0]
        next_node = person.route[1]
        edge = state.building.edges[edge_id]
        at_exit = state.building.nodes[next_node].kind == "exit"
        was_queued_on_edge = person.status == "Queued" and person.queued_edge == edge_id
        entering_edge = person.movement_progress <= 0.0
        if entering_edge and edge_use[edge_id] >= edge.capacity_per_step:
            person.status = "Queued"
            person.queued_edge = edge_id
            person.queued_ticks += 1
            if not was_queued_on_edge:
                log_event(state, "queue", f"{person.id}: waiting for capacity on {edge_id}.")
            continue

        if entering_edge:
            edge_use[edge_id] += 1
        person.queued_edge = None
        # One beat is one wall-clock second in the app. Corridors take about
        # 12–15 seconds; stair links take about 24 seconds.
        ticks_for_edge = _movement_ticks_for_edge(person, edge)
        person.movement_progress = min(1.0, person.movement_progress + 1.0 / ticks_for_edge)
        if person.movement_progress < 1.0 - 1e-9:
            person.status = "Moving"
            continue
        person.movement_progress = 1.0

        if at_exit and exit_use[next_node] >= state.building.nodes[next_node].exit_capacity:
            person.movement_progress = 0.99
            person.status = "Queued"
            person.queued_edge = edge_id
            person.queued_ticks += 1
            if not was_queued_on_edge:
                log_event(state, "queue", f"{person.id}: waiting for exit capacity at {next_node}.")
            continue

        person.current_node = next_node
        person.traversed_edges.append(edge_id)
        person.traversed_nodes.append(next_node)
        person.movement_progress = 0.0
        person.route = person.route[1:]
        person.route_edges = person.route_edges[1:]
        person.queued_edge = None
        if at_exit:
            exit_use[next_node] += 1
            person.status = "Evacuated"
            person.route = []
            person.route_edges = []
            person.assigned_exit = next_node
            log_event(state, "evacuation", f"{person.id}: evacuated through {next_node}.")
        else:
            person.status = "Moving"

    if must_replan:
        assign_group_routes(state, reason="route became unavailable")
    else:
        queued_load = Counter(person.queued_edge for person in state.people if person.status == "Queued" and person.queued_edge)
        persistent = Counter({edge_id: count for edge_id, count in queued_load.items() if count >= 2})
        if persistent and state.tick - state.last_replan_tick >= 3:
            bias = Counter({edge_id: count * 4 for edge_id, count in persistent.items()})
            assign_group_routes(state, reason="persistent congestion", congestion_bias=bias)
            log_event(state, "congestion", "Persistent queues detected; group routes compared with available alternatives.")

    if state.running and not any(person.status in {"Waiting", "Moving", "Queued"} for person in state.people):
        state.running = False
        log_event(state, "control", "Evacuation run ended; no person remains on an active route.")

