from __future__ import annotations

from datetime import datetime, timezone
from typing import Any

from .schemas import CrisisAssessment, CrisisSummary, OperationalSnapshot


REVERSIBLE_TYPES = {
    "demand_spike",
    "route_disruption",
    "station_outage",
    "depot_constraint",
}
PERSISTENT_TYPES = {"shipment_delay", "supply_shortfall"}
KNOWN_TYPES = REVERSIBLE_TYPES | PERSISTENT_TYPES

SEVERITY = {
    "demand_spike": "HIGH",
    "route_disruption": "HIGH",
    "station_outage": "CRITICAL",
    "depot_constraint": "MEDIUM",
    "shipment_delay": "MEDIUM",
    "supply_shortfall": "HIGH",
}

IMPACTS = {
    "demand_spike": [
        "Demand pressure is elevated for affected stations or regions.",
        "Forecasts and stockout risk must be recalculated from the latest multiplier-adjusted state.",
    ],
    "route_disruption": [
        "Affected routes are unavailable for new allocations while the event is active.",
        "Previously generated recommendations using an affected route can become invalid.",
    ],
    "station_outage": [
        "Affected stations cannot receive or serve normal demand while OUTAGE.",
        "Allocations to affected stations must be withheld until the station reopens.",
    ],
    "depot_constraint": [
        "Affected depots remain technically shippable but represent reduced operational confidence.",
        "Prefer healthy alternate depots where comparable feasible routes exist.",
    ],
    "shipment_delay": [
        "Scheduled depot resupply has been shifted later.",
        "Near-term recommendations should avoid depending on delayed replenishment.",
    ],
    "supply_shortfall": [
        "Future depot resupply quantity has been reduced.",
        "Conserve constrained depot inventory and prefer alternatives when feasible.",
    ],
}

ACTIONS = {
    "demand_spike": [
        "Recalculate forecasts and runway immediately.",
        "Prioritize high/critical stockout risks and preserve human approval.",
    ],
    "route_disruption": [
        "Invalidate recommendations that reference disrupted routes.",
        "Replan using an available route and revalidate all constraints.",
    ],
    "station_outage": [
        "Suppress allocations to the affected station.",
        "Continue monitoring until the station returns OPEN, then recompute risk.",
    ],
    "depot_constraint": [
        "Penalize the constrained depot during route ranking.",
        "Use the constrained depot only when it remains the best feasible option.",
    ],
    "shipment_delay": [
        "Flag delayed inbound supply as pressure on the affected depot/fuel.",
        "Prefer alternatives that do not depend on delayed replenishment.",
    ],
    "supply_shortfall": [
        "Flag reduced future supply as persistent pressure.",
        "Protect remaining inventory and prefer alternate feasible supply paths.",
    ],
}


def _now() -> str:
    return datetime.now(timezone.utc).isoformat()


def _list(value: Any) -> list[str]:
    if not isinstance(value, list):
        return []
    return [str(item) for item in value if str(item)]


def _event_id(event: dict[str, Any]) -> str:
    return str(event.get("id", "unknown"))


def _params(event: dict[str, Any]) -> dict[str, Any]:
    raw = event.get("parameters")
    return raw if isinstance(raw, dict) else {}


def _matches_filter(params: dict[str, Any], key: str, value: str) -> bool:
    values = _list(params.get(key))
    return not values or value in values


def event_applies_to_depot_fuel(
    event: dict[str, Any],
    depot_id: str,
    fuel_type: str,
) -> bool:
    params = _params(event)
    return (
        _matches_filter(params, "depot_ids", depot_id)
        and _matches_filter(params, "fuel_types", fuel_type)
    )


def _future_supply_matches(
    snapshot: OperationalSnapshot,
    event: dict[str, Any],
) -> bool:
    event_type = str(event.get("type", ""))
    if event_type not in PERSISTENT_TYPES:
        return False

    for arrival in snapshot.supply_arrivals:
        depot_id = str(arrival.get("depot_id", ""))
        fuel_type = str(arrival.get("fuel_type", ""))
        if not event_applies_to_depot_fuel(event, depot_id, fuel_type):
            continue
        try:
            planned_tick = int(arrival.get("planned_tick"))
        except (TypeError, ValueError):
            continue
        status = str(arrival.get("status", ""))
        if planned_tick >= snapshot.tick and status in {"SCHEDULED", "DELAYED"}:
            return True
    return False


def _operational_status(
    snapshot: OperationalSnapshot,
    event: dict[str, Any],
) -> str:
    status = str(event.get("status", "UNKNOWN")).upper()
    event_type = str(event.get("type", ""))

    if status == "ACTIVE":
        return "ACTIVE"
    if status == "SCHEDULED":
        return "SCHEDULED"
    if (
        status == "RESOLVED"
        and event_type in PERSISTENT_TYPES
        and _future_supply_matches(snapshot, event)
    ):
        return "PERSISTENT_EFFECT"
    if status == "RESOLVED":
        return "RESOLVED"
    return status


def _affected_resources(event: dict[str, Any]) -> list[str]:
    event_type = str(event.get("type", ""))
    params = _params(event)

    mapping = {
        "demand_spike": (("station_ids", "station"), ("region_ids", "region")),
        "route_disruption": (("route_ids", "route"),),
        "station_outage": (("station_ids", "station"),),
        "depot_constraint": (("depot_ids", "depot"),),
        "shipment_delay": (("depot_ids", "depot"), ("fuel_types", "fuel")),
        "supply_shortfall": (("depot_ids", "depot"), ("fuel_types", "fuel")),
    }

    resources: list[str] = []
    for key, prefix in mapping.get(event_type, ()):
        values = _list(params.get(key))
        if values:
            resources.extend(f"{prefix}:{value}" for value in values)
        else:
            resources.append(f"{prefix}:ALL")

    return resources


def assess_event(
    snapshot: OperationalSnapshot,
    event: dict[str, Any],
) -> CrisisAssessment | None:
    event_type = str(event.get("type", ""))
    if event_type not in KNOWN_TYPES:
        return None

    operational_status = _operational_status(snapshot, event)
    return CrisisAssessment(
        event_id=_event_id(event),
        event_type=event_type,
        simulator_status=str(event.get("status", "UNKNOWN")).upper(),
        operational_status=operational_status,
        severity=SEVERITY[event_type],
        start_tick=int(event.get("start_tick", 0) or 0),
        end_tick=int(event.get("end_tick", 0) or 0),
        affected_resources=_affected_resources(event),
        impacts=list(IMPACTS[event_type]),
        adaptation_actions=list(ACTIONS[event_type]),
    )


def analyze_crises(snapshot: OperationalSnapshot) -> CrisisSummary:
    assessments: list[CrisisAssessment] = []
    for event in snapshot.events:
        if not isinstance(event, dict):
            continue
        assessment = assess_event(snapshot, event)
        if assessment is not None:
            assessments.append(assessment)

    assessments.sort(
        key=lambda item: (
            item.operational_status not in {"ACTIVE", "PERSISTENT_EFFECT"},
            -item.start_tick,
            item.event_type,
        )
    )

    relevant = [
        item
        for item in assessments
        if item.operational_status in {"ACTIVE", "PERSISTENT_EFFECT"}
    ]
    active_types = sorted({item.event_type for item in relevant})
    combined = len(active_types) >= 2

    severity_rank = {"INFO": 0, "MEDIUM": 1, "HIGH": 2, "CRITICAL": 3}
    max_severity = max(
        (severity_rank[item.severity] for item in relevant),
        default=0,
    )

    if not relevant:
        crisis_level = "NORMAL"
    elif combined or max_severity >= 3:
        crisis_level = "CRITICAL"
    elif max_severity >= 2:
        crisis_level = "HIGH"
    else:
        crisis_level = "ELEVATED"

    decision_context: list[str] = []
    if "demand_spike" in active_types:
        decision_context.append("Demand multiplier is elevated; forecasts and stockout runway are recalculated.")
    if "route_disruption" in active_types:
        decision_context.append("Disrupted routes are excluded from candidate allocation paths.")
    if "station_outage" in active_types:
        decision_context.append("Outage stations are excluded from allocation recommendations.")
    if "depot_constraint" in active_types:
        decision_context.append("Constrained depots receive a ranking penalty versus healthy alternatives.")
    if "shipment_delay" in active_types:
        decision_context.append("Delayed depot replenishment reduces confidence in affected supply paths.")
    if "supply_shortfall" in active_types:
        decision_context.append("Reduced future supply applies pressure to affected depot/fuel choices.")
    if combined:
        decision_context.insert(
            0,
            "Multiple domain crises overlap; treat recommendations as a combined-crisis replan.",
        )

    return CrisisSummary(
        generated_at=_now(),
        snapshot_tick=snapshot.tick,
        crisis_level=crisis_level,
        combined_crisis=combined,
        active_crisis_count=len(relevant),
        active_types=active_types,
        replan_required=bool(relevant),
        assessments=assessments,
        decision_context=decision_context,
    )


def supply_pressure_for_candidate(
    snapshot: OperationalSnapshot,
    *,
    depot_id: str,
    fuel_type: str,
) -> tuple[float, list[str]]:
    penalty = 0.0
    reasons: list[str] = []

    depot = next(
        (item for item in snapshot.depots if str(item.get("id")) == depot_id),
        None,
    )
    if depot is not None and str(depot.get("status")) == "CONSTRAINED":
        penalty += 24.0
        reasons.append("DEPOT_CONSTRAINED")

    delayed = any(
        str(arrival.get("depot_id")) == depot_id
        and str(arrival.get("fuel_type")) == fuel_type
        and str(arrival.get("status")) == "DELAYED"
        and int(arrival.get("planned_tick", -1) or -1) >= snapshot.tick
        for arrival in snapshot.supply_arrivals
    )
    if delayed:
        penalty += 8.0
        reasons.append("SUPPLY_DELAY_PRESSURE")

    for event in snapshot.events:
        if not isinstance(event, dict):
            continue
        event_type = str(event.get("type", ""))
        if event_type not in PERSISTENT_TYPES:
            continue
        if not event_applies_to_depot_fuel(event, depot_id, fuel_type):
            continue
        operational_status = _operational_status(snapshot, event)
        if operational_status not in {"ACTIVE", "PERSISTENT_EFFECT"}:
            continue

        if event_type == "shipment_delay":
            if "SUPPLY_DELAY_PRESSURE" not in reasons:
                penalty += 8.0
                reasons.append("SUPPLY_DELAY_PRESSURE")
        elif event_type == "supply_shortfall":
            penalty += 12.0
            reasons.append("SUPPLY_SHORTFALL_PRESSURE")

    return penalty, reasons
