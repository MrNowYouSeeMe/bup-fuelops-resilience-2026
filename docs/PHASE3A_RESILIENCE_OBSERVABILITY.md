# Phase 3A â€” Resilience Core + Observability Foundation

## Scope

Phase 3 is intentionally split into small verified increments.

- **3A (this part):** bounded simulator retries, last-known-state fallback counters, recovery tracking, request IDs, API latency/error metrics, structured request logs, technical incident lifecycle, `/api/system/health`, `/api/system/metrics`, `/api/incidents`, and an operator observability panel.
- **3B:** six domain-crisis handlers and combined-crisis adaptation/replanning.
- **3C:** full injected-fault matrix, recovery/circuit behavior, final Phase 3 UI polish and regression freeze.

## Safety contracts

1. REST remains authoritative.
2. Transient simulator GET failures receive a bounded retry only.
3. If REST remains unavailable and a previously verified snapshot exists, the backend serves it as `UNKNOWN` / degraded state.
4. Allocation execution still requires `FRESH` data and existing Phase 2 fresh-state revalidation.
5. Technical incidents are deduplicated and later marked `RESOLVED`; they are not silently deleted.

## Observability endpoints

- `GET /api/system/health`
- `GET /api/system/metrics`
- `GET /api/incidents`

Metrics include request count, error rate, avg/p50/p95/p99 API latency, simulator retries/transient failures, fallback activations, snapshot recoveries, SSE reconnects/events, recommendation generation, decisions and active incidents.

## Evidence labels

This part is independently gated. Passing Phase 3A does not claim the six crisis types or the complete fault matrix are tested; those stay `NOT-TESTED` until 3B/3C.
