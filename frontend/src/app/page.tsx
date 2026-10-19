"use client";

import Link from "next/link";
import { useApi } from "@/hooks";
import { api } from "@/lib/api";
import { KpiCard, SectionTitle, SeverityBadge, StatusDot } from "@/components/ui";
import { EmptyState, ErrorState, SkeletonCards, SkeletonTable } from "@/components/states";
import { fmtNum, fmtRssi, fmtRelative } from "@/lib/format";
import { TelemetryLineChart, Mq2AreaChart } from "@/components/charts";

import type { Telemetry } from "@/lib/types";

export default function OverviewPage() {
  const devices = useApi(() => api.listDevices(), [], 15000);
  const openAlerts = useApi(() => api.listAlerts({ status: "open", limit: 50 }), [], 15000);
  const latest = useApi(() => api.latest(undefined, 50), [], 15000);
  const devItems = devices.data?.items ?? [];

  // Latest reading per device, oldest first builds the overview strip
  const lastPerDevice = new Map<number, Telemetry>();
  for (const r of latest.data ?? []) if (!lastPerDevice.has(r.device_id)) lastPerDevice.set(r.device_id, r);

  const onlineCount = devItems.filter((d) => d.status === "online").length;
  const openCount = openAlerts.data?.total ?? 0;
  const critCount = (openAlerts.data?.items ?? []).filter((a) => a.severity === "critical").length;
  const values = [...lastPerDevice.values()];
  const maxTemp = values.length ? Math.max(...values.map((v) => v.temperature_c ?? -Infinity)) : null;
  const avgHum = values.length
    ? values.reduce((acc, v) => acc + (v.humidity_pct ?? 0), 0) / values.filter((v) => v.humidity_pct !== null).length
    : null;
  const maxMq2 = values.length ? Math.max(...values.map((v) => v.mq2_raw ?? -Infinity)) : null;

  return (
    <div className="mx-auto max-w-6xl px-4 py-6">
      <div className="mb-4 flex items-center justify-between">
        <h1 className="text-xl font-semibold tracking-tight">Overview</h1>
      </div>

      {devices.loading ? (
        <SkeletonCards />
      ) : devices.error ? (
        <ErrorState error={devices.error} onRetry={devices.refetch} />
      ) : (
        <>
          <div className="grid grid-cols-1 gap-3 sm:grid-cols-2 lg:grid-cols-4">
            <KpiCard
              label="Devices online"
              value={`${onlineCount}/${devItems.length}`}
              detail={`${devItems.filter((d) => d.is_active).length} active in fleet`}
              tone={onlineCount === devItems.length ? "ok" : "warn"}
            />
            <KpiCard
              label="Open alerts"
              value={openCount}
              detail={`${critCount} critical`}
              tone={critCount > 0 ? "crit" : openCount > 0 ? "warn" : "ok"}
            />
            <KpiCard
              label="Max temperature"
              value={maxTemp === null ? "—" : fmtNum(maxTemp, 1, " °C")}
              detail="latest per device"
              tone={maxTemp !== null && maxTemp > 35 ? "crit" : "plain"}
            />
            <KpiCard
              label="Top MQ-2 counts"
              value={maxMq2 === null ? "—" : fmtNum(maxMq2, 0)}
              detail={avgHum === null ? "—" : `avg humidity ${fmtNum(avgHum, 0, " %" )}`}
              tone={maxMq2 !== null && maxMq2 > 800 ? "crit" : "plain"}
            />
          </div>

          <div className="mt-8 grid grid-cols-1 gap-8 lg:grid-cols-2">
            <section aria-labelledby="h-recent">
              <SectionTitle>Recent readings</SectionTitle>
              <div className="border-subtle bg-surface overflow-hidden rounded-lg border">
                {devItems.length === 0 ? (
                  <div className="p-4">
                    <EmptyState title="No devices registered" detail="Register a device on the Devices page to start receiving telemetry." />
                  </div>
                ) : (
                  <table className="w-full text-sm">
                    <thead>
                      <tr className="text-muted border-subtle border-b text-left text-xs uppercase tracking-wide">
                        <th className="px-4 py-2 font-medium">Device</th>
                        <th className="px-4 py-2 font-medium">Temp</th>
                        <th className="px-4 py-2 font-medium">Humidity</th>
                        <th className="px-4 py-2 font-medium">RSSI</th>
                        <th className="px-4 py-2 font-medium">Last seen</th>
                      </tr>
                    </thead>
                    <tbody>
                      {devItems.map((d) => {
                        const r = lastPerDevice.get(d.device_id);
                        return (
                          <tr key={d.device_id} className="border-subtle hover:bg-raised border-b last:border-b-0">
                            <td className="px-4 py-2.5">
                              <Link href={`/devices/${d.device_id}`} className="text-[color:var(--accent)] tabular font-medium">
                                {d.device_id}
                              </Link>
                              <span className="text-muted ml-2 text-xs">{d.name}</span>
                            </td>
                            <td className="tabular px-4 py-2.5">{r ? fmtNum(r.temperature_c, 1, "°") : "—"}</td>
                            <td className="tabular px-4 py-2.5">{r ? fmtNum(r.humidity_pct, 0, "%") : "—"}</td>
                            <td className="tabular px-4 py-2.5">{r ? fmtRssi(r.rssi) : "—"}</td>
                            <td className="text-muted px-4 py-2.5 text-xs">{fmtRelative(d.last_seen_at)}</td>
                          </tr>
                        );
                      })}
                    </tbody>
                  </table>
                )}
              </div>
            </section>

            <section aria-labelledby="h-alerts">
              <SectionTitle>Open alerts</SectionTitle>
              {openAlerts.loading ? (
                <SkeletonTable rows={3} />
              ) : openAlerts.error ? (
                <ErrorState error={openAlerts.error} onRetry={openAlerts.refetch} />
              ) : (openAlerts.data?.items.length ?? 0) === 0 ? (
                <EmptyState title="No open alerts" detail="The fleet is healthy. Rules still run in the background." />
              ) : (
                <ul className="border-subtle bg-surface divide-y divide-[color:var(--border-subtle)] rounded-lg border">
                  {openAlerts.data!.items.slice(0, 6).map((a) => (
                    <li key={a.id} className="flex items-start gap-3 px-4 py-3">
                      <div className="pt-0.5">
                        <SeverityBadge severity={a.severity} />
                      </div>
                      <div className="min-w-0 flex-1">
                        <div className="flex items-baseline gap-2 text-sm">
                          <span className="tabular font-semibold">{a.rule_key}</span>
                          <span className="text-muted tabular text-xs">device {a.device_id}</span>
                        </div>
                        <p className="text-muted mt-1 line-clamp-2 text-xs">{a.description}</p>
                      </div>
                      <span className="text-muted shrink-0 text-xs">{fmtRelative(a.created_at)}</span>
                    </li>
                  ))}
                </ul>
              )}
              <Link href="/alerts" className="text-muted hover:text-fg mt-3 inline-block text-xs underline underline-offset-4">
                All alerts →
              </Link>
            </section>
          </div>

          <section aria-label="Fleet charts" className="mt-8">
            <SectionTitle>Telemetry trend (24 h window of latest data)</SectionTitle>
            {latest.loading ? (
              <SkeletonCards count={1} />
            ) : latest.error ? (
              <ErrorState error={latest.error} onRetry={latest.refetch} />
            ) : (latest.data?.length ?? 0) === 0 ? (
              <EmptyState title="No telemetry yet" detail="Charts will appear once packets arrive from the gateway." />
            ) : (
              <div className="border-subtle bg-surface rounded-lg border p-4">
                <div className="mb-2 flex items-center justify-between text-xs">
                  <span className="text-muted">{onlineCount} device(s) online — showing latest readings</span>
                  <StatusDot status={onlineCount === devItems.length ? "online" : "offline"} />
                </div>
                <TelemetryLineChart readings={latest.data!} height={280} />
                <div className="mt-4">
                  <Mq2AreaChart readings={latest.data!} height={180} />
                </div>
              </div>
            )}
          </section>
        </>
      )}
    </div>
  );
}
