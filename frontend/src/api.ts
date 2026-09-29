import type { Health, Snapshot } from "./types";

const API_BASE = import.meta.env.VITE_API_BASE_URL ?? "http://127.0.0.1:8001";

async function getJson<T>(path: string): Promise<T> {
  const response = await fetch(`${API_BASE}${path}`, {
    headers: { Accept: "application/json" },
  });
  if (!response.ok) {
    throw new Error(`${path} returned HTTP ${response.status}`);
  }
  return response.json() as Promise<T>;
}

export const api = {
  snapshot: () => getJson<Snapshot>("/api/snapshot"),
  health: () => getJson<Health>("/api/health"),
};
