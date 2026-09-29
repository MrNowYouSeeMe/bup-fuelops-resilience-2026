# Phase 3B â€” Domain Crisis Detection, Adaptation and Replanning

## Scope

Phase 3B covers the six official simulator domain-event types and combined-crisis behavior:

1. `demand_spike`
2. `route_disruption`
3. `station_outage`
4. `depot_constraint`
5. `shipment_delay`
6. `supply_shortfall`
7. overlapping/combined crises

Phase 3C remains responsible for the complete injected engineering-fault matrix (`latency`, `unavailable`, `error_rate`, `stale_data`, `stream_disconnect`) and the final Phase 3 freeze.

## Contract

`GET /api/crisis` returns:

- `snapshot_tick`
- `crisis_level`: `NORMAL | ELEVATED | HIGH | CRITICAL`
- `combined_crisis`
- `active_crisis_count`
- `active_types`
- `replan_required`
- per-event assessment:
  - simulator status
  - operational status
  - severity
  - affected resources
  - operational impacts
  - adaptation actions
- decision context

Operational statuses are:

- `SCHEDULED`
- `ACTIVE`
- `PERSISTENT_EFFECT`
- `RESOLVED`
- `UNKNOWN`

`PERSISTENT_EFFECT` is used for one-shot supply events whose simulator event can resolve while the changed future supply state still matters.

## Adaptation Rules

- Demand spike: simulator `demand_multiplier` is already part of the forecasting/risk path, so the intelligence layer recalculates demand and runway from the current state.
- Route disruption: unavailable routes are excluded; approval still performs fresh-state revalidation.
- Station outage: non-OPEN stations are excluded from recommendations.
- Depot constraint: constrained depots remain legal but receive an operational ranking penalty against comparable healthy alternatives.
- Shipment delay: matching delayed inbound supply adds candidate pressure and explanation.
- Supply shortfall: matching active/persistent shortfall adds candidate pressure and explanation.
- Combined crisis: multiple active/persistent event types raise crisis level to CRITICAL and open a combined-crisis incident.

## Incident Integration

Phase 3A's incident store is reused.

Per-event incident key:
`domain-event-<event_id>`

Combined incident:
`COMBINED_DOMAIN_CRISIS`

Domain incidents are resolved when the corresponding current simulator crisis no longer requires active handling.

## Test Matrix

### Unit/API
- no event â†’ NORMAL / no replan
- all six official event types classified
- resolved shipment delay with delayed future arrival â†’ persistent effect
- resolved shortfall with affected future arrival â†’ persistent effect
- two overlapping event types â†’ combined CRITICAL crisis
- constrained depot/supply delay/shortfall produce candidate pressure reason codes
- healthy equal alternative outranks constrained depot
- only feasible constrained depot remains usable but explicitly explained
- `/api/crisis` schema + domain incident
- combined incident opens and resolves

### Live Official Simulator
Each event is tested from a reset, paused deterministic world. No wall-clock sleep is used for domain activation; the harness advances `/admin/step` and observes actual event/entity state instead of assuming activation after one step.

- demand spike:
  - event becomes ACTIVE
  - station multiplier increases
  - crisis API reports `demand_spike`
  - decision risk carries `DEMAND_SPIKE`
- route disruption:
  - route becomes `DISRUPTED`
  - crisis API reports event
  - new recommendations do not use disrupted route
- station outage:
  - station becomes `OUTAGE`
  - no new recommendation targets outage station
- depot constraint:
  - depot becomes `CONSTRAINED`
  - crisis API reports event
- shipment delay:
  - affected scheduled arrival moves later and becomes `DELAYED`
  - crisis API reports supply delay pressure
- supply shortfall:
  - affected arrival quantity decreases
  - crisis API reports supply shortfall pressure
- combined crisis:
  - demand spike + route disruption overlap
  - crisis API reports `combined_crisis=true`, `CRITICAL`
  - demand risk adapts and disrupted route is excluded
  - combined domain incident is ACTIVE
- recovery:
  - simulator reset returns crisis API to NORMAL
  - domain/combined incidents resolve

## Safety Boundary

Phase 3B does not auto-execute allocations. Recommendations remain human-reviewed, and any approval re-fetches current REST state and revalidates all allocation constraints before the simulator write.
