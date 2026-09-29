from __future__ import annotations

from copy import deepcopy

from fastapi.testclient import TestClient

from app.crisis import analyze_crises, supply_pressure_for_candidate
from app.decision import build_recommendations
from app.intelligence import assess_risks, build_forecasts
from app.main import create_app
from app.observability import ObservabilityHub
from app.state import SnapshotStore, StreamMonitor
from tests.helpers import base_snapshot
from tests.test_phase2_api import FakeSimulator


def _event(
    event_type: str,
    *,
    event_id: int = 1,
    status: str = "ACTIVE",
    start_tick: int = 32,
    end_tick: int = 40,
    parameters: dict | None = None,
):
    return {
        "id": event_id,
        "type": event_type,
        "start_tick": start_tick,
        "end_tick": end_tick,
        "status": status,
        "parameters": parameters or {},
    }


def test_no_domain_event_is_normal():
    summary = analyze_crises(base_snapshot())

    assert summary.crisis_level == "NORMAL"
    assert summary.active_crisis_count == 0
    assert not summary.combined_crisis
    assert not summary.replan_required


def test_all_six_domain_event_types_are_classified():
    cases = {
        "demand_spike": "HIGH",
        "route_disruption": "HIGH",
        "station_outage": "CRITICAL",
        "depot_constraint": "MEDIUM",
        "shipment_delay": "MEDIUM",
        "supply_shortfall": "HIGH",
    }

    for index, (event_type, severity) in enumerate(cases.items(), start=1):
        snap = base_snapshot()
        snap.events = [_event(event_type, event_id=index)]
        summary = analyze_crises(snap)

        assert summary.active_crisis_count == 1
        assert summary.active_types == [event_type]
        assert summary.assessments[0].severity == severity
        assert summary.assessments[0].operational_status == "ACTIVE"
        assert summary.assessments[0].adaptation_actions


def test_resolved_shipment_delay_remains_persistent_while_delayed_future_supply_exists():
    snap = base_snapshot()
    snap.supply_arrivals = [
        {
            "id": "supply-x",
            "depot_id": "depot-gazipur",
            "fuel_type": "DIESEL",
            "quantity": 5000,
            "planned_tick": 45,
            "actual_tick": None,
            "status": "DELAYED",
        }
    ]
    snap.events = [
        _event(
            "shipment_delay",
            status="RESOLVED",
            parameters={"depot_ids": ["depot-gazipur"], "fuel_types": ["DIESEL"]},
        )
    ]

    summary = analyze_crises(snap)

    assert summary.active_crisis_count == 1
    assert summary.assessments[0].operational_status == "PERSISTENT_EFFECT"


def test_resolved_supply_shortfall_remains_persistent_for_matching_future_supply():
    snap = base_snapshot()
    snap.supply_arrivals = [
        {
            "id": "supply-x",
            "depot_id": "depot-gazipur",
            "fuel_type": "DIESEL",
            "quantity": 2500,
            "planned_tick": 45,
            "actual_tick": None,
            "status": "SCHEDULED",
        }
    ]
    snap.events = [
        _event(
            "supply_shortfall",
            status="RESOLVED",
            parameters={"depot_ids": ["depot-gazipur"], "fuel_types": ["DIESEL"]},
        )
    ]

    summary = analyze_crises(snap)

    assert summary.active_crisis_count == 1
    assert summary.assessments[0].operational_status == "PERSISTENT_EFFECT"


def test_combined_crisis_is_critical_and_requires_replan():
    snap = base_snapshot()
    snap.events = [
        _event(
            "demand_spike",
            event_id=1,
            parameters={"station_ids": ["station-mirpur"], "multiplier": 1.8},
        ),
        _event(
            "route_disruption",
            event_id=2,
            parameters={"route_ids": ["route-gazipur-mirpur"]},
        ),
    ]

    summary = analyze_crises(snap)

    assert summary.combined_crisis
    assert summary.crisis_level == "CRITICAL"
    assert summary.active_crisis_count == 2
    assert set(summary.active_types) == {"demand_spike", "route_disruption"}
    assert summary.replan_required
    assert any("combined-crisis" in item.lower() for item in summary.decision_context)


def test_depot_constraint_and_supply_events_create_candidate_pressure():
    snap = base_snapshot()
    snap.depots[0]["status"] = "CONSTRAINED"
    snap.supply_arrivals = [
        {
            "id": "supply-x",
            "depot_id": "depot-gazipur",
            "fuel_type": "DIESEL",
            "quantity": 2500,
            "planned_tick": 45,
            "actual_tick": None,
            "status": "DELAYED",
        }
    ]
    snap.events = [
        _event(
            "shipment_delay",
            event_id=1,
            parameters={"depot_ids": ["depot-gazipur"], "fuel_types": ["DIESEL"]},
        ),
        _event(
            "supply_shortfall",
            event_id=2,
            parameters={"depot_ids": ["depot-gazipur"], "fuel_types": ["DIESEL"], "factor": 0.5},
        ),
    ]

    penalty, reasons = supply_pressure_for_candidate(
        snap,
        depot_id="depot-gazipur",
        fuel_type="DIESEL",
    )

    assert penalty > 0
    assert "DEPOT_CONSTRAINED" in reasons
    assert "SUPPLY_DELAY_PRESSURE" in reasons
    assert "SUPPLY_SHORTFALL_PRESSURE" in reasons


def test_recommendation_prefers_healthy_equal_alternative_over_constrained_depot():
    snap = base_snapshot()
    snap.stations[0]["inventory"]["DIESEL"] = 250
    snap.depots[0]["status"] = "CONSTRAINED"

    # Make the Patiya alternative operationally equal to isolate the crisis penalty.
    for route in snap.routes:
        if route["id"] == "route-patiya-mirpur":
            route["transit_ticks"] = 2
            route["max_shipment"] = 7000

    forecasts = build_forecasts(snap)
    risks = assess_risks(snap, forecasts)
    recs = build_recommendations(snap, forecasts, risks)
    rec = next(
        item
        for item in recs
        if item.destination_station_id == "station-mirpur"
        and item.fuel_type == "DIESEL"
    )

    assert rec.source_depot_id == "depot-patiya"


def test_if_constrained_depot_is_only_feasible_choice_reason_is_explained():
    snap = base_snapshot()
    snap.stations[1]["inventory"]["DIESEL"] = 250  # Tongi has only Gazipur route.
    snap.depots[0]["status"] = "CONSTRAINED"

    forecasts = build_forecasts(snap)
    risks = assess_risks(snap, forecasts)
    recs = build_recommendations(snap, forecasts, risks)
    rec = next(
        item
        for item in recs
        if item.destination_station_id == "station-tongi"
        and item.fuel_type == "DIESEL"
    )

    assert rec.source_depot_id == "depot-gazipur"
    assert "DEPOT_CONSTRAINED" in rec.reason_codes


def test_crisis_endpoint_and_domain_incident_contract():
    snap = base_snapshot()
    snap.events = [
        _event(
            "station_outage",
            parameters={"station_ids": ["station-mirpur"]},
        )
    ]
    fake = FakeSimulator(snap)
    store = SnapshotStore()
    monitor = StreamMonitor()
    monitor.note_connected()
    app = create_app(
        background_enabled=False,
        simulator_client=fake,
        snapshot_store=store,
        stream_monitor=monitor,
    )

    with TestClient(app) as client:
        crisis = client.get("/api/crisis")
        incidents = client.get("/api/incidents")

    assert crisis.status_code == 200
    body = crisis.json()
    assert body["crisis_level"] == "CRITICAL"
    assert body["active_types"] == ["station_outage"]
    assert body["replan_required"] is True

    assert incidents.status_code == 200
    assert any(
        item["kind"] == "DOMAIN_STATION_OUTAGE"
        and item["status"] == "ACTIVE"
        for item in incidents.json()
    )


def test_combined_crisis_opens_and_then_resolves_combined_incident():
    hub = ObservabilityHub()
    snap = base_snapshot()
    snap.events = [
        _event("demand_spike", event_id=1),
        _event("route_disruption", event_id=2),
    ]
    combined = analyze_crises(snap)
    hub.reconcile_domain_crises(combined)

    assert any(
        item.kind == "COMBINED_DOMAIN_CRISIS" and item.status == "ACTIVE"
        for item in hub.incidents.history()
    )

    snap.events = []
    clear = analyze_crises(snap)
    hub.reconcile_domain_crises(clear)

    assert any(
        item.kind == "COMBINED_DOMAIN_CRISIS" and item.status == "RESOLVED"
        for item in hub.incidents.history()
    )
