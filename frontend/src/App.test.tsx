import { cleanup, fireEvent, render, screen, waitFor } from "@testing-library/react";
import { afterEach, describe, expect, it, vi } from "vitest";
import App from "./App";

const snapshot = {
  captured_at: "2026-01-01T08:00:00Z",
  tick: 32,
  tick_minutes: 15,
  sim_time: "2026-01-01T08:00:00+00:00",
  simulation_status: "PAUSED",
  data_freshness: "FRESH",
  depots: [
    {
      id: "depot-gazipur",
      name: "Gazipur Depot",
      region_id: "region-dhaka",
      status: "OPEN",
      dispatch_capacity_per_tick: 12000,
      capacity: { DIESEL: 90000, PETROL: 70000, OCTANE: 45000 },
      inventory: { DIESEL: 60000, PETROL: 45000, OCTANE: 26000 },
    },
  ],
  stations: [
    {
      id: "station-mirpur",
      name: "Mirpur Fuel Station",
      region_id: "region-dhaka",
      status: "OPEN",
      demand_profile: "urban_high",
      demand_multiplier: 1,
      capacity: { DIESEL: 15000, PETROL: 14000, OCTANE: 9000 },
      inventory: { DIESEL: 300, PETROL: 3900, OCTANE: 2400 },
    },
  ],
  routes: [
    {
      id: "route-gazipur-mirpur",
      source_depot_id: "depot-gazipur",
      destination_station_id: "station-mirpur",
      transit_ticks: 2,
      max_shipment: 7000,
      status: "AVAILABLE",
    },
  ],
  supply_arrivals: [],
  events: [],
  allocations: [],
  demand_history: [],
  metrics: { service_level: 0.98 },
  degraded_reasons: [],
};

const health = {
  status: "HEALTHY",
  backend: { status: "HEALTHY" },
  simulator: { status: "HEALTHY" },
  sse: { status: "HEALTHY" },
  snapshot: { status: "HEALTHY" },
  tick: 32,
  reconnects: 0,
  events_seen: 3,
};

const forecast = {
  station_id: "station-mirpur",
  fuel_type: "DIESEL",
  horizon_ticks: 16,
  predicted_demand_liters: 3200,
  demand_per_tick: 200,
  confidence: 0.84,
  method: "profile_adjusted_ewma",
  sample_count: 16,
  per_tick_liters: Array(16).fill(200),
};

const risk = {
  station_id: "station-mirpur",
  fuel_type: "DIESEL",
  risk_level: "CRITICAL",
  runway_ticks: 2,
  projected_stockout_tick: 34,
  confidence: 0.84,
  reason_codes: ["LOW_INVENTORY", "STOCKOUT_WITHIN_FORECAST_HORIZON"],
  inventory_liters: 300,
  capacity_liters: 15000,
  inbound_liters: 0,
  fastest_route_ticks: 2,
  risk_score: 0.92,
};

const recommendation = {
  recommendation_id: "rec-abc",
  generated_tick: 32,
  source_depot_id: "depot-gazipur",
  destination_station_id: "station-mirpur",
  route_id: "route-gazipur-mirpur",
  fuel_type: "DIESEL",
  quantity: 7000,
  priority: "CRITICAL",
  confidence: 0.84,
  risk_before: 0.92,
  risk_after: 0.28,
  constraints_checked: true,
  human_review_required: true,
  executable: true,
  expected_arrival_tick: 34,
  expected_runway_after_ticks: 36.5,
  recommended_action: "Allocate 7,000 L DIESEL from depot-gazipur to station-mirpur.",
  safe_boundary: "Human approval required. Fresh state is revalidated before execution.",
  reason_codes: ["LOW_INVENTORY", "STOCKOUT_WITHIN_FORECAST_HORIZON"],
  constraints: [{ code: "ROUTE_STATUS", passed: true, detail: "status=AVAILABLE" }],
  alternatives: [],
};

const support = {
  generated_at: "2026-01-01T08:00:00Z",
  snapshot_tick: 32,
  data_freshness: "FRESH",
  forecasts: [forecast],
  risks: [risk],
  recommendations: [recommendation],
};

const decision = {
  decision_id: "dec-1",
  recommendation_id: "rec-abc",
  action: "APPROVE",
  status: "EXECUTED",
  decided_at: "2026-01-01T08:00:01Z",
  decision_tick: 32,
  reason: "approved",
  allocation: { id: 11, idempotency_key: "fuelops-rec-abc" },
  invalidated_constraints: [],
};


const systemHealth = {
  status: "HEALTHY",
  tick: 32,
  data_freshness: "FRESH",
  components: {
    backend: { status: "HEALTHY" },
    simulator: { status: "HEALTHY" },
    snapshot: { status: "HEALTHY" },
    sse: { status: "HEALTHY" },
    decision: { status: "HEALTHY" },
  },
  degraded_reasons: [],
  active_incidents: 0,
};

const systemMetrics = {
  generated_at: "2026-01-01T08:00:00Z",
  requests_total: 42,
  errors_total: 1,
  error_rate: 0.0238,
  in_flight: 0,
  latency: { sample_count: 42, avg_ms: 8.2, p50_ms: 5.1, p95_ms: 18.4, p99_ms: 24.7 },
  simulator_requests_total: 120,
  simulator_retry_count: 2,
  simulator_transient_failures: 2,
  simulator_last_latency_ms: 4.2,
  fallback_activations: 1,
  snapshot_recoveries: 1,
  sse_reconnects: 0,
  sse_events_seen: 3,
  recommendation_batches: 4,
  recommendations_generated: 7,
  decisions_executed: 1,
  decisions_rejected: 0,
  decisions_blocked: 0,
  active_incidents: 0,
};

const incidents = [
  {
    incident_id: "inc-0001",
    kind: "SIMULATOR_UNAVAILABLE",
    severity: "HIGH",
    status: "RESOLVED",
    started_at: "2026-01-01T07:00:00Z",
    last_updated_at: "2026-01-01T07:00:01Z",
    resolved_at: "2026-01-01T07:00:01Z",
    tick: 31,
    detail: "Simulator data path recovered.",
    occurrences: 1,
  },
];

function mockFetch(options?: { stale?: boolean; approveError?: boolean }) {
  return vi.fn(async (input: RequestInfo | URL, init?: RequestInit) => {
    const url = String(input);

    if (url.endsWith("/api/health")) {
      return new Response(JSON.stringify(health), {
        status: 200,
        headers: { "Content-Type": "application/json" },
      });
    }

    if (url.endsWith("/api/snapshot")) {
      return new Response(
        JSON.stringify(
          options?.stale
            ? { ...snapshot, data_freshness: "STALE" }
            : snapshot,
        ),
        { status: 200, headers: { "Content-Type": "application/json" } },
      );
    }

    if (url.endsWith("/api/system/health")) {
      return new Response(JSON.stringify(systemHealth), {
        status: 200,
        headers: { "Content-Type": "application/json" },
      });
    }

    if (url.endsWith("/api/system/metrics")) {
      return new Response(JSON.stringify(systemMetrics), {
        status: 200,
        headers: { "Content-Type": "application/json" },
      });
    }

    if (url.endsWith("/api/incidents")) {
      return new Response(JSON.stringify(incidents), {
        status: 200,
        headers: { "Content-Type": "application/json" },
      });
    }

    if (url.endsWith("/api/decision-support")) {
      return new Response(
        JSON.stringify(
          options?.stale
            ? {
                ...support,
                data_freshness: "STALE",
                recommendations: [{ ...recommendation, executable: false }],
              }
            : support,
        ),
        { status: 200, headers: { "Content-Type": "application/json" } },
      );
    }

    if (url.includes("/approve") && init?.method === "POST") {
      if (options?.approveError) {
        return new Response(
          JSON.stringify({
            detail: { code: "RECOMMENDATION_INVALIDATED", message: "Fresh-state revalidation failed." },
          }),
          { status: 409, headers: { "Content-Type": "application/json" } },
        );
      }
      return new Response(JSON.stringify(decision), {
        status: 200,
        headers: { "Content-Type": "application/json" },
      });
    }

    if (url.includes("/reject") && init?.method === "POST") {
      return new Response(
        JSON.stringify({ ...decision, action: "REJECT", status: "REJECTED", allocation: null }),
        { status: 200, headers: { "Content-Type": "application/json" } },
      );
    }

    return new Response("not found", { status: 404 });
  });
}

afterEach(() => {
  cleanup();
  vi.unstubAllGlobals();
  vi.restoreAllMocks();
});

describe("Phase 2 operator dashboard", () => {
  it("renders forecast, risk and human-review recommendation", async () => {
    vi.stubGlobal("fetch", mockFetch());
    render(<App />);

    await waitFor(() => {
      expect(screen.getByText("Demand & Stockout Intelligence")).toBeInTheDocument();
    });

    expect(screen.getAllByText("Mirpur Fuel Station").length).toBeGreaterThan(0);
    expect(screen.getAllByText("CRITICAL").length).toBeGreaterThan(0);
    expect(screen.getByText("Approve & Execute")).toBeInTheDocument();
    expect(screen.getByText(/Allocate 7,000 L DIESEL/)).toBeInTheDocument();
  });

  it("approves a recommendation and shows allocation feedback", async () => {
    const fetchMock = mockFetch();
    vi.stubGlobal("fetch", fetchMock);
    render(<App />);

    const button = await screen.findByRole("button", { name: "Approve & Execute" });
    fireEvent.click(button);

    await waitFor(() => {
      expect(screen.getByText(/Allocation executed/)).toBeInTheDocument();
    });

    expect(
      fetchMock.mock.calls.some(([input, init]) =>
        String(input).includes("/api/recommendations/rec-abc/approve")
        && (init as RequestInit | undefined)?.method === "POST",
      ),
    ).toBe(true);
  });

  it("blocks approval button when data is stale", async () => {
    vi.stubGlobal("fetch", mockFetch({ stale: true }));
    render(<App />);

    const button = await screen.findByText("Execution Blocked");
    expect(button).toBeDisabled();
    expect(screen.getByText(/Data freshness: STALE/)).toBeInTheDocument();
  });

  it("surfaces fresh-state invalidation from backend", async () => {
    vi.stubGlobal("fetch", mockFetch({ approveError: true }));
    render(<App />);

    fireEvent.click(await screen.findByRole("button", { name: "Approve & Execute" }));

    await waitFor(() => {
      expect(screen.getByText(/Decision blocked: RECOMMENDATION_INVALIDATED/)).toBeInTheDocument();
    });
  });
  it("renders resilience and observability metrics", async () => {
    vi.stubGlobal("fetch", mockFetch());
    render(<App />);

    await waitFor(() => {
      expect(screen.getByText("Resilience & Observability")).toBeInTheDocument();
    });

    expect(screen.getByText("42")).toBeInTheDocument();
    expect(screen.getByText("18.4 ms")).toBeInTheDocument();
    expect(screen.getByText("SIMULATOR UNAVAILABLE")).toBeInTheDocument();
    expect(screen.getByText("RESOLVED")).toBeInTheDocument();
  });

});
