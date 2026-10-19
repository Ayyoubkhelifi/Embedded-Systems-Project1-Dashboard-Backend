"use client";

import { FormEvent, useState } from "react";
import Link from "next/link";
import { useApi } from "@/hooks";
import { useAuth } from "@/auth";
import { api } from "@/lib/api";
import { PageShell } from "@/components/nav";
import { EmptyState, ErrorState, SkeletonTable } from "@/components/states";
import { StatusDot, Field, inputClass, btnClass } from "@/components/ui";
import { fmtNum, fmtRssi, fmtRelative, fmtDateTime } from "@/lib/format";
import type { DeviceDetail } from "@/lib/types";

export default function DevicesPage() {
  const { can } = useAuth();
  const canManage = can("operator");
  const devices = useApi(() => api.listDevices(), [], 10000);
  const items = devices.data?.items ?? [];

  const [formOpen, setFormOpen] = useState(false);
  const [error, setError] = useState<string | null>(null);
  const [busy, setBusy] = useState(false);
  const [statusFilter, setStatusFilter] = useState<"all" | "online" | "offline">("all");

  const filtered = items.filter((d) => statusFilter === "all" || d.status === statusFilter);

  async function onCreate(e: FormEvent<HTMLFormElement>) {
    e.preventDefault();
    const fd = new FormData(e.currentTarget);
    const body = {
      device_id: Number(fd.get("device_id")),
      name: String(fd.get("name")).trim(),
      location: String(fd.get("location") ?? "").trim() || undefined,
    };
    setBusy(true);
    setError(null);
    try {
      await api.createDevice(body);
      setFormOpen(false);
      await devices.refetch();
    } catch (err) {
      const ae = err as { code?: string; message?: string };
      setError(ae.code === "DEVICE_ID_TAKEN" ? "That LoRa device ID is already registered." : (ae.message ?? "Failed."));
    } finally {
      setBusy(false);
    }
  }

  async function toggleActive(d: DeviceDetail) {
    await api.updateDevice(d.device_id, { is_active: !d.is_active });
    await devices.refetch();
  }

  async function onRemove(d: DeviceDetail) {
    if (!confirm(`Deactivate node ${d.device_id} (${d.name})? Telemetry from it will be rejected.`)) return;
    await api.deleteDevice(d.device_id);
    await devices.refetch();
  }

  return (
    <PageShell
      title="Devices"
      actions={
        canManage && (
          <button className={btnClass} onClick={() => setFormOpen((f) => !f)} aria-expanded={formOpen}>
            {formOpen ? "Cancel" : "Register device"}
          </button>
        )
      }
    >
      {canManage && formOpen && (
        <form onSubmit={onCreate} className="border-subtle bg-surface mb-6 grid grid-cols-1 gap-3 rounded-lg border p-4 sm:grid-cols-4">
          <Field label="LoRa device ID">
            <input className={inputClass} name="device_id" type="number" min={1} max={4294967295} required aria-label="Device ID" />
          </Field>
          <Field label="Name">
            <input className={inputClass} name="name" required minLength={1} maxLength={128} aria-label="Device name" />
          </Field>
          <Field label="Location (optional)">
            <input className={inputClass} name="location" maxLength={255} aria-label="Location" />
          </Field>
          <div className="flex items-end">
            <button type="submit" disabled={busy} className="w-full rounded bg-[color:var(--accent)] px-3 py-2 text-sm font-semibold text-black disabled:opacity-60">
              {busy ? "Registering…" : "Register"}
            </button>
          </div>
          {error && (
            <p role="alert" className="text-sm text-[color:var(--crit)] sm:col-span-4">
              {error}
            </p>
          )}
        </form>
      )}

      <div className="mb-3 flex gap-2" role="group" aria-label="Filter by status">
        {(["all", "online", "offline"] as const).map((s) => (
          <button
            key={s}
            onClick={() => setStatusFilter(s)}
            aria-pressed={statusFilter === s}
            className={statusFilter === s ? `${btnClass} bg-raised` : btnClass}
          >
            {s}
          </button>
        ))}
      </div>

      {devices.loading ? (
        <SkeletonTable rows={4} />
      ) : devices.error ? (
        <ErrorState error={devices.error} onRetry={devices.refetch} />
      ) : filtered.length === 0 ? (
        <EmptyState
          title={statusFilter === "all" ? "No devices registered" : `No ${statusFilter} devices`}
          detail={statusFilter === "all" ? "Register the first ESP32 node to start collecting telemetry." : undefined}
        />
      ) : (
        <div className="border-subtle bg-surface overflow-x-auto rounded-lg border">
          <table className="w-full min-w-[760px] text-sm">
            <thead>
              <tr className="text-muted border-subtle border-b text-left text-xs uppercase tracking-wide">
                <th className="px-4 py-2.5 font-medium">Device</th>
                <th className="px-4 py-2.5 font-medium">Status</th>
                <th className="px-4 py-2.5 font-medium">Last reading</th>
                <th className="px-4 py-2.5 font-medium">Last seen</th>
                <th className="px-4 py-2.5 font-medium">Seq</th>
                <th className="px-4 py-2.5 font-medium">RSSI / SNR</th>
                {canManage && <th className="px-4 py-2.5 font-medium">Actions</th>}
              </tr>
            </thead>
            <tbody>
              {filtered.map((d) => {
                const r = d.latest_reading;
                return (
                  <tr key={d.device_id} className="border-subtle hover:bg-raised border-b last:border-b-0">
                    <td className="px-4 py-3">
                      <Link href={`/devices/${d.device_id}`} className={d.is_active ? "text-[color:var(--accent)] tabular font-semibold" : "text-muted tabular line-through"}>
                        {d.device_id}
                      </Link>
                      <div className="text-muted text-xs">
                        {d.name}
                        {d.location && <span className="px-1">· {d.location}</span>}
                      </div>
                    </td>
                    <td className="px-4 py-3">
                      <StatusDot status={d.is_active ? d.status : "offline inactive"} label={d.is_active ? d.status : "inactive"} />
                    </td>
                    <td className="tabular px-4 py-3 text-xs">
                      {r ? (
                        <>
                          {fmtNum(r.temp_valid ? r.temperature_c : null, 1, "°C")} ·{" "}
                          {fmtNum(r.hum_valid ? r.humidity_pct : null, 0, "%")} ·{" "}
                          {fmtNum(r.mq2_valid ? r.mq2_raw : null, 0)} MQ2
                          {r.temp_valid === false && <span className="text-muted ml-1">(invalid)</span>}
                        </>
                      ) : (
                        <span className="text-muted">no data</span>
                      )}
                    </td>
                    <td className="text-muted px-4 py-3 text-xs" title={d.last_seen_at ? fmtDateTime(d.last_seen_at) : undefined}>
                      {fmtRelative(d.last_seen_at)}
                    </td>
                    <td className="tabular px-4 py-3 text-xs">{d.last_seq ?? "—"}</td>
                    <td className="tabular px-4 py-3 text-xs">
                      {d.last_rssi !== null ? `${fmtRssi(d.last_rssi)} / ${fmtNum(d.last_snr, 1, " dB")}` : "—"}
                    </td>
                    {canManage && (
                      <td className="px-4 py-3">
                        <div className="flex gap-2 text-xs">
                          <button onClick={() => void toggleActive(d)} className="border-subtle rounded border px-2 py-1">
                            {d.is_active ? "Deactivate" : "Activate"}
                          </button>
                          <button onClick={() => void onRemove(d)} className="border-subtle rounded border px-2 py-1 hover:text-[color:var(--crit)]">
                            Retire
                          </button>
                        </div>
                      </td>
                    )}
                  </tr>
                );
              })}
            </tbody>
          </table>
        </div>
      )}
    </PageShell>
  );
}
