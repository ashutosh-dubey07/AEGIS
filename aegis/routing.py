"""Non-negative, congestion-aware Dijkstra routing for the small building graph."""

from __future__ import annotations

import heapq
from collections import Counter
from dataclasses import dataclass
from typing import Iterable, Mapping

from aegis.models import Building, PERSON_PROFILE_SPECS


@dataclass(frozen=True)
class Route:
    nodes: tuple[str, ...]
    edges: tuple[str, ...]
    exit_id: str
    cost: float


def _edge_cost(edge, load: int, caution: bool, person_profile: str = "Standard") -> float:
    # Every term is non-negative. Load adds expected delay; a caution area
    # remains usable but costs more than a normal passage.
    capacity = max(1, edge.capacity_per_step)
    congestion_delay = edge.travel_time * 0.75 * load / capacity
    profile = PERSON_PROFILE_SPECS.get(person_profile, PERSON_PROFILE_SPECS["Standard"])
    stair_factor = profile.stair_cost_multiplier if edge.is_stair else 1.0
    caution_penalty = 8.0 * profile.caution_cost_multiplier if caution else 0.0
    return edge.travel_time * stair_factor + congestion_delay * stair_factor + caution_penalty


def find_route(
    building: Building,
    start: str,
    *,
    blocked_nodes: Iterable[str] = (),
    blocked_edges: Iterable[str] = (),
    caution_nodes: Iterable[str] = (),
    caution_edges: Iterable[str] = (),
    edge_load: Mapping[str, int] | None = None,
    exit_load: Mapping[str, int] | None = None,
    person_profile: str = "Standard",
) -> Route | None:
    """Find the least-cost safe route from start to one of the exits."""
    if start not in building.nodes:
        return None
    blocked_node_set = set(blocked_nodes)
    blocked_edge_set = set(blocked_edges)
    caution_node_set = set(caution_nodes)
    caution_edge_set = set(caution_edges)
    edge_load = edge_load or Counter()
    exit_load = exit_load or Counter()
    profile = PERSON_PROFILE_SPECS.get(person_profile, PERSON_PROFILE_SPECS["Standard"])
    if start in blocked_node_set:
        return None

    exits = {node_id for node_id, node in building.nodes.items() if node.kind == "exit"}
    if not exits:
        return None

    distances: dict[str, float] = {start: 0.0}
    previous: dict[str, tuple[str, str]] = {}
    queue: list[tuple[float, str]] = [(0.0, start)]
    destination: str | None = None

    while queue:
        cost, node_id = heapq.heappop(queue)
        if cost != distances.get(node_id):
            continue
        if node_id in exits:
            destination = node_id
            break

        for neighbor, edge in building.neighbors(node_id):
            if edge.id in blocked_edge_set or neighbor.id in blocked_node_set:
                continue
            if profile.step_free_route and (edge.is_stair or not edge.is_accessible):
                continue
            step_cost = _edge_cost(
                edge,
                int(edge_load.get(edge.id, 0)),
                edge.id in caution_edge_set,
                person_profile,
            )
            if neighbor.id in caution_node_set:
                step_cost += 8.0 * profile.caution_cost_multiplier
            if neighbor.id in exits:
                exit_capacity = max(1, building.nodes[neighbor.id].exit_capacity)
                step_cost += 3.0 * int(exit_load.get(neighbor.id, 0)) / exit_capacity
            candidate = cost + step_cost
            old = distances.get(neighbor.id)
            if old is None or candidate < old - 1e-9:
                distances[neighbor.id] = candidate
                previous[neighbor.id] = (node_id, edge.id)
                heapq.heappush(queue, (candidate, neighbor.id))

    if destination is None:
        return None

    nodes = [destination]
    edges: list[str] = []
    cursor = destination
    while cursor != start:
        parent, edge_id = previous[cursor]
        edges.append(edge_id)
        nodes.append(parent)
        cursor = parent
    nodes.reverse()
    edges.reverse()
    return Route(tuple(nodes), tuple(edges), destination, distances[destination])
