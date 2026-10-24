import { useMemo, useRef, useState, type ComponentRef } from "react";
import { Canvas, useFrame } from "@react-three/fiber";
import { Grid, Html, Line, OrbitControls } from "@react-three/drei";
import * as THREE from "three";
import type { BuildingEdge, BuildingNode, FloorFilter, Person, Snapshot } from "./types";

const floorHeight = 3.7;
const pointOf = (node: BuildingNode): [number, number, number] => [node.x - 11, node.floor * floorHeight, node.z - 7];

interface Props {
  snapshot: Snapshot;
  selectedId: string;
  floorFilter: FloorFilter;
  followPerson: boolean;
  onSelectPerson: (id: string) => void;
}

export default function BuildingScene({ snapshot, selectedId, floorFilter, followPerson, onSelectPerson }: Props) {
  const [hovered, setHovered] = useState("");
  const nodeMap = useMemo(() => new Map(snapshot.nodes.map((node) => [node.id, node])), [snapshot.nodes]);
  const edgeMap = useMemo(() => new Map(snapshot.edges.map((edge) => [edge.id, edge])), [snapshot.edges]);
  const selected = snapshot.people.find((person) => person.id === selectedId) ?? null;
  const focusY = floorFilter === "all"
    ? ((snapshot.floors.at(-1)?.index ?? 0) * floorHeight) / 2
    : floorFilter * floorHeight;
  const cameraPosition: [number, number, number] = followPerson
    ? [11, 8, 14]
    : floorFilter === "all" ? [26, focusY + 18, 32] : [14, focusY + 11, 21];

  return (
    <div className="three-canvas-wrap">
      <Canvas
        key={snapshot.session_id}
        dpr={[1, 1.25]}
        camera={{ position: cameraPosition, fov: floorFilter === "all" ? 43 : 40, near: 0.1, far: 180 }}
        gl={{ antialias: true, alpha: false }}
      >
        <color attach="background" args={["#edf1f4"]} />
        <ambientLight intensity={1.35} />
        <directionalLight position={[8, 20, 12]} intensity={1.6} />
        <directionalLight position={[-12, 9, -10]} intensity={0.45} />
        <SceneContent
          snapshot={snapshot}
          nodeMap={nodeMap}
          edgeMap={edgeMap}
          selected={selected}
          floorFilter={floorFilter}
          onSelectPerson={onSelectPerson}
          onHover={setHovered}
        />
        <SceneCamera
          snapshot={snapshot}
          selected={selected}
          selectedId={selectedId}
          followPerson={followPerson}
          floorFilter={floorFilter}
          floorCenterY={focusY}
        />
      </Canvas>
      {hovered && <div className="scene-hover-label">{hovered}</div>}
    </div>
  );
}

function SceneCamera({
  snapshot, selected, selectedId, followPerson, floorFilter, floorCenterY,
}: {
  snapshot: Snapshot;
  selected: Person | null;
  selectedId: string;
  followPerson: boolean;
  floorFilter: FloorFilter;
  floorCenterY: number;
}) {
  const controlsRef = useRef<ComponentRef<typeof OrbitControls>>(null);
  const nodeMap = useMemo(() => new Map(snapshot.nodes.map((node) => [node.id, node])), [snapshot.nodes]);
  const edgeMap = useMemo(() => new Map(snapshot.edges.map((edge) => [edge.id, edge])), [snapshot.edges]);
  const previousFollow = useRef(followPerson);
  const previousSelectedId = useRef(selectedId);
  const previousFloor = useRef(floorFilter);
  const transitionDistance = useRef<number | null>(null);

  useFrame((_, delta) => {
    const controls = controlsRef.current;
    if (!controls) return;

    const focusChanged = followPerson !== previousFollow.current || selectedId !== previousSelectedId.current;
    const floorChanged = floorFilter !== previousFloor.current;
    if (focusChanged) {
      const currentDistance = controls.object.position.distanceTo(controls.target);
      transitionDistance.current = followPerson
        ? (currentDistance > 25 ? 18 : THREE.MathUtils.clamp(currentDistance, 13, 20))
        : floorFilter === "all" ? 42 : 27;
    } else if (floorChanged && !followPerson) {
      transitionDistance.current = floorFilter === "all" ? 42 : 27;
    }
    previousFollow.current = followPerson;
    previousSelectedId.current = selectedId;
    previousFloor.current = floorFilter;

    let desiredTarget: THREE.Vector3;
    if (followPerson && selected) {
      const edgeId = selected.route_edges[0];
      const edge = edgeId ? edgeMap.get(edgeId) : undefined;
      const point = getPersonPoint(selected, snapshot, nodeMap, edge);
      desiredTarget = new THREE.Vector3(point[0], point[1] + 0.5, point[2]);
    } else {
      desiredTarget = new THREE.Vector3(0, floorCenterY, 0);
    }

    const targetAlpha = 1 - Math.exp(-8 * Math.max(0, delta));
    const targetShift = desiredTarget.sub(controls.target).multiplyScalar(targetAlpha);
    controls.target.add(targetShift);
    controls.object.position.add(targetShift);

    if (transitionDistance.current !== null) {
      const offset = controls.object.position.clone().sub(controls.target);
      if (offset.lengthSq() > 0.001) {
        const distance = THREE.MathUtils.damp(offset.length(), transitionDistance.current, 6, delta);
        offset.setLength(distance);
        controls.object.position.copy(controls.target).add(offset);
        if (Math.abs(distance - transitionDistance.current) < 0.15) transitionDistance.current = null;
      }
    }
    controls.update();
  });

  return (
    <OrbitControls
      ref={controlsRef}
      makeDefault
      zoomToCursor
      enableDamping
      dampingFactor={0.12}
      minDistance={8}
      maxDistance={64}
      maxPolarAngle={Math.PI * 0.49}
    />
  );
}

function SceneContent({
  snapshot, nodeMap, edgeMap, selected, floorFilter, onSelectPerson, onHover,
}: {
  snapshot: Snapshot;
  nodeMap: Map<string, BuildingNode>;
  edgeMap: Map<string, BuildingEdge>;
  selected: Person | null;
  floorFilter: FloorFilter;
  onSelectPerson: (id: string) => void;
  onHover: (label: string) => void;
}) {
  const visibleFloor = (floor: number) => floorFilter === "all" || floor === floorFilter;
  const traversed = selected?.traversed_edges ?? [];
  const visibleEdges = snapshot.edges.filter((edge) => {
    const a = nodeMap.get(edge.a);
    const b = nodeMap.get(edge.b);
    return a && b && (visibleFloor(a.floor) || ((edge.is_stair || edge.is_evacuation_lift) && visibleFloor(b.floor)));
  });
  const visibleNodes = snapshot.nodes.filter((node) => visibleFloor(node.floor));
  const selectedStart = selected?.route[0] ? nodeMap.get(selected.route[0]) : undefined;
  const selectedNext = selected?.route[1] ? nodeMap.get(selected.route[1]) : undefined;
  const currentEdge = selected?.route_edges[0] ? edgeMap.get(selected.route_edges[0]) : undefined;
  const actorPosition = selected && selectedStart
    ? getPersonPoint(selected, snapshot, nodeMap, currentEdge)
    : null;

  return (
    <>
      {snapshot.floors.filter((floor) => visibleFloor(floor.index)).map((floor) => {
        const y = floor.index * floorHeight - 0.18;
        return <group key={`floor-${floor.index}`}>
          <mesh rotation={[-Math.PI / 2, 0, 0]} position={[0, y, 0]} receiveShadow>
            <planeGeometry args={[22.8, 13.8]} />
            <meshStandardMaterial color="#f8fafb" roughness={0.96} />
          </mesh>
          <Grid
            position={[0, y + 0.008, 0]}
            args={[22.8, 13.8]}
            cellSize={1.2}
            cellThickness={0.38}
            cellColor="#dfe5e9"
            sectionSize={4.8}
            sectionThickness={0.7}
            sectionColor="#cad4dc"
            fadeDistance={28}
            infiniteGrid={false}
          />
          <mesh position={[0, floor.index * floorHeight - 0.3, 0]}>
            <boxGeometry args={[23, 0.12, 14]} />
            <meshStandardMaterial color="#dfe5e9" roughness={0.9} />
          </mesh>
        </group>;
      })}

      {visibleEdges.map((edge) => {
        const a = nodeMap.get(edge.a)!;
        const b = nodeMap.get(edge.b)!;
        const color = edge.blocked ? "#b94545" : edge.caution ? "#c5872c" : edge.is_evacuation_lift ? "#577a9b" : edge.is_narrow ? "#8995a0" : "#abb6bf";
        return <Beam key={edge.id} a={a} b={b} color={color} radius={edge.is_stair || edge.is_evacuation_lift ? 0.11 : edge.is_narrow ? 0.07 : 0.055} />;
      })}

      {visibleNodes.map((node) => (
        <BuildingNodeMesh key={node.id} node={node} onHover={onHover} />
      ))}

      {selected && actorPosition && selectedStart && selectedNext && currentEdge && (
        <>
          {traversed.map((edgeId) => {
            const edge = edgeMap.get(edgeId);
            const a = edge && nodeMap.get(edge.a);
            const b = edge && nodeMap.get(edge.b);
            return edge && a && b && (visibleFloor(a.floor) || visibleFloor(b.floor))
              ? <RouteLine key={`traveled-${edgeId}`} points={[pointOf(a), pointOf(b)]} color="#778594" width={4} />
              : null;
          })}
          {!selected.backtracking && selected.movement_progress > 0.005 && (
            <RouteLine points={[pointOf(selectedStart), actorPosition]} color="#778594" width={4} />
          )}
          {selected.route_edges.map((edgeId, index) => {
            const edge = edgeMap.get(edgeId);
            const a = edge && nodeMap.get(edge.a);
            const b = edge && nodeMap.get(edge.b);
            if (!edge || !a || !b || (floorFilter !== "all" && !visibleFloor(a.floor) && !visibleFloor(b.floor))) return null;
            if (index === 0 && selected.movement_progress > 0.005) {
              return <RouteLine key={`route-${edgeId}`} points={[actorPosition, pointOf(selected.backtracking ? selectedStart : selectedNext)]} color="#3478c6" width={6} />;
            }
            const routeFrom = nodeMap.get(selected.route[index]);
            const routeTo = nodeMap.get(selected.route[index + 1]);
            if (!routeFrom || !routeTo || (index === 0 && selected.backtracking)) return null;
            return <RouteLine key={`route-${edgeId}`} points={[pointOf(routeFrom), pointOf(routeTo)]} color="#3478c6" width={6} />;
          })}
        </>
      )}

      {snapshot.hazards.map((hazard) => {
        const target = hazard.target_kind === "node" ? nodeMap.get(hazard.target_id) : undefined;
        const edge = hazard.target_kind === "edge" ? edgeMap.get(hazard.target_id) : undefined;
        const a = edge && nodeMap.get(edge.a);
        const b = edge && nodeMap.get(edge.b);
        const at = target ? pointOf(target) : a && b ? midpoint(pointOf(a), pointOf(b)) : null;
        if (!at || (floorFilter !== "all" && target?.floor !== floorFilter && a?.floor !== floorFilter && b?.floor !== floorFilter)) return null;
        return <mesh key={hazard.id} position={[at[0], at[1] + 0.45, at[2]]}>
          <sphereGeometry args={[0.38 + hazard.intensity / 280, 20, 20]} />
          <meshStandardMaterial color="#b94545" transparent opacity={0.2} emissive="#8e3434" emissiveIntensity={0.22} />
        </mesh>;
      })}

      {snapshot.sensors.filter((sensor) => sensor.state !== "Normal").map((sensor) => {
        const node = sensor.target_kind === "node" ? nodeMap.get(sensor.target_id) : undefined;
        const edge = sensor.target_kind === "edge" ? edgeMap.get(sensor.target_id) : undefined;
        const a = edge && nodeMap.get(edge.a);
        const b = edge && nodeMap.get(edge.b);
        const at = node ? pointOf(node) : a && b ? midpoint(pointOf(a), pointOf(b)) : null;
        if (!at || (floorFilter !== "all" && node?.floor !== floorFilter && a?.floor !== floorFilter && b?.floor !== floorFilter)) return null;
        return <mesh key={sensor.id} position={[at[0] + 0.3, at[1] + 0.5, at[2] + 0.3]}>
          <octahedronGeometry args={[sensor.state === "Alarm" ? 0.22 : 0.16, 0]} />
          <meshStandardMaterial color={sensor.state === "Alarm" ? "#b94545" : "#cf8b28"} emissive={sensor.state === "Alarm" ? "#8e3434" : "#a87523"} emissiveIntensity={0.28} />
        </mesh>;
      })}

      {snapshot.people.map((person) => {
        const node = nodeMap.get(person.current_node);
        if (!node || !visibleFloor(node.floor)) return null;
        return <PersonMarker
          key={person.id}
          person={person}
          snapshot={snapshot}
          nodeMap={nodeMap}
          edgeMap={edgeMap}
          selected={person.id === selected?.id}
          onSelect={() => onSelectPerson(person.id)}
          onHover={onHover}
        />;
      })}

    </>
  );
}

function BuildingNodeMesh({ node, onHover }: { node: BuildingNode; onHover: (label: string) => void }) {
  const [x, y, z] = pointOf(node);
  const color = node.blocked ? "#b94545" : node.caution ? "#d59a43" : node.kind === "exit" ? "#19816e" : node.kind === "stairs" ? "#768797" : node.kind === "lift" ? "#4d789d" : node.kind === "junction" ? "#cbd4dc" : "#e8edf1";
  const geometry = node.kind === "room" ? <boxGeometry args={[1.15, 0.44, 0.92]} />
    : node.kind === "exit" ? <boxGeometry args={[0.9, 0.48, 0.8]} />
      : node.kind === "stairs" ? <boxGeometry args={[0.65, 1.5, 0.65]} />
        : node.kind === "lift" ? <boxGeometry args={[0.78, 1.15, 0.78]} />
        : <cylinderGeometry args={[0.27, 0.3, 0.18, 12]} />;
  return <mesh position={[x, y + (node.kind === "stairs" ? 0.72 : node.kind === "lift" ? 0.55 : 0.09), z]} castShadow receiveShadow
    onPointerOver={(event) => { event.stopPropagation(); onHover(`${node.label} · ${node.kind}`); }}
    onPointerOut={() => onHover("")}
  >
    {geometry}
    <meshStandardMaterial color={color} roughness={0.75} metalness={0.02} />
  </mesh>;
}

function Beam({ a, b, color, radius }: { a: BuildingNode; b: BuildingNode; color: string; radius: number }) {
  const start = new THREE.Vector3(...pointOf(a));
  const end = new THREE.Vector3(...pointOf(b));
  const direction = new THREE.Vector3().subVectors(end, start);
  const length = direction.length();
  const quaternion = new THREE.Quaternion().setFromUnitVectors(new THREE.Vector3(0, 1, 0), direction.clone().normalize());
  const position = new THREE.Vector3().addVectors(start, end).multiplyScalar(0.5);
  return <mesh position={position} quaternion={quaternion}>
    <cylinderGeometry args={[radius, radius, length, 8]} />
    <meshStandardMaterial color={color} roughness={0.84} />
  </mesh>;
}

function RouteLine({ points, color, width }: { points: [number, number, number][]; color: string; width: number }) {
  const raisedPoints = points.map((point): [number, number, number] => [point[0], point[1] + 0.24, point[2]]);
  return <Line points={raisedPoints} color={color} lineWidth={width} transparent opacity={0.96} depthTest={false} />;
}

function PersonMarker({
  person, snapshot, nodeMap, edgeMap, selected, onSelect, onHover,
}: {
  person: Person;
  snapshot: Snapshot;
  nodeMap: Map<string, BuildingNode>;
  edgeMap: Map<string, BuildingEdge>;
  selected: boolean;
  onSelect: () => void;
  onHover: (label: string) => void;
}) {
  const mesh = useRef<THREE.Mesh>(null);
  const hasAccessibilityProfile = person.accessibility_profile !== "Standard";
  const markerColor = person.status === "Needs Assistance" ? "#171a1d" : hasAccessibilityProfile ? "#db5b91" : selected ? "#7b4bb7" : "#18834b";
  useFrame(() => {
    if (!mesh.current) return;
    const edgeId = person.route_edges[0];
    const edge = edgeId ? edgeMap.get(edgeId) : undefined;
    const point = getPersonPoint(person, snapshot, nodeMap, edge);
    mesh.current.position.set(point[0], point[1] + 0.5, point[2]);
  });
  return <mesh ref={mesh} position={[0, 0.5, 0]} onClick={(event) => { event.stopPropagation(); onSelect(); }}
    onPointerOver={(event) => { event.stopPropagation(); onHover(`${person.id} · ${person.accessibility_profile} · ${person.status}`); }}
    onPointerOut={() => onHover("")}
  >
    <sphereGeometry args={[selected ? 0.27 : 0.21, 12, 12]} />
    <meshStandardMaterial color={markerColor} emissive={markerColor} emissiveIntensity={person.status === "Needs Assistance" ? 0 : selected ? 0.15 : 0.04} roughness={0.38} />
    {selected && <mesh scale={1.6}><sphereGeometry args={[0.27, 12, 12]} /><meshBasicMaterial color="#a68aca" transparent opacity={0.2} depthWrite={false} /></mesh>}
    {selected && <Html position={[0, 0.58, 0]} center distanceFactor={18} style={{ pointerEvents: "none" }}>
      <div className="scene-person-label">{person.id} Â· {person.accessibility_profile}</div>
    </Html>}
  </mesh>;
}

function getPersonPoint(
  person: Person,
  snapshot: Snapshot,
  nodeMap: Map<string, BuildingNode>,
  edge: BuildingEdge | undefined,
): [number, number, number] {
  const current = nodeMap.get(person.current_node);
  if (!current) return [0, 0, 0];
  const nextId = person.route[1];
  const next = nextId ? nodeMap.get(nextId) : undefined;
  if (!next || !edge) return pointOf(current);
  const duration = Math.max(snapshot.movement_ticks_per_unit, Math.ceil(edge.travel_time * snapshot.movement_ticks_per_unit / Math.max(0.1, person.movement_speed_factor)));
  const elapsed = Math.max(0, Math.min(0.99, (performance.now() - snapshot.receivedAt) / 1000));
  let progress = person.movement_progress;
  if (snapshot.running && person.status === "Moving") {
    progress += (person.backtracking ? -1 : 1) * elapsed / duration;
  }
  progress = THREE.MathUtils.clamp(progress, 0, 1);
  const from = pointOf(current);
  const to = pointOf(next);
  return [
    THREE.MathUtils.lerp(from[0], to[0], progress),
    THREE.MathUtils.lerp(from[1], to[1], progress),
    THREE.MathUtils.lerp(from[2], to[2], progress),
  ];
}

function midpoint(a: [number, number, number], b: [number, number, number]): [number, number, number] {
  return [(a[0] + b[0]) / 2, (a[1] + b[1]) / 2, (a[2] + b[2]) / 2];
}
