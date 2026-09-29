# Phase 2 â€” Prediction, Risk, Recommendation, Human Approval

## Goal

Phase 2 converts the verified Phase 1 simulator integration into an operator-facing decision-support loop:

`Observe â†’ Forecast â†’ Assess Risk â†’ Recommend â†’ Human Review â†’ Fresh-State Revalidate â†’ Execute`

The simulator remains the world/source of truth. FuelOps is the decision layer.

## Intelligence choice

Phase 2 intentionally uses a lightweight, explainable hybrid rather than a trained black-box model.

### Forecast pipeline

For every `station Ã— fuel` pair (4 Ã— 3 = 12 series):

1. Read bounded recent `/v1/demand-history`.
2. Normalize observations by the published station hour-of-day factor.
3. Estimate the recent baseline using EWMA.
4. Estimate a capped recent trend.
5. Build a profile/context anchor from the published daily demand profile, region factor, `tick_minutes`, station `demand_multiplier`, and future hour factor.
6. Blend statistical and profile estimates according to sample count.
7. Emit a 16-tick per-tick series, total predicted demand, mean demand/tick, sample count and confidence.

Cold start falls back to the deterministic profile/context estimate. No `.pkl`, `.pt`, ONNX model, paid model, or external service is required.

### Confidence

Confidence is deterministic and inspectable:

- more samples â†’ higher confidence;
- stable history â†’ higher confidence;
- cold start â†’ lower confidence;
- stale/degraded data â†’ confidence penalty.

## Forecast contract

```json
{
  "station_id": "station-mirpur",
  "fuel_type": "DIESEL",
  "horizon_ticks": 16,
  "predicted_demand_liters": 3100.0,
  "demand_per_tick": 193.75,
  "confidence": 0.82,
  "method": "profile_adjusted_ewma",
  "sample_count": 16,
  "per_tick_liters": [190.0, 192.0]
}
```

The original core fields remain stable; `sample_count` and `per_tick_liters` are additive.

## Risk engine

For each forecast:

- start from current station inventory;
- subtract projected per-tick demand;
- add known `IN_TRANSIT` deliveries at their expected arrival tick;
- find projected stockout tick;
- estimate runway;
- compare runway against fastest currently available route;
- consider inventory ratio and active demand multiplier;
- reduce confidence when data is stale.

Risk levels: `LOW`, `MEDIUM`, `HIGH`, `CRITICAL`.

Important reason codes include:

- `LOW_INVENTORY`
- `STOCKOUT_WITHIN_FORECAST_HORIZON`
- `STOCKOUT_BEFORE_OR_NEAR_FASTEST_ROUTE`
- `DEMAND_SPIKE`
- `NO_AVAILABLE_ROUTE`
- `STATION_UNAVAILABLE`
- `DEGRADED_DATA`

## Recommendation engine

Recommendations are generated only for actionable `MEDIUM/HIGH/CRITICAL` station-fuel risks.

Candidate routes are ranked using:

- risk severity;
- route transit time;
- feasible quantity/coverage;
- live depot/station/route state.

Quantity is capped by:

- route maximum shipment;
- source depot inventory;
- remaining depot dispatch capacity;
- destination capacity;
- already committed destination inbound;
- amount required to restore an operational buffer.

Each recommendation includes risk before/after, confidence, expected arrival tick, expected runway after action, reason codes, all constraint checks, and up to two alternatives.

## Constraint guard

Before a recommendation is shown as executable, and again immediately before execution, FuelOps checks:

- quantity > 0;
- valid fuel enum;
- depot/station/route exist;
- route endpoints match;
- depot status is `OPEN` or `CONSTRAINED`;
- station is `OPEN`;
- route is `AVAILABLE`;
- route max shipment;
- depot inventory;
- remaining dispatch capacity;
- current destination capacity;
- additional future-inbound headroom safety.

The final simulator POST still remains authoritative.

## Human review and race safety

FuelOps never auto-allocates in Phase 2.

`GET recommendation â†’ operator Approve/Reject â†’ fresh REST snapshot â†’ revalidate â†’ POST /v1/allocations`

Approval uses a stable idempotency key derived from the recommendation ID.

Duplicate approval returns the already executed decision instead of creating another allocation.

If route status, inventory, capacity, freshness or another constraint changes between recommendation and approval, execution is blocked.

## API

- `GET /api/decision-support`
- `GET /api/forecasts`
- `GET /api/risks`
- `GET /api/recommendations`
- `GET /api/decisions`
- `POST /api/recommendations/{recommendation_id}/approve`
- `POST /api/recommendations/{recommendation_id}/reject`

Phase 1 endpoints remain available.

## Frontend

The existing live dashboard is preserved and extended with:

- 12-series demand/stockout intelligence table;
- risk pills;
- forecast horizon and confidence;
- stockout tick/runway;
- explainable recommendation cards;
- risk-before/risk-after;
- alternative routes;
- operator Approve/Reject;
- stale-state execution blocking;
- decision success/error feedback.

## Tests

Phase 2 adds unit/integration coverage for:

- cold start/no history;
- few/mature history;
- deterministic replay;
- hour-profile boundary;
- demand multiplier spike;
- stale confidence penalty;
- malformed/future history rows;
- 12-series contract;
- low inventory and stockout;
- in-transit arrival;
- route-transit risk;
- quantity zero/negative/0.001;
- route max exact/over;
- route mismatch;
- disrupted route;
- station outage;
- constrained depot;
- insufficient inventory;
- destination exact capacity/over;
- pending inbound headroom;
- dispatch commitment;
- feasible recommendation;
- stale recommendation non-executable;
- operator approval;
- duplicate approval idempotency;
- reject/idempotent reject;
- stale approval block;
- route race block;
- inventory race block;
- simulator POST retry with same idempotency key;
- simulator 409 error-code preservation;
- frontend forecast/risk/recommendation rendering;
- frontend approve action;
- frontend stale button block;
- frontend invalidation feedback.

The apply script also performs real integration against the official simulator: generates demand history deterministically, verifies 12 forecasts/12 risks, executes one approved allocation, checks duplicate approval, checks stale-state execution blocking, and checks a route-disruption recommendation race.
