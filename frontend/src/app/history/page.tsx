"use client";

import { FormEvent, useMemo, useState } from "react";
import { useApi } from "@/hooks";
import { api } from "@/lib/api";
import { PageShell } from "@/components/nav";
import { EmptyState, ErrorState, Skeleton } from "@/components/states";
import { Field, inputClass, btnClass, SectionTitle } from "@/components/ui";
import { Mq2AreaChart, TelemetryLineChart } from "@/components/charts";
import { fmtDateTime, fmtNum, fmtRssi } from "@/lib/format";
import type { Telemetry } from "@/lib/types";

const RANGES = [
  { label: "1 h", hours: 1 },
  { label: "6 h", hours: 6 },
  { label: "24 h", hours: 24 },
  { label: "7 d", hours: 24 * 7 },
] as const;

export default function HistoryPage() {
  const devices = useApi(() => api.listDevices(), []);
  const [deviceId, setDeviceId] = useState<number | undefined>(undefined);
  const [rangeIdx, setRangeIdx] = useState(2);

  const deviceOptions = devices.data?.items ?? [];
  const activeId = deviceId ?? deviceOptions[0]?.device_id;
  const hours = RANGES[rangeIdx].hours;

  const history = useApi<Telemetry[]>(
    () =>
      activeId === undefined
        ? Promise.resolve([])
        : api.history({ deviceId: activeId, start: new Date(Date.now() - hours * 3600_000), end: new Date() }),
    [activeId, hours],
    30000,
  );

  const readings = useMemo(() => {
    const out = history.data ?? [];
    return [...out].sort((a, b) => (a.gateway_time < b.gateway_time ? -1 : 1));
  }, [history.data]);

  const lastN = useMemo(() => [...(history.data ?? [])].slice(0, 40), [history.data]);

  function onDeviceChange(e: FormEvent<HTMLSelectElement>) {
    const v = Number(e.currentTarget.value);
    setDeviceId(Number.isFinite(v) ? v : undefined);
  }

  return (
    <PageShell
      title="History"
      actions={
        <div className="flex items-center gap-2" role="group" aria-label="Time range">
          {RANGES.map((r, i) => (
            <button
              key={r.label}
              onClick={() => setRangeIdx(i)}
              aria-pressed={i === rangeIdx}
              className={i === rangeIdx ? `${btnClass} bg-raised` : btnClass}
            >
              {r.label}
            </button>
          ))}
        </div>
      }
    >
      <div className="mb-4 grid grid-cols-1 gap-3 sm:grid-cols-2 lg:w-96 lg:grid-cols-1">
        <Field label="Device">
          <select
            className={inputClass}
            aria-label="Device"
            value={activeId ?? ""}
            onChange={onDeviceChange}
          >
            {deviceOptions.map((d) => (
              <option key={d.device_id} value={d.device_id}>
                {d.device_id} — {d.name}
              </option>
            ))}
          </select>
        </Field>
      </div>

      {devices.loading || (activeId === undefined && devices.loading) ? (
        <Skeleton className="h-64 rounded-lg" />
      ) : devices.error ? (
        <ErrorState error={devices.error} onRetry={devices.refetch} />
      ) : activeId === undefined ? (
        <EmptyState title="No devices registered" detail="Register a device to browse its history." />
      ) : history.loading ? (
        <Skeleton className="h-64 rounded-lg" />
      ) : history.error ? (
        <ErrorState error={history.error} onRetry={history.refetch} />
      ) : readings.length === 0 ? (
        <EmptyState title="No readings in this window" detail="Try a wider time range or check whether the device is reporting." />
      ) : (
        <>
          <div className="border-subtle bg-surface rounded-lg border p-4">
            <TelemetryLineChart readings={readings} height={300} />
            <div className="mt-6">
              <SectionTitle>MQ-2 gas counts</SectionTitle>
              <Mq2AreaChart readings={readings} height={200} />
            </div>
          </div>

          <div className="mt-8">
            <SectionTitle>Recent raw readings</SectionTitle>
            <div className="border-subtle bg-surface overflow-x-auto rounded-lg border">
              <table className="w-full min-w-[720px] text-sm">
                <thead>
                  <tr className="text-muted border-subtle border-b text-left text-xs uppercase tracking-wide">
                    <th className="px-4 py-2 font-medium">Time (UTC)</th>
                    <th className="px-4 py-2 font-medium">Seq</th>
                    <th className="px-4 py-2 font-medium">Temp °C</th>
                    <th className="px-4 py-2 font-medium">Humidity %</th>
                    <th className="px-4 py-2 font-medium">MQ-2</th>
                    <th className="px-4 py-2 font-medium">RSSI / SNR</th>
                    <th className="px-4 py-2 font-medium">Flags</th>
                  </tr>
                </thead>
                <tbody>
                  {lastN.map((r) => (
                    <tr key={r.id} className="border-subtle hover:bg-raised border-b last:border-b-0">
                      <td className="tabular px-4 py-2">{fmtDateTime(r.gateway_time)}</td>
                      <td className="tabular px-4 py-2">{r.packet_seq}</td>
                      <td className="tabular px-4 py-2">{r.temp_valid ? fmtNum(r.temperature_c, 2) : <Invalid />}</td>
                      <td className="tabular px-4 py-2">{r.hum_valid ? fmtNum(r.humidity_pct, 2) : <Invalid />}</td>
                      <td className="tabular px-4 py-2">{r.mq2_valid ? fmtNum(r.mq2_raw, 0) : <Invalid />}</td>
                      <td className="tabular px-4 py-2 text-xs">
                        {fmtRssi(r.rssi)} / {fmtNum(r.snr, 1, " dB")}
                      </td>
                      <td className="text-xs">
                        {r.simulated && <Flag label="SIM" tone="muted" />}
                        {r.gas_alarm && <Flag label="GAS" tone="crit" />}
                        {r.water_detected && <Flag label="WATER" tone="warn" />}
                      </td>
                    </tr>
                  ))}
                </tbody>
              </table>
            </div>
          </div>
        </>
      )}
    </PageShell>
  );
}

function Invalid() {
  return <span className="text-muted" title="Sensor flag invalid in packet">invalid</span>;
}

function Flag({ label, tone }: { label: string; tone: "crit" | "warn" | "muted" }) {
  const color = tone === "crit" ? "var(--crit)" : tone === "warn" ? "var(--warn)" : "var(--offline)";
  return (
    <span
      className="tabular mr-1 rounded px-1.5 py-0.5 text-[10px] font-semibold uppercase"
      style={{ color, background: "rgba(255,255,255,0.03)" }}
    >
      {label}
    </span>
  );
}
