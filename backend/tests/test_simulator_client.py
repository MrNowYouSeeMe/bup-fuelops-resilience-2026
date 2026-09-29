import json

import httpx
import pytest

from app.simulator_client import (
    SSEParser,
    SimulatorClient,
    SimulatorContractError,
)
from app.state import SnapshotStore, StreamMonitor


def fixture_payloads():
    return {
        "/v1/health": {"status": "ok", "database": "ok", "simulation": {"status": "PAUSED", "tick": 0}},
        "/v1/instance": {
            "id": 1,
            "scenario_id": "baseline",
            "scenario_version": "1.0",
            "seed": 12345,
            "sim_time": "2026-01-01T00:00:00+00:00",
            "tick": 0,
            "tick_minutes": 15,
            "status": "PAUSED",
        },
        "/v1/regions": [
            {"id": "region-dhaka", "name": "Dhaka Division", "demand_factor": 1.0}
        ],
        "/v1/depots": [
            {
                "id": "depot-gazipur",
                "name": "Gazipur Depot",
                "region_id": "region-dhaka",
                "status": "OPEN",
                "dispatch_capacity_per_tick": 12000,
                "capacity": {"DIESEL": 90000, "PETROL": 70000, "OCTANE": 45000},
                "inventory": {"DIESEL": 60000, "PETROL": 45000, "OCTANE": 26000},
            }
        ],
        "/v1/stations": [
            {
                "id": "station-mirpur",
                "name": "Mirpur Fuel Station",
                "region_id": "region-dhaka",
                "status": "OPEN",
                "demand_profile": "urban_high",
                "demand_multiplier": 1.0,
                "capacity": {"DIESEL": 15000, "PETROL": 14000, "OCTANE": 9000},
                "inventory": {"DIESEL": 9000, "PETROL": 9000, "OCTANE": 5000},
            }
        ],
        "/v1/routes": [
            {
                "id": "route-gazipur-mirpur",
                "source_depot_id": "depot-gazipur",
                "destination_station_id": "station-mirpur",
                "transit_ticks": 2,
                "max_shipment": 7000,
                "status": "AVAILABLE",
            }
        ],
        "/v1/supply-arrivals": [],
        "/v1/events": [],
        "/v1/allocations": [],
        "/v1/demand-history": [],
        "/v1/metrics": {
            "served_demand_liters": 0.0,
            "unmet_demand_liters": 0.0,
            "service_level": 1.0,
            "allocation_liters": 0.0,
            "allocation_failures": 0,
        },
    }


def transport_from(payloads, *, stale=False, broken_path=None, bad_json_path=None):
    def handler(request: httpx.Request):
        path = request.url.path
        if broken_path == path:
            return httpx.Response(503, json={"error": {"code": "FAULT_INJECTED"}})
        if bad_json_path == path:
            return httpx.Response(200, content=b"not-json")
        payload = payloads[path]
        headers = {"X-Simulator-Stale": "true"} if stale and path != "/v1/health" else {}
        return httpx.Response(200, json=payload, headers=headers)

    return httpx.MockTransport(handler)


@pytest.mark.asyncio
async def test_fetch_snapshot_fresh():
    payloads = fixture_payloads()
    async with httpx.AsyncClient(transport=transport_from(payloads)) as raw:
        client = SimulatorClient(base_url="http://sim", client=raw)
        snap = await client.fetch_snapshot()

    assert snap.tick == 0
    assert snap.simulation_status == "PAUSED"
    assert snap.data_freshness == "FRESH"
    assert snap.stations[0]["id"] == "station-mirpur"
    assert snap.depots[0]["id"] == "depot-gazipur"


@pytest.mark.asyncio
async def test_stale_header_marks_entire_snapshot_stale():
    payloads = fixture_payloads()
    async with httpx.AsyncClient(transport=transport_from(payloads, stale=True)) as raw:
        client = SimulatorClient(base_url="http://sim", client=raw)
        snap = await client.fetch_snapshot()

    assert snap.data_freshness == "STALE"
    assert "SIMULATOR_STALE_DATA" in snap.degraded_reasons


@pytest.mark.asyncio
async def test_wrong_collection_shape_is_rejected():
    payloads = fixture_payloads()
    payloads["/v1/stations"] = {"not": "a list"}

    async with httpx.AsyncClient(transport=transport_from(payloads)) as raw:
        client = SimulatorClient(base_url="http://sim", client=raw)
        with pytest.raises(SimulatorContractError):
            await client.fetch_snapshot()


@pytest.mark.asyncio
async def test_malformed_json_is_rejected():
    payloads = fixture_payloads()
    async with httpx.AsyncClient(
        transport=transport_from(payloads, bad_json_path="/v1/routes")
    ) as raw:
        client = SimulatorClient(base_url="http://sim", client=raw)
        with pytest.raises(SimulatorContractError):
            await client.fetch_snapshot()


@pytest.mark.asyncio
async def test_store_uses_last_verified_state_when_simulator_fails():
    payloads = fixture_payloads()

    async with httpx.AsyncClient(transport=transport_from(payloads)) as raw:
        client = SimulatorClient(base_url="http://sim", client=raw)
        store = SnapshotStore()
        first = await store.refresh(client)
        assert first.data_freshness == "FRESH"

    async with httpx.AsyncClient(
        transport=transport_from(payloads, broken_path="/v1/instance")
    ) as raw:
        client = SimulatorClient(base_url="http://sim", client=raw)
        fallback = await store.refresh(client)

    assert fallback.data_freshness == "UNKNOWN"
    assert fallback.tick == 0
    assert "SIMULATOR_UNAVAILABLE_USING_LAST_VERIFIED_STATE" in fallback.degraded_reasons


def test_sse_parser_ignores_comment_and_parses_event():
    parser = SSEParser()
    assert parser.feed(": connected") is None
    assert parser.feed("") is None
    assert parser.feed("event: simulation.tick") is None
    assert parser.feed('data: {"tick": 2, "sim_time": "x"}') is None
    event = parser.feed("")
    assert event == {
        "event": "simulation.tick",
        "data": {"tick": 2, "sim_time": "x"},
    }


def test_stream_monitor_reconnect_is_counted():
    monitor = StreamMonitor()
    monitor.note_connected()
    assert monitor.status == "CONNECTED"
    assert monitor.reconnects == 0

    monitor.note_disconnect("network")
    assert monitor.status == "DEGRADED"

    monitor.note_connected()
    assert monitor.status == "CONNECTED"
    assert monitor.reconnects == 1

    monitor.note_event("simulation.tick")
    assert monitor.events_seen == 1
    assert monitor.last_event == "simulation.tick"
