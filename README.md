# AEGIS — Evacuation Lab

AEGIS is a local hackathon simulation for emergency exit and safe-route planning. The browser client renders a generated multi-floor building in 3D and animates every person's route, while highlighting the selected person's view. Python manages the simulation state, hazards, sensors, queues, and rerouting.

> **Simulation boundary:** people, buildings, sensor readings, incidents, and routes in AEGIS are generated demo data. It does not connect to real building systems, GPS, live alarms, or emergency dispatch, and it is not certified life-safety guidance.

## Recommended app: local 3D browser client

The browser app runs on your computer without an account or hosted server. You can also open it from a phone on the same Wi-Fi network; follow the LAN steps below.

### Dependencies to install

- **Python 3.15** for the simulation API. Check it with `py -V`.
- **Node.js 24 LTS** for the browser build tools (22.12 or newer is the minimum); the official x64 Windows `.msi` installer includes `npm`. Leave the default PATH and npm options selected. After setup, restart VS Code and check `node --version` and `npm --version`. Get the installer from [nodejs.org](https://nodejs.org/en/download/).
- Python packages in `requirements-api.txt`: FastAPI, Pydantic, and Uvicorn.
- JavaScript packages in `web/package.json`: React, Three.js, React Three Fiber, Drei, Vite, and TypeScript. They install locally into `web/node_modules`.

### Install and run (Windows PowerShell)

Open the AEGIS folder in VS Code. If `.venv` already exists, keep using it. In **Terminal 1**, run:

```powershell
py -m venv .venv
.\.venv\Scripts\python.exe -m pip install -r requirements-api.txt
.\.venv\Scripts\python.exe -m uvicorn aegis_api.main:app --host 0.0.0.0 --port 8000
```

If the virtual environment is already made, skip the first line. Leave Terminal 1 running. Open **Terminal 2** from the AEGIS folder and run:

```powershell
cd web
npm install
npm run dev
```

Open the local URL Vite prints, normally `http://127.0.0.1:5173`. Keep both terminals running while using the app. The API health page on the PC is `http://127.0.0.1:8000/api/health`.

### Open on a phone on the same Wi-Fi

1. Start both servers using the commands above and leave their terminals running.
2. On the PC, run `ipconfig` in PowerShell. Find the **IPv4 Address** under the Wi-Fi adapter (for example, `192.168.1.23`).
3. Connect the phone to that same Wi-Fi network and open `http://192.168.1.23:5173`, replacing the example with the PC's IPv4 address. Do not use `localhost` on the phone; that points to the phone itself.
4. If Windows asks about network access, allow Python/Node on **Private networks**. The browser client uses the same PC address for the API automatically.

To stop either server, click its terminal and press **Ctrl+C**. Future runs do not need `npm install` again unless `package.json` changes: start the API in Terminal 1, then run `cd web` and `npm run dev` in Terminal 2.

### Optional AI evacuation review

AI is optional and disabled until a model and token are configured. When you click **Review current simulation**, the local API sends Hugging Face a compact summary of the synthetic scenario: hazard types and intensities, blocked or caution routes, queues, status counts, and the selected person's route. It does not send an actual address, callback number, or real person data. The model must cite supplied simulation facts for each observation; unsupported evidence IDs are discarded. The review is advisory and never changes routes, simulation state, or emergency contacts.

1. Create a Hugging Face token with **Make calls to Inference Providers** permission, and select a chat model available through an Inference Provider. Do not paste the token into the app, README, or chat.
2. Set the values in **Terminal 1** before starting Uvicorn (replace the examples locally):

   ```powershell
   $env:HF_TOKEN="hf_your_token"
   $env:HF_MODEL="provider/model-name"
   .\.venv\Scripts\python.exe -m uvicorn aegis_api.main:app --host 0.0.0.0 --port 8000
   ```

   The API uses Python's standard library to contact Hugging Face, so no extra package needs to be installed. The selected provider receives the synthetic simulation summary only when you click **Review current simulation**. Model/provider availability and pricing can vary. Leave AI disabled if you do not want that external request.

## What is in the browser app

- Seeded Office, School, Hospital, and Mall layouts, from 3 to 5 floors, with variable room counts and two stair cores.
- A Three.js 3D building view with orbit, zoom, floor selection, live markers for every person, selected-person route highlighting, and browser-frame animation between Python simulation updates.
- Optional inclusive demo personas for wheelchair use, limited mobility, low vision, hard of hearing, and pregnancy support. Profiled people receive higher route/queue priority, suitable movement pacing, and profile-specific route or communication preferences; their markers are pink, while people who need immediate assistance remain dark.
- Designated step-free passages and simulated evacuation lifts, with wheelchair routes restricted to the mapped accessible graph. Selecting a low-vision persona enlarges route guidance, increases scene focus around that person, and offers spoken turn-by-turn updates through the browser's built-in speech engine.
- Optional on-demand Hugging Face review of current hazards, queues, reroutes, and the selected person, with evidence labels tied to supplied simulation facts. AI never controls routing.
- Route guidance, per-person status, queue/assistance counts, event history, and route change counts.
- Fire/smoke, gas, blocked passage, and earthquake scenarios. Hazard intensity grows with simulation time; new sensor alarms can close passages and cause route replanning.
- Emergency contact reference numbers, source links, and a **simulated** dialing/connected call flow. The demo never opens a phone dialer or places a real call. The copyable report is never sent. For a real emergency in India, use the official **112** service.
- A local REST API plus WebSocket stream; the live scene does not reload the page every second.

## Emergency contact behavior

The contact buttons are `tel:` links. A person must choose one and confirm/place the call through their device. AEGIS never calls, messages, or dispatches automatically. The included report clearly labels simulated counts and hazards; enter the real address yourself if you choose to prepare a draft. Check official service information at [India's ERSS 112 site](https://112.gov.in/) and the [National Portal helpline directory](https://www.india.gov.in/directory/helpline).

## Existing Streamlit version

The original dashboard remains available as a fallback. Its dependencies are separate from the browser app:

```powershell
.\.venv\Scripts\python.exe -m pip install -r requirements.txt
.\.venv\Scripts\python.exe -m streamlit run app.py
```

The Streamlit page uses a periodic rerun model. Use the local browser client above for continuous 3D movement and the WebSocket interface.

## Deploy the browser app on Render

The repository includes a `render.yaml` Blueprint for the React/Vite site and FastAPI/WebSocket API. It wires the deployed API URL into the frontend build and allows the deployed site through API CORS.

1. Push the repository's `main` branch to GitHub.
2. In the [Render Dashboard](https://dashboard.render.com/), choose **New → Blueprint** and connect `ashutosh-dubey07/AEGIS`.
3. Select the `main` branch, review the two services (`aegis-api` and `aegis-web`), then apply the Blueprint.
4. When both deployments finish, open the `aegis-web` URL shown in Render.

The free API service can sleep when idle, so its first request may take longer. Simulation sessions are held in memory and reset when the API restarts; this setup is for a public demo, not persistent or operational emergency response.

## Project map

- `aegis/` — simulation models, seeded layouts, sensor state, route planning, movement, queues, hazard growth, and visualization helpers.
- `aegis_api/main.py` — FastAPI endpoints, command handling, optional evidence-linked Hugging Face simulation review, and live WebSocket snapshots.
- `aegis/emergency.py` — official contact links and draft-only summary generation.
- `web/src/App.tsx` — local browser controls and status panels.
- `web/src/BuildingScene.tsx` — Three.js / React Three Fiber scene and smooth person animation.
- `tests/` — core simulation checks.

## Core checks

Run the existing standard-library tests from the project folder:

```powershell
.\.venv\Scripts\python.exe -m unittest discover -s tests -v
```

The routing engine is a transparent weighted-graph heuristic with capacity, closure, caution, congestion, and persona preference costs. The floor plans, designated evacuation lifts, mobility/communication profiles, and hazard intensity are synthetic demo mechanics. An evacuation lift is treated as usable only because the generated scenario explicitly marks it as an available simulated evacuation lift; this must never be read as a real building's lift safety status. The demo does not validate building-code compliance, measured fire/smoke spread, clinical needs, or actual sensor uncertainty.
