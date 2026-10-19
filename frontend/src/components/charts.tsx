"use client";

import {
  Area,
  AreaChart,
  CartesianGrid,
  Legend,
  Line,
  LineChart,
  ResponsiveContainer,
  Tooltip,
  XAxis,
  YAxis,
} from "recharts";
import type { Telemetry } from "@/lib/types";

const axis = { stroke: "#8b94a3", fontSize: 11 } as const;

function ts(iso: string) {
  return new Date(iso).toLocaleTimeString(undefined, { hour: "2-digit", minute: "2-digit" });
}

function toRows(readings: Telemetry[]) {
  return readings
    .filter((r) => r.temp_valid || r.hum_valid)
    .map((r) => ({
      ts: new Date(r.gateway_time).getTime(),
      label: ts(r.gateway_time),
      temp: r.temp_valid ? r.temperature_c : null,
      hum: r.hum_valid ? r.humidity_pct : null,
      mq2: r.mq2_valid ? r.mq2_raw : null,
    }));
}

export function TelemetryLineChart({ readings, height = 260 }: { readings: Telemetry[]; height?: number }) {
  const rows = toRows(readings);
  return (
    <div role="img" aria-label="Temperature and humidity over time">
      <ResponsiveContainer width="100%" height={height}>
        <LineChart data={rows} margin={{ top: 8, right: 12, bottom: 0, left: -18 }}>
          <CartesianGrid stroke="var(--border-subtle)" strokeDasharray="3 3" />
          <XAxis dataKey="ts" type="number" scale="time" domain={["dataMin", "dataMax"]} tick={axis} tickFormatter={(v) => ts(new Date(v).toISOString())} tickLine={false} />
          <YAxis yAxisId="t" tick={axis} tickLine={false} tickFormatter={(v: number) => `${v}°`} />
          <YAxis yAxisId="h" orientation="right" tick={axis} tickLine={false} tickFormatter={(v: number) => `${v}%`} />
          <Tooltip
            contentStyle={{ background: "var(--raised)", border: "1px solid var(--border-subtle)", fontSize: 12 }}
            labelFormatter={(v) => new Date(Number(v)).toLocaleString()}
          />
          <Legend wrapperStyle={{ fontSize: 12 }} />
          <Line yAxisId="t" dataKey="temp" name="Temperature °C" stroke="var(--warn)" dot={false} strokeWidth={1.6} connectNulls />
          <Line yAxisId="h" dataKey="hum" name="Humidity %" stroke="var(--ok)" dot={false} strokeWidth={1.6} connectNulls />
        </LineChart>
      </ResponsiveContainer>
    </div>
  );
}

export function Mq2AreaChart({ readings, height = 200 }: { readings: Telemetry[]; height?: number }) {
  const rows = toRows(readings);
  return (
    <div role="img" aria-label="MQ-2 gas sensor raw ADC counts over time">
      <ResponsiveContainer width="100%" height={height}>
        <AreaChart data={rows} margin={{ top: 8, right: 12, bottom: 0, left: -18 }}>
          <CartesianGrid stroke="var(--border-subtle)" strokeDasharray="3 3" />
          <XAxis dataKey="ts" type="number" scale="time" domain={["dataMin", "dataMax"]} tick={axis} tickFormatter={(v) => ts(new Date(v).toISOString())} tickLine={false} />
          <YAxis tick={axis} tickLine={false} tickFormatter={(v: number) => String(v)} />
          <Tooltip
            contentStyle={{ background: "var(--raised)", border: "1px solid var(--border-subtle)", fontSize: 12 }}
            labelFormatter={(v) => new Date(Number(v)).toLocaleString()}
          />
          <Area dataKey="mq2" name="MQ-2 raw" stroke="var(--crit)" fill="rgba(248,113,113,0.12)" connectNulls />
        </AreaChart>
      </ResponsiveContainer>
    </div>
  );
}
