"use client";

import { useState } from "react";
import { useApi } from "@/hooks";
import { useAuth } from "@/auth";
import { api } from "@/lib/api";
import { PageShell } from "@/components/nav";
import { EmptyState, ErrorState, SkeletonTable } from "@/components/states";
import { AlertStatusBadge, SeverityBadge, btnClass } from "@/components/ui";
import { fmtDateTime } from "@/lib/format";

const TABS = ["open", "acknowledged", "closed", "all"] as const;

export default function AlertsPage() {
  const { can } = useAuth();
  const canAck = can("operator");
  const [tab, setTab] = useState<(typeof TABS)[number]>("open");
  const [deviceFilter, setDeviceFilter] = useState("");
  const [busyId, setBusyId] = useState<number | null>(null);

  const devices = useApi(() => api.listDevices(), []);

  const parsedDevice = deviceFilter.trim() === "" ? undefined : Number(deviceFilter.trim());
  const validDevice = parsedDevice !== undefined && Number.isFinite(parsedDevice) ? parsedDevice : undefined;

  const alerts = useApi(
    () =>
      api.listAlerts({
        status: tab,
        deviceId: validDevice,
        limit: 100,
      }),
    [tab, validDevice],
    10000,
  );

  async function onAck(id: number) {
    setBusyId(id);
    try {
      await api.acknowledgeAlert(id);
      await alerts.refetch();
    } catch (e) {
      const ae = e as { code?: string };
      if (ae.code === "ALERT_ALREADY_CLOSED") await alerts.refetch();
    } finally {
      setBusyId(null);
    }
  }

  const items = alerts.data?.items ?? [];

  return (
    <PageShell title="Alerts">
      <div className="mb-4 flex flex-wrap items-center justify-between gap-3">
        <div className="flex gap-2" role="tablist" aria-label="Alert status filter">
          {TABS.map((t) => (
            <button
              key={t}
              role="tab"
              aria-selected={tab === t}
              onClick={() => setTab(t)}
              className={tab === t ? `${btnClass} bg-raised` : btnClass}
            >
              {t}
            </button>
          ))}
        </div>
        <div className="flex items-center gap-2">
          <label htmlFor="device-filter" className="text-muted text-xs uppercase tracking-wide">
            Device
          </label>
          <select
            id="device-filter"
            className={`${btnClass} bg-raised`}
            value={deviceFilter}
            onChange={(e) => setDeviceFilter(e.target.value)}
          >
            <option value="">All</option>
            {(devices.data?.items ?? []).map((d) => (
              <option key={d.device_id} value={d.device_id}>
                {d.device_id} — {d.name}
              </option>
            ))}
          </select>
        </div>
      </div>

      {alerts.loading ? (
        <SkeletonTable rows={5} />
      ) : alerts.error ? (
        <ErrorState error={alerts.error} onRetry={alerts.refetch} />
      ) : items.length === 0 ? (
        <EmptyState
          title={tab === "all" ? "No alerts recorded" : `No ${tab} alerts`}
          detail={tab === "all" ? undefined : "Switch to the All tab to see the full history."}
        />
      ) : (
        <div className="border-subtle bg-surface overflow-x-auto rounded-lg border">
          <table className="w-full min-w-[760px] text-sm">
            <thead>
              <tr className="text-muted border-subtle border-b text-left text-xs uppercase tracking-wide">
                <th className="px-4 py-2.5 font-medium">Severity</th>
                <th className="px-4 py-2.5 font-medium">Rule</th>
                <th className="px-4 py-2.5 font-medium">Description</th>
                <th className="px-4 py-2.5 font-medium">Device</th>
                <th className="px-4 py-2.5 font-medium">Raised</th>
                <th className="px-4 py-2.5 font-medium">Status</th>
                {canAck && <th className="px-4 py-2.5 font-medium">Action</th>}
              </tr>
            </thead>
            <tbody>
              {items.map((a) => (
                <tr key={a.id} className="border-subtle hover:bg-raised border-b last:border-b-0">
                  <td className="px-4 py-3">
                    <SeverityBadge severity={a.severity} />
                  </td>
                  <td className="tabular px-4 py-3 font-medium">{a.rule_key}</td>
                  <td className="text-muted max-w-md px-4 py-3 text-xs">
                    {a.description.replace(/\*\*/g, "")}
                  </td>
                  <td className="tabular px-4 py-3">{a.device_id}</td>
                  <td className="tabular text-muted px-4 py-3 text-xs">{fmtDateTime(a.created_at)}</td>
                  <td className="px-4 py-3">
                    <div className="flex flex-col gap-0.5">
                      <AlertStatusBadge status={a.status} />
                      {(a.acknowledged_at || a.closed_at) && (
                        <span className="text-muted text-[10px]">{a.closed_at ? `closed ${fmtDateTime(a.closed_at)}` : `ack ${fmtDateTime(a.acknowledged_at)}`}</span>
                      )}
                    </div>
                  </td>
                  {canAck && (
                    <td className="px-4 py-3">
                      {a.status === "open" && (
                        <button
                          onClick={() => void onAck(a.id)}
                          disabled={busyId === a.id}
                          className="border-subtle rounded border px-2.5 py-1 text-xs hover:bg-raised disabled:opacity-60"
                        >
                          {busyId === a.id ? "…" : "Acknowledge"}
                        </button>
                      )}
                    </td>
                  )}
                </tr>
              ))}
            </tbody>
          </table>
        </div>
      )}
      <p className="text-muted mt-3 text-xs">
        {items.length} of {alerts.data?.total ?? items.length} alerts shown · both ack and clear events also arrive on the Live feed.
      </p>
    </PageShell>
  );
}
