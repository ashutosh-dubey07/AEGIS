"""AEGIS Streamlit dashboard. People, hazards, and sensor readings are simulated."""

from __future__ import annotations

from collections import Counter
import math
import random

import streamlit as st

from aegis.building import validate_building
from aegis.models import SimulationState
from aegis.simulation import (
    HAZARD_OPTIONS,
    create_scenario,
    inject_sensor_alarm,
    set_running,
    step_simulation,
)
from aegis.visualization import (
    FLOOR_LABELS,
    build_route_instructions,
    render_floor_map,
    route_floor_sequence,
)


st.set_page_config(page_title="AEGIS | Evacuation Simulation", layout="wide")


def _person_by_id(state: SimulationState, person_id: str | None):
    return next((person for person in state.people if person.id == person_id), None)


def _new_scenario(count: int, seed_value: str, incident_type: str) -> SimulationState:
    seed = int(seed_value.strip()) if seed_value.strip() else None
    return create_scenario(count, seed, incident_type)


def _exit_label(state: SimulationState, exit_id: str | None) -> str:
    if not exit_id:
        return "No safe exit"
    return state.building.nodes[exit_id].label


def _sensor_location_label(state: SimulationState, sensor_id: str) -> str:
    sensor = next(item for item in state.sensors if item.id == sensor_id)
    if sensor.target_kind == "node":
        node = state.building.nodes[sensor.target_id]
        location = f"{FLOOR_LABELS[node.floor]} · {node.label}"
    else:
        edge = state.building.edges[sensor.target_id]
        start = state.building.nodes[edge.a]
        end = state.building.nodes[edge.b]
        floors = FLOOR_LABELS[start.floor]
        if start.floor != end.floor:
            floors += f" → {FLOOR_LABELS[end.floor]}"
        location = f"{floors} · Passage: {start.label} to {end.label}"
    return f"{sensor.label} · {location}"


def _hazard_location_label(state: SimulationState, hazard) -> str:
    if hazard.target_kind == "node":
        node = state.building.nodes[hazard.target_id]
        return f"{FLOOR_LABELS[node.floor]} · {node.label}"
    edge = state.building.edges[hazard.target_id]
    start, end = state.building.nodes[edge.a], state.building.nodes[edge.b]
    floor = FLOOR_LABELS[start.floor]
    if start.floor != end.floor:
        floor += f" to {FLOOR_LABELS[end.floor]}"
    return f"{floor} · passage {start.label} to {end.label}"


def _person_label(state: SimulationState, person_id: str) -> str:
    person = _person_by_id(state, person_id)
    if not person:
        return person_id
    node = state.building.nodes[person.current_node]
    return f"{person.id} · {node.label} · {FLOOR_LABELS[node.floor]}"


if "person_count" not in st.session_state:
    st.session_state.person_count = 8
if "sim_state" not in st.session_state:
    st.session_state.sim_state = create_scenario(st.session_state.person_count)
if "selected_person_id" not in st.session_state:
    st.session_state.selected_person_id = st.session_state.sim_state.people[0].id
if "selected_floor" not in st.session_state:
    st.session_state.selected_floor = 0
if "follow_selected_person" not in st.session_state:
    st.session_state.follow_selected_person = True
if "seed_input" not in st.session_state:
    st.session_state.seed_input = ""
if "hazard_type_input" not in st.session_state:
    st.session_state.hazard_type_input = HAZARD_OPTIONS[0]

state: SimulationState = st.session_state.sim_state

st.title("AEGIS")
st.caption("Emergency evacuation simulation")
st.warning(
    "Simulation only: people, hazards, locations, and sensor readings are synthetic. "
    "This demo is not a real emergency system."
)

with st.sidebar:
    st.header("Simulation controls")
    st.number_input("People in next scenario", min_value=1, max_value=20, step=1, key="person_count")
    st.text_input(
        "Replay seed (optional)",
        key="seed_input",
        help="Leave blank for a new random scenario. Enter a number to replay the same initial scenario.",
    )
    st.selectbox(
        "Hazard type",
        options=HAZARD_OPTIONS,
        key="hazard_type_input",
        help="The selected hazard type is fixed; its location is chosen randomly for each new scenario.",
    )
    if st.button("Create Scenario", type="primary", width="stretch"):
        try:
            state = _new_scenario(
                int(st.session_state.person_count),
                st.session_state.seed_input,
                st.session_state.hazard_type_input,
            )
            st.session_state.sim_state = state
            st.session_state.selected_person_id = state.people[0].id
            st.session_state.selected_floor = state.building.nodes[state.people[0].current_node].floor
            st.success(f"Scenario ready · seed {state.seed}")
        except ValueError as exc:
            st.error(f"Seed must be a whole number. {exc}")

    state = st.session_state.sim_state
    if st.button("Reset this scenario", width="stretch"):
        incident_type = state.hazards[0].incident_type if state.hazards else None
        state = create_scenario(len(state.people), state.seed, incident_type)
        st.session_state.sim_state = state
        st.session_state.selected_person_id = state.people[0].id
        st.session_state.selected_floor = state.building.nodes[state.people[0].current_node].floor

    has_movable_people = any(person.status in {"Waiting", "Moving", "Queued"} for person in state.people)
    start_col, pause_col, step_col = st.columns(3)
    with start_col:
        if st.button("Start", disabled=state.running or not has_movable_people, width="stretch"):
            set_running(state, True)
    with pause_col:
        if st.button("Pause", disabled=not state.running, width="stretch"):
            set_running(state, False)
    with step_col:
        if st.button("Advance one beat", disabled=state.running or not has_movable_people, width="stretch"):
            step_simulation(state)
    st.caption("Movement updates every second: corridor links take about 12–15 seconds; a stair link takes about 24 seconds.")

    existing_hazard_targets = {(hazard.target_kind, hazard.target_id) for hazard in state.hazards}
    available_sensors = [
        sensor for sensor in state.sensors
        if sensor.state != "Alarm"
        and (sensor.target_kind, sensor.target_id) not in existing_hazard_targets
        and sensor.target_id not in (
            state.blocked_nodes if sensor.target_kind == "node" else state.blocked_edges
        )
    ]
    active_alarm_count = sum(sensor.state == "Alarm" for sensor in state.sensors)
    st.divider()
    st.subheader("Additional sensor alarms")
    st.caption(
        f"{active_alarm_count} active alarm(s) · {len(available_sensors)} other monitored locations available. "
        "Trigger another alarm while people are moving to close passages and recalculate their routes."
    )
    if available_sensors:
        sensor_options = ["__random_location__", *(sensor.id for sensor in available_sensors)]
        selected_sensor = st.selectbox(
            "Alarm location",
            options=sensor_options,
            format_func=lambda sensor_id: (
                "Random monitored location"
                if sensor_id == "__random_location__"
                else _sensor_location_label(state, sensor_id)
            ),
            key=f"alarm_sensor_input_{len(state.hazards)}",
        )
        if st.button("Trigger another alarm", width="stretch"):
            if selected_sensor == "__random_location__":
                alarm_rng = random.Random(state.seed + state.tick + len(state.hazards) * 101)
                sensor = alarm_rng.choice(sorted(available_sensors, key=lambda item: item.id))
                selected_sensor = sensor.id
            sensor_label = _sensor_location_label(state, selected_sensor)
            previous_blocked_edges = set(state.blocked_edges)
            previous_reroutes = state.rerouted_total
            if inject_sensor_alarm(state, selected_sensor):
                new_closures = len(state.blocked_edges - previous_blocked_edges)
                new_routes = state.rerouted_total - previous_reroutes
                st.success(
                    f"Alarm at {sensor_label}. {new_closures} new passage closure(s); "
                    f"{new_routes} route(s) changed."
                )
            else:
                st.warning("That sensor location is no longer available. Choose another location.")

    st.divider()
    st.caption("No hardware, GPS, cameras, alarms, or live building feeds are connected.")

state = st.session_state.sim_state
graph_errors = validate_building(state.building)
if graph_errors:
    st.error("Building graph validation failed: " + "; ".join(graph_errors))


def render_view_controls() -> None:
    current: SimulationState = st.session_state.sim_state
    person_col, map_col = st.columns([2, 1])
    with person_col:
        person_ids = [person.id for person in current.people]
        selected = st.session_state.get("selected_person_id")
        if selected not in person_ids:
            selected = person_ids[0]
        st.selectbox(
            "Person perspective",
            options=person_ids,
            index=person_ids.index(selected),
            format_func=lambda person_id: _person_label(current, person_id),
            key="selected_person_id",
        )
    with map_col:
        st.checkbox("Follow selected person", key="follow_selected_person")
        if st.session_state.follow_selected_person:
            selected_person = _person_by_id(current, st.session_state.selected_person_id)
            if selected_person:
                selected_floor = current.building.nodes[selected_person.current_node].floor
                st.caption(f"Map follows {selected_person.id} · {FLOOR_LABELS[selected_floor]}")
        else:
            st.selectbox(
                "Floor plan",
                options=[0, 1, 2],
                format_func=lambda floor: FLOOR_LABELS[floor],
                key="selected_floor",
            )


refresh_interval = "1s" if state.running else None


@st.fragment(run_every=refresh_interval)
def render_live_dashboard() -> None:
    current: SimulationState = st.session_state.sim_state
    was_running = current.running
    if was_running:
        step_simulation(current)

    active_count = sum(person.status in {"Waiting", "Moving", "Queued"} for person in current.people)
    evacuated_count = sum(person.status == "Evacuated" for person in current.people)
    assistance_count = sum(person.status == "Needs Assistance" for person in current.people)
    queued_count = sum(person.status == "Queued" for person in current.people)
    high_risk_count = max(1, math.ceil(len(current.people) * 0.25)) if current.people else 0
    high_risk_ids = {
        person.id
        for person in sorted(current.people, key=lambda person: (-person.priority_score, person.id))[:high_risk_count]
    }
    cols = st.columns(6)
    for col, label, value in zip(
        cols,
        ("Active", "Evacuated", "Queued", "High priority", "Rerouted", "Assistance"),
        (active_count, evacuated_count, queued_count, len(high_risk_ids), current.rerouted_total, assistance_count),
    ):
        col.metric(label, value)

    hazard_summary = "; ".join(
        f"{hazard.incident_type} at {_hazard_location_label(current, hazard)} ({hazard.level} {hazard.intensity:.0f}/100)"
        for hazard in current.hazards
    ) or "No incident"
    st.info(
        f"**Seed:** `{current.seed}` · **Incident:** {hazard_summary} · "
        f"**Tick:** {current.tick} · **Mode:** {'Running' if current.running else 'Paused'}"
    )
    st.caption("Intensity is a synthetic 0–100 demo index. It rises each tick and expands the simulated caution/closure area at set stages.")

    map_col, perspective_col = st.columns([3, 1])
    person_ids = [person.id for person in current.people]
    selected_id = st.session_state.get("selected_person_id")
    if selected_id not in person_ids:
        selected_id = person_ids[0]
    with perspective_col:
        st.subheader("Person perspective")
        st.selectbox(
            "Follow a person",
            options=person_ids,
            index=person_ids.index(selected_id),
            format_func=lambda person_id: _person_label(current, person_id),
            key="selected_person_id",
        )
        selected_id = st.session_state.selected_person_id
        selected = _person_by_id(current, selected_id)
        st.checkbox("Follow on map", key="follow_selected_person")
        if st.session_state.follow_selected_person and selected:
            floor = current.building.nodes[selected.current_node].floor
            st.caption(f"Following {selected.id} on {FLOOR_LABELS[floor]}.")
        else:
            st.selectbox(
                "Map floor",
                options=[0, 1, 2],
                format_func=lambda floor: FLOOR_LABELS[floor],
                key="selected_floor",
            )
        if selected:
            location = current.building.nodes[selected.current_node]
            st.write(f"**{selected.status}**")
            st.caption(f"{location.label} · {FLOOR_LABELS[location.floor]}")

    selected = _person_by_id(current, selected_id)
    if st.session_state.get("follow_selected_person", True) and selected:
        floor = current.building.nodes[selected.current_node].floor
    else:
        floor = int(st.session_state.get("selected_floor", 0))
    with map_col:
        if selected and (selected.route or selected.traversed_edges):
            floor_path = " → ".join(FLOOR_LABELS[item] for item in route_floor_sequence(current, selected))
            st.caption(f"{selected.id} full journey: {floor_path}. Grey shows the path covered; blue shows the route ahead.")
        st.plotly_chart(
            render_floor_map(current, floor, selected_id),
            width="stretch",
            key="floor_map",
            config={"scrollZoom": True, "displaylogo": False},
        )
    st.caption(
        "Map key: blue = route ahead · grey = path covered · red = closed/danger · amber = caution · "
        "slate = stairwell · green = exit · blue dot = selected person only · "
        "S = warning/alarm sensor · QUEUE n = people waiting. "
        "Scroll to zoom; drag to pan."
    )

    detail_col, navigation_col = st.columns([1, 1.2])
    with detail_col:
        st.subheader(f"Person detail · {selected.id if selected else '—'}")
        if selected:
            location = current.building.nodes[selected.current_node].label
            destination = _exit_label(current, selected.assigned_exit)
            st.write(f"**Current location:** {location}")
            if selected.backtracking:
                st.warning(f"Passage ahead closed. Walking back to {location} before choosing another route.")
            st.write(f"**Starting location:** {current.building.nodes[selected.start_node].label}")
            st.write(f"**Status:** {selected.status}")
            st.write(f"**Urgency score:** {selected.priority_score:.2f} · higher means closer to the detected hazard")
            st.write(f"**Assigned exit:** {destination}")
            st.write(f"**Personal reroutes:** {selected.reroutes}")
            journey = " → ".join(FLOOR_LABELS[item] for item in route_floor_sequence(current, selected))
            st.write(f"**Floors on journey:** {journey or 'Not started'}")
            if selected.movement_progress > 0:
                st.progress(selected.movement_progress, text="Walking the current segment")
        else:
            st.info("Choose a person to inspect their location and route.")

    with navigation_col:
        st.subheader("Live navigation")
        if selected:
            destination = _exit_label(current, selected.assigned_exit)
            if selected.status == "Evacuated":
                st.success(f"Arrived at {destination}. The grey line shows this person’s completed path.")
            elif selected.status == "Needs Assistance":
                st.error("No safe route is available in this simulation. Assistance is needed.")
            elif selected.backtracking:
                st.info("Passage ahead is unsafe. The person is walking back through the current segment; a new route will be assigned at the previous junction.")
            elif selected.route:
                floor_path = " → ".join(FLOOR_LABELS[item] for item in route_floor_sequence(current, selected))
                directions = build_route_instructions(current, selected)
                remaining_cost = sum(current.building.edges[edge_id].travel_time for edge_id in selected.route_edges)
                st.caption(
                    f"Floor path: {floor_path} · {len(directions)} steps · "
                    f"graph cost {remaining_cost:g} units (not real travel time)"
                )
                if directions:
                    st.info(f"**NEXT · 1**  {directions[0]}")
                    if selected.movement_progress > 0:
                        st.caption(f"Along this segment: {selected.movement_progress:.0%}")
                    for step_number, instruction in enumerate(directions[1:], start=2):
                        st.markdown(f"**{step_number}.** {instruction}")
            else:
                st.info("No remaining route steps.")
        else:
            st.info("No person is selected.")

    st.subheader("Corridor and exit load")
    assigned_edges: Counter = Counter()
    queued_edges: Counter = Counter()
    assigned_exits: Counter = Counter()
    for person in current.people:
        if person.status != "Evacuated":
            assigned_edges.update(person.route_edges)
            if person.queued_edge:
                queued_edges[person.queued_edge] += 1
            if person.assigned_exit:
                assigned_exits[person.assigned_exit] += 1
    load_rows = []
    for edge_id, count in sorted(assigned_edges.items()):
        edge = current.building.edges[edge_id]
        load_rows.append({
            "Passage": f"{current.building.nodes[edge.a].label} to {current.building.nodes[edge.b].label}",
            "Routes": count,
            "Capacity / step": edge.capacity_per_step,
            "Queue": queued_edges[edge_id],
        })
    for exit_id, count in sorted(assigned_exits.items()):
        load_rows.append({
            "Passage": current.building.nodes[exit_id].label,
            "Routes": count,
            "Capacity / step": current.building.nodes[exit_id].exit_capacity,
            "Queue": 0,
        })
    load_rows.sort(key=lambda row: (-row["Queue"], -row["Routes"], row["Passage"]))
    st.dataframe(
        load_rows[:12] if load_rows else [{"Passage": "No active route reservations", "Routes": 0, "Capacity / step": "-", "Queue": 0}],
        hide_index=True,
        width="stretch",
        height=280,
    )
    st.caption("Routes show planned corridor use; queue counts show people waiting now.")

    with st.expander("Group status (all people)", expanded=False):
        people_rows = []
        for person in current.people:
            people_rows.append({
                "Person": person.id,
                "Current location": current.building.nodes[person.current_node].label,
                "Status": person.status,
                "Priority": round(person.priority_score, 2),
                "Exit": _exit_label(current, person.assigned_exit),
                "Reroutes": person.reroutes,
            })
        st.dataframe(people_rows, hide_index=True, width="stretch")

    sensor_col, event_col = st.columns([1, 1.5])
    with sensor_col:
        st.subheader("Simulated sensor readings")
        sensor_rows = [
            {"Sensor": sensor.id, "Reading": f"{sensor.metric} {sensor.reading:g} {sensor.unit}", "State": sensor.state}
            for sensor in current.sensors
        ]
        st.dataframe(sensor_rows, hide_index=True, width="stretch", height=270)
    with event_col:
        st.subheader("Recent events · latest 25")
        with st.container(height=270):
            if current.event_log:
                for event in current.event_log[-25:]:
                    st.write(f"`T+{event.tick:03d}` **{event.kind.upper()}** · {event.message}")
            else:
                st.caption("No events yet.")

    if was_running and not current.running:
        st.rerun()


render_live_dashboard()

st.caption(
    "Decision model: people nearer the detected hazard receive higher priority. Routes use shared capacity "
    "and occupancy estimates; this is a transparent heuristic, not a certified safety system."
)
