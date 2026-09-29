from __future__ import annotations

import asyncio
import hashlib
from datetime import datetime, timezone
from typing import Any

from .schemas import (
    AllocationAlternative,
    AllocationRecommendation,
    ConstraintCheck,
    DecisionRecord,
    ForecastResult,
    OperationalSnapshot,
    RiskAssessment,
)


RISK_ORDER = {"LOW": 0, "MEDIUM": 1, "HIGH": 2, "CRITICAL": 3}


def _entity(items: list[dict[str, Any]], entity_id: str) -> dict[str, Any] | None:
    for item in items:
        if item.get("id") == entity_id:
            return item
    return None


def _float(value: Any, default: float = 0.0) -> float:
    try:
        return float(value)
    except (TypeError, ValueError):
        return default


def _int(value: Any, default: int = 0) -> int:
    try:
        return int(value)
    except (TypeError, ValueError):
        return default


def _dispatch_committed(snapshot: OperationalSnapshot, depot_id: str) -> float:
    total = 0.0
    for allocation in snapshot.allocations:
        if allocation.get("source_depot_id") != depot_id:
            continue
        status = allocation.get("status")
        if status == "PENDING":
            total += max(_float(allocation.get("quantity")), 0.0)
        elif status == "IN_TRANSIT" and _int(allocation.get("departure_tick"), -1) == snapshot.tick:
            total += max(_float(allocation.get("quantity")), 0.0)
    return total


def _destination_committed(
    snapshot: OperationalSnapshot,
    station_id: str,
    fuel_type: str,
) -> float:
    total = 0.0
    for allocation in snapshot.allocations:
        if allocation.get("destination_station_id") != station_id:
            continue
        if allocation.get("fuel_type") != fuel_type:
            continue
        if allocation.get("status") not in {"PENDING", "IN_TRANSIT"}:
            continue
        total += max(_float(allocation.get("quantity")), 0.0)
    return total


def validate_allocation(
    snapshot: OperationalSnapshot,
    *,
    source_depot_id: str,
    destination_station_id: str,
    route_id: str,
    fuel_type: str,
    quantity: float,
    include_future_inbound_safety: bool = True,
) -> list[ConstraintCheck]:
    checks: list[ConstraintCheck] = []
    depot = _entity(snapshot.depots, source_depot_id)
    station = _entity(snapshot.stations, destination_station_id)
    route = _entity(snapshot.routes, route_id)

    def add(code: str, passed: bool, detail: str) -> None:
        checks.append(ConstraintCheck(code=code, passed=bool(passed), detail=detail))

    add("QUANTITY_POSITIVE", quantity > 0, f"quantity={quantity}")
    add(
        "FUEL_TYPE_VALID",
        fuel_type in {"DIESEL", "PETROL", "OCTANE"},
        f"fuel_type={fuel_type}",
    )
    add("DEPOT_EXISTS", depot is not None, f"source_depot_id={source_depot_id}")
    add("STATION_EXISTS", station is not None, f"destination_station_id={destination_station_id}")
    add("ROUTE_EXISTS", route is not None, f"route_id={route_id}")

    if depot is None or station is None or route is None:
        return checks

    add(
        "ROUTE_MATCH",
        route.get("source_depot_id") == source_depot_id
        and route.get("destination_station_id") == destination_station_id,
        f"{route.get('source_depot_id')}->{route.get('destination_station_id')}",
    )
    add(
        "DEPOT_STATUS",
        depot.get("status") in {"OPEN", "CONSTRAINED"},
        f"status={depot.get('status')}",
    )
    add(
        "STATION_STATUS",
        station.get("status") == "OPEN",
        f"status={station.get('status')}",
    )
    add(
        "ROUTE_STATUS",
        route.get("status") == "AVAILABLE",
        f"status={route.get('status')}",
    )

    route_max = max(_float(route.get("max_shipment")), 0.0)
    add(
        "ROUTE_CAPACITY",
        quantity <= route_max,
        f"quantity={quantity}, max={route_max}",
    )

    depot_inventory = max(_float(depot.get("inventory", {}).get(fuel_type)), 0.0)
    add(
        "DEPOT_INVENTORY",
        quantity <= depot_inventory,
        f"quantity={quantity}, inventory={depot_inventory}",
    )

    dispatch_cap = max(_float(depot.get("dispatch_capacity_per_tick")), 0.0)
    committed_dispatch = _dispatch_committed(snapshot, source_depot_id)
    dispatch_remaining = max(0.0, dispatch_cap - committed_dispatch)
    add(
        "DISPATCH_CAPACITY",
        quantity <= dispatch_remaining,
        f"quantity={quantity}, remaining={dispatch_remaining}",
    )

    station_inventory = max(_float(station.get("inventory", {}).get(fuel_type)), 0.0)
    station_capacity = max(_float(station.get("capacity", {}).get(fuel_type)), 0.0)
    official_headroom = max(0.0, station_capacity - station_inventory)
    add(
        "DESTINATION_CAPACITY",
        quantity <= official_headroom,
        f"quantity={quantity}, headroom={official_headroom}",
    )

    if include_future_inbound_safety:
        committed_inbound = _destination_committed(snapshot, destination_station_id, fuel_type)
        safe_headroom = max(0.0, official_headroom - committed_inbound)
        add(
            "FUTURE_INBOUND_HEADROOM",
            quantity <= safe_headroom,
            (
                f"quantity={quantity}, safe_headroom={safe_headroom}, "
                f"committed_inbound={committed_inbound}"
            ),
        )

    return checks


def constraints_pass(checks: list[ConstraintCheck]) -> bool:
    return all(check.passed for check in checks)


def _candidate_quantity(
    snapshot: OperationalSnapshot,
    station: dict[str, Any],
    depot: dict[str, Any],
    route: dict[str, Any],
    forecast: ForecastResult,
    fuel: str,
) -> float:
    inventory = max(_float(station.get("inventory", {}).get(fuel)), 0.0)
    capacity = max(_float(station.get("capacity", {}).get(fuel)), 0.0)
    inbound = _destination_committed(snapshot, str(station.get("id")), fuel)
    effective_inventory = inventory + inbound

    transit = max(_int(route.get("transit_ticks"), 1), 1)
    demand_window = sum(forecast.per_tick_liters[: min(len(forecast.per_tick_liters), transit + 6)])
    target_level = min(capacity, max(capacity * 0.65, demand_window * 1.25))
    need = max(0.0, target_level - effective_inventory)

    route_limit = max(_float(route.get("max_shipment")), 0.0)
    depot_inventory = max(_float(depot.get("inventory", {}).get(fuel)), 0.0)
    dispatch_remaining = max(
        0.0,
        _float(depot.get("dispatch_capacity_per_tick"))
        - _dispatch_committed(snapshot, str(depot.get("id"))),
    )
    safe_headroom = max(0.0, capacity - effective_inventory)

    quantity = min(need, route_limit, depot_inventory, dispatch_remaining, safe_headroom)
    return round(max(0.0, quantity), 3)


def _candidate_score(
    risk: RiskAssessment,
    quantity: float,
    need_reference: float,
    transit_ticks: int,
) -> float:
    coverage = min(quantity / max(need_reference, 1.0), 1.0)
    return round(risk.risk_score * 100.0 + coverage * 18.0 - transit_ticks * 6.0, 3)


def _recommendation_id(
    snapshot: OperationalSnapshot,
    station_id: str,
    fuel: str,
    route_id: str,
    quantity: float,
) -> str:
    raw = f"{snapshot.tick}|{station_id}|{fuel}|{route_id}|{quantity:.3f}"
    digest = hashlib.sha256(raw.encode("utf-8")).hexdigest()[:16]
    return f"rec-{digest}"


def build_recommendations(
    snapshot: OperationalSnapshot,
    forecasts: list[ForecastResult],
    risks: list[RiskAssessment],
) -> list[AllocationRecommendation]:
    forecast_map = {(f.station_id, f.fuel_type): f for f in forecasts}
    risk_map = {(r.station_id, r.fuel_type): r for r in risks}
    recommendations: list[AllocationRecommendation] = []

    for key, risk in risk_map.items():
        if RISK_ORDER[risk.risk_level] < RISK_ORDER["MEDIUM"]:
            continue

        station_id, fuel = key
        station = _entity(snapshot.stations, station_id)
        forecast = forecast_map.get(key)
        if station is None or forecast is None:
            continue
        if station.get("status") != "OPEN":
            continue

        routes = [
            route
            for route in snapshot.routes
            if route.get("destination_station_id") == station_id
            and route.get("status") == "AVAILABLE"
        ]
        if not routes:
            continue

        candidates: list[dict[str, Any]] = []
        inventory = max(_float(station.get("inventory", {}).get(fuel)), 0.0)
        capacity = max(_float(station.get("capacity", {}).get(fuel)), 0.0)
        inbound = _destination_committed(snapshot, station_id, fuel)
        need_reference = max(capacity * 0.65 - inventory - inbound, 1.0)

        for route in routes:
            depot = _entity(snapshot.depots, str(route.get("source_depot_id")))
            if depot is None or depot.get("status") not in {"OPEN", "CONSTRAINED"}:
                continue

            quantity = _candidate_quantity(
                snapshot,
                station,
                depot,
                route,
                forecast,
                fuel,
            )
            if quantity <= 0:
                continue

            checks = validate_allocation(
                snapshot,
                source_depot_id=str(depot.get("id")),
                destination_station_id=station_id,
                route_id=str(route.get("id")),
                fuel_type=fuel,
                quantity=quantity,
                include_future_inbound_safety=True,
            )
            if not constraints_pass(checks):
                continue

            transit = max(_int(route.get("transit_ticks"), 1), 1)
            score = _candidate_score(risk, quantity, need_reference, transit)
            candidates.append(
                {
                    "depot": depot,
                    "route": route,
                    "quantity": quantity,
                    "transit": transit,
                    "score": score,
                    "checks": checks,
                }
            )

        if not candidates:
            continue

        candidates.sort(key=lambda c: (-c["score"], c["transit"], -c["quantity"]))
        best = candidates[0]

        quantity = float(best["quantity"])
        avg_demand = max(forecast.demand_per_tick, 1e-6)
        expected_runway_after = (inventory + inbound + quantity) / avg_demand
        quantity_effect = min(quantity / max(capacity * 0.65, 1.0), 0.85)
        risk_after = max(0.05, risk.risk_score * (1.0 - quantity_effect))

        executable = snapshot.data_freshness == "FRESH"
        reason_codes = list(risk.reason_codes)
        if not executable:
            reason_codes.append("DEGRADED_DATA_BLOCKS_EXECUTION")

        alternatives = [
            AllocationAlternative(
                source_depot_id=str(c["depot"].get("id")),
                route_id=str(c["route"].get("id")),
                quantity=float(c["quantity"]),
                transit_ticks=int(c["transit"]),
                score=float(c["score"]),
            )
            for c in candidates[1:3]
        ]

        recommendation_id = _recommendation_id(
            snapshot,
            station_id,
            fuel,
            str(best["route"].get("id")),
            quantity,
        )

        recommendations.append(
            AllocationRecommendation(
                recommendation_id=recommendation_id,
                generated_tick=snapshot.tick,
                source_depot_id=str(best["depot"].get("id")),
                destination_station_id=station_id,
                route_id=str(best["route"].get("id")),
                fuel_type=fuel,
                quantity=quantity,
                priority=risk.risk_level,
                confidence=round(min(risk.confidence, forecast.confidence), 3),
                risk_before=round(risk.risk_score, 3),
                risk_after=round(risk_after, 3),
                constraints_checked=True,
                human_review_required=True,
                executable=executable,
                expected_arrival_tick=snapshot.tick + int(best["transit"]),
                expected_runway_after_ticks=round(expected_runway_after, 2),
                recommended_action=(
                    f"Allocate {quantity:,.0f} L {fuel} from "
                    f"{best['depot'].get('id')} to {station_id}."
                ),
                safe_boundary=(
                    "Human approval required. Approval always re-fetches REST state "
                    "and revalidates every allocation constraint before POST /v1/allocations."
                ),
                reason_codes=reason_codes,
                constraints=list(best["checks"]),
                alternatives=alternatives,
            )
        )

    recommendations.sort(
        key=lambda r: (
            -RISK_ORDER[r.priority],
            -r.risk_before,
            r.expected_arrival_tick,
            r.destination_station_id,
            r.fuel_type,
        )
    )
    return recommendations


class DecisionStore:
    def __init__(self) -> None:
        self.recommendations: dict[str, AllocationRecommendation] = {}
        self.decisions: dict[str, DecisionRecord] = {}
        self.lock = asyncio.Lock()

    def remember(self, recommendations: list[AllocationRecommendation]) -> None:
        for recommendation in recommendations:
            self.recommendations[recommendation.recommendation_id] = recommendation

    def get_recommendation(self, recommendation_id: str) -> AllocationRecommendation | None:
        return self.recommendations.get(recommendation_id)

    def get_decision(self, recommendation_id: str) -> DecisionRecord | None:
        return self.decisions.get(recommendation_id)

    def save_decision(self, record: DecisionRecord) -> DecisionRecord:
        self.decisions[record.recommendation_id] = record
        return record

    def history(self) -> list[DecisionRecord]:
        return sorted(
            self.decisions.values(),
            key=lambda d: d.decided_at,
            reverse=True,
        )


def make_decision_record(
    recommendation_id: str,
    *,
    action: str,
    status: str,
    tick: int | None,
    reason: str | None = None,
    allocation: dict[str, Any] | None = None,
    invalidated_constraints: list[str] | None = None,
) -> DecisionRecord:
    raw = f"{recommendation_id}|{action}|{status}"
    decision_id = "dec-" + hashlib.sha256(raw.encode("utf-8")).hexdigest()[:16]
    return DecisionRecord(
        decision_id=decision_id,
        recommendation_id=recommendation_id,
        action=action,
        status=status,
        decided_at=datetime.now(timezone.utc).isoformat(),
        decision_tick=tick,
        reason=reason,
        allocation=allocation,
        invalidated_constraints=invalidated_constraints or [],
    )
