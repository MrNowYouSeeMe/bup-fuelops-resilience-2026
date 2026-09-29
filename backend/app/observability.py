from __future__ import annotations

from collections import deque
from datetime import datetime, timezone
from threading import Lock
from time import perf_counter
from typing import Any

from . import config
from .schemas import (
    ComponentHealth,
    CrisisSummary,
    IncidentRecord,
    LatencySummary,
    SystemHealth,
    SystemMetrics,
)


def utc_now() -> str:
    return datetime.now(timezone.utc).isoformat()


def _percentile(values: list[float], percentile: float) -> float:
    if not values:
        return 0.0
    ordered = sorted(values)
    if len(ordered) == 1:
        return ordered[0]
    position = (len(ordered) - 1) * percentile
    low = int(position)
    high = min(low + 1, len(ordered) - 1)
    weight = position - low
    return ordered[low] * (1.0 - weight) + ordered[high] * weight


class RequestMetrics:
    def __init__(self, window: int | None = None) -> None:
        self.window = window or config.REQUEST_METRICS_WINDOW
        self.requests_total = 0
        self.errors_total = 0
        self.in_flight = 0
        self._latencies: deque[float] = deque(maxlen=self.window)
        self._lock = Lock()

    def begin(self) -> float:
        with self._lock:
            self.in_flight += 1
        return perf_counter()

    def end(self, started: float, status_code: int) -> float:
        latency_ms = max(0.0, (perf_counter() - started) * 1000.0)
        with self._lock:
            self.in_flight = max(0, self.in_flight - 1)
            self.requests_total += 1
            if status_code >= 400:
                self.errors_total += 1
            self._latencies.append(latency_ms)
        return latency_ms

    def snapshot(self) -> dict[str, Any]:
        with self._lock:
            values = list(self._latencies)
            total = self.requests_total
            errors = self.errors_total
            in_flight = self.in_flight
        avg = sum(values) / len(values) if values else 0.0
        return {
            "requests_total": total,
            "errors_total": errors,
            "error_rate": (errors / total) if total else 0.0,
            "in_flight": in_flight,
            "latency": LatencySummary(
                sample_count=len(values),
                avg_ms=round(avg, 3),
                p50_ms=round(_percentile(values, 0.50), 3),
                p95_ms=round(_percentile(values, 0.95), 3),
                p99_ms=round(_percentile(values, 0.99), 3),
            ),
        }


class IncidentStore:
    def __init__(self, limit: int | None = None) -> None:
        self.limit = limit or config.INCIDENT_HISTORY_LIMIT
        self._records: deque[IncidentRecord] = deque(maxlen=self.limit)
        self._active_by_key: dict[str, IncidentRecord] = {}
        self._counter = 0
        self._lock = Lock()

    def open_or_update(
        self,
        key: str,
        *,
        kind: str,
        severity: str,
        detail: str,
        tick: int | None,
    ) -> IncidentRecord:
        now = utc_now()
        with self._lock:
            existing = self._active_by_key.get(key)
            if existing is not None:
                existing.last_updated_at = now
                existing.detail = detail
                existing.tick = tick
                existing.occurrences += 1
                return existing

            self._counter += 1
            record = IncidentRecord(
                incident_id=f"inc-{self._counter:04d}",
                kind=kind,
                severity=severity,
                status="ACTIVE",
                started_at=now,
                last_updated_at=now,
                resolved_at=None,
                tick=tick,
                detail=detail,
                occurrences=1,
            )
            self._records.appendleft(record)
            self._active_by_key[key] = record
            return record

    def resolve(
        self,
        key: str,
        *,
        detail: str,
        tick: int | None,
    ) -> IncidentRecord | None:
        now = utc_now()
        with self._lock:
            existing = self._active_by_key.pop(key, None)
            if existing is None:
                return None
            existing.status = "RESOLVED"
            existing.resolved_at = now
            existing.last_updated_at = now
            existing.tick = tick
            existing.detail = detail
            return existing

    def history(self, limit: int = 50) -> list[IncidentRecord]:
        with self._lock:
            return [record.model_copy(deep=True) for record in list(self._records)[:limit]]

    def active_count(self) -> int:
        with self._lock:
            return len(self._active_by_key)


class ObservabilityHub:
    def __init__(self) -> None:
        self.requests = RequestMetrics()
        self.incidents = IncidentStore()
        self.recommendation_batches = 0
        self.recommendations_generated = 0
        self._known_domain_incident_keys: set[str] = set()

    def note_recommendations(self, count: int) -> None:
        self.recommendation_batches += 1
        self.recommendations_generated += max(0, int(count))

    def reconcile_runtime(self, snapshot_store: Any, stream_monitor: Any) -> None:
        current = getattr(snapshot_store, "current", None)
        tick = getattr(current, "tick", None)
        freshness = getattr(current, "data_freshness", "UNKNOWN") if current is not None else "UNKNOWN"
        last_error = getattr(snapshot_store, "last_error", None)

        if freshness == "UNKNOWN" or (current is None and last_error):
            self.incidents.open_or_update(
                "simulator-unavailable",
                kind="SIMULATOR_UNAVAILABLE",
                severity="HIGH",
                detail=last_error or "Simulator data path is unavailable; serving is degraded.",
                tick=tick,
            )
        else:
            self.incidents.resolve(
                "simulator-unavailable",
                detail="Simulator data path recovered.",
                tick=tick,
            )

        if freshness == "STALE":
            self.incidents.open_or_update(
                "snapshot-stale",
                kind="STALE_DATA",
                severity="HIGH",
                detail="Simulator marked one or more REST reads stale.",
                tick=tick,
            )
        else:
            self.incidents.resolve(
                "snapshot-stale",
                detail="Fresh REST state recovered.",
                tick=tick,
            )

        stream_status = str(getattr(stream_monitor, "status", "STARTING"))
        if stream_status == "DEGRADED":
            self.incidents.open_or_update(
                "sse-degraded",
                kind="SSE_DISCONNECTED",
                severity="MEDIUM",
                detail=str(getattr(stream_monitor, "last_error", None) or "SSE connection degraded."),
                tick=tick,
            )
        elif stream_status == "CONNECTED":
            self.incidents.resolve(
                "sse-degraded",
                detail="SSE connection recovered.",
                tick=tick,
            )

    def reconcile_domain_crises(self, summary: CrisisSummary) -> None:
        active_keys: set[str] = set()

        for assessment in summary.assessments:
            key = f"domain-event-{assessment.event_id}-{assessment.event_type}"
            if assessment.operational_status in {"ACTIVE", "PERSISTENT_EFFECT"}:
                active_keys.add(key)
                self._known_domain_incident_keys.add(key)
                self.incidents.open_or_update(
                    key,
                    kind=f"DOMAIN_{assessment.event_type.upper()}",
                    severity=assessment.severity,
                    detail=(
                        f"{assessment.event_type} is {assessment.operational_status}; "
                        + "; ".join(assessment.impacts[:2])
                    ),
                    tick=summary.snapshot_tick,
                )
            elif key in self._known_domain_incident_keys:
                self.incidents.resolve(
                    key,
                    detail=f"{assessment.event_type} no longer requires active crisis handling.",
                    tick=summary.snapshot_tick,
                )

        for key in self._known_domain_incident_keys - active_keys:
            self.incidents.resolve(
                key,
                detail="Domain crisis is no longer active in the current simulator state.",
                tick=summary.snapshot_tick,
            )

        combined_key = "combined-domain-crisis"
        if summary.combined_crisis:
            self.incidents.open_or_update(
                combined_key,
                kind="COMBINED_DOMAIN_CRISIS",
                severity="CRITICAL",
                detail=(
                    "Overlapping domain crises require coordinated replanning: "
                    + ", ".join(summary.active_types)
                ),
                tick=summary.snapshot_tick,
            )
        else:
            self.incidents.resolve(
                combined_key,
                detail="Combined domain crisis condition cleared.",
                tick=summary.snapshot_tick,
            )

    def system_metrics(
        self,
        *,
        simulator_client: Any,
        snapshot_store: Any,
        stream_monitor: Any,
        decision_store: Any,
    ) -> SystemMetrics:
        request = self.requests.snapshot()
        history = list(decision_store.history())
        executed = sum(1 for item in history if item.status == "EXECUTED")
        rejected = sum(1 for item in history if item.status == "REJECTED")
        blocked = sum(1 for item in history if item.status == "BLOCKED")

        return SystemMetrics(
            generated_at=utc_now(),
            requests_total=request["requests_total"],
            errors_total=request["errors_total"],
            error_rate=round(float(request["error_rate"]), 6),
            in_flight=request["in_flight"],
            latency=request["latency"],
            simulator_requests_total=int(getattr(simulator_client, "requests_total", 0)),
            simulator_retry_count=int(getattr(simulator_client, "retry_count", 0)),
            simulator_transient_failures=int(getattr(simulator_client, "transient_failures", 0)),
            simulator_last_latency_ms=getattr(simulator_client, "last_latency_ms", None),
            fallback_activations=int(getattr(snapshot_store, "fallback_activations", 0)),
            snapshot_recoveries=int(getattr(snapshot_store, "recoveries", 0)),
            sse_reconnects=int(getattr(stream_monitor, "reconnects", 0)),
            sse_events_seen=int(getattr(stream_monitor, "events_seen", 0)),
            recommendation_batches=self.recommendation_batches,
            recommendations_generated=self.recommendations_generated,
            decisions_executed=executed,
            decisions_rejected=rejected,
            decisions_blocked=blocked,
            active_incidents=self.incidents.active_count(),
        )

    def system_health(
        self,
        *,
        snapshot_store: Any,
        stream_monitor: Any,
    ) -> SystemHealth:
        self.reconcile_runtime(snapshot_store, stream_monitor)
        current = getattr(snapshot_store, "current", None)
        freshness = getattr(current, "data_freshness", "UNKNOWN") if current is not None else "UNKNOWN"
        tick = getattr(current, "tick", None)
        degraded_reasons = list(getattr(current, "degraded_reasons", []) or [])
        last_error = getattr(snapshot_store, "last_error", None)

        if current is None and last_error:
            simulator_status = "UNAVAILABLE"
            simulator_detail = last_error
        elif freshness == "UNKNOWN":
            simulator_status = "UNAVAILABLE"
            simulator_detail = last_error or "Using last verified simulator state."
        elif freshness == "STALE":
            simulator_status = "DEGRADED"
            simulator_detail = "Simulator REST data is marked stale."
        else:
            simulator_status = "HEALTHY"
            simulator_detail = None

        if current is None:
            snapshot_status = "STARTING" if not last_error else "UNAVAILABLE"
        elif freshness == "FRESH":
            snapshot_status = "HEALTHY"
        else:
            snapshot_status = "DEGRADED"

        sse_raw = str(getattr(stream_monitor, "status", "STARTING"))
        sse_status = (
            "HEALTHY"
            if sse_raw == "CONNECTED"
            else "DEGRADED"
            if sse_raw == "DEGRADED"
            else "STARTING"
        )

        decision_status = "HEALTHY" if freshness == "FRESH" else "DEGRADED"

        components = {
            "backend": ComponentHealth(status="HEALTHY"),
            "simulator": ComponentHealth(status=simulator_status, detail=simulator_detail),
            "snapshot": ComponentHealth(status=snapshot_status, detail=last_error),
            "sse": ComponentHealth(
                status=sse_status,
                detail=getattr(stream_monitor, "last_error", None),
            ),
            "decision": ComponentHealth(
                status=decision_status,
                detail=None if freshness == "FRESH" else "Execution requires fresh simulator state.",
            ),
        }

        overall = "HEALTHY"
        if any(component.status in {"DEGRADED", "UNAVAILABLE"} for component in components.values()):
            overall = "DEGRADED"
        elif any(component.status == "STARTING" for component in components.values()):
            overall = "STARTING"

        return SystemHealth(
            status=overall,
            tick=tick,
            data_freshness=freshness,
            components=components,
            degraded_reasons=degraded_reasons,
            active_incidents=self.incidents.active_count(),
        )
