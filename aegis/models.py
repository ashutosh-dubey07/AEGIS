"""Small, explicit data models shared by the AEGIS simulation."""

from __future__ import annotations

from dataclasses import dataclass, field


@dataclass(frozen=True)
class PersonProfileSpec:
    """Illustrative movement and interface needs for the demo personas."""

    priority_bonus: float = 0.0
    movement_speed_factor: float = 1.0
    step_free_route: bool = False
    stair_cost_multiplier: float = 1.0
    caution_cost_multiplier: float = 1.0
    support_needs: str = "Standard evacuation guidance"
    communication_mode: str = "Standard visual instructions"
    priority_reason: str = "Standard routing priority"


PERSON_PROFILE_SPECS: dict[str, PersonProfileSpec] = {
    "Standard": PersonProfileSpec(),
    "Wheelchair user": PersonProfileSpec(
        priority_bonus=3.5,
        movement_speed_factor=0.82,
        step_free_route=True,
        support_needs="Step-free route using mapped accessible passages and evacuation lifts",
        communication_mode="Clear, large-text visual directions",
        priority_reason="Step-free evacuation support",
    ),
    "Limited mobility": PersonProfileSpec(
        priority_bonus=3.0,
        movement_speed_factor=0.68,
        stair_cost_multiplier=1.8,
        support_needs="Reduced movement pace; avoid unnecessary stair links",
        communication_mode="Large text with one route action at a time",
        priority_reason="Mobility assistance and slower movement",
    ),
    "Low vision": PersonProfileSpec(
        priority_bonus=2.8,
        movement_speed_factor=0.84,
        caution_cost_multiplier=1.35,
        support_needs="High-contrast route with explicit landmark directions",
        communication_mode="High-contrast, enlarged text with spoken-direction cue",
        priority_reason="Accessible navigation support",
    ),
    "Hard of hearing": PersonProfileSpec(
        priority_bonus=2.8,
        support_needs="Visual confirmation of alarms and route changes",
        communication_mode="Visual and text alerts; no audio-only instruction",
        priority_reason="Accessible alarm and communication support",
    ),
    "Pregnancy support": PersonProfileSpec(
        priority_bonus=2.8,
        movement_speed_factor=0.84,
        caution_cost_multiplier=1.2,
        support_needs="Higher route priority with a lower-exertion route preference",
        communication_mode="Clear, large-text visual directions",
        priority_reason="Pregnancy support profile",
    ),
}

INCLUSIVE_DEMO_PROFILES = (
    "Wheelchair user",
    "Limited mobility",
    "Low vision",
    "Hard of hearing",
    "Pregnancy support",
)


@dataclass(frozen=True)
class Node:
    id: str
    floor: int
    x: float
    y: float
    kind: str
    label: str
    exit_capacity: int = 0


@dataclass(frozen=True)
class Edge:
    id: str
    a: str
    b: str
    travel_time: float
    width_m: float
    capacity_per_step: int
    is_stair: bool = False
    is_narrow: bool = False
    is_accessible: bool = True
    is_evacuation_lift: bool = False


@dataclass
class Building:
    nodes: dict[str, Node]
    edges: dict[str, Edge]
    adjacency: dict[str, list[str]] = field(init=False)

    def __post_init__(self) -> None:
        self.adjacency = {node_id: [] for node_id in self.nodes}
        for edge in self.edges.values():
            if edge.a in self.adjacency:
                self.adjacency[edge.a].append(edge.id)
            if edge.b in self.adjacency:
                self.adjacency[edge.b].append(edge.id)

    def neighbors(self, node_id: str):
        """Yield (neighbor node, connecting edge) pairs in stable order."""
        for edge_id in sorted(self.adjacency.get(node_id, [])):
            edge = self.edges[edge_id]
            other_id = edge.b if edge.a == node_id else edge.a
            if other_id in self.nodes:
                yield self.nodes[other_id], edge


@dataclass
class Hazard:
    id: str
    incident_type: str
    target_id: str
    target_kind: str  # "node" or "edge"
    severity: str  # "block" or "caution"
    description: str
    intensity: float = 15.0
    growth_per_tick: float = 6.0
    spread_stage: int = 0
    spread_edges: list[str] = field(default_factory=list)

    @property
    def level(self) -> str:
        if self.intensity >= 85:
            return "Critical"
        if self.intensity >= 60:
            return "High"
        if self.intensity >= 35:
            return "Elevated"
        return "Low"


@dataclass
class Sensor:
    id: str
    target_id: str
    target_kind: str
    metric: str
    reading: float
    unit: str
    state: str = "Normal"
    label: str = ""


@dataclass
class Person:
    id: str
    start_node: str
    current_node: str
    status: str = "Waiting"
    priority_score: float = 0.0
    route: list[str] = field(default_factory=list)
    route_edges: list[str] = field(default_factory=list)
    assigned_exit: str | None = None
    reroutes: int = 0
    queued_ticks: int = 0
    queued_edge: str | None = None
    traversed_nodes: list[str] = field(default_factory=list)
    traversed_edges: list[str] = field(default_factory=list)
    movement_progress: float = 0.0
    backtracking: bool = False
    accessibility_profile: str = "Standard"

    def __post_init__(self) -> None:
        if self.accessibility_profile not in PERSON_PROFILE_SPECS:
            self.accessibility_profile = "Standard"
        if not self.traversed_nodes:
            self.traversed_nodes = [self.current_node]


@dataclass(frozen=True)
class Event:
    tick: int
    kind: str
    message: str


@dataclass
class SimulationState:
    building: Building
    seed: int
    people: list[Person] = field(default_factory=list)
    sensors: list[Sensor] = field(default_factory=list)
    hazards: list[Hazard] = field(default_factory=list)
    blocked_nodes: set[str] = field(default_factory=set)
    blocked_edges: set[str] = field(default_factory=set)
    caution_nodes: set[str] = field(default_factory=set)
    caution_edges: set[str] = field(default_factory=set)
    event_log: list[Event] = field(default_factory=list)
    tick: int = 0
    running: bool = False
    rerouted_total: int = 0
    last_replan_tick: int = -100
