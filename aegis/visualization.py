"""Plotly floor plan and turn-by-turn guidance for the synthetic building."""

from __future__ import annotations

from collections import Counter

import plotly.graph_objects as go

from aegis.models import Person, SimulationState


FLOOR_LABELS = {0: "Ground", 1: "Floor 1", 2: "Floor 2"}
KIND_STYLE = {
    "room": ("#64748b", "circle"),
    "junction": ("#334155", "circle"),
    "stairs": ("#475569", "square"),
    "exit": ("#15803d", "triangle-up"),
}


def route_floor_sequence(state: SimulationState, person: Person) -> list[int]:
    """Return floors in the person's traveled path followed by the remaining route."""
    floors: list[int] = []
    for node_id in _journey_nodes(person):
        floor = state.building.nodes[node_id].floor
        if not floors or floors[-1] != floor:
            floors.append(floor)
    return floors


def _heading(a, b) -> str:
    dx, dy = b.x - a.x, b.y - a.y
    if abs(dx) >= abs(dy):
        return "east" if dx >= 0 else "west"
    return "south" if dy >= 0 else "north"


def _turn(previous: str, following: str) -> str:
    compass = {"north": 0, "east": 1, "south": 2, "west": 3}
    delta = (compass[following] - compass[previous]) % 4
    return {0: "continue straight", 1: "turn right", 2: "turn around", 3: "turn left"}[delta]


def _journey_nodes(person: Person) -> list[str]:
    journey = list(person.traversed_nodes)
    if person.route:
        journey.extend(person.route[1:] if journey and person.route[0] == journey[-1] else person.route)
    return journey


def _person_position(building, person: Person) -> tuple[float, float]:
    node = building.nodes[person.current_node]
    x, y = node.x, node.y
    if person.movement_progress > 0 and len(person.route) > 1 and person.route_edges:
        edge = building.edges[person.route_edges[0]]
        source = building.nodes[person.route[0]]
        destination = building.nodes[person.route[1]]
        if not edge.is_stair and source.floor == destination.floor:
            progress = min(1.0, max(0.0, person.movement_progress))
            x += (destination.x - source.x) * progress
            y += (destination.y - source.y) * progress
    return x, y


def _fit_axis(
    low: float,
    high: float,
    *,
    minimum: float,
    maximum: float,
    min_span: float,
    padding: float,
) -> tuple[float, float]:
    span = min(maximum - minimum, max(min_span, high - low + 2 * padding))
    center = (low + high) / 2
    start, end = center - span / 2, center + span / 2
    if start < minimum:
        end += minimum - start
        start = minimum
    if end > maximum:
        start -= end - maximum
        end = maximum
    return start, end


def _person_viewport(state: SimulationState, floor: int, person: Person | None):
    if person is None:
        return [-0.5, 22.5], [14.0, 0.0]

    points = [
        (state.building.nodes[node_id].x, state.building.nodes[node_id].y)
        for node_id in _journey_nodes(person)
        if node_id in state.building.nodes and state.building.nodes[node_id].floor == floor
    ]
    if state.building.nodes[person.current_node].floor == floor:
        points.append(_person_position(state.building, person))
    if not points:
        return [-0.5, 22.5], [14.0, 0.0]

    x_min, x_max = min(x for x, _ in points), max(x for x, _ in points)
    y_min, y_max = min(y for _, y in points), max(y for _, y in points)
    x_range = _fit_axis(x_min, x_max, minimum=-0.5, maximum=22.5, min_span=13.5, padding=2.0)
    y_range = _fit_axis(y_min, y_max, minimum=0.0, maximum=14.0, min_span=8.5, padding=1.7)
    return list(x_range), [y_range[1], y_range[0]]


def build_route_instructions(state: SimulationState, person: Person) -> list[str]:
    """Build short, plain-language directions for the remaining graph route."""
    building = state.building
    if len(person.route) < 2 or not person.route_edges:
        return []

    directions: list[str] = []
    for index, edge_id in enumerate(person.route_edges):
        if index + 1 >= len(person.route):
            break
        here = building.nodes[person.route[index]]
        following = building.nodes[person.route[index + 1]]
        edge = building.edges[edge_id]

        if edge.is_stair:
            stair = here if here.kind == "stairs" else following
            vertical = "up" if following.floor > here.floor else "down"
            directions.append(f"Take the {stair.label} {vertical} to {FLOOR_LABELS[following.floor]}.")
            continue

        if following.kind == "exit":
            directions.append(f"Continue to the {following.label} and leave through the safe exit.")
            continue

        if index == 0:
            if here.kind == "room":
                directions.append(f"Leave {here.label} and follow the passage to {following.label}.")
            elif here.kind == "stairs":
                directions.append(f"From {here.label}, follow the corridor toward {following.label}.")
            else:
                directions.append(f"Head {_heading(here, following)} toward {following.label}.")
            continue

        if here.kind == "stairs":
            directions.append(f"Leave {here.label} and follow the corridor toward {following.label}.")
            continue

        previous = building.nodes[person.route[index - 1]]
        prior_heading = _heading(previous, here)
        next_heading = _heading(here, following)
        maneuver = _turn(prior_heading, next_heading)
        if maneuver == "continue straight":
            directions.append(f"Continue straight through {here.label} toward {following.label}.")
        else:
            directions.append(f"At {here.label}, {maneuver} and continue toward {following.label}.")

    return directions


def _add_floorplan_shapes(fig: go.Figure, nodes_on_floor: dict) -> None:
    """Draw room blocks, corridor bands, stairwells, and the building outline."""
    fig.add_shape(
        type="rect", x0=0.75, y0=0.45, x1=21.25, y1=13.55,
        line={"color": "#94a3b8", "width": 2}, fillcolor="#f1f5f9", layer="below",
    )
    fig.add_shape(
        type="rect", x0=0.75, y0=6.35, x1=21.25, y1=7.65,
        line={"width": 0}, fillcolor="#dbe4ee", layer="below",
    )

    junctions = sorted(
        (node for node in nodes_on_floor.values() if node.kind == "junction"),
        key=lambda node: node.x,
    )
    for junction in junctions:
        fig.add_shape(
            type="rect", x0=junction.x - 0.23, y0=4.1, x1=junction.x + 0.23, y1=6.4,
            line={"width": 0}, fillcolor="#e2e8f0", layer="below",
        )
        fig.add_shape(
            type="rect", x0=junction.x - 0.23, y0=7.6, x1=junction.x + 0.23, y1=9.9,
            line={"width": 0}, fillcolor="#e2e8f0", layer="below",
        )

    for node in nodes_on_floor.values():
        if node.kind == "room":
            north = node.y < 7.0
            y0, y1 = (0.95, 4.1) if north else (9.9, 13.05)
            fig.add_shape(
                type="rect", x0=node.x - 1.45, y0=y0, x1=node.x + 1.45, y1=y1,
                line={"color": "#cbd5e1", "width": 1.5}, fillcolor="#ffffff", layer="below",
            )
        elif node.kind == "stairs":
            fig.add_shape(
                type="rect", x0=node.x - 0.55, y0=5.95, x1=node.x + 0.55, y1=8.05,
                line={"color": "#64748b", "width": 1.5}, fillcolor="#e2e8f0", layer="below",
            )

    fig.add_shape(
        type="rect", x0=-0.15, y0=6.45, x1=0.65, y1=7.55,
        line={"color": "#86efac", "width": 1}, fillcolor="#dcfce7", layer="below",
    )
    fig.add_shape(
        type="rect", x0=21.35, y0=6.45, x1=22.15, y1=7.55,
        line={"color": "#86efac", "width": 1}, fillcolor="#dcfce7", layer="below",
    )


def render_floor_map(state: SimulationState, floor: int, selected_person_id: str | None = None) -> go.Figure:
    building = state.building
    fig = go.Figure()
    nodes_on_floor = {node_id: node for node_id, node in building.nodes.items() if node.floor == floor}
    selected = next((person for person in state.people if person.id == selected_person_id), None)
    if selected is None and state.people:
        selected = state.people[0]
        selected_person_id = selected.id
    route_reservations: Counter = Counter()
    queued_edges: Counter = Counter()
    for person in state.people:
        if person.status != "Evacuated":
            route_reservations.update(person.route_edges)
        if person.queued_edge:
            queued_edges[person.queued_edge] += 1
    _add_floorplan_shapes(fig, nodes_on_floor)

    edge_styles = {
        "Open corridor": ("#94a3b8", "solid", 3),
        "Narrow corridor": ("#64748b", "dash", 4),
        "Caution area": ("#d97706", "dash", 5),
        "Closed passage": ("#b91c1c", "dash", 6),
    }
    edge_groups: dict[str, list[tuple[float, float, float, float, str, str]]] = {
        label: [] for label in edge_styles
    }
    for edge in building.edges.values():
        a, b = building.nodes[edge.a], building.nodes[edge.b]
        if a.floor != floor or b.floor != floor:
            continue
        if edge.id in state.blocked_edges:
            label = "Closed passage"
        elif edge.id in state.caution_edges or a.id in state.caution_nodes or b.id in state.caution_nodes:
            label = "Caution area"
        elif edge.is_narrow:
            label = "Narrow corridor"
        else:
            label = "Open corridor"
        hover = (
            f"{edge.id}<br>{label}<br>Width: {edge.width_m:g} m<br>"
            f"Capacity: {edge.capacity_per_step} people / step<br>"
            f"Route reservations: {route_reservations[edge.id]}<br>Queue: {queued_edges[edge.id]}"
        )
        edge_groups[label].append((a.x, a.y, b.x, b.y, edge.id, hover))

    for label, items in edge_groups.items():
        if not items:
            continue
        color, dash, width = edge_styles[label]
        xs: list[float | None] = []
        ys: list[float | None] = []
        hover_text: list[str | None] = []
        for x1, y1, x2, y2, _edge_id, hover in items:
            xs.extend((x1, x2, None))
            ys.extend((y1, y2, None))
            hover_text.extend((hover, hover, None))
        fig.add_trace(go.Scatter(
            x=xs, y=ys, mode="lines", name=label,
            line={"color": color, "width": width, "dash": dash},
            hovertext=hover_text, hoverinfo="text", connectgaps=False,
        ))

    for edge_id, queue_count in queued_edges.items():
        if not queue_count or edge_id not in building.edges:
            continue
        edge = building.edges[edge_id]
        a, b = building.nodes[edge.a], building.nodes[edge.b]
        if a.floor == floor and b.floor == floor:
            x, y = (a.x + b.x) / 2, (a.y + b.y) / 2 - 0.55
        elif edge.is_stair and floor in {a.floor, b.floor}:
            landing = a if a.floor == floor else b
            x, y = landing.x, 5.55
        else:
            continue
        fig.add_annotation(
            x=x, y=y, text=f"QUEUE {queue_count}", showarrow=False,
            font={"size": 9, "color": "#92400e"},
            bgcolor="#fef3c7", bordercolor="#d97706", borderpad=3,
        )

    if selected:
        traveled_x: list[float | None] = []
        traveled_y: list[float | None] = []
        stair_x: list[float] = []
        stair_y: list[float] = []
        for edge_id in selected.traversed_edges:
            if edge_id not in building.edges:
                continue
            edge = building.edges[edge_id]
            a, b = building.nodes[edge.a], building.nodes[edge.b]
            if a.floor == floor and b.floor == floor:
                traveled_x.extend((a.x, b.x, None))
                traveled_y.extend((a.y, b.y, None))
            elif edge.is_stair and floor in {a.floor, b.floor}:
                landing = a if a.floor == floor else b
                stair_x.append(landing.x)
                stair_y.append(5.7)
        if selected.movement_progress > 0 and len(selected.route) > 1 and selected.route_edges:
            edge = building.edges[selected.route_edges[0]]
            source = building.nodes[selected.route[0]]
            destination = building.nodes[selected.route[1]]
            if not edge.is_stair and source.floor == floor and destination.floor == floor:
                current_x, current_y = _person_position(building, selected)
                traveled_x.extend((source.x, current_x, None))
                traveled_y.extend((source.y, current_y, None))
        if traveled_x or stair_x:
            fig.add_trace(go.Scatter(
                x=traveled_x,
                y=traveled_y,
                mode="lines", name=f"{selected.id} traveled path",
                line={"color": "#64748b", "width": 8},
                hoverinfo="skip", connectgaps=False,
            ))
        if stair_x:
            fig.add_trace(go.Scatter(
                x=stair_x, y=stair_y, mode="markers", name=f"{selected.id} completed stair links",
                marker={"size": 9, "color": "#64748b", "symbol": "square"},
                hoverinfo="skip", showlegend=False,
            ))

        route_x: list[float | None] = []
        route_y: list[float | None] = []
        step_x: list[float] = []
        step_y: list[float] = []
        step_text: list[str] = []
        for index, edge_id in enumerate(selected.route_edges):
            step_number = index + 1
            if edge_id not in building.edges:
                continue
            edge = building.edges[edge_id]
            source = building.nodes[selected.route[index]]
            destination = building.nodes[selected.route[index + 1]]
            if source.floor == floor and destination.floor == floor:
                route_start = _person_position(building, selected) if index == 0 and selected.movement_progress > 0 else (source.x, source.y)
                route_end = (source.x, source.y) if index == 0 and selected.backtracking else (destination.x, destination.y)
                route_x.extend((route_start[0], route_end[0], None))
                route_y.extend((route_start[1], route_end[1], None))
                step_x.append((route_start[0] + route_end[0]) / 2)
                step_y.append((route_start[1] + route_end[1]) / 2)
                step_text.append(str(step_number))
            elif edge.is_stair and floor in {source.floor, destination.floor}:
                landing = source if source.floor == floor else destination
                step_x.append(landing.x)
                step_y.append(5.7)
                step_text.append(str(step_number))
        if route_x:
            fig.add_trace(go.Scatter(
                x=route_x, y=route_y, mode="lines", name="Route outline",
                line={"color": "#ffffff", "width": 13}, hoverinfo="skip", connectgaps=False,
                showlegend=False,
            ))
            fig.add_trace(go.Scatter(
                x=route_x, y=route_y, mode="lines", name=f"{selected.id} safe route",
                line={"color": "#2563eb", "width": 8}, hoverinfo="skip", connectgaps=False,
            ))
        if step_x:
            fig.add_trace(go.Scatter(
                x=step_x, y=step_y, mode="markers+text", name="Route step numbers",
                text=step_text, textposition="middle center", textfont={"size": 10, "color": "white"},
                marker={"size": 22, "color": "#1d4ed8", "line": {"color": "white", "width": 2}},
                hovertemplate="Route step %{text}<extra></extra>",
            ))

    marker_sizes = {"room": 9, "junction": 13, "stairs": 22, "exit": 22}
    marker_names = {"room": "Rooms", "junction": "Corridor junctions", "stairs": "Stairwells", "exit": "Safe exits"}
    for kind, (base_color, symbol) in KIND_STYLE.items():
        nodes = [node for node in nodes_on_floor.values() if node.kind == kind]
        if not nodes:
            continue
        colors = [
            "#b91c1c" if node.id in state.blocked_nodes
            else ("#f59e0b" if node.id in state.caution_nodes else base_color)
            for node in nodes
        ]
        if kind == "stairs":
            labels = [
                f"{node.label}<br>{'UP' if floor == 0 else 'DOWN' if floor == 2 else 'UP / DOWN'}"
                for node in nodes
            ]
        elif kind == "exit":
            labels = [node.label.replace(" Assembly", "") for node in nodes]
            text_positions = ["top right" if node.x < 11 else "top left" for node in nodes]
        elif kind == "junction":
            labels = [node.label for node in nodes]
        else:
            labels = [node.label for node in nodes]
        positions = {"room": "middle center", "junction": "top center", "stairs": "bottom center"}
        fig.add_trace(go.Scatter(
            x=[node.x for node in nodes], y=[node.y for node in nodes], mode="markers+text",
            name=marker_names[kind], text=labels,
            textposition=text_positions if kind == "exit" else positions[kind],
            textfont={"size": 9 if kind in {"room", "junction"} else 10, "color": "#1e293b"},
            marker={"size": marker_sizes[kind], "color": colors, "symbol": symbol,
                    "line": {"color": "white" if kind == "room" else "#334155", "width": 1.5}},
            customdata=[[node.label, node.id] for node in nodes],
            hovertemplate="%{customdata[0]}<br>ID: %{customdata[1]}<extra></extra>",
        ))

    for hazard in state.hazards:
        if hazard.target_kind == "node" and hazard.target_id in nodes_on_floor:
            node = building.nodes[hazard.target_id]
            fig.add_annotation(
                x=node.x, y=node.y - 0.8,
                text=f"! {hazard.incident_type} · {hazard.level.upper()} {hazard.intensity:.0f}/100",
                showarrow=False,
                font={"size": 9, "color": "#991b1b"}, bgcolor="#fee2e2", bordercolor="#ef4444", borderpad=3,
            )
        elif hazard.target_kind == "edge":
            edge = building.edges[hazard.target_id]
            a, b = building.nodes[edge.a], building.nodes[edge.b]
            if a.floor == floor and b.floor == floor:
                fig.add_annotation(
                    x=(a.x + b.x) / 2, y=(a.y + b.y) / 2 - 0.3,
                    text=f"! {hazard.incident_type} · {hazard.level.upper()} {hazard.intensity:.0f}/100",
                    showarrow=False,
                    font={"size": 9, "color": "#991b1b"}, bgcolor="#fee2e2", bordercolor="#ef4444", borderpad=2,
                )

    sensors = [sensor for sensor in state.sensors if sensor.state in {"Warning", "Alarm"} and (
        (sensor.target_kind == "node" and sensor.target_id in nodes_on_floor)
        or (sensor.target_kind == "edge" and building.nodes[building.edges[sensor.target_id].a].floor == floor)
    )]
    if sensors:
        sx: list[float] = []
        sy: list[float] = []
        sensor_hover: list[str] = []
        sensor_colors: list[str] = []
        for sensor in sensors:
            if sensor.target_kind == "node":
                node = building.nodes[sensor.target_id]
                x, y = node.x + 0.35, node.y - 0.35
            else:
                edge = building.edges[sensor.target_id]
                a, b = building.nodes[edge.a], building.nodes[edge.b]
                x, y = (a.x + b.x) / 2, (a.y + b.y) / 2
            sx.append(x)
            sy.append(y)
            sensor_hover.append(f"{sensor.id}<br>{sensor.metric}: {sensor.reading:g} {sensor.unit}<br>{sensor.state}")
            sensor_colors.append({"Normal": "#0f766e", "Warning": "#d97706", "Alarm": "#b91c1c"}[sensor.state])
        fig.add_trace(go.Scatter(
            x=sx, y=sy, mode="markers+text", name="Simulated sensors", text=["S" for _ in sensors],
            textposition="top right", textfont={"size": 8, "color": "white"},
            marker={"size": 14, "color": sensor_colors, "symbol": "square", "line": {"color": "white", "width": 1}},
            hovertext=sensor_hover, hoverinfo="text",
        ))

    occupants: dict[str, list] = {}
    for person in state.people:
        if person.id != selected_person_id:
            continue
        if person.current_node in nodes_on_floor:
            occupants.setdefault(person.current_node, []).append(person)
    px: list[float] = []
    py: list[float] = []
    ptext: list[str] = []
    phover: list[str] = []
    pcolor: list[str] = []
    psymbol: list[str] = []
    for node_id, people in occupants.items():
        for person in sorted(people, key=lambda item: item.id):
            node = building.nodes[node_id]
            x, y = _person_position(building, person)
            px.append(x)
            py.append(y)
            ptext.append(person.id)
            phover.append(
                f"{person.id}<br>{node.label}<br>Status: {person.status}<br>"
                f"Progress: {person.movement_progress:.0%}<br>Priority: {person.priority_score:.2f}"
            )
            pcolor.append("#171a1d" if person.status == "Needs Assistance" else ("#7b4bb7" if person.id == selected_person_id else "#18834b"))
            psymbol.append("circle")
    if px:
        fig.add_trace(go.Scatter(
            x=px, y=py, mode="markers", name="Person position halo",
            marker={"size": 38, "color": "rgba(37, 99, 235, 0.18)"},
            hoverinfo="skip", showlegend=False,
        ))
        fig.add_trace(go.Scatter(
            x=px, y=py, mode="markers+text", name=f"Selected person · {selected_person_id}", text=ptext,
            textposition="top center", textfont={"size": 11, "color": "#1e293b"},
            marker={"size": 18, "color": pcolor, "symbol": psymbol, "line": {"color": "white", "width": 3}},
            hovertext=phover, hoverinfo="text",
        ))

    floor_name = FLOOR_LABELS.get(floor, f"Floor {floor}")
    if selected and building.nodes[selected.current_node].floor != floor:
        selected_floor = building.nodes[selected.current_node].floor
        selected_floor_name = FLOOR_LABELS.get(selected_floor, f"Floor {selected_floor}")
        fig.add_annotation(
            x=11, y=0.25,
            text=f"{selected.id} is currently on {selected_floor_name}",
            showarrow=False,
            font={"size": 11, "color": "#9a3412"},
            bgcolor="#ffedd5", bordercolor="#f97316", borderpad=5,
        )
    fig.add_annotation(x=11, y=6.95, text="MAIN CORRIDOR", showarrow=False,
                       font={"size": 9, "color": "#64748b"}, bgcolor="#dbe4ee")
    fig.add_annotation(x=11, y=0.7, text="NORTH WING", showarrow=False,
                       font={"size": 9, "color": "#64748b"})
    fig.add_annotation(x=11, y=13.3, text="SOUTH WING", showarrow=False,
                       font={"size": 9, "color": "#64748b"})
    x_range, y_range = _person_viewport(state, floor, selected)
    journey_signature = "|".join(_journey_nodes(selected)) if selected else "all"
    fig.update_layout(
        title=f"{floor_name} floor plan",
        height=560, margin={"l": 10, "r": 10, "t": 50, "b": 20},
        paper_bgcolor="#ffffff", plot_bgcolor="#f8fafc",
        font={"family": "Arial, sans-serif", "size": 12, "color": "#0f172a"},
        legend={"orientation": "h", "y": -0.12, "x": 0, "font": {"color": "#0f172a"}},
        xaxis={"range": x_range, "visible": False, "fixedrange": False, "constrain": "domain"},
        yaxis={"range": y_range, "visible": False, "fixedrange": False, "scaleanchor": "x", "scaleratio": 1},
        dragmode="pan", hovermode="closest",
        uirevision=f"floor-{floor}-person-{selected_person_id}-{journey_signature}",
        transition={"duration": 800, "easing": "cubic-in-out"},
    )
    return fig
