from __future__ import annotations

import asyncio
from contextlib import asynccontextmanager
from datetime import datetime, timezone
from typing import Any

from fastapi import FastAPI, HTTPException, Request
from fastapi.middleware.cors import CORSMiddleware

from . import config
from .decision import (
    DecisionStore,
    build_recommendations,
    constraints_pass,
    make_decision_record,
    validate_allocation,
)
from .intelligence import assess_risks, build_forecasts
from .schemas import (
    AppHealth,
    ComponentHealth,
    DecisionRecord,
    DecisionSupportBundle,
    ForecastResult,
    OperationalSnapshot,
    RejectRequest,
    RiskAssessment,
    AllocationRecommendation,
)
from .simulator_client import (
    SimulatorAPIError,
    SimulatorClient,
    SimulatorError,
    SimulatorUnavailable,
)
from .state import SnapshotStore, StreamMonitor


async def _poll_loop(app: FastAPI) -> None:
    while True:
        try:
            await app.state.snapshot_store.refresh(app.state.simulator_client)
        except Exception:
            pass
        await asyncio.sleep(config.SNAPSHOT_POLL_SECONDS)


def _horizon_ticks() -> int:
    return max(1, min(int(getattr(config, "FORECAST_HORIZON_TICKS", 16)), 96))


async def _get_snapshot(request: Request) -> OperationalSnapshot:
    try:
        return await request.app.state.snapshot_store.refresh(
            request.app.state.simulator_client
        )
    except SimulatorError as exc:
        raise HTTPException(
            status_code=503,
            detail={"code": "SIMULATOR_UNAVAILABLE", "message": str(exc)},
        ) from exc


def _compute_support(
    request: Request,
    snapshot: OperationalSnapshot,
) -> DecisionSupportBundle:
    forecasts = build_forecasts(snapshot, horizon_ticks=_horizon_ticks())
    risks = assess_risks(snapshot, forecasts)
    recommendations = build_recommendations(snapshot, forecasts, risks)
    request.app.state.decision_store.remember(recommendations)

    return DecisionSupportBundle(
        generated_at=datetime.now(timezone.utc).isoformat(),
        snapshot_tick=snapshot.tick,
        data_freshness=snapshot.data_freshness,
        forecasts=forecasts,
        risks=risks,
        recommendations=recommendations,
    )


def create_app(
    *,
    background_enabled: bool = True,
    simulator_client: SimulatorClient | Any | None = None,
    snapshot_store: SnapshotStore | None = None,
    stream_monitor: StreamMonitor | None = None,
    decision_store: DecisionStore | None = None,
) -> FastAPI:
    @asynccontextmanager
    async def lifespan(app: FastAPI):
        app.state.simulator_client = simulator_client or SimulatorClient()
        app.state.snapshot_store = snapshot_store or SnapshotStore()
        app.state.stream_monitor = stream_monitor or StreamMonitor()
        app.state.decision_store = decision_store or DecisionStore()
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
        version="0.2.0-phase2",
        lifespan=lifespan,
    )

    app.add_middleware(
        CORSMiddleware,
        allow_origins=config.CORS_ORIGINS,
        allow_credentials=False,
        allow_methods=["GET", "POST"],
        allow_headers=["*"],
    )

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
        return await _get_snapshot(request)

    @app.get("/api/stations")
    async def stations(request: Request):
        return (await _get_snapshot(request)).stations

    @app.get("/api/depots")
    async def depots(request: Request):
        return (await _get_snapshot(request)).depots

    @app.get("/api/routes")
    async def routes(request: Request):
        return (await _get_snapshot(request)).routes

    @app.get("/api/events")
    async def events(request: Request):
        return (await _get_snapshot(request)).events

    @app.get("/api/decision-support", response_model=DecisionSupportBundle)
    async def decision_support(request: Request) -> DecisionSupportBundle:
        snap = await _get_snapshot(request)
        return _compute_support(request, snap)

    @app.get("/api/forecasts", response_model=list[ForecastResult])
    async def forecasts(request: Request) -> list[ForecastResult]:
        snap = await _get_snapshot(request)
        return _compute_support(request, snap).forecasts

    @app.get("/api/risks", response_model=list[RiskAssessment])
    async def risks(request: Request) -> list[RiskAssessment]:
        snap = await _get_snapshot(request)
        return _compute_support(request, snap).risks

    @app.get("/api/recommendations", response_model=list[AllocationRecommendation])
    async def recommendations(request: Request) -> list[AllocationRecommendation]:
        snap = await _get_snapshot(request)
        return _compute_support(request, snap).recommendations

    @app.get("/api/decisions", response_model=list[DecisionRecord])
    async def decisions(request: Request) -> list[DecisionRecord]:
        return request.app.state.decision_store.history()

    @app.post(
        "/api/recommendations/{recommendation_id}/approve",
        response_model=DecisionRecord,
    )
    async def approve_recommendation(
        recommendation_id: str,
        request: Request,
    ) -> DecisionRecord:
        store: DecisionStore = request.app.state.decision_store

        async with store.lock:
            existing = store.get_decision(recommendation_id)
            if existing is not None:
                if existing.status == "EXECUTED":
                    return existing
                raise HTTPException(
                    status_code=409,
                    detail={
                        "code": "RECOMMENDATION_ALREADY_DECIDED",
                        "message": f"Recommendation is already {existing.status}.",
                    },
                )

            recommendation = store.get_recommendation(recommendation_id)
            if recommendation is None:
                # One recovery attempt: compute the latest recommendations in case
                # the operator opened the page before this backend process saw them.
                snap = await _get_snapshot(request)
                _compute_support(request, snap)
                recommendation = store.get_recommendation(recommendation_id)

            if recommendation is None:
                raise HTTPException(
                    status_code=404,
                    detail={
                        "code": "RECOMMENDATION_NOT_FOUND",
                        "message": "Recommendation is unknown or expired from this process.",
                    },
                )

            fresh = await _get_snapshot(request)
            if fresh.data_freshness != "FRESH":
                raise HTTPException(
                    status_code=409,
                    detail={
                        "code": "STALE_STATE",
                        "message": "Execution blocked because fresh simulator state is unavailable.",
                    },
                )

            checks = validate_allocation(
                fresh,
                source_depot_id=recommendation.source_depot_id,
                destination_station_id=recommendation.destination_station_id,
                route_id=recommendation.route_id,
                fuel_type=recommendation.fuel_type,
                quantity=recommendation.quantity,
                include_future_inbound_safety=True,
            )
            failed = [check.code for check in checks if not check.passed]
            if failed:
                record = make_decision_record(
                    recommendation_id,
                    action="BLOCK",
                    status="BLOCKED",
                    tick=fresh.tick,
                    reason="Fresh-state revalidation invalidated the recommendation.",
                    invalidated_constraints=failed,
                )
                store.save_decision(record)
                raise HTTPException(
                    status_code=409,
                    detail={
                        "code": "RECOMMENDATION_INVALIDATED",
                        "message": "Fresh-state revalidation failed.",
                        "failed_constraints": failed,
                    },
                )

            payload = {
                "idempotency_key": f"fuelops-{recommendation.recommendation_id}",
                "source_depot_id": recommendation.source_depot_id,
                "destination_station_id": recommendation.destination_station_id,
                "route_id": recommendation.route_id,
                "fuel_type": recommendation.fuel_type,
                "quantity": recommendation.quantity,
            }

            try:
                allocation = await request.app.state.simulator_client.create_allocation(payload)
            except SimulatorAPIError as exc:
                raise HTTPException(
                    status_code=exc.status_code,
                    detail={"code": exc.code, "message": exc.message},
                ) from exc
            except SimulatorUnavailable as exc:
                raise HTTPException(
                    status_code=503,
                    detail={
                        "code": "SIMULATOR_UNAVAILABLE",
                        "message": str(exc),
                    },
                ) from exc

            record = make_decision_record(
                recommendation_id,
                action="APPROVE",
                status="EXECUTED",
                tick=fresh.tick,
                reason="Human-approved recommendation passed fresh-state validation.",
                allocation=allocation,
            )
            store.save_decision(record)
            return record

    @app.post(
        "/api/recommendations/{recommendation_id}/reject",
        response_model=DecisionRecord,
    )
    async def reject_recommendation(
        recommendation_id: str,
        body: RejectRequest,
        request: Request,
    ) -> DecisionRecord:
        store: DecisionStore = request.app.state.decision_store

        async with store.lock:
            existing = store.get_decision(recommendation_id)
            if existing is not None:
                if existing.status == "REJECTED":
                    return existing
                raise HTTPException(
                    status_code=409,
                    detail={
                        "code": "RECOMMENDATION_ALREADY_DECIDED",
                        "message": f"Recommendation is already {existing.status}.",
                    },
                )

            recommendation = store.get_recommendation(recommendation_id)
            if recommendation is None:
                snap = await _get_snapshot(request)
                _compute_support(request, snap)
                recommendation = store.get_recommendation(recommendation_id)

            if recommendation is None:
                raise HTTPException(
                    status_code=404,
                    detail={
                        "code": "RECOMMENDATION_NOT_FOUND",
                        "message": "Recommendation is unknown or expired from this process.",
                    },
                )

            current = request.app.state.snapshot_store.current
            record = make_decision_record(
                recommendation_id,
                action="REJECT",
                status="REJECTED",
                tick=current.tick if current else recommendation.generated_tick,
                reason=body.reason or "Rejected by operator.",
            )
            store.save_decision(record)
            return record

    return app


app = create_app()
