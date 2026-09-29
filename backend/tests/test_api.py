from datetime import datetime, timezone

from fastapi.testclient import TestClient

from app.main import create_app
from app.schemas import OperationalSnapshot
from app.state import SnapshotStore, StreamMonitor


def snapshot():
    return OperationalSnapshot(
        captured_at=datetime.now(timezone.utc).isoformat(),
        tick=7,
        sim_time="2026-01-01T01:45:00+00:00",
        simulation_status="PAUSED",
        data_freshness="FRESH",
        depots=[{"id": "depot-gazipur"}],
        stations=[{"id": "station-mirpur"}],
        routes=[{"id": "route-gazipur-mirpur"}],
        metrics={"service_level": 1.0},
    )


class FakeSimulator:
    def __init__(self):
        self.snap = snapshot()

    async def fetch_snapshot(self):
        return self.snap

    async def health(self):
        return {
            "status": "ok",
            "database": "ok",
            "simulation": {"status": "PAUSED", "tick": 7},
        }

    async def close(self):
        pass


def make_client():
    store = SnapshotStore()
    monitor = StreamMonitor()
    monitor.note_connected()
    app = create_app(
        background_enabled=False,
        simulator_client=FakeSimulator(),
        snapshot_store=store,
        stream_monitor=monitor,
    )
    return TestClient(app)


def test_health_endpoint():
    with make_client() as client:
        client.get("/api/snapshot")
        response = client.get("/api/health")

    assert response.status_code == 200
    body = response.json()
    assert body["status"] == "HEALTHY"
    assert body["simulator"]["status"] == "HEALTHY"
    assert body["sse"]["status"] == "HEALTHY"
    assert body["tick"] == 7


def test_snapshot_endpoint():
    with make_client() as client:
        response = client.get("/api/snapshot")

    assert response.status_code == 200
    body = response.json()
    assert body["tick"] == 7
    assert body["stations"][0]["id"] == "station-mirpur"


def test_resource_endpoints():
    with make_client() as client:
        assert client.get("/api/stations").json()[0]["id"] == "station-mirpur"
        assert client.get("/api/depots").json()[0]["id"] == "depot-gazipur"
        assert client.get("/api/routes").json()[0]["id"] == "route-gazipur-mirpur"
        assert client.get("/api/events").json() == []
