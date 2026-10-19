"use client";

import { use, useState } from "react";
import Link from "next/link";
import { useApi } from "@/hooks";
import { api } from "@/lib/api";
import { PageShell } from "@/components/nav";
import { EmptyState, ErrorState, SkeletonTable } from "@/components/states";
import { SectionTitle, SeverityBadge, StatusDot, btnClass } from "@/components/ui";
import { TelemetryLineChart, Mq2AreaChart } from "@/components/charts";
import { fmtDateTime, fmtNum, fmtRssi, fmtRelative } from "@/lib/format";

export default function DeviceDetailPage({ params }: { params: Promise<{ id: string }> }) {
  const { id } = use(params);
  const deviceId = Number(id);
  const [rangeIdx, setRangeIdx] = useState(1);
  const RANGES = [1, 6, 24, 168];

  const detail = useApi(() => api.getDevice(deviceId), [deviceId], 15000);
  const history = useApi(
    () =>
      api.history({
        deviceId,
        start: new Date(Date.now() - RANGES[rangeIdx] * 3600_000),
        end: new Date(),
      }),
    [deviceId, rangeIdx],
    30000,
  );
  const alerts = useApi(() => api.listAlerts({ deviceId, limit: 10 }), [deviceId], 15000);

  const d = detail.data;

  return (
    <PageShell
      title={`Node ${deviceId}`}
      actions={
        <Link href="/devices" className={btnClass}>
          ← All devices
        </Link>
      }
    >
      {detail.loading ? (
        <SkeletonTable rows={3} />
      ) : detail.error ? (
        <ErrorState error={detail.error} onRetry={detail.refetch} />
      ) : !d ? null : (
        <>
          <div className="border-subtle bg-surface mb-6 grid grid-cols-2 gap-x-6 gap-y-3 rounded-lg border p-4 text-sm sm:grid-cols-4">
            <Info label="Name" value={d.name} />
            <Info label="Type" value={d.device_type} />
            <Info label="Location" value={d.location ?? "—"} />
            <Info label="Registered" value={fmtDateTime(d.registered_at)} />
            <Info label="Status" value={<StatusDot status={d.is_active ? d.status : "offline inactive"} label={d.is_active ? d.status : "inactive"} />} />
            <Info label="Last seen" value={fmtRelative(d.last_seen_at)} />
            <Info label="Last seq" value={d.last_seq ?? "—"} />
            <Info label="Last RSSI / SNR" value={d.last_rssi !== null ? `${fmtRssi(d.last_rssi)} / ${fmtNum(d.last_snr, 1, " dB")}` : "—"} />
          </div>

          {d.latest_reading && (
            <div className="border-subtle bg-surface mb-6 grid grid-cols-2 gap-3 rounded-lg border p-4 sm:grid-cols-6">
              <Metric label="Temperature" value={fmtNum(d.latest_reading.temp_valid ? d.latest_reading.temperature_c : null, 1, "°C")} />
              <Metric label="Humidity" value={fmtNum(d.latest_reading.hum_valid ? d.latest_reading.humidity_pct : null, 1, "%")} />
              <Metric label="MQ-2 counts" value={fmtNum(d.latest_reading.mq2_valid ? d.latest_reading.mq2_raw : null, 0)} />
              <Metric label="Water" value={d.latest_reading.water_detected ? <span className="text-[color:var(--warn)]">DETECTED</span> : "clear"} />
              <Metric label="Battery" value={fmtNum(d.latest_reading.battery_valid ? d.latest_reading.battery_mv : null, 0, " mV")} />
              <Metric label="Simulated" value={d.latest_reading.simulated ? "yes" : "no"} />
            </div>
          )}

          <div className="mb-4 flex gap-2" role="group" aria-label="History range">
            {["1 h", "6 h", "24 h", "7 d"].map((label, i) => (
              <button
                key={label}
                onClick={() => setRangeIdx(i)}
                aria-pressed={rangeIdx === i}
                className={rangeIdx === i ? `${btnClass} bg-raised` : btnClass}
              >
                {label}
              </button>
            ))}
          </div>

          {history.loading ? (
            <SkeletonTable rows={2} />
          ) : history.error ? (
            <ErrorState error={history.error} onRetry={history.refetch} />
          ) : (history.data?.length ?? 0) === 0 ? (
            <EmptyState title="No readings in this window" />
          ) : (
            <div className="border-subtle bg-surface rounded-lg border p-4">
              <TelemetryLineChart readings={[...(history.data ?? [])].sort((a, b) => (a.gateway_time < b.gateway_time ? -1 : 1))} height={280} />
              <div className="mt-4">
                <Mq2AreaChart readings={[...(history.data ?? [])].sort((a, b) => (a.gateway_time < b.gateway_time ? -1 : 1))} height={180} />
              </div>
            </div>
          )}

          <div className="mt-8">
            <SectionTitle>Recent alerts</SectionTitle>
            {alerts.loading ? (
              <SkeletonTable rows={2} />
            ) : alerts.error ? (
              <ErrorState error={alerts.error} onRetry={alerts.refetch} />
            ) : (alerts.data?.items.length ?? 0) === 0 ? (
              <EmptyState title="No alerts for this device" />
            ) : (
              <ul className="border-subtle bg-surface divide-y divide-[color:var(--border-subtle)] rounded-lg border">
                {alerts.data!.items.map((a) => (
                  <li key={a.id} className="flex items-start gap-3 px-4 py-3">
                    <div className="pt-0.5">
                      <SeverityBadge severity={a.severity} />
                    </div>
                    <div className="min-w-0 flex-1">
                      <div className="text-sm">
                        <span className="tabular font-semibold">{a.rule_key}</span>{" "}
                        <span className="text-muted text-xs capitalize">· {a.status}</span>
                      </div>
                      <p className="text-muted mt-0.5 text-xs">{a.description}</p>
                    </div>
                    <span className="text-muted shrink-0 text-xs">{fmtRelative(a.created_at)}</span>
                  </li>
                ))}
              </ul>
            )}
          </div>
        </>
      )}
    </PageShell>
  );
}

function Info({ label, value }: { label: string; value: React.ReactNode }) {
  return (
    <div>
      <div className="text-muted text-xs font-medium uppercase tracking-wide">{label}</div>
      <div className="tabular mt-1">{value}</div>
    </div>
  );
}

function Metric({ label, value }: { label: string; value: React.ReactNode }) {
  return (
    <div className="border-subtle bg-bg rounded border p-3">
      <div className="text-muted text-xs font-medium uppercase tracking-wide">{label}</div>
      <div className="tabular mt-1 text-lg font-semibold">{value}</div>
    </div>
  );
}
