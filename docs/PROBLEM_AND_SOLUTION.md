# Problem and Version 1 Solution Approach

## Problem

The simulated fuel network must keep stations supplied with **DIESEL, PETROL and OCTANE** while demand, inventory, routes, supply arrivals and disruptions change over time.

The simulator is the world, not the brain. It exposes operational state and executes participant allocations, but it does not predict, optimize or recommend.

The application must answer:

- Where is a shortage likely?
- Which fuel is affected?
- When could stockout occur?
- How severe is the risk?
- How much fuel should be moved?
- From which depot?
- Through which valid route?
- Why is the action recommended?
- What is the expected impact?
- Is the underlying data fresh and trustworthy?
- What should happen if the simulator, stream or intelligence component fails?

The challenge combines:

1. operational intelligence
2. constraint-aware decision making
3. human decision support
4. simulator/API integration
5. resilience and incident response
6. observability and measurable performance
7. reproducible engineering

## Official Simulator World

The published simulator models:

- 2 regions
- 2 depots
- 4 stations
- 6 routes
- 3 fuel types
- a controllable 15-minute simulation tick

The main operational write is:

```text
POST /v1/allocations
```

The simulator can inject domain crises:

- demand spike
- route disruption
- station outage
- depot constraint
- shipment delay
- supply shortfall

And engineering faults:

- latency
- unavailable API
- transient error rate
- stale data
- SSE stream disconnect

## Why a Naive Refill Rule Is Not Enough

A valid decision may depend on:

- station inventory
- recent and expected demand
- time-of-day behavior
- demand multiplier
- projected stockout runway
- depot inventory
- depot dispatch capacity
- route pairing
- route availability
- route maximum shipment
- route transit time
- destination free capacity
- pending/in-transit allocations
- future depot supply arrivals
- active crisis events
- data freshness
- uncertainty/confidence

## V1 Operational Loop

```text
Simulator
â†’ OperationalSnapshot
â†’ Baseline Demand Estimate
â†’ Inventory Runway
â†’ Shortage Risk
â†’ Candidate Allocations
â†’ Deterministic Constraint Guard
â†’ Heuristic Ranking
â†’ Explainable Recommendation
â†’ Operator Review
â†’ Fresh State Revalidation
â†’ Simulator Allocation
â†’ Monitor Result
```

## OperationalSnapshot

```json
{
  "tick": 24,
  "sim_time": "...",
  "simulation_status": "RUNNING",
  "data_freshness": "FRESH",
  "depots": [],
  "stations": [],
  "routes": [],
  "supply_arrivals": [],
  "active_events": [],
  "allocations": [],
  "recent_demand": [],
  "metrics": {}
}
```

## Baseline Demand Estimation

V1 starts with a lightweight deterministic estimator using recent history, station demand profile, demand multiplier, simulated time and recent trend.

```json
{
  "station_id": "station-mirpur",
  "fuel_type": "DIESEL",
  "horizon_ticks": 16,
  "predicted_demand_liters": 3078.4,
  "demand_per_tick": 192.4,
  "confidence": 0.81,
  "method": "baseline_weighted"
}
```

## Inventory Runway and Shortage Risk

The platform monitors every station/fuel pair: 4 stations Ã— 3 fuels = 12 simultaneous operational risk states.

Risk levels:

```text
LOW
MEDIUM
HIGH
CRITICAL
```

## Deterministic Constraint Guard

Before a recommendation is executable, validate:

- IDs exist
- route matches source/destination
- depot is usable
- station is open
- route is available
- quantity is positive
- route max shipment is respected
- depot inventory is sufficient
- depot dispatch capacity is respected
- destination capacity is respected

## Heuristic Allocation Engine

Rank feasible candidates using signals such as:

- shortage urgency
- projected stockout time
- transit time
- depot inventory availability
- destination free capacity
- expected risk reduction
- active disruptions
- future supply context

Output contract:

```json
{
  "recommendation_id": "...",
  "source_depot_id": "depot-gazipur",
  "destination_station_id": "station-mirpur",
  "route_id": "route-gazipur-mirpur",
  "fuel_type": "DIESEL",
  "quantity": 4500,
  "priority": "HIGH",
  "confidence": 0.84,
  "risk_before": 0.76,
  "risk_after": 0.24,
  "constraints_checked": true,
  "reason_codes": [
    "STOCKOUT_RISK",
    "PEAK_DEMAND_APPROACHING",
    "ROUTE_AVAILABLE",
    "DEPOT_INVENTORY_AVAILABLE"
  ],
  "alternatives": []
}
```

## Human-in-the-Loop

```text
Recommendation
â†’ Why?
â†’ Expected impact
â†’ Confidence
â†’ Constraints checked
â†’ Approve / Reject
```

## Fresh-State Revalidation

```text
Operator clicks Approve
â†’ re-fetch authoritative REST state
â†’ rerun deterministic validation
â†’ if valid: execute
â†’ if invalid: invalidate and re-plan
```

## Resilience

| Failure | V1 behavior |
|---|---|
| SSE disconnected | REST polling fallback |
| simulator returns 503 | bounded retry/backoff |
| stale-data response | mark state DEGRADED |
| forecast failure | deterministic baseline estimator |
| decision module failure | safe heuristic fallback |
| malformed simulator payload | reject update + incident |
| simulator unavailable | last-known verified state read-only |
| dependency recovery | full fresh REST resync |

Unknown or stale state must not silently become a high-confidence executable decision.

## Observability

Minimum health/performance evidence:

- backend health
- simulator health
- SSE state
- forecast health
- decision-engine health
- request/error counts
- p50/p95/p99 latency
- recommendations/executions
- fallback activations
- reconnects
- stale-response count
- incident timeline
- structured logs

## Initial V1 Non-Goals

V1 does not depend on:

- reinforcement learning
- multi-agent systems
- a large language model
- Kubernetes
- Terraform
- Redis
- a complex microservice architecture

These may be explored only after the baseline system is verified.
