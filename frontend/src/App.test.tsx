import { render, screen, waitFor } from "@testing-library/react";
import { afterEach, describe, expect, it, vi } from "vitest";
import App from "./App";

const snapshot = {
  captured_at: "2026-01-01T00:00:00Z",
  tick: 0,
  sim_time: "2026-01-01T00:00:00+00:00",
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
      inventory: { DIESEL: 9000, PETROL: 9000, OCTANE: 5000 },
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
  metrics: { service_level: 1 },
  degraded_reasons: [],
};

const health = {
  status: "HEALTHY",
  backend: { status: "HEALTHY" },
  simulator: { status: "HEALTHY" },
  sse: { status: "HEALTHY" },
  snapshot: { status: "HEALTHY" },
  tick: 0,
  reconnects: 0,
  events_seen: 0,
};

afterEach(() => {
  vi.restoreAllMocks();
});

describe("Phase 1 dashboard", () => {
  it("renders normalized live-state contract", async () => {
    vi.stubGlobal(
      "fetch",
      vi.fn(async (input: RequestInfo | URL) => {
        const url = String(input);
        const body = url.endsWith("/api/health") ? health : snapshot;
        return new Response(JSON.stringify(body), {
          status: 200,
          headers: { "Content-Type": "application/json" },
        });
      }),
    );

    render(<App />);

    await waitFor(() => {
      expect(screen.getByText("Mirpur Fuel Station")).toBeInTheDocument();
    });

    expect(screen.getByText("Gazipur Depot")).toBeInTheDocument();
    expect(screen.getByText("100.00%")).toBeInTheDocument();
    expect(screen.getAllByText("HEALTHY").length).toBeGreaterThan(0);
    expect(screen.getByText(/depot-gazipur â†’ station-mirpur/)).toBeInTheDocument();
  });

  it("shows a degraded-data warning", async () => {
    const stale = { ...snapshot, data_freshness: "STALE" };

    vi.stubGlobal(
      "fetch",
      vi.fn(async (input: RequestInfo | URL) => {
        const url = String(input);
        const body = url.endsWith("/api/health") ? health : stale;
        return new Response(JSON.stringify(body), {
          status: 200,
          headers: { "Content-Type": "application/json" },
        });
      }),
    );

    render(<App />);

    await waitFor(() => {
      expect(screen.getByText(/Data freshness: STALE/)).toBeInTheDocument();
    });
  });
});
