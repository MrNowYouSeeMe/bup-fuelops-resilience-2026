export type FuelMap = Record<"DIESEL" | "PETROL" | "OCTANE", number>;

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
