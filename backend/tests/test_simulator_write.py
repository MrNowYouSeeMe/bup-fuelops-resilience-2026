from __future__ import annotations

import httpx
import pytest

from app.simulator_client import SimulatorAPIError, SimulatorClient


@pytest.mark.asyncio
async def test_create_allocation_retries_same_idempotent_body_after_503():
    calls = {"count": 0, "keys": []}

    def handler(request: httpx.Request):
        calls["count"] += 1
        payload = __import__("json").loads(request.content.decode("utf-8"))
        calls["keys"].append(payload["idempotency_key"])
        if calls["count"] == 1:
            return httpx.Response(
                503,
                json={"error": {"code": "FAULT_INJECTED", "message": "temporary"}},
            )
        return httpx.Response(
            201,
            json={
                "id": 1,
                **payload,
                "created_tick": 4,
                "departure_tick": None,
                "expected_arrival_tick": None,
                "actual_arrival_tick": None,
                "status": "PENDING",
                "failure_reason": None,
            },
        )

    async with httpx.AsyncClient(transport=httpx.MockTransport(handler)) as raw:
        client = SimulatorClient(base_url="http://sim", client=raw)
        result = await client.create_allocation(
            {
                "idempotency_key": "fuelops-rec-1",
                "source_depot_id": "depot-gazipur",
                "destination_station_id": "station-mirpur",
                "route_id": "route-gazipur-mirpur",
                "fuel_type": "DIESEL",
                "quantity": 1000,
            }
        )

    assert result["status"] == "PENDING"
    assert calls["count"] == 2
    assert calls["keys"] == ["fuelops-rec-1", "fuelops-rec-1"]


@pytest.mark.asyncio
async def test_create_allocation_preserves_409_error_code():
    def handler(request: httpx.Request):
        return httpx.Response(
            409,
            json={
                "detail": {
                    "code": "ROUTE_DISRUPTED",
                    "message": "Route is disrupted.",
                }
            },
        )

    async with httpx.AsyncClient(transport=httpx.MockTransport(handler)) as raw:
        client = SimulatorClient(base_url="http://sim", client=raw)
        with pytest.raises(SimulatorAPIError) as exc:
            await client.create_allocation(
                {
                    "idempotency_key": "fuelops-rec-2",
                    "source_depot_id": "depot-gazipur",
                    "destination_station_id": "station-mirpur",
                    "route_id": "route-gazipur-mirpur",
                    "fuel_type": "DIESEL",
                    "quantity": 1000,
                }
            )

    assert exc.value.status_code == 409
    assert exc.value.code == "ROUTE_DISRUPTED"
