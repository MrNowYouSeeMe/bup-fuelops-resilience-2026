# Team Parallelization and Integration Contracts

## Principle

Do not split work mechanically into frontend/backend roles.

Parallelize only modules that can be independently built and verified behind frozen contracts.

The core integrator must always retain a runnable baseline system.

## Core Integrator

Owns:
- simulator adapter
- OperationalSnapshot
- main backend/orchestration
- baseline demand estimator
- shortage-risk engine
- baseline heuristic allocator
- deterministic constraint guard
- operator approval workflow
- fresh-state revalidation
- simulator allocation execution
- main dashboard integration
- cross-module integration

## Forecasting Owner

Input:

```text
OperationalSnapshot
```

Output:

```text
ForecastResult[]
```

Entry point:

```text
forecast(snapshot) -> ForecastResult[]
```

Required tests:
- cold start
- no history
- short history
- normal history
- demand spike
- noise
- zero demand
- confidence bounds
- schema validation

The core baseline estimator remains available as fallback.

## Optimization Owner

Input:

```text
OperationalSnapshot
RiskAssessment[]
ForecastResult[]
```

Output:

```text
AllocationRecommendation[]
```

The optimizer may use heuristics, weighted scoring, OR-Tools, linear/integer optimization or another justified method.

It must not bypass the deterministic constraint guard.

The baseline heuristic allocator remains available as fallback.

## DevOps / Observability Owner

Freeze:
- simulator port
- backend port
- frontend port
- environment variables
- health endpoints
- startup command
- metrics contract

Ownership may include:
- Dockerfiles
- docker-compose
- environment wiring
- health checks
- reproducible startup
- optional CI
- load-test scripts
- resource/performance evidence

## Contract Change Rule

Internal implementation can change freely.

Shared field names, enum values, meanings, endpoints, error semantics and configuration names must not silently change.

## Handoff Standard

Every handoff must state:

```text
module
what changed
input contract
output contract
tests run
tests passed
tests failed
not tested
known risks
integration steps
next exact action
```
