import type {
  Alert,
  Device,
  DeviceDetail,
  Settings,
  Telemetry,
  User,
} from "@/lib/types";
import type { Api, AlertParams, HistoryParams } from "@/lib/api";
import { setWsToken } from "@/lib/api";

/** In-browser simulation so the dashboard is fully demoable without a backend. */

const DEMO_TOKEN = "demo-token";

const users: User[] = [
  { id: 1, username: "demo_admin", role: "admin", is_active: true, created_at: "2026-01-05T09:00:00Z" },
];

function device(id: number, name: string, location: string): DeviceDetail {
  return {
    device_id: id,
    name,
    device_type: "esp32_env_node",
    location,
    registered_at: "2026-01-06T10:00:00Z",
    last_seen_at: null,
    last_seq: null,
    last_rssi: null,
    last_snr: null,
    status: "online",
    is_active: true,
    latest_reading: null,
  };
}

const devices: DeviceDetail[] = [
  device(101, "ESP32 Node A", "Annex C2 — switchgear"),
  device(102, "ESP32 Node B", "Annex C2 — riser"),
  device(103, "ESP32 Node C", "Yard — sensor mast"),
];

interface SimState {
  t: number;
  temp: number;
  hum: number;
  mq2: number;
}

const states = new Map<number, SimState>();

function stateFor(deviceId: number, time: number): SimState {
  let s = states.get(deviceId);
  if (!s) {
    s = {
      t: time,
      temp: 24 + ((deviceId * 7) % 5),
      hum: 40 + ((deviceId * 11) % 15),
      mq2: 180 + ((deviceId * 13) % 60),
    };
    states.set(deviceId, s);
  }
  return s;
}

function makeReading(deviceId: number, time: number): Telemetry {
  const s = stateFor(deviceId, time);
  const dt = time - s.t;
  s.t = time;
  const dayPhase = (time / 40) % (Math.PI * 2);
  s.temp += Math.cos(dayPhase) * 0.06 * (dt / 5) + (Math.random() - 0.5) * 0.2;
  s.hum += -s.temp * 0.004 + (Math.random() - 0.5) * 0.4 + 0.02;
  s.hum = Math.max(25, Math.min(99, s.hum));
  s.temp = Math.max(10, Math.min(60, s.temp));
  s.mq2 += (Math.random() - 0.5) * 24;
  if (Math.random() < 0.01) s.mq2 += 900 + Math.random() * 600; // transient spike
  s.mq2 = Math.max(60, Math.min(4095, s.mq2));
  if (s.mq2 > 300) s.mq2 -= (s.mq2 - 300) * 0.03; // decay toward baseline
  const waterDet = Math.random() < 0.008;
  const seq = Math.floor(time / 5) + deviceId * 1000;
  return {
    id: seq,
    device_id: deviceId,
    packet_seq: seq,
    temperature_c: Math.round(s.temp * 100) / 100,
    humidity_pct: Math.round(s.hum * 100) / 100,
    mq2_raw: Math.round(s.mq2),
    water_raw: waterDet ? Math.round(400 + Math.random() * 300) : Math.round(Math.random() * 40),
    battery_mv: 3750 + Math.round(Math.random() * 120),
    temp_valid: Math.random() > 0.02,
    hum_valid: true,
    mq2_valid: true,
    water_valid: true,
    battery_valid: true,
    gas_alarm: s.mq2 > 800,
    water_detected: false,
    simulated: true,
    rssi: Math.round(-95 + Math.random() * 22),
    snr: Math.round((Math.random() * 14 - 4) * 10) / 10,
    gateway_id: "gw-sim",
    gateway_time: new Date(time * 1000).toISOString(),
    device_time: null,
  };
}

function reading(reId: number, dId: number, ageMinutes: number): Telemetry {
  return makeReading(dId, Math.floor(Date.now() / 1000) - ageMinutes * 60);
}

function seedHistory(deviceId: number, minutes: number): Telemetry[] {
  const out: Telemetry[] = [];
  const nowSec = Math.floor(Date.now() / 1000);
  for (let i = minutes; i >= 0; i -= 2) {
    out.push(makeReading(deviceId, nowSec - i * 60));
  }
  return out;
}

let alertSeq = 100;
function seedAlert(id: number, dId: number, rule: string, severity: Alert["severity"], desc: string, status: Alert["status"], sinceMin: number): Alert {
  return {
    id,
    device_id: dId,
    rule_key: rule,
    severity,
    description: desc,
    status,
    created_at: new Date(Date.now() - sinceMin * 60000).toISOString(),
    acknowledged_at: status !== "open" ? new Date(Date.now() - sinceMin * 40000).toISOString() : null,
    acknowledged_by: status !== "open" ? 1 : null,
    closed_at: status === "closed" ? new Date(Date.now() - 1000).toISOString() : null,
  };
}

const alerts: Alert[] = [
  seedAlert(101, 103, "humidity_high", "warning", "Relative humidity 92.3 % exceeded **85.0 %** for 2 consecutive readings (preliminary indication — not a certified safety alarm).", "open", 34),
  seedAlert(102, 102, "temp_high", "critical", "Temperature 41.2 °C exceeded **35.0 °C** for 3 consecutive readings.", "acknowledged", 120),
];

function applyAlerts(r: Telemetry) {
  if (r.temperature_c && r.temperature_c > 35) {
    const open = alerts.find((a) => a.rule_key === "temp_high" && a.device_id === r.device_id && a.status !== "closed");
    if (!open) {
      alerts.unshift(seedAlert(++alertSeq, r.device_id, "temp_high", "critical", `Temperature ${r.temperature_c} °C exceeded **35.0 °C** for 2 consecutive readings.`, "open", 0));
    }
  }
  if (r.mq2_raw && r.mq2_raw > 800) {
    const open = alerts.find((a) => a.rule_key === "mq2_threshold" && a.device_id === r.device_id && a.status !== "closed");
    if (!open) alerts.unshift(seedAlert(++alertSeq, r.device_id, "mq2_threshold", "critical", "MQ-2 raw counts crossed the preliminary 800 threshold — investigate possible smoke/gas (not a certified safety alarm).", "open", 0));
  }
}

let tick = 0;
const listeners = new Set<() => void>();

setInterval(() => {
  tick += 1;
  const nowSec = Math.floor(Date.now() / 1000);
  for (const d of devices) {
    const r = makeReading(d.device_id, nowSec);
    d.last_seen_at = r.gateway_time;
    d.last_seq = r.packet_seq;
    d.last_rssi = r.rssi;
    d.last_snr = r.snr;
    d.latest_reading = r;
    applyAlerts(r);
  }
  listeners.forEach((fn) => fn());
}, 5000);

type EventType = "telemetry" | "alert" | "alert_closed" | "device_status" | "hello" | "pong";

export function demoSubscribe(onEvent: (type: EventType, data: unknown) => void): () => void {
  const fn = () => {
    for (const d of devices) {
      if (d.latest_reading) {
        onEvent("telemetry", d.latest_reading);
        if (d.latest_reading.gas_alarm) {
          const open = alerts.find((a) => a.rule_key === "mq2_threshold" && a.device_id === d.device_id && a.status !== "closed");
          if (open) onEvent("alert", open);
        }
      }
      onEvent("device_status", { device_id: d.device_id, status: "online", last_seq: d.last_seq, last_seen_at: d.last_seen_at });
    }
  };
  listeners.add(fn);
  onEvent("hello", { user: "demo_admin", conn_id: "demo" });
  fn();
  return () => listeners.delete(fn);
}

export interface TelemetryOut {
  items: Telemetry[];
  total: number;
}

const historyCache = new Map<number, Telemetry[]>();

export const demoApi: Api = {
  async login() {
    setWsToken(DEMO_TOKEN);
    return { user: users[0], token: DEMO_TOKEN };
  },
  async logout() {
    return;
  },
  async me() {
    return users[0];
  },
  async listDevices() {
    return { items: devices.map((d) => ({ ...d })), total: devices.length };
  },
  async getDevice(id) {
    const d = devices.find((x) => x.device_id === id);
    if (!d) throw new Error("Device not found.");
    return { ...d, latest_reading: d.latest_reading ? { ...d.latest_reading } : null };
  },
  async createDevice(body) {
    const d = device(body.device_id, body.name, body.location ?? "");
    devices.push(d);
    return { ...d };
  },
  async updateDevice(id, body) {
    const d = devices.find((x) => x.device_id === id);
    if (!d) throw new Error("Device not found.");
    Object.assign(d, body as Partial<Device>);
    return { ...d };
  },
  async deleteDevice(id) {
    const i = devices.findIndex((x) => x.device_id === id);
    if (i >= 0) devices.splice(i, 1);
  },
  async latest(deviceId, limit = 25) {
    const list = deviceId !== undefined ? seedHistory(deviceId, 60) : devices.flatMap((d) => seedHistory(d.device_id, 60));
    return list
      .sort((a, b) => (a.gateway_time < b.gateway_time ? 1 : -1))
      .slice(0, limit) as Telemetry[];
  },
  async history({ deviceId }: HistoryParams) {
    if (!historyCache.has(deviceId ?? -1)) historyCache.set(deviceId ?? -1, seedHistory(deviceId ?? 101, 180));
    return historyCache.get(deviceId ?? -1)!;
  },
  async listAlerts(params: AlertParams = {}) {
    let items = [...alerts];
    if (params.status && params.status !== "all") items = items.filter((a) => a.status === params.status);
    if (params.deviceId !== undefined) items = items.filter((a) => a.device_id === params.deviceId);
    if (params.ruleKey) items = items.filter((a) => a.rule_key === params.ruleKey);
    return { items, total: items.length };
  },
  async acknowledgeAlert(id) {
    const a = alerts.find((x) => x.id === id);
    if (a) {
      a.status = "acknowledged";
      a.acknowledged_at = new Date().toISOString();
      a.acknowledged_by = 1;
    }
  },
  async getSettings(): Promise<Settings> {
    return {
      alert_rules: [
        { rule_key: "temp_high", threshold: 35, hysteresis: 2, sustained: 2, severity: "critical", enabled: true },
        { rule_key: "humidity_high", threshold: 85, hysteresis: 3, sustained: 3, severity: "warning", enabled: true },
        { rule_key: "mq2_threshold", threshold: 800, hysteresis: 100, sustained: 2, severity: "critical", enabled: true },
        { rule_key: "water_detected", threshold: 0, hysteresis: 0, sustained: 1, severity: "warning", enabled: true },
        { rule_key: "sensor_malfunction", threshold: 0, hysteresis: 0, sustained: 3, severity: "warning", enabled: true },
        { rule_key: "device_offline", threshold: 0, hysteresis: 0, sustained: 1, severity: "warning", enabled: true },
      ],
      device_freshness_timeout_seconds: 900,
    };
  },
  async patchSettings() {
    return this.getSettings();
  },
  async listUsers() {
    return { items: users, total: users.length };
  },
  async createUser(body) {
    const u: User = {
      id: users.length + 1,
      username: body.username,
      role: body.role,
      is_active: true,
      created_at: new Date().toISOString(),
    };
    users.push(u);
    return u;
  },
  async updateUser(id, body) {
    const u = users.find((x) => x.id === id);
    if (!u) throw new Error("User not found.");
    if (body.role) u.role = body.role;
    if (body.is_active !== undefined) u.is_active = body.is_active;
    return u;
  },
  async deleteUser(id) {
    const u = users.find((x) => x.id === id);
    if (u) u.is_active = false;
  },
};

// keep the unused helper referenced for JSON-shaped seeding in future tests
export function _seedReading(reId: number, dId: number, ageMin: number) {
  return reading(reId, dId, ageMin);
}
