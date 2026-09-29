from __future__ import annotations

from app.decision import constraints_pass, validate_allocation
from app.intelligence import assess_risks, build_forecasts
from app.decision import build_recommendations
from tests.helpers import base_snapshot


def check_map(checks):
    return {c.code: c for c in checks}


def valid_checks(snapshot, quantity=1000.0):
    return validate_allocation(
        snapshot,
        source_depot_id="depot-gazipur",
        destination_station_id="station-mirpur",
        route_id="route-gazipur-mirpur",
        fuel_type="DIESEL",
        quantity=quantity,
    )


def test_exact_small_positive_quantity_is_allowed():
    snap = base_snapshot()
    checks = valid_checks(snap, quantity=0.001)
    assert constraints_pass(checks)


def test_zero_and_negative_quantities_are_rejected():
    snap = base_snapshot()
    assert not check_map(valid_checks(snap, 0.0))["QUANTITY_POSITIVE"].passed
    assert not check_map(valid_checks(snap, -1.0))["QUANTITY_POSITIVE"].passed


def test_route_capacity_boundary_and_over_boundary():
    snap = base_snapshot()
    at_limit = check_map(valid_checks(snap, 7000.0))
    over = check_map(valid_checks(snap, 7000.001))

    assert at_limit["ROUTE_CAPACITY"].passed
    assert not over["ROUTE_CAPACITY"].passed


def test_route_mismatch_is_rejected():
    snap = base_snapshot()
    checks = validate_allocation(
        snap,
        source_depot_id="depot-patiya",
        destination_station_id="station-mirpur",
        route_id="route-gazipur-mirpur",
        fuel_type="DIESEL",
        quantity=1000,
    )
    assert not check_map(checks)["ROUTE_MATCH"].passed


def test_disrupted_route_is_rejected():
    snap = base_snapshot()
    snap.routes[0]["status"] = "DISRUPTED"
    checks = valid_checks(snap, 1000)
    assert not check_map(checks)["ROUTE_STATUS"].passed


def test_closed_station_is_rejected():
    snap = base_snapshot()
    snap.stations[0]["status"] = "OUTAGE"
    checks = valid_checks(snap, 1000)
    assert not check_map(checks)["STATION_STATUS"].passed


def test_constrained_depot_is_still_allowed_by_simulator_contract():
    snap = base_snapshot()
    snap.depots[0]["status"] = "CONSTRAINED"
    checks = valid_checks(snap, 1000)
    assert check_map(checks)["DEPOT_STATUS"].passed


def test_insufficient_depot_inventory_is_rejected():
    snap = base_snapshot()
    snap.depots[0]["inventory"]["DIESEL"] = 900
    checks = valid_checks(snap, 1000)
    assert not check_map(checks)["DEPOT_INVENTORY"].passed


def test_destination_exact_capacity_boundary_and_over():
    snap = base_snapshot()
    snap.stations[0]["inventory"]["DIESEL"] = 14000

    exact = check_map(valid_checks(snap, 1000))
    over = check_map(valid_checks(snap, 1000.001))

    assert exact["DESTINATION_CAPACITY"].passed
    assert not over["DESTINATION_CAPACITY"].passed


def test_pending_inbound_reduces_safe_destination_headroom():
    snap = base_snapshot()
    snap.stations[0]["inventory"]["DIESEL"] = 10000
    snap.allocations = [
        {
            "id": 1,
            "source_depot_id": "depot-gazipur",
            "destination_station_id": "station-mirpur",
            "route_id": "route-gazipur-mirpur",
            "fuel_type": "DIESEL",
            "quantity": 4000,
            "status": "PENDING",
            "created_tick": snap.tick,
        }
    ]
    checks = check_map(valid_checks(snap, 1500))

    assert checks["DESTINATION_CAPACITY"].passed
    assert not checks["FUTURE_INBOUND_HEADROOM"].passed


def test_pending_dispatch_reduces_dispatch_capacity():
    snap = base_snapshot()
    snap.allocations = [
        {
            "id": 1,
            "source_depot_id": "depot-gazipur",
            "destination_station_id": "station-tongi",
            "route_id": "route-gazipur-tongi",
            "fuel_type": "DIESEL",
            "quantity": 11500,
            "status": "PENDING",
            "created_tick": snap.tick,
        }
    ]
    checks = check_map(valid_checks(snap, 1000))

    assert not checks["DISPATCH_CAPACITY"].passed


def test_recommendations_are_feasible_and_human_reviewed():
    snap = base_snapshot()
    snap.stations[0]["inventory"]["DIESEL"] = 300
    forecasts = build_forecasts(snap)
    risks = assess_risks(snap, forecasts)
    recommendations = build_recommendations(snap, forecasts, risks)

    assert recommendations
    rec = next(r for r in recommendations if r.destination_station_id == "station-mirpur" and r.fuel_type == "DIESEL")
    assert rec.constraints_checked
    assert rec.human_review_required
    assert rec.executable
    assert rec.quantity > 0
    assert all(c.passed for c in rec.constraints)


def test_stale_state_can_explain_but_cannot_execute():
    snap = base_snapshot(freshness="STALE")
    snap.stations[0]["inventory"]["DIESEL"] = 300
    forecasts = build_forecasts(snap)
    risks = assess_risks(snap, forecasts)
    recommendations = build_recommendations(snap, forecasts, risks)

    rec = next(r for r in recommendations if r.destination_station_id == "station-mirpur" and r.fuel_type == "DIESEL")
    assert not rec.executable
    assert "DEGRADED_DATA_BLOCKS_EXECUTION" in rec.reason_codes
