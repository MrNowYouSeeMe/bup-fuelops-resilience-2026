from __future__ import annotations

from app.intelligence import assess_risks, build_forecasts
from tests.helpers import base_snapshot


def find_risk(items, station_id: str, fuel: str):
    return next(x for x in items if x.station_id == station_id and x.fuel_type == fuel)


def test_risk_returns_all_12_station_fuel_states():
    snap = base_snapshot()
    forecasts = build_forecasts(snap)
    risks = assess_risks(snap, forecasts)

    assert len(risks) == 12
    assert {r.risk_level for r in risks} <= {"LOW", "MEDIUM", "HIGH", "CRITICAL"}
    assert all(0 <= r.risk_score <= 1 for r in risks)


def test_low_inventory_escalates_risk():
    snap = base_snapshot()
    snap.stations[0]["inventory"]["DIESEL"] = 150.0

    risk = find_risk(
        assess_risks(snap, build_forecasts(snap)),
        "station-mirpur",
        "DIESEL",
    )

    assert risk.risk_level in {"HIGH", "CRITICAL"}
    assert "LOW_INVENTORY" in risk.reason_codes
    assert risk.projected_stockout_tick is not None


def test_route_transit_is_used_in_critical_reasoning():
    snap = base_snapshot()
    snap.stations[0]["inventory"]["DIESEL"] = 100.0

    risk = find_risk(
        assess_risks(snap, build_forecasts(snap)),
        "station-mirpur",
        "DIESEL",
    )

    assert risk.fastest_route_ticks == 2
    assert "STOCKOUT_BEFORE_OR_NEAR_FASTEST_ROUTE" in risk.reason_codes


def test_in_transit_arrival_extends_projected_runway():
    without = base_snapshot()
    without.stations[0]["inventory"]["DIESEL"] = 250.0
    base_risk = find_risk(
        assess_risks(without, build_forecasts(without)),
        "station-mirpur",
        "DIESEL",
    )

    with_inbound = base_snapshot()
    with_inbound.stations[0]["inventory"]["DIESEL"] = 250.0
    with_inbound.allocations = [
        {
            "id": 1,
            "destination_station_id": "station-mirpur",
            "source_depot_id": "depot-gazipur",
            "route_id": "route-gazipur-mirpur",
            "fuel_type": "DIESEL",
            "quantity": 3000.0,
            "status": "IN_TRANSIT",
            "expected_arrival_tick": with_inbound.tick + 1,
        }
    ]
    inbound_risk = find_risk(
        assess_risks(with_inbound, build_forecasts(with_inbound)),
        "station-mirpur",
        "DIESEL",
    )

    assert inbound_risk.inbound_liters == 3000.0
    assert inbound_risk.runway_ticks >= base_risk.runway_ticks


def test_demand_spike_reason_is_exposed():
    snap = base_snapshot()
    snap.stations[1]["demand_multiplier"] = 1.8

    risk = find_risk(
        assess_risks(snap, build_forecasts(snap)),
        "station-tongi",
        "DIESEL",
    )

    assert "DEMAND_SPIKE" in risk.reason_codes


def test_stale_snapshot_caps_risk_confidence():
    snap = base_snapshot(freshness="STALE")
    risk = find_risk(
        assess_risks(snap, build_forecasts(snap)),
        "station-mirpur",
        "DIESEL",
    )

    assert risk.confidence <= 0.50
    assert "DEGRADED_DATA" in risk.reason_codes
