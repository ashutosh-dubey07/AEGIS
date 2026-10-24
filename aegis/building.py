"""Synthetic three-floor building and structural validation."""

from __future__ import annotations

import random
from collections import deque

from aegis.models import Building, Edge, Node


def build_sample_building() -> Building:
    nodes: dict[str, Node] = {}
    edges: dict[str, Edge] = {}

    def add_node(node: Node) -> None:
        if node.id in nodes:
            raise ValueError(f"Duplicate node ID: {node.id}")
        nodes[node.id] = node

    def add_edge(edge: Edge) -> None:
        if edge.id in edges:
            raise ValueError(f"Duplicate edge ID: {edge.id}")
        edges[edge.id] = edge

    floors = ((0, "G"), (1, "F1"), (2, "F2"))
    junction_x = (3.2, 6.9, 11.0, 15.1, 18.8)
    north_rooms = {
        0: ("West Reception", "Security Office", "Main Lobby", "Visitor Lounge", "First Aid"),
        1: ("Office 101", "Office 102", "Meeting Room", "Office 104", "Office 105"),
        2: ("Classroom 201", "Classroom 202", "Lecture Hall", "Classroom 204", "Classroom 205"),
    }
    south_rooms = {
        0: ("Loading Office", "Cafeteria", "Dining Hall", "Records Room", "Maintenance"),
        1: ("Office 106", "Office 107", "Copy Room", "Conference Room", "Office 110"),
        2: ("Computer Lab", "Science Lab", "Library", "Project Room", "Classroom 210"),
    }
    junction_names = ("West Hall", "West Connector", "Central Hall", "East Connector", "East Hall")

    for floor, prefix in floors:
        for index, (x, junction_name) in enumerate(zip(junction_x, junction_names), start=1):
            add_node(Node(f"{prefix}-J{index}", floor, x, 7.0, "junction", junction_name))

            north_id = f"{prefix}-RN{index}"
            south_id = f"{prefix}-RS{index}"
            add_node(Node(north_id, floor, x, 2.7, "room", north_rooms[floor][index - 1]))
            add_node(Node(south_id, floor, x, 11.3, "room", south_rooms[floor][index - 1]))
            add_edge(Edge(f"{prefix}-ACCESS-N{index}", north_id, f"{prefix}-J{index}", 1.0, 1.5, 2))
            add_edge(Edge(f"{prefix}-ACCESS-S{index}", south_id, f"{prefix}-J{index}", 1.0, 1.5, 2))

        west_stair = f"{prefix}-STAIR-W"
        east_stair = f"{prefix}-STAIR-E"
        add_node(Node(west_stair, floor, 1.3, 7.0, "stairs", "West Stair"))
        add_node(Node(east_stair, floor, 20.7, 7.0, "stairs", "East Stair"))

        for index in range(1, 5):
            narrow = floor == 1 and index == 2
            add_edge(Edge(
                f"{prefix}-CORRIDOR-{index:02d}", f"{prefix}-J{index}", f"{prefix}-J{index + 1}",
                1.2, 1.2 if narrow else 2.4, 1 if narrow else 4, is_narrow=narrow,
            ))
        add_edge(Edge(f"{prefix}-STAIR-ACCESS-W", f"{prefix}-J1", west_stair, 1.0, 1.6, 2))
        add_edge(Edge(f"{prefix}-STAIR-ACCESS-E", f"{prefix}-J5", east_stair, 1.0, 1.6, 2))

        lift_id = f"{prefix}-LIFT"
        add_node(Node(lift_id, floor, 11.0, 5.0, "lift", "Evacuation lift lobby"))
        add_edge(Edge(f"{prefix}-LIFT-ACCESS", lift_id, f"{prefix}-J3", 0.8, 1.8, 3))

        if floor == 0:
            add_node(Node("G-EXIT-W", 0, 0.2, 7.0, "exit", "West Assembly Exit", exit_capacity=2))
            add_node(Node("G-EXIT-E", 0, 21.8, 7.0, "exit", "East Assembly Exit", exit_capacity=2))
            add_edge(Edge("G-EXIT-LINK-W", west_stair, "G-EXIT-W", 1.0, 2.0, 3))
            add_edge(Edge("G-EXIT-LINK-E", east_stair, "G-EXIT-E", 1.0, 2.0, 3))
            add_edge(Edge("G-ACCESSIBLE-EXIT-W", "G-J1", "G-EXIT-W", 1.2, 2.0, 3))
            add_edge(Edge("G-ACCESSIBLE-EXIT-E", "G-J5", "G-EXIT-E", 1.2, 2.0, 3))

    for lower_prefix, upper_prefix, floor in (("G", "F1", 0), ("F1", "F2", 1)):
        for side in ("W", "E"):
            lower = f"{lower_prefix}-STAIR-{side}"
            upper = f"{upper_prefix}-STAIR-{side}"
            add_edge(Edge(f"STAIR-{side}-F{floor}-F{floor + 1}", lower, upper, 2.0, 1.6, 2, is_stair=True, is_accessible=False))
        add_edge(Edge(
            f"LIFT-F{floor}-F{floor + 1}", f"{lower_prefix}-LIFT", f"{upper_prefix}-LIFT",
            2.5, 1.8, 2, is_accessible=True, is_evacuation_lift=True,
        ))

    return Building(nodes=nodes, edges=edges)


BUILDING_PROFILES = {
    "Office": ("Workspace", "Meeting Room", "Conference Room", "Copy Room", "Records", "Reception"),
    "School": ("Classroom", "Science Lab", "Library", "Staff Room", "Lecture Hall", "Art Room"),
    "Hospital": ("Patient Ward", "Treatment Room", "Laboratory", "Pharmacy", "Imaging", "Waiting Room"),
    "Mall": ("Retail Unit", "Food Court", "Cinema", "Service Desk", "Storage", "Atrium"),
}


def build_generated_building(
    seed: int,
    profile: str = "Office",
    *,
    floor_count: int | None = None,
    rooms_per_wing: int | None = None,
) -> Building:
    """Build a seeded, connected multi-floor layout for the browser demo."""
    if profile not in BUILDING_PROFILES:
        raise ValueError(f"profile must be one of {', '.join(BUILDING_PROFILES)}")
    rng = random.Random(int(seed))
    floor_count = rng.randint(3, 5) if floor_count is None else int(floor_count)
    rooms_per_wing = rng.randint(3, 5) if rooms_per_wing is None else int(rooms_per_wing)
    if not 3 <= floor_count <= 5:
        raise ValueError("floor_count must be between 3 and 5")
    if not 2 <= rooms_per_wing <= 6:
        raise ValueError("rooms_per_wing must be between 2 and 6")

    nodes: dict[str, Node] = {}
    edges: dict[str, Edge] = {}
    corridor_names = (
        "North Hall", "West Connector", "Central Hall", "East Connector",
        "South Hall", "Crossing", "Main Concourse",
    )
    stair_cores = (("W", "West Stair"), ("E", "East Stair"))
    labels = BUILDING_PROFILES[profile]

    def add_node(node: Node) -> None:
        nodes[node.id] = node

    def add_edge(edge: Edge) -> None:
        edges[edge.id] = edge

    junction_count = rng.randint(4, 7)
    left_x, right_x = 3.0, 19.0
    spacing = (right_x - left_x) / (junction_count - 1)
    narrow_index = rng.randrange(junction_count - 1)
    for floor in range(floor_count):
        prefix = "G" if floor == 0 else f"L{floor}"
        junction_ids: list[str] = []
        for index in range(junction_count):
            node_id = f"{prefix}-J{index + 1}"
            junction_ids.append(node_id)
            add_node(Node(
                node_id, floor, left_x + spacing * index, 7.0, "junction",
                corridor_names[index % len(corridor_names)],
            ))

        for core_index, (side, name) in enumerate(stair_cores):
            stair_id = f"{prefix}-STAIR-{side}"
            stair_x = 0.9 if side == "W" else 21.1
            add_node(Node(stair_id, floor, stair_x, 7.0, "stairs", name))
            junction_id = junction_ids[0] if side == "W" else junction_ids[-1]
            add_edge(Edge(
                f"{prefix}-STAIR-ACCESS-{side}", junction_id, stair_id,
                1.0, 1.6, 2,
            ))

        lift_id = f"{prefix}-LIFT"
        add_node(Node(lift_id, floor, 11.0, 5.0, "lift", "Evacuation lift lobby"))
        center_junction = junction_ids[len(junction_ids) // 2]
        add_edge(Edge(f"{prefix}-LIFT-ACCESS", lift_id, center_junction, 0.8, 1.8, 3))

        for index, (start, end) in enumerate(zip(junction_ids, junction_ids[1:])):
            narrow = index == narrow_index
            edge_id = f"{prefix}-CORRIDOR-{index + 1:02d}"
            add_edge(Edge(
                edge_id, start, end, round(rng.uniform(1.0, 1.5), 1),
                1.2 if narrow else 2.4, 1 if narrow else rng.randint(3, 5),
                is_narrow=narrow,
            ))

        for wing, y in (("N", 2.7), ("S", 11.3)):
            shuffled_labels = list(labels)
            rng.shuffle(shuffled_labels)
            for index in range(rooms_per_wing):
                room_id = f"{prefix}-R{wing}{index + 1:02d}"
                junction = rng.choice(junction_ids)
                label = shuffled_labels[index % len(shuffled_labels)]
                add_node(Node(
                    room_id, floor,
                    nodes[junction].x + rng.uniform(-0.7, 0.7), y, "room",
                    f"{label} {floor * rooms_per_wing * 2 + index + 1}",
                ))
                add_edge(Edge(
                    f"{prefix}-ACCESS-{wing}{index + 1:02d}",
                    room_id, junction, round(rng.uniform(0.9, 1.2), 1), 1.5, 2,
                ))

    for floor in range(floor_count - 1):
        for side, _name in stair_cores:
            lower_prefix = "G" if floor == 0 else f"L{floor}"
            upper_prefix = f"L{floor + 1}"
            add_edge(Edge(
                f"STAIR-{side}-F{floor}-F{floor + 1}",
                f"{lower_prefix}-STAIR-{side}", f"{upper_prefix}-STAIR-{side}",
                2.0, 1.6, 2, is_stair=True, is_accessible=False,
            ))
        add_edge(Edge(
            f"LIFT-F{floor}-F{floor + 1}",
            f"{lower_prefix}-LIFT", f"{upper_prefix}-LIFT",
            2.5, 1.8, 2, is_accessible=True, is_evacuation_lift=True,
        ))

    add_node(Node("G-EXIT-W", 0, 0.2, 6.4, "exit", "West Assembly Exit", exit_capacity=2))
    add_node(Node("G-EXIT-E", 0, 21.8, 7.6, "exit", "East Assembly Exit", exit_capacity=2))
    add_edge(Edge("G-EXIT-LINK-W", "G-STAIR-W", "G-EXIT-W", 1.0, 2.0, 3))
    add_edge(Edge("G-EXIT-LINK-E", "G-STAIR-E", "G-EXIT-E", 1.0, 2.0, 3))
    add_edge(Edge("G-ACCESSIBLE-EXIT-W", "G-J1", "G-EXIT-W", 1.2, 2.0, 3))
    add_edge(Edge("G-ACCESSIBLE-EXIT-E", f"G-J{junction_count}", "G-EXIT-E", 1.2, 2.0, 3))
    return Building(nodes=nodes, edges=edges)


def validate_building(building: Building) -> list[str]:
    """Return every graph issue found; an empty list means the graph is valid."""
    errors: list[str] = []
    if len(building.nodes) != len(set(building.nodes)):
        errors.append("Duplicate node IDs")
    if len(building.edges) != len(set(building.edges)):
        errors.append("Duplicate edge IDs")

    for edge in building.edges.values():
        if edge.a not in building.nodes or edge.b not in building.nodes:
            errors.append(f"Edge {edge.id} has a missing endpoint")
            continue
        if edge.a == edge.b:
            errors.append(f"Edge {edge.id} is a self-loop")
        if edge.travel_time <= 0 or edge.width_m <= 0 or edge.capacity_per_step <= 0:
            errors.append(f"Edge {edge.id} has a non-positive travel time, width, or capacity")
        floor_a = building.nodes[edge.a].floor
        floor_b = building.nodes[edge.b].floor
        if floor_a != floor_b and not (edge.is_stair or edge.is_evacuation_lift):
            errors.append(f"Cross-floor edge {edge.id} is not marked as a stair or evacuation lift")
        if edge.is_stair and abs(floor_a - floor_b) != 1:
            errors.append(f"Stair edge {edge.id} does not connect adjacent floors")
        if edge.is_evacuation_lift:
            if abs(floor_a - floor_b) != 1:
                errors.append(f"Evacuation lift edge {edge.id} does not connect adjacent floors")
            if not edge.is_accessible:
                errors.append(f"Evacuation lift edge {edge.id} must be marked accessible")
            if building.nodes[edge.a].kind != "lift" or building.nodes[edge.b].kind != "lift":
                errors.append(f"Evacuation lift edge {edge.id} must connect lift lobbies")

    for node in building.nodes.values():
        if node.floor < 0:
            errors.append(f"Node {node.id} has an invalid floor")
        if node.kind == "exit" and node.exit_capacity <= 0:
            errors.append(f"Exit {node.id} has no capacity")

    exits = {node_id for node_id, node in building.nodes.items() if node.kind == "exit"}
    if len(exits) < 2:
        errors.append("The baseline building must have at least two exits")
    floors = sorted({node.floor for node in building.nodes.values()})
    if len(floors) < 3 or floors != list(range(floors[-1] + 1)):
        errors.append("The building must contain at least three contiguous floors")

    if exits:
        seen = set(exits)
        queue = deque(exits)
        while queue:
            node_id = queue.popleft()
            for neighbor, _edge in building.neighbors(node_id):
                if neighbor.id not in seen:
                    seen.add(neighbor.id)
                    queue.append(neighbor.id)
        for node_id in building.nodes:
            if node_id not in seen:
                errors.append(f"Node {node_id} cannot reach a baseline exit")

    if not any(edge.is_narrow for edge in building.edges.values()):
        errors.append("The building must include a narrow passage")
    for floor in range(max(0, len(floors) - 1)):
        connecting_stairs = sum(
            1 for edge in building.edges.values()
            if edge.is_stair and {building.nodes[edge.a].floor, building.nodes[edge.b].floor} == {floor, floor + 1}
        )
        if connecting_stairs < 2:
            errors.append(f"Floors {floor} and {floor + 1} need two independent stair connections")
        if not any(
            edge.is_evacuation_lift
            and {building.nodes[edge.a].floor, building.nodes[edge.b].floor} == {floor, floor + 1}
            for edge in building.edges.values()
        ):
            errors.append(f"Floors {floor} and {floor + 1} need a designated evacuation lift connection")
    return errors
