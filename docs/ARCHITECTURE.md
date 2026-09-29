# Version 1 System Architecture

## Main Architecture

```mermaid
flowchart TB
    subgraph SIM["BUP Fuel Supply Simulator"]
        SIMREST["REST API /v1/*"]
        SIMSSE["SSE /v1/stream"]
        SIMADMIN["Admin APIs /admin/*\nSelf-Test Only"]
    end

    subgraph INTEGRATION["Simulator Integration"]
        CLIENT["Async Simulator Client"]
        SSE["SSE Listener"]
        RETRY["Retry / Backoff"]
        STALE["Stale-Data Detector"]
        NORMALIZER["State Normalizer"]
    end

    subgraph STATE["Operational State"]
        SNAPSHOT["OperationalSnapshot"]
        CACHE["Last Known Verified State"]
    end

    subgraph INTELLIGENCE["Decision Intelligence"]
        DEMAND["Baseline Demand Estimator"]
        RUNWAY["Inventory Runway Engine"]
        RISK["Shortage Risk Engine"]
        CANDIDATE["Candidate Allocation Generator"]
        ALLOCATOR["Heuristic Allocation Engine"]
        GUARD["Deterministic Constraint Guard"]
    end

    subgraph DECISION["Decision Support"]
        RECOMMEND["AllocationRecommendation"]
        EXPLAIN["Reason Codes + Expected Impact"]
        HISTORY["Decision / Allocation History"]
    end

    subgraph OPERATOR["Operator Application"]
        DASHBOARD["Operations Dashboard"]
        ALERTS["Risk & Incident Alerts"]
        REVIEW["Recommendation Review"]
        APPROVE["Approve / Reject"]
    end

    subgraph EXECUTION["Safe Execution"]
        REFRESH["Fresh State Re-fetch"]
        REVALIDATE["Revalidate Recommendation"]
        IDEMPOTENCY["Idempotency Guard"]
        EXECUTE["POST /v1/allocations"]
    end

    subgraph RESILIENCE["Resilience Controller"]
        DEGRADED["Degraded Mode"]
        FALLBACK["Fallback Demand / Decision Policy"]
        POLLING["REST Polling Fallback"]
        RECOVERY["Recovery + State Resync"]
    end

    subgraph OBS["Observability"]
        HEALTH["Component Health"]
        METRICS["Latency / Errors / Decision Metrics"]
        LOGS["Structured Logs"]
        INCIDENTS["Incident Timeline"]
    end

    SIMREST --> CLIENT
    SIMSSE --> SSE
    CLIENT --> RETRY
    CLIENT --> STALE
    SSE --> NORMALIZER
    RETRY --> NORMALIZER
    STALE --> NORMALIZER
    NORMALIZER --> SNAPSHOT
    SNAPSHOT --> CACHE
    SNAPSHOT --> DEMAND
    DEMAND --> RUNWAY
    RUNWAY --> RISK
    RISK --> CANDIDATE
    SNAPSHOT --> CANDIDATE
    CANDIDATE --> ALLOCATOR
    ALLOCATOR --> GUARD
    GUARD --> RECOMMEND
    RISK --> EXPLAIN
    RECOMMEND --> EXPLAIN
    RECOMMEND --> DASHBOARD
    RISK --> ALERTS
    EXPLAIN --> REVIEW
    REVIEW --> APPROVE
    APPROVE --> REFRESH
    REFRESH --> REVALIDATE
    REVALIDATE --> IDEMPOTENCY
    IDEMPOTENCY --> EXECUTE
    EXECUTE --> SIMREST
    EXECUTE --> HISTORY
    CLIENT -. failure .-> DEGRADED
    SSE -. disconnect .-> POLLING
    DEMAND -. failure .-> FALLBACK
    ALLOCATOR -. failure .-> FALLBACK
    DEGRADED --> CACHE
    POLLING --> CLIENT
    FALLBACK --> GUARD
    RECOVERY --> NORMALIZER
    SIMADMIN -. crisis / fault injection .-> SIM
    CLIENT --> HEALTH
    SSE --> HEALTH
    DEMAND --> HEALTH
    ALLOCATOR --> HEALTH
    RETRY --> METRICS
    GUARD --> METRICS
    EXECUTE --> METRICS
    CLIENT --> LOGS
    GUARD --> LOGS
    EXECUTE --> LOGS
    DEGRADED --> INCIDENTS
    RECOVERY --> INCIDENTS
```

## Core Decision Pipeline

```mermaid
flowchart LR
    A["Operational Snapshot"] --> B["Demand Estimation"]
    B --> C["Inventory Runway"]
    C --> D["Shortage Risk"]
    D --> E{"Risk significant?"}
    E -- No --> F["Continue Monitoring"]
    E -- Yes --> G["Generate Candidate Allocations"]
    G --> H["Check Depot / Route / Station Constraints"]
    H --> I{"Feasible candidate?"}
    I -- No --> J["Operator Alert: No Safe Allocation"]
    I -- Yes --> K["Rank Candidates"]
    K --> L["Create Recommendation"]
    L --> M["Explain Why + Expected Impact"]
    M --> N["Operator Review"]
    N --> O{"Approve?"}
    O -- No --> P["Record Rejection"]
    O -- Yes --> Q["Re-fetch Latest Simulator State"]
    Q --> R["Revalidate"]
    R --> S{"Still Valid?"}
    S -- No --> T["Invalidate + Re-plan"]
    S -- Yes --> U["Execute Allocation"]
    U --> V["Monitor Result"]
    V --> A
    T --> A
```

## Failure and Recovery

```mermaid
flowchart TD
    A["Normal Operation"] --> B{"Failure Detected"}
    B -->|"Simulator 503"| C["Retry with Backoff"]
    B -->|"SSE Disconnect"| D["Switch to REST Polling"]
    B -->|"Stale Response"| E["Mark Data DEGRADED"]
    B -->|"Forecast Failure"| F["Use Baseline Demand Estimator"]
    B -->|"Decision Module Failure"| G["Use Safe Heuristic Policy"]
    B -->|"Simulator Unreachable"| H["Read-Only Last Known State"]
    E --> I["Block Unsafe Execution"]
    H --> I
    C --> J{"Dependency Recovered?"}
    D --> J
    E --> J
    F --> J
    G --> J
    H --> J
    J -- No --> K["Continue Degraded Operation"]
    K --> J
    J -- Yes --> L["Fetch Full Fresh State"]
    L --> M["Rebuild Operational Snapshot"]
    M --> N["Recalculate Risk"]
    N --> O["Resume Normal Operation"]
    O --> A
```

## Crisis Adaptation Example

```mermaid
sequenceDiagram
    participant S as Simulator
    participant A as Adapter
    participant R as Risk Engine
    participant D as Decision Engine
    participant U as Operator UI

    S->>A: Current network state
    A->>R: OperationalSnapshot
    R->>D: Mirpur Diesel = HIGH risk
    D->>U: Recommend Gazipur -> Mirpur

    S-->>A: route_disruption event
    A->>S: Re-fetch routes/state
    S->>A: Route now DISRUPTED
    A->>R: Updated snapshot
    R->>D: Recalculate risk
    D->>D: Invalidate old recommendation
    D->>D: Evaluate alternatives
    D->>U: Recommend alternative
    U->>D: Operator approves
    D->>S: POST allocation
    S->>D: Allocation accepted
```

## Replaceable Intelligence

```mermaid
flowchart LR
    STATE["OperationalSnapshot"]
    STATE --> FBASE["Baseline Forecast"]
    STATE -. optional .-> FADV["Advanced Forecast Model"]
    FBASE --> SELECTF["Forecast Interface"]
    FADV --> SELECTF
    SELECTF --> RISK["Risk Engine"]
    RISK --> H["Heuristic Allocator"]
    RISK -. optional .-> OPT["Optimization Engine"]
    H --> SELECTD["Recommendation Interface"]
    OPT --> SELECTD
    SELECTD --> GUARD["Constraint Guard"]
    GUARD --> UI["Operator Workflow"]
```

## Frozen Contracts

### ForecastResult

```text
forecast(snapshot) -> ForecastResult[]
```

Fields:
- station_id
- fuel_type
- horizon_ticks
- predicted_demand_liters
- demand_per_tick
- confidence
- method

### RiskAssessment

Fields:
- station_id
- fuel_type
- risk_level
- runway_ticks
- projected_stockout_tick
- confidence
- reason_codes

### AllocationRecommendation

Fields:
- recommendation_id
- source_depot_id
- destination_station_id
- route_id
- fuel_type
- quantity
- priority
- confidence
- risk_before
- risk_after
- constraints_checked
- reason_codes
- alternatives
