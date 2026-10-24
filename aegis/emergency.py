"""Human-controlled emergency contact actions and simulation report text."""

from __future__ import annotations

from aegis.models import SimulationState


EMERGENCY_SERVICES = (
    {
        "id": "integrated",
        "name": "Integrated emergency response",
        "number": "112",
        "description": "Police, fire and rescue, and health emergencies",
        "source": "https://112.gov.in/",
    },
    {
        "id": "fire",
        "name": "Fire and rescue",
        "number": "101",
        "description": "National fire helpline",
        "source": "https://www.india.gov.in/directory/helpline",
    },
    {
        "id": "ambulance",
        "name": "National ambulance service",
        "number": "102",
        "description": "National Ambulance Service helpline",
        "source": "https://www.india.gov.in/directory/helpline",
    },
    {
        "id": "police",
        "name": "Police",
        "number": "100",
        "description": "Police helpline",
        "source": "https://www.india.gov.in/directory/helpline",
    },
)


def build_emergency_brief(
    state: SimulationState,
    *,
    profile: str,
    site_address: str = "",
    callback_number: str = "",
) -> str:
    """Create a copyable draft; never transmits it to a service or contact."""
    active = sum(person.status in {"Waiting", "Moving", "Queued", "Needs Assistance"} for person in state.people)
    evacuated = sum(person.status == "Evacuated" for person in state.people)
    assistance = sum(person.status == "Needs Assistance" for person in state.people)
    hazard_lines = [
        f"- Simulated {hazard.incident_type} at {hazard.target_id} ({hazard.level}, {hazard.intensity:.0f}/100)"
        for hazard in state.hazards
    ] or ["- No simulated active hazard"]
    location = site_address.strip() or "Not provided; the displayed building is synthetic."
    callback = callback_number.strip() or "Not provided."
    return "\n".join((
        "AEGIS SIMULATION REPORT — DRAFT ONLY; NOT SENT",
        f"Building profile: {profile}",
        f"Actual site address supplied by user: {location}",
        f"Callback number supplied by user: {callback}",
        f"People: {len(state.people)} total; {active} active; {evacuated} evacuated; {assistance} need assistance.",
        f"Simulation seed: {state.seed}; simulation tick: {state.tick}.",
        "Hazards:",
        *hazard_lines,
        "All people, hazards, locations, and sensor readings above are simulated. Verify the real situation before contacting responders.",
    ))
