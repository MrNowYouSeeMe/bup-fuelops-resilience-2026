from __future__ import annotations

from copy import deepcopy

from fastapi.testclient import TestClient

from app.main import create_app
from app.state import SnapshotStore, StreamMonitor
from tests.helpers import base_snapshot


class FakeSimulator:
    def __init__(self, snapshot=None):
        self.snap = snapshot or base_snapshot()
        self.create_calls = 0
        self.allocations_created = []

    async def fetch_snapshot(self):
        return deepcopy(self.snap)

    async def health(self):
        return {
            "status": "ok",
            "database": "ok",
            "simulation": {"status": self.snap.simulation_status, "tick": self.snap.tick},
        }

    async def create_allocation(self, payload):
        self.create_calls += 1
        allocation = {
            "id": 100 + self.create_calls,
            **payload,
            "created_tick": self.snap.tick,
            "departure_tick": None,
            "expected_arrival_tick": None,
            "actual_arrival_tick": None,
            "status": "PENDING",
            "failure_reason": None,
        }
        self.allocations_created.append(allocation)
        return allocation

    async def close(self):
        pass


def make_client(fake: FakeSimulator):
    store = SnapshotStore()
    monitor = StreamMonitor()
    monitor.note_connected()
    app = create_app(
        background_enabled=False,
        simulator_client=fake,
        snapshot_store=store,
        stream_monitor=monitor,
    )
    return TestClient(app)


def first_recommendation(client: TestClient):
    response = client.get("/api/decision-support")
    assert response.status_code == 200
    body = response.json()
    assert len(body["forecasts"]) == 12
    assert len(body["risks"]) == 12
    assert body["recommendations"]
    return body["recommendations"][0]


def test_decision_support_contract_has_forecast_risk_and_recommendations():
    snap = base_snapshot()
    snap.stations[0]["inventory"]["DIESEL"] = 250
    fake = FakeSimulator(snap)

    with make_client(fake) as client:
        response = client.get("/api/decision-support")

    assert response.status_code == 200
    body = response.json()
    assert body["snapshot_tick"] == snap.tick
    assert body["data_freshness"] == "FRESH"
    assert len(body["forecasts"]) == 12
    assert len(body["risks"]) == 12
    assert len(body["recommendations"]) >= 1


def test_approve_revalidates_then_creates_allocation():
    snap = base_snapshot()
    snap.stations[0]["inventory"]["DIESEL"] = 250
    fake = FakeSimulator(snap)

    with make_client(fake) as client:
        rec = first_recommendation(client)
        response = client.post(f"/api/recommendations/{rec['recommendation_id']}/approve")

    assert response.status_code == 200
    body = response.json()
    assert body["status"] == "EXECUTED"
    assert body["allocation"]["idempotency_key"] == f"fuelops-{rec['recommendation_id']}"
    assert fake.create_calls == 1


def test_double_approve_is_idempotent_at_app_layer():
    snap = base_snapshot()
    snap.stations[0]["inventory"]["DIESEL"] = 250
    fake = FakeSimulator(snap)

    with make_client(fake) as client:
        rec = first_recommendation(client)
        url = f"/api/recommendations/{rec['recommendation_id']}/approve"
        first = client.post(url)
        second = client.post(url)

    assert first.status_code == 200
    assert second.status_code == 200
    assert first.json()["allocation"]["id"] == second.json()["allocation"]["id"]
    assert fake.create_calls == 1


def test_stale_state_blocks_execution():
    snap = base_snapshot()
    snap.stations[0]["inventory"]["DIESEL"] = 250
    fake = FakeSimulator(snap)

    with make_client(fake) as client:
        rec = first_recommendation(client)
        fake.snap.data_freshness = "STALE"
        fake.snap.degraded_reasons = ["SIMULATOR_STALE_DATA"]
        response = client.post(f"/api/recommendations/{rec['recommendation_id']}/approve")

    assert response.status_code == 409
    assert response.json()["detail"]["code"] == "STALE_STATE"
    assert fake.create_calls == 0


def test_route_change_between_recommendation_and_approval_is_blocked():
    snap = base_snapshot()
    snap.stations[0]["inventory"]["DIESEL"] = 250
    fake = FakeSimulator(snap)

    with make_client(fake) as client:
        rec = first_recommendation(client)
        for route in fake.snap.routes:
            if route["id"] == rec["route_id"]:
                route["status"] = "DISRUPTED"
        response = client.post(f"/api/recommendations/{rec['recommendation_id']}/approve")

    assert response.status_code == 409
    detail = response.json()["detail"]
    assert detail["code"] == "RECOMMENDATION_INVALIDATED"
    assert "ROUTE_STATUS" in detail["failed_constraints"]
    assert fake.create_calls == 0


def test_inventory_change_between_recommendation_and_approval_is_blocked():
    snap = base_snapshot()
    snap.stations[0]["inventory"]["DIESEL"] = 250
    fake = FakeSimulator(snap)

    with make_client(fake) as client:
        rec = first_recommendation(client)
        for depot in fake.snap.depots:
            if depot["id"] == rec["source_depot_id"]:
                depot["inventory"][rec["fuel_type"]] = 0
        response = client.post(f"/api/recommendations/{rec['recommendation_id']}/approve")

    assert response.status_code == 409
    assert "DEPOT_INVENTORY" in response.json()["detail"]["failed_constraints"]
    assert fake.create_calls == 0


def test_reject_is_recorded_and_blocks_later_approve():
    snap = base_snapshot()
    snap.stations[0]["inventory"]["DIESEL"] = 250
    fake = FakeSimulator(snap)

    with make_client(fake) as client:
        rec = first_recommendation(client)
        rid = rec["recommendation_id"]
        rejected = client.post(
            f"/api/recommendations/{rid}/reject",
            json={"reason": "Operator prefers alternate route."},
        )
        approve = client.post(f"/api/recommendations/{rid}/approve")
        history = client.get("/api/decisions").json()

    assert rejected.status_code == 200
    assert rejected.json()["status"] == "REJECTED"
    assert approve.status_code == 409
    assert any(item["recommendation_id"] == rid for item in history)


def test_reject_is_idempotent():
    snap = base_snapshot()
    snap.stations[0]["inventory"]["DIESEL"] = 250
    fake = FakeSimulator(snap)

    with make_client(fake) as client:
        rec = first_recommendation(client)
        rid = rec["recommendation_id"]
        first = client.post(f"/api/recommendations/{rid}/reject", json={})
        second = client.post(f"/api/recommendations/{rid}/reject", json={})

    assert first.status_code == 200
    assert second.status_code == 200
    assert first.json()["decision_id"] == second.json()["decision_id"]
