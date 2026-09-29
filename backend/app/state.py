from __future__ import annotations

import asyncio
from datetime import datetime, timezone
from typing import Awaitable, Callable

from . import config
from .schemas import OperationalSnapshot
from .simulator_client import SimulatorClient, SimulatorError


class SnapshotStore:
    def __init__(self) -> None:
        self.current: OperationalSnapshot | None = None
        self.last_verified: OperationalSnapshot | None = None
        self.last_error: str | None = None
        self._lock = asyncio.Lock()

    async def refresh(self, client: SimulatorClient) -> OperationalSnapshot:
        async with self._lock:
            try:
                snapshot = await client.fetch_snapshot()
                self.current = snapshot
                self.last_error = None
                if snapshot.data_freshness == "FRESH":
                    self.last_verified = snapshot
                return snapshot
            except SimulatorError as exc:
                self.last_error = str(exc)
                if self.last_verified is None:
                    raise

                fallback = self.last_verified.model_copy(deep=True)
                fallback.captured_at = datetime.now(timezone.utc).isoformat()
                fallback.data_freshness = "UNKNOWN"
                fallback.degraded_reasons = ["SIMULATOR_UNAVAILABLE_USING_LAST_VERIFIED_STATE"]
                self.current = fallback
                return fallback


class StreamMonitor:
    def __init__(self) -> None:
        self.status = "STARTING"
        self.last_error: str | None = None
        self.last_event: str | None = None
        self.last_event_at: str | None = None
        self.reconnects = 0
        self.events_seen = 0
        self._ever_connected = False
        self._stop = asyncio.Event()

    def stop(self) -> None:
        self._stop.set()

    def note_connected(self) -> None:
        if self._ever_connected:
            self.reconnects += 1
        self._ever_connected = True
        self.status = "CONNECTED"
        self.last_error = None

    def note_disconnect(self, detail: str) -> None:
        self.status = "DEGRADED"
        self.last_error = detail

    def note_event(self, name: str) -> None:
        self.events_seen += 1
        self.last_event = name
        self.last_event_at = datetime.now(timezone.utc).isoformat()

    async def run(
        self,
        client: SimulatorClient,
        on_signal: Callable[[], Awaitable[None]],
    ) -> None:
        while not self._stop.is_set():
            try:
                async for event in client.stream_events():
                    if self._stop.is_set():
                        return
                    name = str(event.get("event", "message"))
                    if name == "__connected__":
                        self.note_connected()
                        # REST is authoritative; refresh after initial connect/reconnect.
                        await on_signal()
                        continue
                    self.note_event(name)
                    await on_signal()
            except asyncio.CancelledError:
                raise
            except Exception as exc:
                self.note_disconnect(str(exc))
                try:
                    await asyncio.wait_for(
                        self._stop.wait(),
                        timeout=config.SSE_RECONNECT_SECONDS,
                    )
                except asyncio.TimeoutError:
                    pass
