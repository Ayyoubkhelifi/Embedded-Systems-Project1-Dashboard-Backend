export type Role = "admin" | "operator" | "viewer";

export interface User {
  id: number;
  username: string;
  role: Role;
  is_active: boolean;
  created_at: string;
}

export interface Flags {
  temp: boolean;
  hum: boolean;
  mq2: boolean;
  water: boolean;
  water_detected: boolean;
  battery: boolean;
  ack_requested: boolean;
  simulated: boolean;
}

export interface Telemetry {
  id: number;
  device_id: number;
  packet_seq: number;
  temperature_c: number | null;
  humidity_pct: number | null;
  mq2_raw: number | null;
  water_raw: number | null;
  battery_mv: number | null;
  temp_valid: boolean;
  hum_valid: boolean;
  mq2_valid: boolean;
  water_valid: boolean;
  battery_valid: boolean;
  gas_alarm: boolean;
  water_detected: boolean;
  simulated: boolean;
  rssi: number | null;
  snr: number | null;
  gateway_id: string | null;
  gateway_time: string;
  device_time: string | null;
}

export type DeviceStatus = "online" | "offline";

export interface Device {
  device_id: number;
  name: string;
  device_type: string;
  location: string | null;
  registered_at: string;
  last_seen_at: string | null;
  last_seq: number | null;
  last_rssi: number | null;
  last_snr: number | null;
  status: DeviceStatus;
  is_active: boolean;
}

export interface DeviceDetail extends Device {
  latest_reading: Telemetry | null;
}

export interface DeviceList {
  items: DeviceDetail[];
  total: number;
}

export type AlertStatus = "open" | "acknowledged" | "closed";
export type Severity = "info" | "warning" | "critical";

export interface Alert {
  id: number;
  device_id: number;
  rule_key: string;
  severity: Severity;
  description: string;
  status: AlertStatus;
  created_at: string;
  acknowledged_at: string | null;
  acknowledged_by: number | null;
  closed_at: string | null;
}

export interface AlertList {
  items: Alert[];
  total: number;
}

export interface AlertRule {
  rule_key: string;
  threshold: number;
  hysteresis: number;
  sustained: number;
  severity: Severity;
  enabled: boolean;
}

export interface Settings {
  alert_rules: AlertRule[];
  device_freshness_timeout_seconds: number;
}

export interface WsMessage {
  type: "hello" | "pong" | "telemetry" | "alert" | "alert_closed" | "device_status" | "heartbeat";
  data: Telemetry | Alert | Record<string, unknown>;
}
