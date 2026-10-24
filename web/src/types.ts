export type NodeKind = "room" | "junction" | "stairs" | "exit";
export type FloorFilter = "all" | number;

export interface BuildingNode {
  id: string;
  floor: number;
  x: number;
  z: number;
  kind: NodeKind;
  label: string;
  exit_capacity: number;
  blocked: boolean;
  caution: boolean;
}

export interface BuildingEdge {
  id: string;
  a: string;
  b: string;
  travel_time: number;
  width_m: number;
  capacity: number;
  is_stair: boolean;
  is_narrow: boolean;
  blocked: boolean;
  caution: boolean;
}

export interface Person {
  id: string;
  start_node: string;
  current_node: string;
  status: string;
  priority: number;
  route: string[];
  route_edges: string[];
  traversed_edges: string[];
  assigned_exit: string | null;
  reroutes: number;
  queued_edge: string | null;
  movement_progress: number;
  backtracking: boolean;
  assistance_reason: string | null;
  assistance_blockers: string[];
}

export interface Sensor {
  id: string;
  target_id: string;
  target_kind: "node" | "edge";
  metric: string;
  reading: number;
  unit: string;
  state: "Normal" | "Warning" | "Alarm";
  label: string;
}

export interface Hazard {
  id: string;
  incident_type: string;
  target_id: string;
  target_kind: "node" | "edge";
  intensity: number;
  level: string;
}

export interface SimEvent {
  tick: number;
  kind: string;
  message: string;
}

export interface Snapshot {
  session_id: string;
  seed: number;
  profile: string;
  tick: number;
  running: boolean;
  rerouted_total: number;
  floors: { index: number; label: string }[];
  nodes: BuildingNode[];
  edges: BuildingEdge[];
  people: Person[];
  sensors: Sensor[];
  hazards: Hazard[];
  events: SimEvent[];
  movement_ticks_per_unit: number;
  receivedAt: number;
}

export interface ServiceLink {
  id: string;
  name: string;
  number: string;
  description: string;
  source: string;
}

export interface AppConfig {
  profiles: string[];
  incident_types: string[];
  services: ServiceLink[];
  ai_configured: boolean;
  ai_provider: string;
}

export interface ScenarioOptions {
  person_count: number;
  seed?: number;
  incident_type: string;
  building_profile: string;
  floors?: number;
  rooms_per_wing?: number;
}

export interface AIReviewItem {
  text: string;
  evidence: { id: string; label: string }[];
}

export interface AIReview {
  provider: string;
  model: string;
  tick: number;
  person_id: string;
  observations: AIReviewItem[];
  operator_checks: AIReviewItem[];
  evidence_mode: string;
}
