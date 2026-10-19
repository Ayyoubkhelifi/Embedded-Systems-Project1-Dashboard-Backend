"use client";

import type { ReactNode } from "react";
import type { Severity } from "@/lib/types";

export function StatusDot({ status, label }: { status: "online" | "offline" | string; label?: string }) {
  const color = status === "online" ? "var(--ok)" : "var(--offline)";
  return (
    <span className="inline-flex items-center gap-1.5">
      <span
        aria-hidden
        className="inline-block size-2 rounded-full"
        style={{ background: color, boxShadow: status === "online" ? `0 0 6px ${color}` : undefined }}
      />
      <span className="text-sm capitalize">{label ?? status}</span>
      <span className="sr-only">{`Device is ${status}`}</span>
    </span>
  );
}

const severityTone: Record<Severity, { bg: string; fg: string; label: string }> = {
  info: { bg: "rgba(139,148,163,0.15)", fg: "#8b94a3", label: "info" },
  warning: { bg: "rgba(251,191,36,0.14)", fg: "var(--warn)", label: "warning" },
  critical: { bg: "rgba(248,113,113,0.14)", fg: "var(--crit)", label: "critical" },
};

export function SeverityBadge({ severity }: { severity: Severity }) {
  const tone = severityTone[severity] ?? severityTone.info;
  return (
    <span
      className="rounded px-2 py-0.5 text-xs font-medium uppercase tracking-wide"
      style={{ background: tone.bg, color: tone.fg }}
    >
      {tone.label}
    </span>
  );
}

const statusTone: Record<string, string> = {
  open: "var(--crit)",
  acknowledged: "var(--warn)",
  closed: "var(--offline)",
};

export function AlertStatusBadge({ status }: { status: string }) {
  return (
    <span className="text-muted text-xs capitalize" style={{ color: statusTone[status] }}>
      {status}
    </span>
  );
}

export function KpiCard({
  label,
  value,
  detail,
  tone,
}: {
  label: string;
  value: ReactNode;
  detail?: ReactNode;
  tone?: "ok" | "warn" | "crit" | "plain";
}) {
  const valueColor =
    tone === "ok" ? "var(--ok)" : tone === "warn" ? "var(--warn)" : tone === "crit" ? "var(--crit)" : "var(--text-primary)";
  return (
    <div className="border-subtle bg-surface rounded-lg border p-4">
      <div className="text-muted text-xs font-medium uppercase tracking-wider">{label}</div>
      <div className="tabular mt-2 text-2xl font-semibold" style={{ color: valueColor }}>
        {value}
      </div>
      {detail && <div className="text-muted mt-1 text-xs">{detail}</div>}
    </div>
  );
}

export function SectionTitle({ children }: { children: ReactNode }) {
  return (
    <h2 className="text-muted border-subtle mb-3 border-b pb-2 text-xs font-semibold uppercase tracking-wider">
      {children}
    </h2>
  );
}

export function Field({ label, children }: { label: string; children: ReactNode }) {
  return (
    <label className="block">
      <span className="text-muted mb-1 block text-xs font-medium uppercase tracking-wide">{label}</span>
      {children}
    </label>
  );
}

export const inputClass =
  "border-subtle bg-raised w-full rounded border px-2.5 py-1.5 text-sm focus:border-[color:var(--accent)]";

export const btnClass = "border-subtle hover:bg-raised rounded border px-3 py-1.5 text-sm transition-colors";
