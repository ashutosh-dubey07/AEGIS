# AEGIS

AEGIS is a browser-based evacuation simulation for exploring how people move through a multi-floor building during an incident.

## How it works

1. **Create a scenario.** Choose a building profile, number of floors, rooms, people, incident type, and optional replay seed. AEGIS generates a synthetic floor plan, connected passages, exits, people, and sensor network.
2. **Start the incident.** The selected hazard begins at a simulated location. As simulation time advances, its intensity rises and its affected area can expand. Sensors display corresponding simulated readings and alarms.
3. **Plan safe routes.** The Python simulation evaluates available passages, hazards, closures, travel time, congestion, exit capacity, and each person's movement or accessibility needs. When a passage becomes unsafe or congestion persists, it recalculates routes for the affected people.
4. **Move people over time.** People progress gradually through rooms, corridors, stairs, and exits. Passage and exit capacities can make people queue. Accessibility profiles affect priority, pace, and route requirements.
5. **Inspect the evacuation.** The 3D browser view shows the building, hazards, passages, and all people's current positions. Select a person to inspect their route and status; follow their floor and focus the view on their progress. The event timeline records simulated alarms, queues, movement, and reroutes.

## System flow

The React and Three.js browser client sends scenario and control commands to a Python FastAPI service. The service runs the simulation and sends live state snapshots to the browser over a WebSocket connection. The browser animates movement between updates, so the scene does not need a full page refresh for each simulation step.

## Simulation scope

Buildings, people, hazards, sensor readings, emergency calls, and evacuation outcomes are simulated. AEGIS does not connect to real building sensors or dispatch services and is not certified emergency guidance.
