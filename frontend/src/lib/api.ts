import type { User } from "./types";
import * as demo from "@/mocks/demo";

export const API_BASE = (process.env.NEXT_PUBLIC_API_BASE_URL ?? "").replace(/\/$/, "");
export const DEMO = process.env.NEXT_PUBLIC_DEMO_MODE === "true";

export class ApiError extends Error {
  code: string;
  status: number;
  details?: unknown;

  constructor(code: string, message: string, status: number, details?: unknown) {
    super(message);
    this.name = "ApiError";
    this.code = code;
    this.status = status;
    this.details = details;
  }
}

// Access token lives in memory only — never persisted (cookie auth is primary;
// this token is exclusively for the WS query-param auth path).
let wsToken = "";
export function setWsToken(token: string) {
  wsToken = token;
}
export function getWsToken() {
  return wsToken;
}
export function clearWsToken() {
  wsToken = "";
}

async function request<T>(path: string, init: RequestInit = {}): Promise<T> {
  let res: Response;
  try {
    res = await fetch(`${API_BASE}${path}`, {
      credentials: "include",
      headers: {
        ...(init.body ? { "Content-Type": "application/json" } : {}),
        ...init.headers,
      },
      ...init,
    });
  } catch {
    throw new ApiError("NETWORK", "Cannot reach the ESS backend.", 0);
  }
  if (res.status === 204) return undefined as T;
  let body: unknown;
  try {
    body = await res.json();
  } catch {
    throw new ApiError("HTTP_ERROR", `Unexpected response (${res.status}).`, res.status);
  }
  if (!res.ok) {
    const envelope = body as { error?: { code?: string; message?: string; details?: unknown } };
    if (envelope?.error?.code === "TOKEN_EXPIRED" || envelope?.error?.code === "UNAUTHORIZED") clearWsToken();
    throw new ApiError(
      envelope?.error?.code ?? "HTTP_ERROR",
      envelope?.error?.message ?? `Request failed (${res.status}).`,
      res.status,
      envelope?.error?.details,
    );
  }
  return body as T;
}

export interface HistoryParams {
  deviceId?: number;
  start: Date;
  end: Date;
  limit?: number;
  offset?: number;
  order?: "asc" | "desc";
}

export interface AlertParams {
  status?: "open" | "acknowledged" | "closed" | "all";
  deviceId?: number;
  ruleKey?: string;
  severity?: string;
  limit?: number;
  offset?: number;
}

export interface Api {
  login(username: string, password: string): Promise<{ user: User; token: string }>;
  logout(): Promise<void>;
  me(): Promise<User>;
  listDevices(): Promise<{ items: import("./types").DeviceDetail[]; total: number }>;
  getDevice(id: number): Promise<import("./types").DeviceDetail>;
  createDevice(body: { device_id: number; name: string; location?: string }): Promise<import("./types").Device>;
  updateDevice(id: number, body: Record<string, unknown>): Promise<import("./types").Device>;
  deleteDevice(id: number): Promise<void>;
  latest(deviceId?: number, limit?: number): Promise<import("./types").Telemetry[]>;
  history(params: HistoryParams): Promise<import("./types").Telemetry[]>;
  listAlerts(params?: AlertParams): Promise<import("./types").AlertList>;
  acknowledgeAlert(id: number): Promise<void>;
  getSettings(): Promise<import("./types").Settings>;
  patchSettings(body: Record<string, unknown>): Promise<import("./types").Settings>;
  listUsers(): Promise<{ items: import("./types").User[]; total: number }>;
  createUser(body: { username: string; password: string; role: import("./types").Role }): Promise<import("./types").User>;
  updateUser(id: number, body: Partial<{ password: string; role: import("./types").Role; is_active: boolean }>): Promise<import("./types").User>;
  deleteUser(id: number): Promise<void>;
}

const realApi: Api = {
  async login(username, password) {
    const out = await request<{ access_token: string; user: User }>("/auth/login", {
      method: "POST",
      body: JSON.stringify({ username, password }),
    });
    setWsToken(out.access_token);
    return { user: out.user, token: out.access_token };
  },
  async logout() {
    try {
      await request<{ ok: boolean }>("/auth/logout", { method: "POST" });
    } finally {
    }
  },
  async me() {
    return request<User>("/auth/me");
  },
  async listDevices() {
    return request("/devices");
  },
  async getDevice(id) {
    return request(`/devices/${id}`);
  },
  async createDevice(body) {
    return request("/devices", { method: "POST", body: JSON.stringify(body) });
  },
  async updateDevice(id, body) {
    return request(`/devices/${id}`, { method: "PATCH", body: JSON.stringify(body) });
  },
  async deleteDevice(id) {
    return request(`/devices/${id}`, { method: "DELETE" });
  },
  async latest(deviceId, limit = 25) {
    const q = new URLSearchParams({ limit: String(limit) });
    if (deviceId !== undefined) q.set("device_id", String(deviceId));
    return request(`/telemetry/latest?${q.toString()}`);
  },
  async history({ deviceId, start, end, limit = 500, offset = 0, order = "asc" }) {
    const q = new URLSearchParams({
      start: start.toISOString().replace(/\.000Z$/, "Z"),
      end: end.toISOString().replace(/\.000Z$/, "Z"),
      limit: String(limit),
      offset: String(offset),
      order,
    });
    if (deviceId !== undefined) q.set("device_id", String(deviceId));
    return request(`/telemetry/history?${q.toString()}`);
  },
  async listAlerts(params = {}) {
    const q = new URLSearchParams();
    if (params.status && params.status !== "all") q.set("status", params.status);
    if (params.deviceId !== undefined) q.set("device_id", String(params.deviceId));
    if (params.ruleKey) q.set("rule_key", params.ruleKey);
    if (params.severity) q.set("severity", params.severity);
    q.set("limit", String(params.limit ?? 100));
    q.set("offset", String(params.offset ?? 0));
    const suffix = q.toString();
    return request(`/alerts${suffix ? `?${suffix}` : ""}`);
  },
  async acknowledgeAlert(id) {
    await request(`/alerts/${id}`, { method: "PATCH", body: JSON.stringify({ status: "acknowledged" }) });
  },
  async getSettings() {
    return request("/settings");
  },
  async patchSettings(body) {
    return request("/settings", { method: "PATCH", body: JSON.stringify(body) });
  },
  async listUsers() {
    return request("/auth/users");
  },
  async createUser(body) {
    return request("/auth/users", { method: "POST", body: JSON.stringify(body) });
  },
  async updateUser(id, body) {
    return request(`/auth/users/${id}`, { method: "PATCH", body: JSON.stringify(body) });
  },
  async deleteUser(id) {
    return request(`/auth/users/${id}`, { method: "DELETE" });
  },
};

export const api: Api = DEMO ? demo.demoApi : realApi;
