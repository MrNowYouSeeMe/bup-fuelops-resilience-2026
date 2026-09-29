from __future__ import annotations

from copy import deepcopy

import httpx
import pytest
from fastapi.testclient import TestClient

from app.main import create_app
from app.observability import IncidentStore, RequestMetrics
from app.simulator_client import SimulatorClient, SimulatorUnavailable
from app.state import SnapshotStore, StreamMonitor
from tests.helpers import base_snapshot


class ToggleSimulator:
    def __init__(self):
        self.snap = base_snapshot()
        self.fail = False
        self.requests_total = 0
        self.retry_count = 0
        self.transient_failures = 0
        self.last_latency_ms = 1.5

    async def fetch_snapshot(self):
        if self.fail:
            raise SimulatorUnavailable("simulator unavailable")
        return deepcopy(self.snap)

    async def health(self):
        return {"status": "ok"}

    async def close(self):
        pass


def test_request_metrics_percentiles_and_errors():
    metrics = RequestMetrics(window=100)
    for status in (200, 200, 404, 503):
        started = metrics.begin()
        metrics.end(started, status)
    snap = metrics.snapshot()
    assert snap["requests_total"] == 4
    assert snap["errors_total"] == 2
    assert snap["error_rate"] == 0.5
    assert snap["latency"].sample_count == 4
    assert snap["latency"].p95_ms >= 0


def test_incident_store_deduplicates_and_resolves():
    store = IncidentStore(limit=10)
    one = store.open_or_update(
        "sim",
        kind="SIMULATOR_UNAVAILABLE",
        severity="HIGH",
        detail="down",
        tick=3,
    )
    two = store.open_or_update(
        "sim",
        kind="SIMULATOR_UNAVAILABLE",
        severity="HIGH",
        detail="still down",
        tick=4,
    )
    assert one.incident_id == two.incident_id
    assert two.occurrences == 2
    assert store.active_count() == 1

    resolved = store.resolve("sim", detail="recovered", tick=5)
    assert resolved is not None
    assert resolved.status == "RESOLVED"
    assert store.active_count() == 0


@pytest.mark.asyncio
async def test_simulator_get_retries_transient_503(monkeypatch):
    calls = 0

    def handler(request: httpx.Request):
        nonlocal calls
        calls += 1
        if calls == 1:
            return httpx.Response(503, json={"error": {"code": "FAULT_INJECTED"}})
        return httpx.Response(200, json={"status": "ok"})

    monkeypatch.setattr("app.config.SIMULATOR_GET_RETRY_ATTEMPTS", 2)
    monkeypatch.setattr("app.config.SIMULATOR_RETRY_BACKOFF_SECONDS", 0.001)

    async with httpx.AsyncClient(transport=httpx.MockTransport(handler)) as raw:
        client = SimulatorClient(base_url="http://sim", client=raw)
        health = await client.health()

    assert health["status"] == "ok"
    assert calls == 2
    assert client.retry_count == 1
    assert client.transient_failures == 1
    assert client.requests_total == 2


def test_system_endpoints_show_fallback_and_recovery():
    fake = ToggleSimulator()
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
        fresh = client.get("/api/snapshot")
        assert fresh.status_code == 200
        assert fresh.json()["data_freshness"] == "FRESH"

        fake.fail = True
        fallback = client.get("/api/snapshot")
        assert fallback.status_code == 200
        assert fallback.json()["data_freshness"] == "UNKNOWN"

        health = client.get("/api/system/health")
        assert health.status_code == 200
        assert health.json()["status"] == "DEGRADED"
        assert health.json()["components"]["simulator"]["status"] == "UNAVAILABLE"

        metrics = client.get("/api/system/metrics").json()
        assert metrics["fallback_activations"] >= 1
        assert metrics["active_incidents"] >= 1

        incidents = client.get("/api/incidents").json()
        assert any(item["kind"] == "SIMULATOR_UNAVAILABLE" and item["status"] == "ACTIVE" for item in incidents)

        fake.fail = False
        recovered = client.get("/api/snapshot")
        assert recovered.status_code == 200
        assert recovered.json()["data_freshness"] == "FRESH"

        metrics_after = client.get("/api/system/metrics").json()
        assert metrics_after["snapshot_recoveries"] >= 1

        incidents_after = client.get("/api/incidents").json()
        assert any(item["kind"] == "SIMULATOR_UNAVAILABLE" and item["status"] == "RESOLVED" for item in incidents_after)


def test_request_id_header_and_request_metrics_are_exposed():
    fake = ToggleSimulator()
    monitor = StreamMonitor()
    monitor.note_connected()
    app = create_app(
        background_enabled=False,
        simulator_client=fake,
        snapshot_store=SnapshotStore(),
        stream_monitor=monitor,
    )

    with TestClient(app) as client:
        response = client.get("/api/system/health", headers={"X-Request-ID": "judge-demo-1"})
        assert response.status_code == 200
        assert response.headers["X-Request-ID"] == "judge-demo-1"

        metrics = client.get("/api/system/metrics").json()
        assert metrics["requests_total"] >= 1
        assert metrics["latency"]["sample_count"] >= 1
