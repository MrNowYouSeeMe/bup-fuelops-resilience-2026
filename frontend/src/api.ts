import type {
  CrisisSummary,
  DecisionRecord,
  DecisionSupportBundle,
  Health,
  IncidentRecord,
  Snapshot,
  SystemHealth,
  SystemMetrics,
} from "./types";

const API_BASE = import.meta.env.VITE_API_BASE_URL ?? "http://127.0.0.1:8001";

async function requestJson<T>(
  path: string,
  init?: RequestInit,
): Promise<T> {
  const response = await fetch(`${API_BASE}${path}`, {
    ...init,
    headers: {
      Accept: "application/json",
      ...(init?.body ? { "Content-Type": "application/json" } : {}),
      ...(init?.headers ?? {}),
    },
  });

  if (!response.ok) {
    let detail = `${path} returned HTTP ${response.status}`;
    try {
      const body = (await response.json()) as {
        detail?: string | { code?: string; message?: string };
      };
      if (typeof body.detail === "string") {
        detail = body.detail;
      } else if (body.detail) {
        const code = body.detail.code ? `${body.detail.code}: ` : "";
        detail = `${code}${body.detail.message ?? detail}`;
      }
    } catch {
      // Keep HTTP fallback message.
    }
    throw new Error(detail);
  }

  return response.json() as Promise<T>;
}

export const api = {
  snapshot: () => requestJson<Snapshot>("/api/snapshot"),
  health: () => requestJson<Health>("/api/health"),
  systemHealth: () => requestJson<SystemHealth>("/api/system/health"),
  systemMetrics: () => requestJson<SystemMetrics>("/api/system/metrics"),
  incidents: () => requestJson<IncidentRecord[]>("/api/incidents"),
  crisis: () => requestJson<CrisisSummary>("/api/crisis"),
  decisionSupport: () =>
    requestJson<DecisionSupportBundle>("/api/decision-support"),
  approveRecommendation: (recommendationId: string) =>
    requestJson<DecisionRecord>(
      `/api/recommendations/${encodeURIComponent(recommendationId)}/approve`,
      { method: "POST" },
    ),
  rejectRecommendation: (recommendationId: string, reason?: string) =>
    requestJson<DecisionRecord>(
      `/api/recommendations/${encodeURIComponent(recommendationId)}/reject`,
      {
        method: "POST",
        body: JSON.stringify({ reason: reason ?? null }),
      },
    ),
};
