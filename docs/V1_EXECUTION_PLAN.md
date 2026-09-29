# V1 Execution and Self-Test Plan

V1 uses **four phases**. A phase advances only after its self-test gate passes.

```text
Design tests
â†’ Implement
â†’ Self-test
â†’ Diagnose
â†’ Consolidated fix pack
â†’ Re-test
â†’ PASS
â†’ Next phase
```

## Phase 1 â€” Foundation + Simulator Integration + Live Dashboard

Goal:

```text
Official Simulator
â†’ Simulator Client
â†’ OperationalSnapshot
â†’ Backend API
â†’ Operator Dashboard
```

Critical tests:
- simulator contract parsing
- offline/timeout/503
- malformed or incomplete payload
- empty collections
- SSE connect/disconnect/reconnect
- REST refresh after SSE reconnect
- UI healthy/degraded/no-data/outage/disruption states

Gate:

```text
simulator_connection      : PASS
snapshot_contract         : PASS
backend_health            : PASS
dashboard_live_data       : PASS
SSE_recovery              : PASS
malformed_input_handling  : PASS
local_run                 : PASS
```

## Phase 2 â€” Intelligence + Decision Support + Allocation Execution

Critical numeric boundaries:
- quantity = 0
- quantity < 0
- minimum positive
- quantity = route max
- quantity just above route max
- quantity = depot inventory
- quantity just above depot inventory
- exact destination capacity
- tiny destination over-capacity

Critical state/race cases:
- disrupted route
- route/source mismatch
- route/destination mismatch
- station outage
- depot constraint
- route changes before approval
- inventory changes before approval
- destination capacity changes before execution
- tick changes between analysis and approval

Idempotency:
- same key + same body
- same key + changed body
- retry after timeout
- duplicate operator click

Forecast:
- normal history
- empty history
- one sample
- few samples
- high noise
- demand spike
- zero demand

Invariants:
- never recommend quantity <= 0
- never exceed route max
- never exceed verified depot inventory
- never exceed destination free capacity
- never knowingly use disrupted route
- never execute without fresh revalidation

Gate:

```text
forecast_baseline        : PASS
risk_all_station_fuels   : PASS
heuristic_allocator      : PASS
constraint_guard         : PASS
operator_review          : PASS
fresh_revalidation       : PASS
allocation_execution     : PASS
idempotency              : PASS
race_tests               : PASS
boundary_suite           : PASS
```

## Phase 3 â€” Resilience + Crisis Handling + Observability

Single domain crises:
- demand spike
- route disruption
- station outage
- depot constraint
- shipment delay
- supply shortfall

Combined:
- demand spike + route disruption
- route disruption + shipment delay
- depot constraint + demand spike
- demand spike + route disruption + supply shortfall

Engineering faults:
- latency
- severe latency
- unavailable
- transient error rate
- stale data
- stream disconnect

Recovery:
- degraded status
- unsafe execution blocked on stale state
- fallback estimator
- REST polling after SSE failure
- fresh full resync after recovery

Gate:

```text
all_single_crises        : PASS
combined_crises          : PASS
API_faults               : PASS
fallback                 : PASS
recovery                 : PASS
observability            : PASS
structured_logs          : PASS
degraded_mode            : PASS
```

## Phase 4 â€” Deployment + Load Test + Full Regression + Evidence

Reproducible startup target:

```text
docker compose up --build
```

Load test:
- sequential baseline
- concurrency 2
- concurrency 4
- concurrency 8
- repeated burst

Record:
- requests
- successes/failures
- timeouts
- 5xx
- p50/p95/p99
- throughput
- error rate

Hidden-style regression:
- invalid IDs
- missing fields
- bad enums
- numeric boundaries
- duplicate requests
- state changes mid-flow
- 503/timeouts/malformed JSON/stale/disconnect
- no feasible allocation
- several valid alternatives
- equal-priority shortages
- competing stations for one depot
- shared dispatch capacity pressure
- long-running simulation
- repeated crises
- simultaneous recommendation/approval requests

Final gate:

```text
working_application      : PASS
simulator_integration    : PASS
intelligence             : PASS
operator_UI              : PASS
architecture             : PASS
deployment               : PASS
observability            : PASS
resilience_demo          : PASS
load_test                : PASS
fresh_run                : PASS
full_regression          : PASS
hidden_style_suite       : PASS
README                    : PASS
```
