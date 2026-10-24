import type { AIReview, AppConfig, ScenarioOptions, Snapshot } from "./types";

const API_BASE = import.meta.env.VITE_API_BASE
  ?? `${window.location.protocol}//${window.location.hostname || "127.0.0.1"}:8000`;

async function request<T>(path: string, init?: RequestInit): Promise<T> {
  const response = await fetch(`${API_BASE}${path}`, {
    ...init,
    headers: { "Content-Type": "application/json", ...init?.headers },
  });
  if (!response.ok) {
    const payload = await response.json().catch(() => ({ detail: response.statusText }));
    throw new Error(typeof payload.detail === "string" ? payload.detail : response.statusText);
  }
  return response.json() as Promise<T>;
}

export const getConfig = () => request<AppConfig>("/api/config");

export const createScenario = (options: ScenarioOptions) =>
  request<Snapshot>("/api/scenarios", { method: "POST", body: JSON.stringify(options) });

export const sendCommand = (
  sessionId: string,
  action: "start" | "pause" | "step" | "alarm",
  sensorId?: string,
) =>
  request<Snapshot>(`/api/scenarios/${sessionId}/command`, {
    method: "POST",
    body: JSON.stringify({ action, sensor_id: sensorId }),
  });

export const analyzeScenario = (sessionId: string, personId: string) =>
  request<AIReview>("/api/ai/evacuation-review", {
    method: "POST",
    body: JSON.stringify({ session_id: sessionId, person_id: personId }),
  });

export const createEmergencyBrief = (
  sessionId: string,
  siteAddress: string,
  callbackNumber: string,
) =>
  request<{ draft_only: boolean; sent: boolean; text: string }>(
    `/api/scenarios/${sessionId}/emergency-brief`,
    { method: "POST", body: JSON.stringify({ site_address: siteAddress, callback_number: callbackNumber }) },
  );

export function streamUrl(sessionId: string): string {
  const url = new URL(API_BASE);
  url.protocol = url.protocol === "https:" ? "wss:" : "ws:";
  url.pathname = `/api/scenarios/${sessionId}/stream`;
  return url.toString();
}
