"use client";

import { useCallback, useMemo, useRef, useState } from "react";
import Link from "next/link";
import { useWebSocket } from "@/hooks";
import { PageShell } from "@/components/nav";
import { EmptyState, ErrorState } from "@/components/states";
import { btnClass } from "@/components/ui";
import { fmtNum, fmtRssi, fmtTime } from "@/lib/format";
import type { Alert, Telemetry } from "@/lib/types";
import { SeverityBadge } from "@/components/ui";

const MAX_ROWS = 200;

interface EventRow {
  key: string;
  kind: "telemetry" | "alert" | "alert_closed" | "device_status";
  at: string;
  data: Telemetry | Alert | Record<string, unknown>;
}

const wsStatusLabel: Record<string, { label: string; color: string }> = {
  idle: { label: "Idle", color: "var(--offline)" },
  connecting: { label: "Connecting…", color: "var(--warn)" },
  open: { label: "Connected", color: "var(--ok)" },
  closed: { label: "Disconnected", color: "var(--offline)" },
  error: { label: "Reconnecting…", color: "var(--warn)" },
  unauthorized: { label: "Session expired", color: "var(--crit)" },
};

export default function LivePage() {
  const [paused, setPaused] = useState(false);
  const pausedRef = useRef(paused);
  pausedRef.current = paused;
  const [rows, setRows] = useState<EventRow[]>([]);
  const [seen, setSeen] = useState(0);

  const onEvent = useCallback((type: string, data: Record<string, unknown>) => {
    if (type !== "telemetry" && type !== "alert" && type !== "alert_closed" && type !== "device_status") return;
    if (pausedRef.current) return;
    setSeen((s) => s + 1);
    setRows((prev) =>
      [
        {
          key: `${type}-${Date.now()}-${Math.random().toString(36).slice(2, 8)}`,
          kind: type as EventRow["kind"],
          at: new Date().toISOString(),
          data,
        },
        ...prev,
      ].slice(0, MAX_ROWS),
    );
  }, []);

  const { status, reconnect } = useWebSocket(onEvent, true);
  const meta = wsStatusLabel[status] ?? wsStatusLabel.idle;

  const latestByDevice = useMemo(() => {
    const m = new Map<number, Telemetry>();
    for (const r of rows) if (r.kind === "telemetry") {
      const t = r.data as Telemetry;
      if (!m.has(t.device_id)) m.set(t.device_id, t);
    }
    return m;
  }, [rows]);

  return (
    <PageShell
      title="Live feed"
      actions={
        <div className="flex items-center gap-3">
          <span className="inline-flex items-center gap-1.5 text-xs" role="status">
            <span
              aria-hidden
              className="size-2 rounded-full"
              style={{ background: meta.color, boxShadow: status === "open" ? `0 0 6px ${meta.color}` : undefined }}
            />
            {meta.label}
          </span>
          <button onClick={() => setPaused((p) => !p)} aria-pressed={paused} className={btnClass}>
            {paused ? "Resume" : "Pause"}
          </button>
          {status === "error" && (
            <button onClick={reconnect} className={btnClass}>
              Reconnect
            </button>
          )}
        </div>
      }
    >
      {status === "unauthorized" && (
        <div role="alert" className="bg-surface rounded-lg border border-[color:var(--crit)] px-6 py-6">
          <p className="font-medium text-[color:var(--crit)]">Session expired</p>
          <p className="text-muted mt-1 text-sm">
            Your real-time session token has expired or is missing. Sign in again to reconnect the live feed.
          </p>
          <Link href="/login" className="mt-3 inline-block text-sm underline underline-offset-4">
            Go to sign in →
          </Link>
        </div>
      )}

      <div className="border-subtle bg-surface mb-6 grid grid-cols-1 gap-3 rounded-lg border p-4 sm:grid-cols-3">
        {[...latestByDevice.values()].map((t) => (
          <div key={t.device_id} className="border-subtle bg-bg rounded border p-3">
            <div className="flex items-center justify-between">
              <Link href={`/devices/${t.device_id}`} className="tabular font-semibold text-[color:var(--accent)]">
                node {t.device_id}
              </Link>
              <span className="text-muted text-xs">{fmtTime(t.gateway_time)}</span>
            </div>
            <div className="tabular mt-2 flex gap-4 text-lg font-semibold">
              <span className="text-[color:var(--warn)]">{fmtNum(t.temp_valid ? t.temperature_c : null, 1, "°C")}</span>
              <span className="text-[color:var(--ok)]">{fmtNum(t.hum_valid ? t.humidity_pct : null, 0, "%")}</span>
            </div>
            <div className="text-muted tabular mt-1 text-xs">
              MQ-2 {fmtNum(t.mq2_raw, 0)} · RSSI {fmtRssi(t.rssi)} · SNR {fmtNum(t.snr, 1, " dB")}
              {t.simulated && <span className="ml-2 uppercase">simulated</span>}
            </div>
          </div>
        ))}
        {rows.length === 0 && <EmptyState title="Waiting for packets…" detail="Events will appear the moment the gateway forwards telemetry." />}
      </div>

      <div className="text-muted mb-2 flex items-center justify-between text-xs">
        <span aria-live="polite">
          {rows.length} event{rows.length === 1 ? "" : "s"} buffered (max {MAX_ROWS}) · {seen} received{paused ? " · paused" : ""}
        </span>
      </div>
      <ul className="border-subtle bg-surface divide-y divide-[color:var(--border-subtle)] overflow-hidden rounded-lg border font-mono text-xs" aria-label="Live event stream">
        {rows.map((r) => (
          <li key={r.key} className="flex items-baseline gap-3 px-4 py-2">
            <span className="text-muted shrink-0">{fmtTime(r.at)}</span>
            {r.kind === "telemetry" ? (
              (() => {
                const t = r.data as Telemetry;
                return (
                  <>
                    <span className="shrink-0 text-[color:var(--accent)] uppercase">telemetry</span>
                    <span className="tabular">
                      dev {t.device_id} · seq {t.packet_seq} · T {fmtNum(t.temp_valid ? t.temperature_c : null, 1)}°C · H{" "}
                      {fmtNum(t.hum_valid ? t.humidity_pct : null, 0)}% · MQ2 {fmtNum(t.mq2_raw, 0)} · RSSI {fmtRssi(t.rssi)}
                    </span>
                    {t.water_detected && <span className="text-[color:var(--warn)] uppercase">water</span>}
                    {t.gas_alarm && <span className="text-[color:var(--crit)] uppercase">gas alarm</span>}
                  </>
                );
              })()
            ) : r.kind === "alert" ? (
              (() => {
                const a = r.data as Alert;
                return (
                  <>
                    <span className="shrink-0 text-[color:var(--crit)] uppercase">alert</span>
                    <span className="inline-block pr-1">
                      <SeverityBadge severity={a.severity} />
                    </span>
                    <span>
                      dev {a.device_id} · {a.rule_key} — {a.description}
                    </span>
                  </>
                );
              })()
            ) : r.kind === "alert_closed" ? (
              (() => {
                const a = r.data as Alert;
                return (
                  <>
                    <span className="shrink-0 text-[color:var(--ok)] uppercase">cleared</span>
                    <span>dev {a.device_id} · {a.rule_key} alert closed</span>
                  </>
                );
              })()
            ) : (
              (() => {
                const d = r.data as { device_id: number; status: string };
                return (
                  <>
                    <span className="shrink-0 text-muted uppercase">device</span>
                    <span>dev {d.device_id} → {d.status}</span>
                  </>
                );
              })()
            )}
          </li>
        ))}
      </ul>
    </PageShell>
  );
}

