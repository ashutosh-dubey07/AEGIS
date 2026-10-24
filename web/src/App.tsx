import { useCallback, useEffect, useMemo, useRef, useState } from "react";
import type { ReactNode } from "react";
import {
  Activity, AlertTriangle, Check, ChevronDown, Copy,
  PhoneCall, PhoneOff, Plus, Radio, RotateCcw,
} from "lucide-react";
import {
  analyzeScenario, createEmergencyBrief, createScenario, getConfig,
  sendCommand, streamUrl,
} from "./api";
import BuildingScene from "./BuildingScene";
import type { AIReview, AppConfig, FloorFilter, Person, ScenarioOptions, Snapshot } from "./types";

const stamp = (snapshot: Snapshot): Snapshot => ({ ...snapshot, receivedAt: performance.now() });

export default function App() {
  const socketRef = useRef<WebSocket | null>(null);
  const snapshotRef = useRef<Snapshot | null>(null);
  const [config, setConfig] = useState<AppConfig | null>(null);
  const [snapshot, setSnapshot] = useState<Snapshot | null>(null);
  const [selectedId, setSelectedId] = useState("P01");
  const [floorFilter, setFloorFilter] = useState<FloorFilter>("all");
  const [followPerson, setFollowPerson] = useState(true);
  const [personCount, setPersonCount] = useState(8);
  const [seed, setSeed] = useState("");
  const [incidentType, setIncidentType] = useState("Random incident");
  const [profile, setProfile] = useState("Office");
  const [floors, setFloors] = useState(3);
  const [roomsPerWing, setRoomsPerWing] = useState(4);
  const [sensorId, setSensorId] = useState("__random__");
  const [aiReview, setAiReview] = useState<AIReview | null>(null);
  const [siteAddress, setSiteAddress] = useState("");
  const [callbackNumber, setCallbackNumber] = useState("");
  const [briefText, setBriefText] = useState("");
  const [notice, setNotice] = useState("");
  const [error, setError] = useState("");
  const [busy, setBusy] = useState(false);
  const [copied, setCopied] = useState(false);

  const acceptSnapshot = useCallback((next: Snapshot) => {
    const current = snapshotRef.current;
    if (current?.session_id === next.session_id && current.tick > next.tick) return;
    snapshotRef.current = next;
    setSnapshot(next);
  }, []);

  const connect = useCallback((sessionId: string) => {
    socketRef.current?.close();
    const socket = new WebSocket(streamUrl(sessionId));
    socketRef.current = socket;
    socket.onmessage = (event) => {
      try {
        if (socketRef.current !== socket) return;
        const next = stamp(JSON.parse(event.data) as Snapshot);
        const current = snapshotRef.current;
        if (!current || current.session_id !== next.session_id || current.tick >= next.tick) return;
        acceptSnapshot(next);
        setSelectedId((current) => next.people.some((person) => person.id === current) ? current : next.people[0]?.id ?? "");
        setError("");
      } catch {
        setError("The live simulation update could not be read.");
      }
    };
    socket.onerror = () => setError("Live connection lost. Check that the Python server is running.");
  }, [acceptSnapshot]);

  const createNewScenario = useCallback(async (overrides: Partial<ScenarioOptions> = {}) => {
    setBusy(true);
    setError("");
    setNotice("");
    try {
      const options: ScenarioOptions = {
        person_count: personCount,
        seed: seed.trim() ? Number(seed) : undefined,
        incident_type: incidentType,
        building_profile: profile,
        floors,
        rooms_per_wing: roomsPerWing,
        ...overrides,
      };
      const next = stamp(await createScenario(options));
      acceptSnapshot(next);
      setSelectedId(next.people[0]?.id ?? "");
      setFloorFilter("all");
      setFollowPerson(true);
      setAiReview(null);
      connect(next.session_id);
      setNotice(`New ${next.profile.toLowerCase()} scenario ready · seed ${next.seed}.`);
    } catch (cause) {
      setError(cause instanceof Error ? cause.message : "Could not create the scenario.");
    } finally {
      setBusy(false);
    }
  }, [acceptSnapshot, connect, floors, incidentType, personCount, profile, roomsPerWing, seed]);

  useEffect(() => {
    let mounted = true;
    Promise.all([
      getConfig(),
      createScenario({ person_count: 8, incident_type: "Random incident", building_profile: "Office" }),
    ]).then(([nextConfig, nextSnapshot]) => {
      if (!mounted) return;
      setConfig(nextConfig);
      const prepared = stamp(nextSnapshot);
      acceptSnapshot(prepared);
      setSelectedId(prepared.people[0]?.id ?? "");
      connect(prepared.session_id);
    }).catch((cause: unknown) => {
      if (mounted) setError(cause instanceof Error ? cause.message : "Could not connect to the local AEGIS server.");
    });
    return () => {
      mounted = false;
      socketRef.current?.close();
    };
  }, [acceptSnapshot, connect]);

  const selectedPerson = useMemo(
    () => snapshot?.people.find((person) => person.id === selectedId) ?? null,
    [snapshot, selectedId],
  );
  useEffect(() => setAiReview(null), [selectedId]);
  useEffect(() => {
    if (!followPerson || !selectedPerson || !snapshot) return;
    const floor = snapshot.nodes.find((node) => node.id === selectedPerson.current_node)?.floor;
    if (floor !== undefined && floorFilter !== floor) setFloorFilter(floor);
  }, [followPerson, floorFilter, selectedPerson, snapshot]);
  const directTargets = useMemo(() => new Set(
    snapshot?.hazards.map((hazard) => `${hazard.target_kind}:${hazard.target_id}`) ?? [],
  ), [snapshot]);
  const availableSensors = useMemo(() => (snapshot?.sensors ?? []).filter((sensor) =>
    sensor.state !== "Alarm" && !directTargets.has(`${sensor.target_kind}:${sensor.target_id}`)
      && !snapshot?.nodes.find((node) => node.id === sensor.target_id)?.blocked
      && !snapshot?.edges.find((edge) => edge.id === sensor.target_id)?.blocked,
  ), [directTargets, snapshot]);
  const activeCount = snapshot?.people.filter((person) => ["Waiting", "Moving", "Queued", "Needs Assistance"].includes(person.status)).length ?? 0;
  const evacuatedCount = snapshot?.people.filter((person) => person.status === "Evacuated").length ?? 0;
  const queuedCount = snapshot?.people.filter((person) => person.status === "Queued").length ?? 0;
  const assistanceCount = snapshot?.people.filter((person) => person.status === "Needs Assistance").length ?? 0;
  const assistancePeople = useMemo(
    () => snapshot?.people.filter((person) => person.status === "Needs Assistance") ?? [],
    [snapshot],
  );
  const assistanceLocations = useMemo(() => {
    const groups = new Map<string, { nodeId: string; label: string; floor: number; people: Person[] }>();
    for (const person of assistancePeople) {
      const node = snapshot?.nodes.find((item) => item.id === person.current_node);
      const group = groups.get(person.current_node) ?? {
        nodeId: person.current_node,
        label: node?.label ?? person.current_node,
        floor: node?.floor ?? 0,
        people: [],
      };
      group.people.push(person);
      groups.set(person.current_node, group);
    }
    return Array.from(groups.values()).sort((a, b) => a.floor - b.floor || a.label.localeCompare(b.label));
  }, [assistancePeople, snapshot]);
  const activeAlarmCount = snapshot?.sensors.filter((sensor) => sensor.state === "Alarm").length ?? 0;

  async function runCommand(action: "start" | "pause" | "step" | "alarm", targetSensor?: string) {
    if (!snapshot) return;
    setError("");
    setNotice("");
    try {
      const next = stamp(await sendCommand(snapshot.session_id, action, targetSensor));
      if (snapshotRef.current?.session_id !== next.session_id) return;
      acceptSnapshot(next);
      if (action === "alarm") {
        setAiReview(null);
        setNotice("Sensor alarm registered; routes are being recalculated.");
      }
    } catch (cause) {
      setError(cause instanceof Error ? cause.message : "The command could not be completed.");
    }
  }

  async function triggerAlarm() {
    if (!snapshot || availableSensors.length === 0) return;
    const target = sensorId === "__random__"
      ? availableSensors[Math.floor(Math.random() * availableSensors.length)]
      : availableSensors.find((sensor) => sensor.id === sensorId);
    if (target) await runCommand("alarm", target.id);
  }

  async function requestAIReview() {
    if (!snapshot || !selectedPerson) return;
    setBusy(true);
    setError("");
    setNotice("");
    try {
      const review = await analyzeScenario(snapshot.session_id, selectedPerson.id);
      setAiReview(review);
      setNotice(`AI reviewed simulation tick ${review.tick} for ${review.person_id}.`);
    } catch (cause) {
      setError(cause instanceof Error ? cause.message : "AI simulation review failed.");
    } finally {
      setBusy(false);
    }
  }

  async function prepareBrief() {
    if (!snapshot) return;
    setError("");
    try {
      const result = await createEmergencyBrief(snapshot.session_id, siteAddress, callbackNumber);
      setBriefText(result.text);
      setCopied(false);
    } catch (cause) {
      setError(cause instanceof Error ? cause.message : "Could not prepare the report.");
    }
  }

  async function copyBrief() {
    if (!briefText) return;
    try {
      await navigator.clipboard.writeText(briefText);
      setCopied(true);
    } catch {
      setError("Clipboard access was denied. Select and copy the draft text manually.");
    }
  }

  return (
    <main className="app-shell">
      <header className="topbar">
        <div aria-hidden="true" />
        <div className="brand-lockup">
          <div className="brand-name">AEGIS</div>
          <div className="brand-tagline">Every Second Counts. Every Route Adapts</div>
        </div>
        <div className="topbar-meta">
          <span className={`connection-dot ${snapshot ? "is-live" : ""}`} />
          <span>{snapshot?.running ? "Simulation live" : snapshot ? "Simulation paused" : "Connecting"}</span>
          <span>LOCAL SESSION</span>
        </div>
      </header>

      <section className="notice-strip">
        <span>Simulation only. People, buildings, hazards, and sensor data are generated; this is not a real emergency service.</span>
      </section>

      {error && <div className="toast toast-error"><AlertTriangle size={16} />{error}</div>}
      {notice && !error && <div className="toast toast-note"><Check size={16} />{notice}</div>}

      <section className="metrics-row">
        <Metric label="PEOPLE ACTIVE" value={activeCount} />
        <Metric label="EVACUATED" value={evacuatedCount} tone="green" />
        <Metric label="QUEUED" value={queuedCount} tone="amber" />
        <Metric label="ROUTES CHANGED" value={snapshot?.rerouted_total ?? 0} />
        <Metric label="NEED ASSISTANCE" value={assistanceCount} tone="red" />
      </section>

      <section className="assistance-overview" aria-label="People needing assistance">
        <section className="panel assistance-panel">
          <div className="panel-title-row">
            <div><div className="eyebrow">ROUTE FAILURE DETAILS</div><h2>Why assistance is needed</h2></div>
            <span className="quiet-label">{assistancePeople.length} PEOPLE</span>
          </div>
          {assistancePeople.length ? <div className="assistance-case-list">
            {assistancePeople.map((person) => {
              const node = snapshot?.nodes.find((item) => item.id === person.current_node);
              return <article className="assistance-case" key={person.id}>
                <div className="assistance-case-heading">
                  <div><strong>{person.id}</strong><span>{node?.label ?? person.current_node} · {node?.floor === 0 ? "Ground" : `Floor ${node?.floor ?? "?"}`}</span></div>
                  <button className="assistance-inspect" onClick={() => { setSelectedId(person.id); setFollowPerson(true); }}>Inspect</button>
                </div>
                <p className="assistance-reason">{person.assistance_reason ?? "No safe route to an exit is currently available."}</p>
                {person.assistance_blockers.length > 0 && <ul className="assistance-blockers">
                  {person.assistance_blockers.map((blocker) => <li key={blocker}>{blocker}</li>)}
                </ul>}
              </article>;
            })}
          </div> : <p className="empty-state">No people currently need assistance.</p>}
        </section>

        <section className="panel assistance-panel">
          <div className="panel-title-row">
            <div><div className="eyebrow">CURRENT POSITIONS</div><h2>Where they are stuck</h2></div>
            <span className="quiet-label">{assistanceLocations.length} LOCATIONS</span>
          </div>
          {assistanceLocations.length ? <div className="assistance-location-list">
            {assistanceLocations.map((group) => (
              <div className="assistance-location" key={group.nodeId}>
                <div><strong>{group.label}</strong><span>{group.floor === 0 ? "Ground" : `Floor ${group.floor}`} · {group.people.length} {group.people.length === 1 ? "person" : "people"}</span></div>
                <div className="assistance-person-chips">
                  {group.people.map((person) => <button key={person.id} onClick={() => { setSelectedId(person.id); setFollowPerson(true); }}>{person.id}</button>)}
                </div>
              </div>
            ))}
          </div> : <p className="empty-state">Locations will appear here if someone needs assistance.</p>}
        </section>
      </section>

      <section className="workspace-grid">
        <div className="primary-column">
          <section className="panel simulation-panel">
            <div className="panel-heading">
              <div><div className="eyebrow">LIVE SCENE</div><h1>Building evacuation</h1></div>
              <div className="scene-badges"><span>{snapshot?.profile ?? profile}</span><span>{snapshot?.floors.length ?? floors} floors</span><span>Seed {snapshot?.seed ?? "—"}</span></div>
            </div>
            <div className="scene-toolbar">
              <div className="floor-tabs" role="group" aria-label="Building floor view">
                <button className={floorFilter === "all" ? "active" : ""} onClick={() => { setFollowPerson(false); setFloorFilter("all"); }}>All floors</button>
                {snapshot?.floors.map((floor) => (
                  <button key={floor.index} className={floorFilter === floor.index ? "active" : ""} onClick={() => { setFollowPerson(false); setFloorFilter(floor.index); }}>{floor.label}</button>
                ))}
              </div>
              <div className="scene-tools-note">Drag to orbit · scroll to zoom toward the pointer · click a person to inspect</div>
            </div>
            <div className="scene-and-person">
              <div className="scene-view">
                {snapshot ? (
                  <BuildingScene
                    snapshot={snapshot}
                    selectedId={selectedId}
                    floorFilter={floorFilter}
                    onSelectPerson={(id) => { setSelectedId(id); setFollowPerson(true); }}
                  />
                ) : <div className="scene-loading">Starting local simulation…</div>}
                <div className="scene-scale">3D BUILDING MODEL <span>·</span> LIVE ROUTES</div>
              </div>
              <aside className="person-rail">
                <div className="eyebrow">PERSON VIEW</div>
                <label className="field-label" htmlFor="person-select">Inspect individual</label>
                <div className="select-wrap">
                  <select id="person-select" value={selectedId} onChange={(event) => setSelectedId(event.target.value)}>
                    {snapshot?.people.map((person) => <option key={person.id} value={person.id}>{person.id} · {snapshot.nodes.find((node) => node.id === person.current_node)?.label ?? person.current_node}</option>)}
                  </select><ChevronDown size={15} />
                </div>
                <label className="toggle-line"><input type="checkbox" checked={followPerson} onChange={(event) => setFollowPerson(event.target.checked)} /><span>Follow their floor</span></label>
                {selectedPerson && <PersonCard person={selectedPerson} snapshot={snapshot!} />}
                <div className="person-rail-hint">Select a marker in the building or use this list.</div>
              </aside>
            </div>
            <div className="map-legend">
              <Legend color="#18834b" label="Person" /><Legend color="#7b4bb7" label="Selected person" />
              <Legend color="#171a1d" label="Needs assistance" />
              <Legend color="#3478c6" label="Route ahead" /><Legend color="#8995a3" label="Covered" />
              <Legend color="#bf4545" label="Closed / alarm" /><Legend color="#cf8b28" label="Sensor / caution" />
              <Legend color="#19816e" label="Exit" />
            </div>
          </section>

          <section className="panel navigation-panel">
            <div className="panel-title-row"><div><div className="eyebrow">ROUTE GUIDANCE</div><h2>Selected person</h2></div><span className="route-status">{selectedPerson?.status ?? "—"}</span></div>
            {selectedPerson && snapshot && <NavigationCard person={selectedPerson} snapshot={snapshot} />}
          </section>

          <section className="panel event-panel">
            <div className="panel-title-row"><div><div className="eyebrow">SYSTEM DECISIONS</div><h2>Event timeline</h2></div><span className="quiet-label">LATEST {snapshot?.events.length ?? 0}</span></div>
            <div className="timeline-list">
              {[...(snapshot?.events ?? [])].reverse().slice(0, 8).map((event, index) => (
                <div className="timeline-item" key={`${event.tick}-${index}`}>
                  <span className={`timeline-kind kind-${event.kind}`}>{event.kind}</span>
                  <span className="timeline-text">{event.message}</span>
                  <span className="timeline-tick">T+{String(event.tick).padStart(3, "0")}</span>
                </div>
              ))}
              {!snapshot?.events.length && <p className="empty-state">Events appear here as the simulation runs.</p>}
            </div>
          </section>
        </div>

        <aside className="control-column">
          <section className="panel controls-panel">
            <div className="eyebrow">SCENARIO BUILDER</div><h2>New simulation</h2>
            <div className="field-grid two-col">
              <Field label="Building profile"><select value={profile} onChange={(event) => setProfile(event.target.value)}>{(config?.profiles ?? ["Office", "School", "Hospital", "Mall"]).map((item) => <option key={item}>{item}</option>)}</select></Field>
              <Field label="Incident"><select value={incidentType} onChange={(event) => setIncidentType(event.target.value)}>{(config?.incident_types ?? ["Random incident", "Fire / smoke", "Gas leak", "Blocked passage", "Earthquake"]).map((item) => <option key={item}>{item}</option>)}</select></Field>
              <Field label="Floors"><select value={floors} onChange={(event) => setFloors(Number(event.target.value))}>{[3, 4, 5].map((value) => <option key={value} value={value}>{value} floors</option>)}</select></Field>
              <Field label="Rooms per wing"><select value={roomsPerWing} onChange={(event) => setRoomsPerWing(Number(event.target.value))}>{[2, 3, 4, 5, 6].map((value) => <option key={value} value={value}>{value}</option>)}</select></Field>
              <Field label="People"><select value={personCount} onChange={(event) => setPersonCount(Number(event.target.value))}>{Array.from({ length: 20 }, (_, index) => index + 1).map((value) => <option key={value}>{value}</option>)}</select></Field>
              <Field label="Replay seed"><input inputMode="numeric" placeholder="Random" value={seed} onChange={(event) => setSeed(event.target.value.replace(/[^0-9]/g, ""))} /></Field>
            </div>
            <button className="button button-primary full-width" onClick={() => void createNewScenario()} disabled={busy}>
              <Plus size={16} /> Generate building and scenario
            </button>
            <div className="control-divider" />
            <div className="button-row">
              <button className="button button-dark" onClick={() => void runCommand("start")} disabled={!snapshot || snapshot.running || activeCount === 0}>Start</button>
              <button className="button button-soft" onClick={() => void runCommand("pause")} disabled={!snapshot?.running}>Pause</button>
              <button className="button button-soft" onClick={() => void runCommand("step")} disabled={!snapshot || snapshot.running || activeCount === 0}>Step</button>
            </div>
            <div className="seed-footnote"><RotateCcw size={13} /> Seeded layouts and incidents can be replayed.</div>
          </section>

          <section className="panel alarm-panel">
            <div className="panel-title-row"><div><div className="eyebrow">LIVE SENSOR NETWORK</div><h2>Inject an alarm</h2></div><span className="alarm-count"><Radio size={13} /> {activeAlarmCount}</span></div>
            <p className="section-copy">Choose a monitored room or passage. The route engine recalculates immediately.</p>
            <Field label="Monitored location">
              <select value={sensorId} onChange={(event) => setSensorId(event.target.value)}>
                <option value="__random__">Random available sensor</option>
                {availableSensors.map((sensor) => <option value={sensor.id} key={sensor.id}>{sensor.label} · {sensor.metric}</option>)}
              </select>
            </Field>
            <button className="button button-alert full-width" onClick={() => void triggerAlarm()} disabled={!snapshot || !availableSensors.length}>
              Trigger additional alarm
            </button>
            <div className="sensor-status-row"><span>{snapshot?.sensors.length ?? 0} sensors</span><span>{availableSensors.length} available</span><span>{snapshot?.hazards.length ?? 0} active hazards</span></div>
          </section>

          <section className="panel ai-panel">
            <div className="panel-title-row"><div><div className="eyebrow">ON-DEMAND MODEL REVIEW</div><h2>Simulation analysis</h2></div><span className={`ai-state ${config?.ai_configured ? "ready" : ""}`}>{config?.ai_configured ? "CONFIGURED" : "DISABLED"}</span></div>
            <p className="section-copy">Reviews the current hazard, blocked routes, queues, reroutes, and selected person's path. Each observation must cite a fact from this simulation. Routing stays deterministic and unchanged.</p>
            <button className="button button-soft full-width" onClick={() => void requestAIReview()} disabled={!snapshot || !selectedPerson || !config?.ai_configured || busy}>
              <Activity size={15} /> Review current simulation
            </button>
            {!config?.ai_configured && <p className="micro-note">AI is not active yet. It will not show fabricated results. To enable a real review, set HF_TOKEN and HF_MODEL in the API terminal. No extra Python package is required.</p>}
            {aiReview && <AIReviewCard review={aiReview} currentTick={snapshot?.tick ?? aiReview.tick} />}
          </section>

          <EmergencyPanel
            services={config?.services ?? []}
            siteAddress={siteAddress}
            setSiteAddress={setSiteAddress}
            callbackNumber={callbackNumber}
            setCallbackNumber={setCallbackNumber}
            onPrepare={prepareBrief}
            briefText={briefText}
            onCopy={copyBrief}
            copied={copied}
          />
        </aside>
      </section>
      <footer className="app-footer"><span>AEGIS · LOCAL SIMULATION</span><span>Routing is a transparent heuristic, not certified emergency guidance.</span></footer>
    </main>
  );
}

function Metric({ label, value, tone = "" }: { label: string; value: number; tone?: string }) {
  return <div className={`metric-card ${tone}`}><div><div className="metric-label">{label}</div><div className="metric-value">{value}</div></div></div>;
}

function Field({ label, children }: { label: string; children: ReactNode }) {
  return <label className="field"><span className="field-label">{label}</span>{children}</label>;
}

function Legend({ color, label }: { color: string; label: string }) {
  return <span className="legend-item"><i style={{ background: color }} />{label}</span>;
}

function PersonCard({ person, snapshot }: { person: Person; snapshot: Snapshot }) {
  const node = snapshot.nodes.find((item) => item.id === person.current_node);
  const exit = snapshot.nodes.find((item) => item.id === person.assigned_exit);
  return <div className="person-mini-card">
    <div className="person-mini-head"><span className={`status-indicator status-${person.status.toLowerCase().replaceAll(" ", "-")}`} />{person.status}</div>
    <div className="person-mini-location">{node?.label ?? person.current_node}</div>
    <div className="person-mini-meta"><span>Exit</span><b>{exit?.label ?? "No safe exit"}</b></div>
    <div className="person-mini-meta"><span>Priority</span><b>{person.priority.toFixed(2)}</b></div>
    {person.backtracking && <div className="backtrack-note"><AlertTriangle size={13} /> Turning back to the last safe node</div>}
  </div>;
}

function NavigationCard({ person, snapshot }: { person: Person; snapshot: Snapshot }) {
  const routeLabels = person.route.map((id) => snapshot.nodes.find((node) => node.id === id)?.label ?? id);
  const nextLabel = routeLabels[1];
  const exit = snapshot.nodes.find((node) => node.id === person.assigned_exit)?.label ?? "No safe exit";
  return <div className="navigation-card">
    <div className="next-instruction"><span className="next-kicker">NEXT ACTION</span><strong>{person.status === "Evacuated" ? `Arrived at ${exit}` : person.backtracking ? "Walk back to the previous safe junction" : nextLabel ? `Continue toward ${nextLabel}` : "Wait for assistance"}</strong></div>
    <div className="route-chips">
      {routeLabels.length ? routeLabels.map((label, index) => <span className={index === 0 ? "current" : ""} key={`${label}-${index}`}>{label}</span>) : <span>No remaining route</span>}
    </div>
    <div className="navigation-meta"><span>Destination <b>{exit}</b></span><span>Reroutes <b>{person.reroutes}</b></span><span>Movement <b>{Math.round(person.movement_progress * 100)}%</b></span></div>
  </div>;
}

function AIReviewCard({ review, currentTick }: { review: AIReview; currentTick: number }) {
  return <div className="ai-review-result" aria-live="polite">
    <div className="ai-review-meta">
      <span>Snapshot T+{String(review.tick).padStart(3, "0")} · {review.person_id}</span>
      {currentTick !== review.tick && <span className="ai-review-stale">New simulation data available</span>}
    </div>
    <ReviewItems title="Observed" items={review.observations} />
    <ReviewItems title="Operator checks" items={review.operator_checks} />
    <p className="micro-note">Model: {review.model}. Advisory for this synthetic run; it does not change routes or trigger actions.</p>
  </div>;
}

function ReviewItems({ title, items }: { title: string; items: AIReview["observations"] }) {
  if (!items.length) return null;
  return <div className="ai-review-section">
    <div className="ai-review-heading">{title}</div>
    <ul className="ai-review-list">
      {items.map((item, index) => <li key={`${title}-${index}`}>
        <p>{item.text}</p>
        <div className="ai-evidence-list">
          {item.evidence.map((evidence) => <span className="ai-evidence" key={evidence.id}>{evidence.label}</span>)}
        </div>
      </li>)}
    </ul>
  </div>;
}

function EmergencyPanel({
  services, siteAddress, setSiteAddress, callbackNumber, setCallbackNumber,
  onPrepare, briefText, onCopy, copied,
}: {
  services: AppConfig["services"];
  siteAddress: string;
  setSiteAddress: (value: string) => void;
  callbackNumber: string;
  setCallbackNumber: (value: string) => void;
  onPrepare: () => void;
  briefText: string;
  onCopy: () => void;
  copied: boolean;
}) {
  const [activeCall, setActiveCall] = useState<{
    name: string;
    number: string;
    status: "dialing" | "connected";
    connectedAt?: number;
  } | null>(null);
  const [callSeconds, setCallSeconds] = useState(0);

  useEffect(() => {
    if (!activeCall || activeCall.status !== "dialing") return;
    const timeout = window.setTimeout(() => {
      setActiveCall((current) => current?.status === "dialing"
        ? { ...current, status: "connected", connectedAt: Date.now() }
        : current);
    }, 1200);
    return () => window.clearTimeout(timeout);
  }, [activeCall]);

  useEffect(() => {
    const connectedAt = activeCall?.status === "connected" ? activeCall.connectedAt : undefined;
    if (!connectedAt) {
      setCallSeconds(0);
      return;
    }
    const updateDuration = () => setCallSeconds(Math.floor((Date.now() - connectedAt) / 1000));
    updateDuration();
    const interval = window.setInterval(updateDuration, 1000);
    return () => window.clearInterval(interval);
  }, [activeCall]);

  function startSimulatedCall(name: string, number: string) {
    setCallSeconds(0);
    setActiveCall({ name, number, status: "dialing" });
  }

  function formatCallTime(totalSeconds: number) {
    const minutes = Math.floor(totalSeconds / 60).toString().padStart(2, "0");
    const seconds = (totalSeconds % 60).toString().padStart(2, "0");
    return `${minutes}:${seconds}`;
  }

  return <section className="panel emergency-panel">
    <div className="panel-title-row"><div><div className="eyebrow">HUMAN-CONTROLLED RESPONSE</div><h2>Emergency contacts</h2></div></div>
    <div className="emergency-safety-note"><AlertTriangle size={15} /><span>Call controls below are a demo; they do not connect to a phone network. For a real emergency in India, dial 112 yourself.</span></div>
    <div className="service-list">
      {services.map((service) => <div className="service-row" key={service.id}>
        <div><strong>{service.name}</strong><span>{service.description} · <a href={service.source} target="_blank" rel="noreferrer">Source</a></span></div>
        <div className="service-actions">
          <span className="service-number">{service.number}</span>
          <button
            className="service-call"
            type="button"
            disabled={Boolean(activeCall)}
            onClick={() => startSimulatedCall(service.name, service.number)}
            aria-label={`Simulate call to ${service.name}`}
          ><PhoneCall size={12} />{activeCall ? "Busy" : "Simulate"}</button>
        </div>
      </div>)}
    </div>
    <div className="call-demo-card" aria-live="polite">
      <div className={`call-demo-indicator ${activeCall?.status === "connected" ? "connected" : ""}`} />
      <div className="call-demo-copy">
        <strong>{activeCall ? (activeCall.status === "connected" ? "Demo call connected" : "Dialing (simulation)") : "Call simulation ready"}</strong>
        <span>{activeCall ? `${activeCall.name} · ${activeCall.number}${activeCall.status === "connected" ? ` · ${formatCallTime(callSeconds)}` : ""}` : "Choose Simulate to preview the call flow."}</span>
      </div>
      {activeCall && <button className="call-end-button" type="button" onClick={() => setActiveCall(null)} aria-label="End simulated call"><PhoneOff size={14} /> End</button>}
      <span className="call-demo-tag">DEMO</span>
    </div>
    <a className="official-link" href="https://112.gov.in/" target="_blank" rel="noreferrer">Official ERSS information</a>
    <div className="control-divider" />
    <div className="eyebrow">COPYABLE REPORT · NEVER SENT</div>
    <p className="section-copy">Add the actual address and callback details; AEGIS's generated map is synthetic.</p>
    <Field label="Actual site address"><input value={siteAddress} onChange={(event) => setSiteAddress(event.target.value)} placeholder="Enter only if preparing a real-world call" /></Field>
    <Field label="Callback number"><input value={callbackNumber} onChange={(event) => setCallbackNumber(event.target.value)} placeholder="Optional" /></Field>
    <button className="button button-soft full-width" onClick={onPrepare}><Copy size={15} /> Prepare incident summary</button>
    {briefText && <div className="brief-box"><pre>{briefText}</pre><button className="button button-dark full-width" onClick={onCopy}>{copied ? <Check size={14} /> : <Copy size={14} />}{copied ? "Copied" : "Copy draft"}</button></div>}
  </section>;
}
