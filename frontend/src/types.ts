export type FuelType = "DIESEL" | "PETROL" | "OCTANE";
export type FuelMap = Record<FuelType, number>;
export type RiskLevel = "LOW" | "MEDIUM" | "HIGH" | "CRITICAL";

export interface Station {
  id: string;
  name: string;
  region_id: string;
  status: "OPEN" | "OUTAGE" | string;
  demand_profile: string;
  demand_multiplier: number;
  capacity: FuelMap;
  inventory: FuelMap;
}

export interface Depot {
  id: string;
  name: string;
  region_id: string;
  status: "OPEN" | "CONSTRAINED" | string;
  dispatch_capacity_per_tick: number;
  capacity: FuelMap;
  inventory: FuelMap;
}

export interface Route {
  id: string;
  source_depot_id: string;
  destination_station_id: string;
  transit_ticks: number;
  max_shipment: number;
  status: "AVAILABLE" | "DISRUPTED" | string;
}

export interface Snapshot {
  captured_at: string;
  tick: number;
  tick_minutes: number;
  sim_time: string | null;
  simulation_status: string;
  data_freshness: "FRESH" | "STALE" | "UNKNOWN";
  depots: Depot[];
  stations: Station[];
  routes: Route[];
  supply_arrivals: Record<string, unknown>[];
  events: Record<string, unknown>[];
  allocations: Record<string, unknown>[];
  demand_history: Record<string, unknown>[];
  metrics: Record<string, number>;
  degraded_reasons: string[];
}

export interface Health {
  status: string;
  backend: { status: string; detail?: string | null };
  simulator: { status: string; detail?: string | null };
  sse: { status: string; detail?: string | null };
  snapshot: { status: string; detail?: string | null };
  tick: number | null;
  reconnects: number;
  events_seen: number;
}

export interface ForecastResult {
  station_id: string;
  fuel_type: FuelType;
  horizon_ticks: number;
  predicted_demand_liters: number;
  demand_per_tick: number;
  confidence: number;
  method: string;
  sample_count: number;
  per_tick_liters: number[];
}

export interface RiskAssessment {
  station_id: string;
  fuel_type: FuelType;
  risk_level: RiskLevel;
  runway_ticks: number | null;
  projected_stockout_tick: number | null;
  confidence: number;
  reason_codes: string[];
  inventory_liters: number;
  capacity_liters: number;
  inbound_liters: number;
  fastest_route_ticks: number | null;
  risk_score: number;
}

export interface ConstraintCheck {
  code: string;
  passed: boolean;
  detail: string;
}

export interface AllocationAlternative {
  source_depot_id: string;
  route_id: string;
  quantity: number;
  transit_ticks: number;
  score: number;
}

export interface AllocationRecommendation {
  recommendation_id: string;
  generated_tick: number;
  source_depot_id: string;
  destination_station_id: string;
  route_id: string;
  fuel_type: FuelType;
  quantity: number;
  priority: RiskLevel;
  confidence: number;
  risk_before: number;
  risk_after: number;
  constraints_checked: boolean;
  human_review_required: boolean;
  executable: boolean;
  expected_arrival_tick: number;
  expected_runway_after_ticks: number | null;
  recommended_action: string;
  safe_boundary: string;
  reason_codes: string[];
  constraints: ConstraintCheck[];
  alternatives: AllocationAlternative[];
}

export interface DecisionSupportBundle {
  generated_at: string;
  snapshot_tick: number;
  data_freshness: "FRESH" | "STALE" | "UNKNOWN";
  forecasts: ForecastResult[];
  risks: RiskAssessment[];
  recommendations: AllocationRecommendation[];
}

export interface DecisionRecord {
  decision_id: string;
  recommendation_id: string;
  action: "APPROVE" | "REJECT" | "BLOCK";
  status: "EXECUTED" | "REJECTED" | "BLOCKED";
  decided_at: string;
  decision_tick: number | null;
  reason: string | null;
  allocation: Record<string, unknown> | null;
  invalidated_constraints: string[];
}


export interface LatencySummary {
  sample_count: number;
  avg_ms: number;
  p50_ms: number;
  p95_ms: number;
  p99_ms: number;
}

export interface SystemMetrics {
  generated_at: string;
  requests_total: number;
  errors_total: number;
  error_rate: number;
  in_flight: number;
  latency: LatencySummary;
  simulator_requests_total: number;
  simulator_retry_count: number;
  simulator_transient_failures: number;
  simulator_last_latency_ms: number | null;
  fallback_activations: number;
  snapshot_recoveries: number;
  sse_reconnects: number;
  sse_events_seen: number;
  recommendation_batches: number;
  recommendations_generated: number;
  decisions_executed: number;
  decisions_rejected: number;
  decisions_blocked: number;
  active_incidents: number;
}

export interface SystemHealth {
  status: "HEALTHY" | "DEGRADED" | "UNAVAILABLE" | "STARTING";
  tick: number | null;
  data_freshness: "FRESH" | "STALE" | "UNKNOWN";
  components: Record<string, { status: string; detail?: string | null }>;
  degraded_reasons: string[];
  active_incidents: number;
}

export interface IncidentRecord {
  incident_id: string;
  kind: string;
  severity: "INFO" | "MEDIUM" | "HIGH" | "CRITICAL";
  status: "ACTIVE" | "RESOLVED";
  started_at: string;
  last_updated_at: string;
  resolved_at: string | null;
  tick: number | null;
  detail: string;
  occurrences: number;
}

export interface CrisisAssessment {
  event_id: string;
  event_type: string;
  simulator_status: string;
  operational_status: "SCHEDULED" | "ACTIVE" | "PERSISTENT_EFFECT" | "RESOLVED" | "UNKNOWN";
  severity: "INFO" | "MEDIUM" | "HIGH" | "CRITICAL";
  start_tick: number;
  end_tick: number;
  affected_resources: string[];
  impacts: string[];
  adaptation_actions: string[];
}

export interface CrisisSummary {
  generated_at: string;
  snapshot_tick: number;
  crisis_level: "NORMAL" | "ELEVATED" | "HIGH" | "CRITICAL";
  combined_crisis: boolean;
  active_crisis_count: number;
  active_types: string[];
  replan_required: boolean;
  assessments: CrisisAssessment[];
  decision_context: string[];
}
