import { useEffect, useMemo, useState } from "react";
import { api } from "./api";
import type {
  AllocationRecommendation,
  DecisionSupportBundle,
  Depot,
  Health,
  ForecastResult,
  IncidentRecord,
  RiskAssessment,
  Snapshot,
  Station,
  SystemHealth,
  SystemMetrics,
} from "./types";
import "./styles.css";

const fuels = ["DIESEL", "PETROL", "OCTANE"] as const;

function StatusPill({ value }: { value: string }) {
  const normalized = value.toLowerCase().replaceAll("_", "-");
  return <span className={`pill pill-${normalized}`}>{value}</span>;
}

function RiskPill({ value }: { value: string }) {
  return <span className={`risk risk-${value.toLowerCase()}`}>{value}</span>;
}

function pct(value: number) {
  return `${Math.round(value * 100)}%`;
}

function liters(value: number) {
  return `${Math.round(value).toLocaleString()} L`;
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
        const width = Math.max(0, Math.min(100, (amount / max) * 100));
        return (
          <div className="inventory-row" key={fuel}>
            <div className="inventory-meta">
              <span>{fuel}</span>
              <strong>{amount.toLocaleString()} L</strong>
            </div>
            <div className="bar">
              <span style={{ width: `${width}%` }} />
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
        Dispatch {depot.dispatch_capacity_per_tick.toLocaleString()} L/tick
      </p>
      <InventoryBars inventory={depot.inventory} capacity={depot.capacity} />
    </article>
  );
}

function RiskTable({
  risks,
  support,
  stationName,
}: {
  risks: RiskAssessment[];
  support: DecisionSupportBundle;
  stationName: (id: string) => string;
}) {
  const forecastMap = useMemo(
    () =>
      new Map<string, ForecastResult>(
        support.forecasts.map(
          (f): [string, ForecastResult] => [`${f.station_id}|${f.fuel_type}`, f],
        ),
      ),
    [support],
  );

  return (
    <div className="table card intelligence-table">
      <div className="table-row intelligence-row table-head-row">
        <span>Station / Fuel</span>
        <span>Forecast</span>
        <span>Runway</span>
        <span>Stockout</span>
        <span>Confidence</span>
        <span>Risk</span>
      </div>
      {risks.map((risk) => {
        const forecast = forecastMap.get(`${risk.station_id}|${risk.fuel_type}`);
        return (
          <div
            className="table-row intelligence-row"
            key={`${risk.station_id}-${risk.fuel_type}`}
          >
            <span>
              <strong>{stationName(risk.station_id)}</strong>
              <small>{risk.fuel_type}</small>
            </span>
            <span>
              {forecast ? liters(forecast.predicted_demand_liters) : "â€”"}
              <small>{forecast?.method ?? "â€”"}</small>
            </span>
            <span>
              {risk.runway_ticks == null ? "â€”" : `${risk.runway_ticks.toFixed(1)} ticks`}
            </span>
            <span>
              {risk.projected_stockout_tick == null
                ? "Beyond horizon"
                : `Tick ${risk.projected_stockout_tick}`}
            </span>
            <span>{pct(risk.confidence)}</span>
            <span><RiskPill value={risk.risk_level} /></span>
          </div>
        );
      })}
    </div>
  );
}

function RecommendationCard({
  recommendation,
  stationName,
  busy,
  onApprove,
  onReject,
}: {
  recommendation: AllocationRecommendation;
  stationName: (id: string) => string;
  busy: boolean;
  onApprove: (id: string) => Promise<void>;
  onReject: (id: string) => Promise<void>;
}) {
  const failed = recommendation.constraints.filter((c) => !c.passed);

  return (
    <article className="card recommendation-card">
      <div className="card-head">
        <div>
          <p className="eyebrow">Human Review Required</p>
          <h3>{stationName(recommendation.destination_station_id)} Â· {recommendation.fuel_type}</h3>
        </div>
        <RiskPill value={recommendation.priority} />
      </div>

      <p className="recommendation-action">{recommendation.recommended_action}</p>

      <div className="recommendation-metrics">
        <div>
          <span>Quantity</span>
          <strong>{liters(recommendation.quantity)}</strong>
        </div>
        <div>
          <span>Arrival</span>
          <strong>Tick {recommendation.expected_arrival_tick}</strong>
        </div>
        <div>
          <span>Confidence</span>
          <strong>{pct(recommendation.confidence)}</strong>
        </div>
        <div>
          <span>Risk</span>
          <strong>{pct(recommendation.risk_before)} â†’ {pct(recommendation.risk_after)}</strong>
        </div>
      </div>

      <div className="route-line">
        <code>{recommendation.source_depot_id}</code>
        <span>â†’</span>
        <code>{recommendation.route_id}</code>
        <span>â†’</span>
        <code>{recommendation.destination_station_id}</code>
      </div>

      <div className="reason-tags">
        {recommendation.reason_codes.slice(0, 4).map((reason) => (
          <span key={reason}>{reason.replaceAll("_", " ")}</span>
        ))}
      </div>

      <p className="safe-boundary">{recommendation.safe_boundary}</p>

      {recommendation.alternatives.length > 0 && (
        <details className="alternatives">
          <summary>{recommendation.alternatives.length} alternate route option(s)</summary>
          {recommendation.alternatives.map((alt) => (
            <p key={`${alt.route_id}-${alt.source_depot_id}`}>
              {alt.route_id} Â· {liters(alt.quantity)} Â· {alt.transit_ticks} ticks
            </p>
          ))}
        </details>
      )}

      {failed.length > 0 && (
        <div className="incident compact">
          Constraint issue: {failed.map((c) => c.code).join(", ")}
        </div>
      )}

      <div className="decision-actions">
        <button
          className="button secondary"
          disabled={busy}
          onClick={() => void onReject(recommendation.recommendation_id)}
        >
          Reject
        </button>
        <button
          className="button primary"
          disabled={busy || !recommendation.executable}
          onClick={() => void onApprove(recommendation.recommendation_id)}
        >
          {busy ? "Workingâ€¦" : recommendation.executable ? "Approve & Execute" : "Execution Blocked"}
        </button>
      </div>
    </article>
  );
}

export default function App() {
  const [snapshot, setSnapshot] = useState<Snapshot | null>(null);
  const [health, setHealth] = useState<Health | null>(null);
  const [support, setSupport] = useState<DecisionSupportBundle | null>(null);
  const [systemHealth, setSystemHealth] = useState<SystemHealth | null>(null);
  const [systemMetrics, setSystemMetrics] = useState<SystemMetrics | null>(null);
  const [incidents, setIncidents] = useState<IncidentRecord[]>([]);
  const [error, setError] = useState<string | null>(null);
  const [decisionMessage, setDecisionMessage] = useState<string | null>(null);
  const [busyId, setBusyId] = useState<string | null>(null);

  const load = async () => {
    try {
      const [
        nextSnapshot,
        nextHealth,
        nextSupport,
        nextSystemHealth,
        nextSystemMetrics,
        nextIncidents,
      ] = await Promise.all([
        api.snapshot(),
        api.health(),
        api.decisionSupport(),
        api.systemHealth(),
        api.systemMetrics(),
        api.incidents(),
      ]);
      setSnapshot(nextSnapshot);
      setHealth(nextHealth);
      setSupport(nextSupport);
      setSystemHealth(nextSystemHealth);
      setSystemMetrics(nextSystemMetrics);
      setIncidents(nextIncidents);
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

  const stationName = (stationId: string) =>
    snapshot?.stations.find((s) => s.id === stationId)?.name ?? stationId;

  const serviceLevel = useMemo(() => {
    const raw = snapshot?.metrics?.service_level;
    return typeof raw === "number" ? `${(raw * 100).toFixed(2)}%` : "â€”";
  }, [snapshot]);

  const criticalCount =
    support?.risks.filter((r) => r.risk_level === "CRITICAL").length ?? 0;
  const highCount =
    support?.risks.filter((r) => r.risk_level === "HIGH").length ?? 0;

  const decide = async (
    recommendationId: string,
    action: "approve" | "reject",
  ) => {
    setBusyId(recommendationId);
    setDecisionMessage(null);
    try {
      const record =
        action === "approve"
          ? await api.approveRecommendation(recommendationId)
          : await api.rejectRecommendation(recommendationId);
      if (record.status === "EXECUTED") {
        const allocationId = record.allocation?.id;
        setDecisionMessage(
          `Allocation executed${allocationId ? ` Â· simulator allocation #${allocationId}` : ""}.`,
        );
      } else {
        setDecisionMessage("Recommendation rejected by operator.");
      }
      await load();
    } catch (err) {
      setDecisionMessage(
        err instanceof Error ? `Decision blocked: ${err.message}` : "Decision failed.",
      );
    } finally {
      setBusyId(null);
    }
  };

  if (!snapshot && !error) {
    return (
      <main className="shell">
        <div className="loading card">Loading live fuel network and intelligenceâ€¦</div>
      </main>
    );
  }

  return (
    <main className="shell">
      <header className="hero">
        <div>
          <p className="eyebrow">BUP CSE Fest 2026 Â· Operational AI</p>
          <h1>FuelOps Resilience</h1>
          <p className="hero-copy">
            Live simulator state, demand forecasting, stockout risk and constrained
            allocation recommendations with human approval and fresh-state revalidation.
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
          Data freshness: {snapshot?.data_freshness}. Recommendations may be shown,
          but execution is blocked until fresh REST state returns.
        </section>
      )}
      {decisionMessage && <section className="decision-message">{decisionMessage}</section>}

      <section className="metrics-grid phase2-metrics">
        <article className="metric card">
          <span>Service level</span>
          <strong>{serviceLevel}</strong>
        </article>
        <article className="metric card">
          <span>Critical / High risks</span>
          <strong>{criticalCount} / {highCount}</strong>
        </article>
        <article className="metric card">
          <span>Recommendations</span>
          <strong>{support?.recommendations.length ?? 0}</strong>
        </article>
        <article className="metric card">
          <span>Forecast horizon</span>
          <strong>{support?.forecasts[0]?.horizon_ticks ?? 0} ticks</strong>
        </article>
      </section>

      {support && (
        <section className="section">
          <div className="section-title">
            <div>
              <p className="eyebrow">Predict â†’ Assess Risk</p>
              <h2>Demand & Stockout Intelligence</h2>
            </div>
            <span className="subtle">
              12 station Ã— fuel forecasts Â· {support.data_freshness}
            </span>
          </div>
          <RiskTable
            risks={support.risks}
            support={support}
            stationName={stationName}
          />
        </section>
      )}

      <section className="section">
        <div className="section-title">
          <div>
            <p className="eyebrow">Decide â†’ Validate â†’ Act</p>
            <h2>Operator Recommendations</h2>
          </div>
          <span className="subtle">No autonomous allocation</span>
        </div>

        {support?.recommendations.length ? (
          <div className="recommendation-grid">
            {support.recommendations.map((recommendation) => (
              <RecommendationCard
                key={recommendation.recommendation_id}
                recommendation={recommendation}
                stationName={stationName}
                busy={busyId === recommendation.recommendation_id}
                onApprove={(id) => decide(id, "approve")}
                onReject={(id) => decide(id, "reject")}
              />
            ))}
          </div>
        ) : (
          <article className="card empty-state">
            <h3>No allocation recommendation right now</h3>
            <p className="subtle">
              Current forecast and inventory do not cross the Phase 2 action threshold.
            </p>
          </article>
        )}
      </section>

      <section className="section">
        <div className="section-title">
          <div>
            <p className="eyebrow">Observe</p>
            <h2>Fuel Stations</h2>
          </div>
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
          <div className="table-row route-row table-head-row">
            <span>Route</span><span>Transit</span><span>Max</span><span>Status</span>
          </div>
          {snapshot?.routes.map((route) => (
            <div className="table-row route-row" key={route.id}>
              <span>{route.source_depot_id} â†’ {route.destination_station_id}</span>
              <span>{route.transit_ticks} ticks</span>
              <span>{route.max_shipment.toLocaleString()} L</span>
              <span><StatusPill value={route.status} /></span>
            </div>
          ))}
        </div>
      </section>


      <section className="section">
        <div className="section-title">
          <div>
            <p className="eyebrow">Resilience</p>
            <h2>Resilience & Observability</h2>
          </div>
          <StatusPill value={systemHealth?.status ?? "STARTING"} />
        </div>

        <div className="metrics-grid">
          <article className="metric card">
            <span>API requests</span>
            <strong>{systemMetrics?.requests_total ?? 0}</strong>
          </article>
          <article className="metric card">
            <span>API p95 latency</span>
            <strong>{systemMetrics ? `${systemMetrics.latency.p95_ms.toFixed(1)} ms` : "â€”"}</strong>
          </article>
          <article className="metric card">
            <span>Fallback activations</span>
            <strong>{systemMetrics?.fallback_activations ?? 0}</strong>
          </article>
          <article className="metric card">
            <span>Simulator retries</span>
            <strong>{systemMetrics?.simulator_retry_count ?? 0}</strong>
          </article>
        </div>

        <div className="observability-grid">
          <article className="card">
            <div className="card-head">
              <div>
                <p className="eyebrow">Safety State</p>
                <h3>{systemHealth?.data_freshness ?? "UNKNOWN"} data</h3>
              </div>
              <StatusPill value={systemHealth?.components.decision?.status ?? "STARTING"} />
            </div>
            <p className="subtle">
              Snapshot recoveries: {systemMetrics?.snapshot_recoveries ?? 0}
              {" Â· "}SSE reconnects: {systemMetrics?.sse_reconnects ?? 0}
              {" Â· "}Errors: {systemMetrics ? pct(systemMetrics.error_rate) : "0%"}
            </p>
          </article>

          <article className="card">
            <div className="card-head">
              <div>
                <p className="eyebrow">Incidents</p>
                <h3>{systemMetrics?.active_incidents ?? 0} active</h3>
              </div>
            </div>
            {incidents.length === 0 ? (
              <p className="subtle">No resilience incidents recorded.</p>
            ) : (
              <div className="incident-list">
                {incidents.slice(0, 4).map((incident) => (
                  <div className="incident-row" key={incident.incident_id}>
                    <div>
                      <strong>{incident.kind.replaceAll("_", " ")}</strong>
                      <small>{incident.detail}</small>
                    </div>
                    <StatusPill value={incident.status} />
                  </div>
                ))}
              </div>
            )}
          </article>
        </div>
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
