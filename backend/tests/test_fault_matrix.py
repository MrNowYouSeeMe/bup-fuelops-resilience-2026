from __future__ import annotations

import asyncio
from copy import deepcopy

import httpx
import pytest

from app.observability import ObservabilityHub
from app.simulator_client import SimulatorClient, SimulatorUnavailable
from app.state import SnapshotStore, StreamMonitor
from tests.helpers import base_snapshot


@pytest.mark.asyncio
async def test_latency_response_is_accepted_and_measured(monkeypatch):
    async def handler(request: httpx.Request) -> httpx.Response:
        await asyncio.sleep(0.02)
        return httpx.Response(200, json=[])

    monkeypatch.setattr("app.config.SIMULATOR_GET_RETRY_ATTEMPTS", 1)

    async with httpx.AsyncClient(transport=httpx.MockTransport(handler)) as raw:
        client = SimulatorClient(base_url="http://sim", client=raw)
        result = await client._get("/v1/stations", expected=list)

    assert result.data == []
    assert result.stale is False
    assert client.requests_total == 1
    assert client.last_latency_ms is not None
    assert client.last_latency_ms >= 10.0


@pytest.mark.asyncio
async def test_error_rate_style_503_exhausts_bounded_retries(monkeypatch):
    calls = 0

    def handler(request: httpx.Request) -> httpx.Response:
        nonlocal calls
        calls += 1
        return httpx.Response(
            503,
            json={
                "error": {
                    "code": "FAULT_INJECTED",
                    "message": "Injected transient API error.",
                }
            },
        )

    monkeypatch.setattr("app.config.SIMULATOR_GET_RETRY_ATTEMPTS", 2)
    monkeypatch.setattr("app.config.SIMULATOR_RETRY_BACKOFF_SECONDS", 0.001)

    async with httpx.AsyncClient(transport=httpx.MockTransport(handler)) as raw:
        client = SimulatorClient(base_url="http://sim", client=raw)
        with pytest.raises(SimulatorUnavailable):
            await client._get("/v1/stations", expected=list)

    assert calls == 2
    assert client.requests_total == 2
    assert client.retry_count == 1
    assert client.transient_failures == 2


@pytest.mark.asyncio
async def test_stale_header_is_propagated():
    def handler(request: httpx.Request) -> httpx.Response:
        return httpx.Response(
            200,
            headers={"X-Simulator-Stale": "true"},
            json=[],
        )

    async with httpx.AsyncClient(transport=httpx.MockTransport(handler)) as raw:
        client = SimulatorClient(base_url="http://sim", client=raw)
        result = await client._get("/v1/stations", expected=list)

    assert result.data == []
    assert result.stale is True


class FreshThenStaleSimulator:
    def __init__(self) -> None:
        self.snapshot = base_snapshot()
        self.stale = False

    async def fetch_snapshot(self):
        snap = deepcopy(self.snapshot)
        if self.stale:
            snap.data_freshness = "STALE"
            snap.degraded_reasons = ["SIMULATOR_STALE_DATA"]
        return snap


@pytest.mark.asyncio
async def test_stale_snapshot_never_replaces_last_verified_state():
    client = FreshThenStaleSimulator()
    store = SnapshotStore()

    fresh = await store.refresh(client)
    assert fresh.data_freshness == "FRESH"
    assert store.last_verified is not None
    verified_tick = store.last_verified.tick

    client.stale = True
    stale = await store.refresh(client)

    assert stale.data_freshness == "STALE"
    assert store.last_verified is not None
    assert store.last_verified.data_freshness == "FRESH"
    assert store.last_verified.tick == verified_tick


@pytest.mark.asyncio
async def test_stream_disconnect_503_raises_unavailable():
    def handler(request: httpx.Request) -> httpx.Response:
        assert request.url.path == "/v1/stream"
        return httpx.Response(
            503,
            json={"detail": {"code": "FAULT_INJECTED"}},
        )

    async with httpx.AsyncClient(transport=httpx.MockTransport(handler)) as raw:
        client = SimulatorClient(base_url="http://sim", client=raw)
        stream = client.stream_events()
        with pytest.raises(SimulatorUnavailable):
            await anext(stream)


def test_observability_distinguishes_stale_and_sse_degradation():
    snapshot = base_snapshot()
    snapshot.data_freshness = "STALE"
    snapshot.degraded_reasons = ["SIMULATOR_STALE_DATA"]

    store = SnapshotStore()
    store.current = snapshot
    store.last_verified = base_snapshot()

    monitor = StreamMonitor()
    monitor.note_disconnect("SSE returned HTTP 503")

    hub = ObservabilityHub()
    health = hub.system_health(
        snapshot_store=store,
        stream_monitor=monitor,
    )

    assert health.status == "DEGRADED"
    assert health.components["simulator"].status == "DEGRADED"
    assert health.components["snapshot"].status == "DEGRADED"
    assert health.components["sse"].status == "DEGRADED"
    assert health.components["decision"].status == "DEGRADED"

    incidents = hub.incidents.history()
    kinds = {item.kind for item in incidents if item.status == "ACTIVE"}
    assert "STALE_DATA" in kinds
    assert "SSE_DISCONNECTED" in kinds
