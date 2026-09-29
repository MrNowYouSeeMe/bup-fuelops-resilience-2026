from __future__ import annotations

from copy import deepcopy

from app.intelligence import build_forecasts, hour_factor
from tests.helpers import base_snapshot


def find_forecast(items, station_id: str, fuel: str):
    return next(x for x in items if x.station_id == station_id and x.fuel_type == fuel)


def test_forecast_returns_all_12_station_fuel_series():
    snap = base_snapshot()
    forecasts = build_forecasts(snap, horizon_ticks=16)

    assert len(forecasts) == 12
    assert all(len(f.per_tick_liters) == 16 for f in forecasts)
    assert all(f.predicted_demand_liters >= 0 for f in forecasts)
    assert all(0.20 <= f.confidence <= 0.93 for f in forecasts)


def test_cold_start_uses_profile_context_fallback():
    snap = base_snapshot(with_history=False)
    forecasts = build_forecasts(snap, horizon_ticks=8)
    item = find_forecast(forecasts, "station-mirpur", "DIESEL")

    assert item.method == "profile_context_fallback"
    assert item.sample_count == 0
    assert item.confidence <= 0.45
    assert item.predicted_demand_liters > 0


def test_history_uses_profile_adjusted_ewma_and_is_deterministic():
    snap = base_snapshot()
    a = build_forecasts(snap, horizon_ticks=16)
    b = build_forecasts(snap, horizon_ticks=16)

    item_a = find_forecast(a, "station-mirpur", "PETROL")
    item_b = find_forecast(b, "station-mirpur", "PETROL")

    assert item_a.method == "profile_adjusted_ewma"
    assert item_a.sample_count >= 8
    assert item_a.model_dump() == item_b.model_dump()


def test_peak_hour_boundary_changes_future_context():
    snap = base_snapshot(tick=27, with_history=False)  # 06:45
    snap.sim_time = "2026-01-01T06:45:00+00:00"

    item = find_forecast(build_forecasts(snap, horizon_ticks=2), "station-mirpur", "DIESEL")

    # urban_high switches from 0.70 at 06:45 to 1.45 at 07:00
    assert item.per_tick_liters[0] > item.per_tick_liters[1] * 0.9
    assert hour_factor("urban_high", __import__("datetime").datetime.fromisoformat("2026-01-01T07:00:00+00:00")) == 1.45


def test_stale_data_reduces_confidence():
    fresh = base_snapshot(freshness="FRESH")
    stale = base_snapshot(freshness="STALE")

    fresh_item = find_forecast(build_forecasts(fresh), "station-tongi", "DIESEL")
    stale_item = find_forecast(build_forecasts(stale), "station-tongi", "DIESEL")

    assert stale_item.confidence < fresh_item.confidence


def test_malformed_and_future_history_rows_are_ignored():
    snap = base_snapshot()
    original_count = len(snap.demand_history)
    snap.demand_history.extend(
        [
            {"station_id": "station-mirpur", "fuel_type": "DIESEL", "tick": "bad", "demand_liters": 10},
            {"station_id": "station-mirpur", "fuel_type": "DIESEL", "tick": snap.tick + 9, "demand_liters": 99999},
            {"station_id": "station-mirpur", "fuel_type": "DIESEL", "tick": snap.tick, "demand_liters": -1},
        ]
    )

    item = find_forecast(build_forecasts(snap), "station-mirpur", "DIESEL")

    assert len(snap.demand_history) == original_count + 3
    assert item.sample_count <= 32
    assert item.predicted_demand_liters >= 0


def test_demand_multiplier_changes_cold_start_anchor():
    normal = base_snapshot(with_history=False)
    spike = base_snapshot(with_history=False)
    spike.stations[0]["demand_multiplier"] = 1.8

    a = find_forecast(build_forecasts(normal), "station-mirpur", "DIESEL")
    b = find_forecast(build_forecasts(spike), "station-mirpur", "DIESEL")

    assert b.predicted_demand_liters > a.predicted_demand_liters
