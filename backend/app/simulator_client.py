from __future__ import annotations

import asyncio
import json
from dataclasses import dataclass
from datetime import datetime, timezone
from typing import Any, AsyncIterator

import httpx

from . import config
from .schemas import OperationalSnapshot


class SimulatorError(RuntimeError):
    pass


class SimulatorUnavailable(SimulatorError):
    pass


class SimulatorContractError(SimulatorError):
    pass


class SimulatorAPIError(SimulatorError):
    def __init__(self, status_code: int, code: str, message: str) -> None:
        super().__init__(f"{code}: {message}")
        self.status_code = status_code
        self.code = code
        self.message = message


@dataclass
class SimulatorResponse:
    data: Any
    stale: bool = False


class SSEParser:
    """Tiny line-based SSE parser. Comments/keepalives are intentionally ignored."""

    def __init__(self) -> None:
        self.event_name: str | None = None
        self.data_lines: list[str] = []

    def feed(self, raw_line: str) -> dict[str, Any] | None:
        line = raw_line.rstrip("\r\n")

        if line.startswith(":"):
            return None

        if line == "":
            if not self.event_name and not self.data_lines:
                return None

            payload: Any = None
            joined = "\n".join(self.data_lines)
            if joined:
                try:
                    payload = json.loads(joined)
                except json.JSONDecodeError:
                    payload = joined

            event = {
                "event": self.event_name or "message",
                "data": payload,
            }
            self.event_name = None
            self.data_lines = []
            return event

        if line.startswith("event:"):
            self.event_name = line.split(":", 1)[1].strip()
        elif line.startswith("data:"):
            self.data_lines.append(line.split(":", 1)[1].lstrip())

        return None


class SimulatorClient:
    def __init__(
        self,
        base_url: str | None = None,
        timeout_seconds: float | None = None,
        client: httpx.AsyncClient | None = None,
    ) -> None:
        self.base_url = (base_url or config.SIMULATOR_BASE_URL).rstrip("/")
        self.timeout_seconds = timeout_seconds or config.SIMULATOR_TIMEOUT_SECONDS
        self._owns_client = client is None
        self.client = client or httpx.AsyncClient(
            timeout=httpx.Timeout(self.timeout_seconds),
            headers={"Accept": "application/json"},
        )

    async def close(self) -> None:
        if self._owns_client:
            await self.client.aclose()

    @staticmethod
    def _api_error(response: httpx.Response) -> SimulatorAPIError:
        code = f"HTTP_{response.status_code}"
        message = response.text or "Simulator request failed."
        try:
            payload = response.json()
            detail = payload.get("detail") if isinstance(payload, dict) else None
            error = payload.get("error") if isinstance(payload, dict) else None
            node = detail if isinstance(detail, dict) else error if isinstance(error, dict) else None
            if node:
                code = str(node.get("code") or code)
                message = str(node.get("message") or message)
        except ValueError:
            pass
        return SimulatorAPIError(response.status_code, code, message)

    async def _get(
        self,
        path: str,
        *,
        expected: type,
        params: dict[str, Any] | None = None,
    ) -> SimulatorResponse:
        try:
            response = await self.client.get(f"{self.base_url}{path}", params=params)
        except (httpx.TimeoutException, httpx.NetworkError) as exc:
            raise SimulatorUnavailable(f"GET {path} failed: {exc.__class__.__name__}") from exc

        if response.status_code >= 500:
            raise SimulatorUnavailable(f"GET {path} returned HTTP {response.status_code}")
        if response.status_code >= 400:
            raise self._api_error(response)

        try:
            data = response.json()
        except ValueError as exc:
            raise SimulatorContractError(f"GET {path} did not return valid JSON") from exc

        if not isinstance(data, expected):
            raise SimulatorContractError(
                f"GET {path} returned {type(data).__name__}; expected {expected.__name__}"
            )

        stale = response.headers.get("X-Simulator-Stale", "").lower() == "true"
        return SimulatorResponse(data=data, stale=stale)

    async def _post_json(
        self,
        path: str,
        payload: dict[str, Any],
        *,
        expected: type = dict,
        safe_retry: bool = False,
    ) -> Any:
        attempts = 2 if safe_retry else 1
        last_exc: Exception | None = None

        for attempt in range(attempts):
            try:
                response = await self.client.post(
                    f"{self.base_url}{path}",
                    json=payload,
                    headers={"Accept": "application/json", "Content-Type": "application/json"},
                )
            except (httpx.TimeoutException, httpx.NetworkError) as exc:
                last_exc = exc
                if attempt + 1 < attempts:
                    await asyncio.sleep(0.08)
                    continue
                raise SimulatorUnavailable(
                    f"POST {path} failed: {exc.__class__.__name__}"
                ) from exc

            if response.status_code >= 500:
                if safe_retry and attempt + 1 < attempts:
                    await asyncio.sleep(0.08)
                    continue
                raise SimulatorUnavailable(
                    f"POST {path} returned HTTP {response.status_code}"
                )

            if response.status_code >= 400:
                raise self._api_error(response)

            try:
                data = response.json()
            except ValueError as exc:
                raise SimulatorContractError(
                    f"POST {path} did not return valid JSON"
                ) from exc

            if not isinstance(data, expected):
                raise SimulatorContractError(
                    f"POST {path} returned {type(data).__name__}; expected {expected.__name__}"
                )
            return data

        raise SimulatorUnavailable(
            f"POST {path} failed: {last_exc.__class__.__name__ if last_exc else 'unknown'}"
        )

    async def health(self) -> dict[str, Any]:
        return (await self._get("/v1/health", expected=dict)).data

    async def fetch_snapshot(self) -> OperationalSnapshot:
        calls = [
            self._get("/v1/instance", expected=dict),
            self._get("/v1/regions", expected=list),
            self._get("/v1/depots", expected=list),
            self._get("/v1/stations", expected=list),
            self._get("/v1/routes", expected=list),
            self._get("/v1/supply-arrivals", expected=list),
            self._get("/v1/events", expected=list),
            self._get("/v1/allocations", expected=list),
            self._get(
                "/v1/demand-history",
                expected=list,
                params={"limit": config.DEMAND_HISTORY_LIMIT},
            ),
            self._get("/v1/metrics", expected=dict),
        ]
        (
            instance,
            regions,
            depots,
            stations,
            routes,
            supply_arrivals,
            events,
            allocations,
            demand_history,
            metrics,
        ) = await asyncio.gather(*calls)

        stale = any(
            r.stale
            for r in (
                instance,
                regions,
                depots,
                stations,
                routes,
                supply_arrivals,
                events,
                allocations,
                demand_history,
                metrics,
            )
        )

        instance_data = instance.data
        required = ("tick", "status")
        missing = [field for field in required if field not in instance_data]
        if missing:
            raise SimulatorContractError(
                f"/v1/instance missing required field(s): {', '.join(missing)}"
            )

        tick_minutes = int(instance_data.get("tick_minutes", 15))
        if tick_minutes <= 0:
            raise SimulatorContractError("/v1/instance tick_minutes must be > 0")

        return OperationalSnapshot(
            captured_at=datetime.now(timezone.utc).isoformat(),
            tick=int(instance_data["tick"]),
            tick_minutes=tick_minutes,
            sim_time=instance_data.get("sim_time"),
            simulation_status=str(instance_data["status"]),
            data_freshness="STALE" if stale else "FRESH",
            regions=regions.data,
            depots=depots.data,
            stations=stations.data,
            routes=routes.data,
            supply_arrivals=supply_arrivals.data,
            events=events.data,
            allocations=allocations.data,
            demand_history=demand_history.data,
            metrics=metrics.data,
            degraded_reasons=["SIMULATOR_STALE_DATA"] if stale else [],
        )

    async def create_allocation(self, payload: dict[str, Any]) -> dict[str, Any]:
        # Allocation creation is safe to retry because the request always carries
        # a stable idempotency_key. Same key + same body returns the same allocation.
        return await self._post_json(
            "/v1/allocations",
            payload,
            expected=dict,
            safe_retry=True,
        )

    async def cancel_allocation(self, allocation_id: int) -> dict[str, Any]:
        return await self._post_json(
            f"/v1/allocations/{allocation_id}/cancel",
            {},
            expected=dict,
            safe_retry=False,
        )

    async def stream_events(self) -> AsyncIterator[dict[str, Any]]:
        parser = SSEParser()
        try:
            async with self.client.stream(
                "GET",
                f"{self.base_url}/v1/stream",
                timeout=None,
                headers={"Accept": "text/event-stream"},
            ) as response:
                if response.status_code == 503:
                    raise SimulatorUnavailable("SSE returned HTTP 503")
                if response.status_code >= 400:
                    raise SimulatorError(f"SSE returned HTTP {response.status_code}")

                yield {"event": "__connected__", "data": None}

                async for line in response.aiter_lines():
                    parsed = parser.feed(line)
                    if parsed is not None:
                        yield parsed
        except (httpx.TimeoutException, httpx.NetworkError) as exc:
            raise SimulatorUnavailable(f"SSE connection failed: {exc.__class__.__name__}") from exc
