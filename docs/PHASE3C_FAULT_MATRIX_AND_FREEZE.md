# Phase 3C - Engineering Fault Matrix and Phase 3 Freeze

Phase 3C closes the resilience phase by verifying the production V1 loop against the remaining official simulator engineering faults and freezing the Phase 3 contracts.

## Baseline

- Phase 1: simulator integration and operational snapshot
- Phase 2: deterministic forecasting, stockout risk, human-reviewed allocation and fresh-state revalidation
- Phase 3A: unavailable fallback, observability, health, metrics, incidents and recovery
- Phase 3B: six domain crises and combined-crisis adaptation
- Phase 3C: engineering fault matrix and final Phase 3 freeze

## Official Engineering Fault Matrix

| Fault | Expected FuelOps behavior |
|---|---|
| `unavailable` | Bounded retry, then last verified read-only state; decision execution is blocked until fresh state recovers. |
| `latency` | Requests remain bounded by configured timeout; state stays fresh when responses arrive within the timeout; latency is observable. |
| `error_rate` | Transient 503 responses are retried a bounded number of times; persistent failure degrades to last verified read-only state; recovery triggers a full fresh refresh. |
| `stale_data` | `X-Simulator-Stale: true` propagates to `data_freshness=STALE`; stale data does not replace last verified state; allocation approval is blocked. |
| `stream_disconnect` | SSE becomes DEGRADED while periodic REST polling continues to refresh authoritative state; SSE reconnects automatically after the fault clears. |

## Combined Engineering Degradation

Phase 3C also verifies `stale_data + stream_disconnect` together:

- REST snapshot is explicitly `STALE`
- SSE component is `DEGRADED`
- overall system health is `DEGRADED`
- no unsafe allocation is allowed from stale state
- clearing faults restores fresh REST state and a healthy SSE connection

## Frozen Safety Rules

1. REST remains the authoritative state.
2. SSE remains advisory and must never be the only state source.
3. `FRESH` simulator state is required before allocation execution.
4. `STALE` and `UNKNOWN` state are read-only/degraded for consequential decisions.
5. Allocation requests use stable idempotency keys.
6. Retry is bounded; no infinite retry loop is permitted.
7. Last verified state may be displayed during simulator unavailability but must be marked degraded.
8. Domain crises change risk/recommendation context, but the deterministic constraint guard remains mandatory.
9. Human approval remains mandatory in V1.
10. `/admin/*` is used only for deterministic self-test/demo fault and crisis injection.

## Frozen Operational Contracts

The following V1 contracts are considered stable after Phase 3:

- `OperationalSnapshot`
- forecast result contract
- risk assessment contract
- allocation recommendation contract
- decision record contract
- crisis summary contract
- system health / metrics / incidents contracts
- simulator adapter REST/SSE boundary
- fresh-state revalidation before `POST /v1/allocations`

Advanced forecasting or optimization may replace the baseline implementation later, but these external contracts should remain compatible.

## Verification Gate

Phase 3C runner must pass:

- full backend regression
- frontend tests
- production frontend build
- unavailable regression
- latency live fault
- error-rate live fault
- stale-data live fault
- stale execution guard
- stream-disconnect live fault
- REST polling fallback while SSE is unavailable
- combined stale + stream degradation
- recovery to fresh/healthy state
- final clean simulator baseline
- isolated Git diff
- commit + remote verification

## After Phase 3

Phase 4 remains intentionally separate:

- load/performance testing
- fresh-clone reproducibility
- final judge/demo packaging and verification

No Phase 4 result is implied by the Phase 3 freeze.
