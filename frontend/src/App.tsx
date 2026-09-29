import { useEffect, useMemo, useState } from "react";
import { api } from "./api";
import type { Depot, Health, Snapshot, Station } from "./types";
import "./styles.css";

const fuels = ["DIESEL", "PETROL", "OCTANE"] as const;

function StatusPill({ value }: { value: string }) {
  const normalized = value.toLowerCase().replaceAll("_", "-");
  return <span className={`pill pill-${normalized}`}>{value}</span>;
}

function InventoryBars({
  inventory,
  capacity,
}: {
  inventory: Record<string, number>;
  capacity: Record<string, number>;
}) {
  return (
    <div className="inventory-list">
      {fuels.map((fuel) => {
        const amount = Number(inventory?.[fuel] ?? 0);
        const max = Math.max(Number(capacity?.[fuel] ?? 0), 1);
        const pct = Math.max(0, Math.min(100, (amount / max) * 100));
        return (
          <div className="inventory-row" key={fuel}>
            <div className="inventory-meta">
              <span>{fuel}</span>
              <strong>{amount.toLocaleString()} L</strong>
            </div>
            <div className="bar">
              <span style={{ width: `${pct}%` }} />
            </div>
          </div>
        );
      })}
    </div>
  );
}

function StationCard({ station }: { station: Station }) {
  return (
    <article className="card station-card">
      <div className="card-head">
        <div>
          <p className="eyebrow">Station</p>
          <h3>{station.name}</h3>
        </div>
        <StatusPill value={station.status} />
      </div>
      <p className="subtle">
        {station.demand_profile} Â· demand Ã—{station.demand_multiplier.toFixed(2)}
      </p>
      <InventoryBars inventory={station.inventory} capacity={station.capacity} />
    </article>
  );
}

function DepotCard({ depot }: { depot: Depot }) {
  return (
    <article className="card">
      <div className="card-head">
        <div>
          <p className="eyebrow">Depot</p>
          <h3>{depot.name}</h3>
        </div>
        <StatusPill value={depot.status} />
      </div>
      <p className="subtle">
        Dispatch capacity {depot.dispatch_capacity_per_tick.toLocaleString()} L/tick
      </p>
      <InventoryBars inventory={depot.inventory} capacity={depot.capacity} />
    </article>
  );
}

export default function App() {
  const [snapshot, setSnapshot] = useState<Snapshot | null>(null);
  const [health, setHealth] = useState<Health | null>(null);
  const [error, setError] = useState<string | null>(null);

  const load = async () => {
    try {
      const [nextSnapshot, nextHealth] = await Promise.all([
        api.snapshot(),
        api.health(),
      ]);
      setSnapshot(nextSnapshot);
      setHealth(nextHealth);
      setError(null);
    } catch (err) {
      setError(err instanceof Error ? err.message : "Unable to load operational state");
    }
  };

  useEffect(() => {
    void load();
    const timer = window.setInterval(() => void load(), 5000);
    return () => window.clearInterval(timer);
  }, []);

  const serviceLevel = useMemo(() => {
    const raw = snapshot?.metrics?.service_level;
    return typeof raw === "number" ? `${(raw * 100).toFixed(2)}%` : "â€”";
  }, [snapshot]);

  if (!snapshot && !error) {
    return (
      <main className="shell">
        <div className="loading card">Loading live fuel networkâ€¦</div>
      </main>
    );
  }

  return (
    <main className="shell">
      <header className="hero">
        <div>
          <p className="eyebrow">BUP CSE Fest 2026 Â· Fuel Supply Simulator</p>
          <h1>FuelOps Resilience</h1>
          <p className="hero-copy">
            Live operational state from the official simulator. Phase 1 establishes
            the trusted integration layer before decision intelligence is added.
          </p>
        </div>
        <div className="hero-health">
          <StatusPill value={health?.status ?? "UNKNOWN"} />
          <span>Tick {snapshot?.tick ?? "â€”"}</span>
        </div>
      </header>

      {error && <section className="incident">Backend connection: {error}</section>}
      {snapshot?.data_freshness !== "FRESH" && (
        <section className="incident">
          Data freshness: {snapshot?.data_freshness}. Operational state may be degraded.
        </section>
      )}

      <section className="metrics-grid">
        <article className="metric card">
          <span>Simulation</span>
          <strong>{snapshot?.simulation_status ?? "UNKNOWN"}</strong>
        </article>
        <article className="metric card">
          <span>Service level</span>
          <strong>{serviceLevel}</strong>
        </article>
        <article className="metric card">
          <span>Stations</span>
          <strong>{snapshot?.stations.length ?? 0}</strong>
        </article>
        <article className="metric card">
          <span>Routes available</span>
          <strong>
            {snapshot?.routes.filter((r) => r.status === "AVAILABLE").length ?? 0}/
            {snapshot?.routes.length ?? 0}
          </strong>
        </article>
      </section>

      <section className="section">
        <div className="section-title">
          <div>
            <p className="eyebrow">Network</p>
            <h2>Fuel Stations</h2>
          </div>
          <span className="subtle">12 station Ã— fuel states</span>
        </div>
        <div className="grid two">
          {snapshot?.stations.map((station) => (
            <StationCard station={station} key={station.id} />
          ))}
        </div>
      </section>

      <section className="section">
        <div className="section-title">
          <div>
            <p className="eyebrow">Supply</p>
            <h2>Depots</h2>
          </div>
        </div>
        <div className="grid two">
          {snapshot?.depots.map((depot) => (
            <DepotCard depot={depot} key={depot.id} />
          ))}
        </div>
      </section>

      <section className="section">
        <div className="section-title">
          <div>
            <p className="eyebrow">Movement</p>
            <h2>Routes</h2>
          </div>
        </div>
        <div className="table card">
          <div className="table-row table-head-row">
            <span>Route</span><span>Transit</span><span>Max</span><span>Status</span>
          </div>
          {snapshot?.routes.map((route) => (
            <div className="table-row" key={route.id}>
              <span>{route.source_depot_id} â†’ {route.destination_station_id}</span>
              <span>{route.transit_ticks} ticks</span>
              <span>{route.max_shipment.toLocaleString()} L</span>
              <span><StatusPill value={route.status} /></span>
            </div>
          ))}
        </div>
      </section>

      <section className="grid two section">
        <article className="card">
          <p className="eyebrow">Upcoming supply</p>
          <h2>{snapshot?.supply_arrivals.length ?? 0} records</h2>
          <p className="subtle">Read directly from /v1/supply-arrivals.</p>
        </article>
        <article className="card">
          <p className="eyebrow">Active / historical events</p>
          <h2>{snapshot?.events.length ?? 0} records</h2>
          <p className="subtle">Crisis awareness will build on this state in Phase 3.</p>
        </article>
      </section>

      <section className="section">
        <div className="section-title">
          <div>
            <p className="eyebrow">System</p>
            <h2>Integration Health</h2>
          </div>
        </div>
        <div className="health-grid">
          {[
            ["Backend", health?.backend.status],
            ["Simulator", health?.simulator.status],
            ["SSE", health?.sse.status],
            ["Snapshot", health?.snapshot.status],
          ].map(([label, value]) => (
            <article className="card health-card" key={label}>
              <span>{label}</span>
              <StatusPill value={value ?? "UNKNOWN"} />
            </article>
          ))}
        </div>
        <p className="subtle footer-note">
          SSE events seen: {health?.events_seen ?? 0} Â· reconnects: {health?.reconnects ?? 0}
          {" Â· "}captured {snapshot?.captured_at ?? "â€”"}
        </p>
      </section>
    </main>
  );
}
