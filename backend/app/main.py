from __future__ import annotations

import asyncio
from contextlib import asynccontextmanager
from typing import Any

from fastapi import FastAPI, HTTPException, Request
from fastapi.middleware.cors import CORSMiddleware

from . import config
from .schemas import AppHealth, ComponentHealth, OperationalSnapshot
from .simulator_client import SimulatorClient, SimulatorError
from .state import SnapshotStore, StreamMonitor


async def _poll_loop(app: FastAPI) -> None:
    while True:
        try:
            await app.state.snapshot_store.refresh(app.state.simulator_client)
        except Exception:
            pass
        await asyncio.sleep(config.SNAPSHOT_POLL_SECONDS)


def create_app(
    *,
    background_enabled: bool = True,
    simulator_client: SimulatorClient | Any | None = None,
    snapshot_store: SnapshotStore | None = None,
    stream_monitor: StreamMonitor | None = None,
) -> FastAPI:
    @asynccontextmanager
    async def lifespan(app: FastAPI):
        app.state.simulator_client = simulator_client or SimulatorClient()
        app.state.snapshot_store = snapshot_store or SnapshotStore()
        app.state.stream_monitor = stream_monitor or StreamMonitor()
        app.state.tasks = []

        if background_enabled:
            try:
                await app.state.snapshot_store.refresh(app.state.simulator_client)
            except Exception:
                pass

            app.state.tasks = [
                asyncio.create_task(_poll_loop(app), name="snapshot-poll"),
                asyncio.create_task(
                    app.state.stream_monitor.run(
                        app.state.simulator_client,
                        lambda: app.state.snapshot_store.refresh(app.state.simulator_client),
                    ),
                    name="simulator-sse",
                ),
            ]

        try:
            yield
        finally:
            if hasattr(app.state, "stream_monitor"):
                app.state.stream_monitor.stop()
            for task in getattr(app.state, "tasks", []):
                task.cancel()
            if getattr(app.state, "tasks", []):
                await asyncio.gather(*app.state.tasks, return_exceptions=True)

            close = getattr(app.state.simulator_client, "close", None)
            if close is not None:
                await close()

    app = FastAPI(
        title="BUP FuelOps Resilience API",
        version="0.1.0-phase1",
        lifespan=lifespan,
    )

    app.add_middleware(
        CORSMiddleware,
        allow_origins=config.CORS_ORIGINS,
        allow_credentials=False,
        allow_methods=["GET"],
        allow_headers=["*"],
    )

    async def get_snapshot(request: Request) -> OperationalSnapshot:
        try:
            return await request.app.state.snapshot_store.refresh(
                request.app.state.simulator_client
            )
        except SimulatorError as exc:
            raise HTTPException(
                status_code=503,
                detail={"code": "SIMULATOR_UNAVAILABLE", "message": str(exc)},
            ) from exc

    @app.get("/api/health", response_model=AppHealth)
    async def health(request: Request) -> AppHealth:
        simulator_status = "UNAVAILABLE"
        simulator_detail = None
        try:
            payload = await request.app.state.simulator_client.health()
            if payload.get("status") == "ok":
                simulator_status = "HEALTHY"
            else:
                simulator_status = "DEGRADED"
                simulator_detail = str(payload)
        except Exception as exc:
            simulator_detail = str(exc)

        store = request.app.state.snapshot_store
        monitor = request.app.state.stream_monitor
        current = store.current

        snapshot_status = "UNKNOWN"
        if current is not None:
            if current.data_freshness == "FRESH":
                snapshot_status = "HEALTHY"
            else:
                snapshot_status = "DEGRADED"

        sse_status = (
            "HEALTHY"
            if monitor.status == "CONNECTED"
            else "DEGRADED" if monitor.status == "DEGRADED" else "STARTING"
        )

        overall = "HEALTHY"
        if simulator_status != "HEALTHY" or snapshot_status == "DEGRADED":
            overall = "DEGRADED"

        return AppHealth(
            status=overall,
            backend=ComponentHealth(status="HEALTHY"),
            simulator=ComponentHealth(
                status=simulator_status,
                detail=simulator_detail,
            ),
            sse=ComponentHealth(
                status=sse_status,
                detail=monitor.last_error,
            ),
            snapshot=ComponentHealth(
                status=snapshot_status,
                detail=store.last_error,
            ),
            tick=current.tick if current else None,
            reconnects=monitor.reconnects,
            events_seen=monitor.events_seen,
        )

    @app.get("/api/snapshot", response_model=OperationalSnapshot)
    async def snapshot(request: Request) -> OperationalSnapshot:
        return await get_snapshot(request)

    @app.get("/api/stations")
    async def stations(request: Request):
        return (await get_snapshot(request)).stations

    @app.get("/api/depots")
    async def depots(request: Request):
        return (await get_snapshot(request)).depots

    @app.get("/api/routes")
    async def routes(request: Request):
        return (await get_snapshot(request)).routes

    @app.get("/api/events")
    async def events(request: Request):
        return (await get_snapshot(request)).events

    return app


app = create_app()
