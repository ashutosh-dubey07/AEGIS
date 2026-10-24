# AEGIS demo and pitch

## 3–4 minute demo script

**0:00–0:30 — Problem.** “SI-03 asks how people can find safer exits when an emergency changes the route. In a multi-floor building, a short path may pass through a hazard, and a shared corridor can become a bottleneck.”

**0:30–1:00 — Model.** Show the Ground floor, then Floor 1 and Floor 2. Point out rooms, junctions, two stair routes, the two exits, and the narrow passage. “This is a fixed synthetic graph so the routing decisions are visible and repeatable.”

**1:00–1:40 — Incident and priority.** Pick Fire / smoke, Gas leak, Blocked passage, or Earthquake, then create a scenario and read the seed aloud. The hazard type is fixed while its location is random. Point to its current synthetic intensity and the matching sensor. “The same seed recreates the incident, location, intensity growth, readings, and starting positions. People closer by graph distance get a higher urgency score.”

**1:40–2:30 — Shared routing and congestion.** Start the simulation. Show route assignments split across safe corridors/exits where capacity and cost allow; if a queue forms, call out the capacity and wait state. The map follows one selected person, and their marker advances along each corridor over several beats. Use Advance one beat while paused for a controlled demo.

**2:30–3:10 — Dynamic alert and individual view.** Step the simulation until hazard intensity rises and its affected area expands, then show route recalculation. Trigger another normal sensor as a simulated alarm if time allows. Switch Person perspective and show that person's traveled path, remaining route, and directions; the map follows their floor. Explain that selection changes only the view.

**3:10–3:40 — Honest boundary.** “AEGIS is a hackathon simulation. People, hazards, and sensor values are generated in software. There is no GPS, building hardware, or real alarm integration, and this is not certified for real evacuation use.”

## 6-slide PPT outline

1. **SI-03: Emergency Exit and Safe Route Finder** — The challenge: hazards change routes, floors add transitions, and corridors/exits have limited throughput. Speaking point: “The shortest path for one person may not be the best shared route for a group.”
2. **AEGIS system view** — Synthetic building graph, simulated sensor layer, shared route planner, presenter dashboard. Speaking point: “Each layer is visible and explainable during the demo.”
3. **Three-floor building model** — Rooms, junctions, two stairs, two exits, narrow passage. Speaking point: “The fixed map keeps attention on changing route decisions.”
4. **How route assignment works** — Hazard closures, caution penalties, urgency ordering, congestion and exit reservations. Speaking point: “Higher-risk people are planned first; routes avoid blocked areas and account for shared capacity.”
5. **Live demo and dynamic rerouting** — Seeded scenario, sensor alarm, queue or alternate route, person selector. Speaking point: “A seed makes a run repeatable; selecting a person changes only what is highlighted.”
6. **Scope, limits, next steps** — What is simulated, absent real integrations, heuristic limitations, possible reviewed future work. Speaking point: “This is a transparent hackathon simulation, not a real emergency product or safety certification.”
