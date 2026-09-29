from __future__ import annotations

from datetime import datetime, timedelta
from statistics import mean, median, pstdev
from typing import Any

from .schemas import ForecastResult, OperationalSnapshot, RiskAssessment


FUELS = ("DIESEL", "PETROL", "OCTANE")
PROFILE_DAILY_LITERS: dict[str, dict[str, float]] = {
    "urban_high": {"DIESEL": 8500.0, "PETROL": 10500.0, "OCTANE": 5600.0},
    "industrial": {"DIESEL": 14000.0, "PETROL": 4500.0, "OCTANE": 2200.0},
    "highway": {"DIESEL": 10500.0, "PETROL": 11000.0, "OCTANE": 6200.0},
    "regional": {"DIESEL": 7200.0, "PETROL": 7600.0, "OCTANE": 3600.0},
}

RISK_SCORE_BY_LEVEL = {
    "LOW": 0.15,
    "MEDIUM": 0.45,
    "HIGH": 0.72,
    "CRITICAL": 0.92,
}


def _parse_time(value: str | None) -> datetime | None:
    if not value:
        return None
    try:
        return datetime.fromisoformat(value.replace("Z", "+00:00"))
    except (TypeError, ValueError):
        return None


def hour_factor(profile: str, when: datetime | None) -> float:
    if when is None:
        return 1.0

    hour = when.hour
    if profile == "industrial":
        return 1.55 if 6 <= hour <= 17 else 0.45
    if profile == "highway":
        return 1.35 if (6 <= hour <= 9 or 16 <= hour <= 20) else 0.75
    if profile == "urban_high":
        return 1.45 if (7 <= hour <= 9 or 16 <= hour <= 20) else 0.70
    if profile == "regional":
        return 1.25 if 7 <= hour <= 20 else 0.65
    return 1.0


def _region_factor(snapshot: OperationalSnapshot, region_id: str | None) -> float:
    for region in snapshot.regions:
        if region.get("id") == region_id:
            try:
                return max(float(region.get("demand_factor", 1.0)), 0.0)
            except (TypeError, ValueError):
                return 1.0
    return 1.0


def _profile_anchor(
    snapshot: OperationalSnapshot,
    station: dict[str, Any],
    fuel: str,
    future_time: datetime | None,
) -> float:
    profile = str(station.get("demand_profile", ""))
    daily = PROFILE_DAILY_LITERS.get(profile, {}).get(fuel)
    if daily is None:
        return 0.0

    ticks_per_day = 1440.0 / max(float(snapshot.tick_minutes), 1.0)
    base_per_tick = daily / ticks_per_day
    region = _region_factor(snapshot, station.get("region_id"))
    try:
        multiplier = max(float(station.get("demand_multiplier", 1.0)), 0.0)
    except (TypeError, ValueError):
        multiplier = 1.0

    return max(0.0, base_per_tick * region * multiplier * hour_factor(profile, future_time))


def _history_for(
    snapshot: OperationalSnapshot,
    station_id: str,
    fuel: str,
) -> list[dict[str, Any]]:
    rows: list[dict[str, Any]] = []
    for row in snapshot.demand_history:
        if row.get("station_id") != station_id or row.get("fuel_type") != fuel:
            continue
        try:
            tick = int(row.get("tick"))
            demand = float(row.get("demand_liters"))
        except (TypeError, ValueError):
            continue
        if tick > snapshot.tick or demand < 0:
            continue
        rows.append({**row, "tick": tick, "demand_liters": demand})
    rows.sort(key=lambda x: x["tick"])
    return rows[-32:]


def _normalized_history(profile: str, rows: list[dict[str, Any]]) -> list[float]:
    values: list[float] = []
    for row in rows:
        when = _parse_time(row.get("sim_time"))
        factor = max(hour_factor(profile, when), 0.1)
        values.append(max(0.0, float(row["demand_liters"])) / factor)
    return values


def _ewma(values: list[float], alpha: float = 0.55) -> float:
    if not values:
        return 0.0
    state = values[0]
    for value in values[1:]:
        state = alpha * value + (1.0 - alpha) * state
    return max(0.0, state)


def _trend(values: list[float], baseline: float) -> float:
    if len(values) < 3:
        return 0.0
    recent = values[-6:]
    diffs = [b - a for a, b in zip(recent, recent[1:])]
    raw = median(diffs) if diffs else 0.0
    cap = max(abs(baseline) * 0.15, 1.0)
    return max(-cap, min(cap, raw))


def _confidence(rows: list[dict[str, Any]], snapshot: OperationalSnapshot) -> float:
    n = len(rows)
    if n == 0:
        base = 0.38
    else:
        values = [float(r["demand_liters"]) for r in rows[-16:]]
        avg = mean(values) if values else 0.0
        cv = (pstdev(values) / avg) if len(values) > 1 and avg > 1e-9 else 0.0
        sample_score = min(n / 16.0, 1.0)
        stability = max(0.0, 1.0 - min(cv, 1.0))
        base = 0.32 + 0.40 * sample_score + 0.20 * stability

    if snapshot.data_freshness != "FRESH":
        base *= 0.55
    return round(max(0.20, min(0.93, base)), 3)


def build_forecasts(
    snapshot: OperationalSnapshot,
    *,
    horizon_ticks: int = 16,
) -> list[ForecastResult]:
    horizon_ticks = max(1, min(int(horizon_ticks), 96))
    current_time = _parse_time(snapshot.sim_time)

    forecasts: list[ForecastResult] = []
    for station in snapshot.stations:
        station_id = str(station.get("id", ""))
        profile = str(station.get("demand_profile", ""))

        for fuel in FUELS:
            rows = _history_for(snapshot, station_id, fuel)
            normalized = _normalized_history(profile, rows)
            baseline = _ewma(normalized)
            trend = _trend(normalized, baseline)

            if len(rows) == 0:
                stat_weight = 0.0
                method = "profile_context_fallback"
            elif len(rows) < 4:
                stat_weight = 0.35
                method = "profile_adjusted_ewma"
            elif len(rows) < 8:
                stat_weight = 0.55
                method = "profile_adjusted_ewma"
            else:
                stat_weight = 0.78
                method = "profile_adjusted_ewma"

            series: list[float] = []
            for step in range(1, horizon_ticks + 1):
                future_time = (
                    current_time + timedelta(minutes=snapshot.tick_minutes * step)
                    if current_time is not None
                    else None
                )
                anchor = _profile_anchor(snapshot, station, fuel, future_time)
                stat = max(0.0, baseline + trend * step) * hour_factor(profile, future_time)

                if stat_weight <= 0:
                    predicted = anchor
                else:
                    predicted = stat_weight * stat + (1.0 - stat_weight) * anchor

                series.append(round(max(0.0, predicted), 3))

            forecasts.append(
                ForecastResult(
                    station_id=station_id,
                    fuel_type=fuel,
                    horizon_ticks=horizon_ticks,
                    predicted_demand_liters=round(sum(series), 3),
                    demand_per_tick=round(mean(series), 3) if series else 0.0,
                    confidence=_confidence(rows, snapshot),
                    method=method,
                    sample_count=len(rows),
                    per_tick_liters=series,
                )
            )

    return forecasts


def _known_arrivals(
    snapshot: OperationalSnapshot,
    station_id: str,
    fuel: str,
) -> dict[int, float]:
    arrivals: dict[int, float] = {}
    for allocation in snapshot.allocations:
        if allocation.get("destination_station_id") != station_id:
            continue
        if allocation.get("fuel_type") != fuel:
            continue
        if allocation.get("status") != "IN_TRANSIT":
            continue
        try:
            tick = int(allocation.get("expected_arrival_tick"))
            qty = float(allocation.get("quantity"))
        except (TypeError, ValueError):
            continue
        if tick >= snapshot.tick and qty > 0:
            arrivals[tick] = arrivals.get(tick, 0.0) + qty
    return arrivals


def _committed_inbound(snapshot: OperationalSnapshot, station_id: str, fuel: str) -> float:
    total = 0.0
    for allocation in snapshot.allocations:
        if allocation.get("destination_station_id") != station_id:
            continue
        if allocation.get("fuel_type") != fuel:
            continue
        if allocation.get("status") not in {"PENDING", "IN_TRANSIT"}:
            continue
        try:
            total += max(float(allocation.get("quantity", 0.0)), 0.0)
        except (TypeError, ValueError):
            pass
    return total


def assess_risks(
    snapshot: OperationalSnapshot,
    forecasts: list[ForecastResult],
) -> list[RiskAssessment]:
    forecast_map = {(f.station_id, f.fuel_type): f for f in forecasts}
    risks: list[RiskAssessment] = []

    for station in snapshot.stations:
        station_id = str(station.get("id", ""))
        station_status = str(station.get("status", "UNKNOWN"))
        try:
            multiplier = float(station.get("demand_multiplier", 1.0))
        except (TypeError, ValueError):
            multiplier = 1.0

        for fuel in FUELS:
            forecast = forecast_map[(station_id, fuel)]
            try:
                inventory = max(float(station.get("inventory", {}).get(fuel, 0.0)), 0.0)
                capacity = max(float(station.get("capacity", {}).get(fuel, 0.0)), 0.0)
            except (TypeError, ValueError):
                inventory = 0.0
                capacity = 0.0

            available_routes = [
                r
                for r in snapshot.routes
                if r.get("destination_station_id") == station_id
                and r.get("status") == "AVAILABLE"
            ]
            fastest = None
            if available_routes:
                fastest = min(max(int(r.get("transit_ticks", 0)), 0) for r in available_routes)

            known_arrivals = _known_arrivals(snapshot, station_id, fuel)
            projected = inventory
            stockout_tick: int | None = None

            for offset, demand in enumerate(forecast.per_tick_liters, start=1):
                tick = snapshot.tick + offset
                projected += known_arrivals.get(tick, 0.0)
                projected -= demand
                if projected <= 0 and stockout_tick is None:
                    stockout_tick = tick
                    break

            avg_demand = max(forecast.demand_per_tick, 1e-6)
            if stockout_tick is not None:
                runway = float(max(stockout_tick - snapshot.tick, 0))
            else:
                runway = min(
                    999.0,
                    max(0.0, (inventory + sum(known_arrivals.values())) / avg_demand),
                )

            inv_ratio = (inventory / capacity) if capacity > 0 else 0.0
            proximity = max(
                0.0,
                min(1.0, 1.0 - runway / max(forecast.horizon_ticks * 1.25, 1.0)),
            )
            multiplier_pressure = max(0.0, min((multiplier - 1.0) / 1.5, 1.0))
            risk_score = max(
                0.0,
                min(
                    1.0,
                    0.60 * proximity
                    + 0.25 * max(0.0, 1.0 - inv_ratio)
                    + 0.15 * multiplier_pressure,
                ),
            )

            reasons: list[str] = []
            if inv_ratio <= 0.35:
                reasons.append("LOW_INVENTORY")
            if stockout_tick is not None:
                reasons.append("STOCKOUT_WITHIN_FORECAST_HORIZON")
            if fastest is None:
                reasons.append("NO_AVAILABLE_ROUTE")
            elif runway <= fastest + 1:
                reasons.append("STOCKOUT_BEFORE_OR_NEAR_FASTEST_ROUTE")
                risk_score = max(risk_score, 0.90)
            if multiplier > 1.20:
                reasons.append("DEMAND_SPIKE")
            if station_status != "OPEN":
                reasons.append("STATION_UNAVAILABLE")
            if snapshot.data_freshness != "FRESH":
                reasons.append("DEGRADED_DATA")

            if inventory <= 0 or (fastest is not None and runway <= fastest + 1):
                level = "CRITICAL"
            elif runway <= max(6.0, float((fastest or 2) + 3)) or risk_score >= 0.65:
                level = "HIGH"
            elif (
                runway <= float(forecast.horizon_ticks)
                or inv_ratio <= 0.40
                or risk_score >= 0.35
            ):
                level = "MEDIUM"
            else:
                level = "LOW"

            level_score = RISK_SCORE_BY_LEVEL[level]
            risk_score = max(risk_score, level_score)

            confidence = forecast.confidence
            if snapshot.data_freshness != "FRESH":
                confidence = min(confidence, 0.50)

            risks.append(
                RiskAssessment(
                    station_id=station_id,
                    fuel_type=fuel,
                    risk_level=level,
                    runway_ticks=round(runway, 2),
                    projected_stockout_tick=stockout_tick,
                    confidence=round(confidence, 3),
                    reason_codes=reasons,
                    inventory_liters=round(inventory, 3),
                    capacity_liters=round(capacity, 3),
                    inbound_liters=round(
                        _committed_inbound(snapshot, station_id, fuel),
                        3,
                    ),
                    fastest_route_ticks=fastest,
                    risk_score=round(risk_score, 3),
                )
            )

    return risks
