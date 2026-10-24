"""Seeded simulated sensor readings and simple alarm thresholds."""

from __future__ import annotations

import random

from aegis.models import Building, Hazard, Sensor


SENSOR_METRICS = {
    "Fire / smoke": ("smoke", "ppm", 65.0),
    "Gas leak": ("gas", "%", 40.0),
    "Blocked passage": ("obstruction", "%", 60.0),
    "Earthquake": ("ground_motion", "index", 65.0),
}

NORMAL_RANGES = {
    "smoke": (4.0, 24.0),
    "gas": (0.0, 8.0),
    "heat": (19.0, 32.0),
    "obstruction": (0.0, 18.0),
    "ground_motion": (0.0, 18.0),
}

WARNING_RANGES = {
    "smoke": (35.0, 64.0),
    "gas": (20.0, 39.0),
    "heat": (45.0, 59.0),
    "obstruction": (35.0, 59.0),
    "ground_motion": (35.0, 64.0),
}


def state_for_reading(metric: str, reading: float) -> str:
    """Convert a reading to a stable Normal, Warning, or Alarm label."""
    warning, alarm = {
        "smoke": (35.0, 65.0),
        "gas": (20.0, 40.0),
        "heat": (45.0, 60.0),
        "obstruction": (35.0, 60.0),
        "ground_motion": (35.0, 65.0),
    }[metric]
    if reading >= alarm:
        return "Alarm"
    if reading >= warning:
        return "Warning"
    return "Normal"


def metric_for_incident(incident_type: str) -> tuple[str, str, float]:
    return SENSOR_METRICS[incident_type]


def reading_for_hazard(metric: str, intensity: float) -> float:
    """Map synthetic 0–100 hazard intensity to a display-only sensor reading."""
    value = max(0.0, min(100.0, intensity))
    if metric == "smoke":
        return round(4.0 + value * 0.9, 1)
    if metric == "gas":
        return round(value * 0.55, 1)
    return round(value, 1)


def create_sensor_network(
    building: Building,
    rng: random.Random,
    hazards: list[Hazard] | None = None,
) -> list[Sensor]:
    """Create simulated sensors for rooms, junctions, stairs, passages, and hazards."""
    hazards = hazards or []
    sensors: list[Sensor] = []
    metric_cycle = ("smoke", "gas", "heat", "obstruction", "ground_motion")
    eligible = [node for node in building.nodes.values() if node.kind in {"room", "junction", "stairs"}]
    for index, node in enumerate(sorted(eligible, key=lambda item: item.id)):
        metric = metric_cycle[index % len(metric_cycle)]
        low, high = NORMAL_RANGES[metric]
        if rng.random() < 0.12:
            warning_low, warning_high = WARNING_RANGES[metric]
            reading = round(rng.uniform(warning_low, warning_high), 1)
        else:
            reading = round(rng.uniform(low, high), 1)
        sensors.append(Sensor(
            id=f"S-{node.id}", target_id=node.id, target_kind="node", metric=metric,
            reading=reading,
            unit=(
                "ppm" if metric == "smoke"
                else "°C" if metric == "heat"
                else "index" if metric == "ground_motion"
                else "%"
            ),
            state=state_for_reading(metric, reading), label=node.label,
        ))

    low, high = NORMAL_RANGES["obstruction"]
    warning_low, warning_high = WARNING_RANGES["obstruction"]
    for edge in sorted(building.edges.values(), key=lambda item: item.id):
        reading = (
            round(rng.uniform(warning_low, warning_high), 1)
            if rng.random() < 0.12
            else round(rng.uniform(low, high), 1)
        )
        start, end = building.nodes[edge.a], building.nodes[edge.b]
        sensors.append(Sensor(
            id=f"S-{edge.id}", target_id=edge.id, target_kind="edge",
            metric="obstruction", reading=reading, unit="%",
            state=state_for_reading("obstruction", reading),
            label=f"Passage from {start.label} to {end.label}",
        ))

    for hazard in hazards:
        metric, unit, _alarm_threshold = metric_for_incident(hazard.incident_type)
        target_id = hazard.target_id
        target_kind = hazard.target_kind
        sensor_id = f"S-ALARM-{target_id}"
        existing = next((
            sensor for sensor in sensors
            if sensor.target_id == target_id and sensor.target_kind == target_kind
        ), None)
        reading = reading_for_hazard(metric, hazard.intensity)
        if existing:
            existing.metric = metric
            existing.reading = reading
            existing.unit = unit
            existing.state = state_for_reading(metric, reading)
        else:
            if target_kind == "node":
                label = building.nodes[target_id].label
            else:
                edge = building.edges[target_id]
                label = f"Passage {edge.id}"
            sensors.append(Sensor(
                id=sensor_id, target_id=target_id, target_kind=target_kind,
                metric=metric, reading=reading, unit=unit,
                state=state_for_reading(metric, reading), label=label,
            ))
    return sensors
