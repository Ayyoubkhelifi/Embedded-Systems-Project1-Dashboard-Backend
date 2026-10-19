"use client";

import { FormEvent, useEffect, useState } from "react";
import { useApi } from "@/hooks";
import { useAuth } from "@/auth";
import { ApiError, api } from "@/lib/api";
import { PageShell } from "@/components/nav";
import { EmptyState, ErrorState, SkeletonTable } from "@/components/states";
import { Field, SectionTitle, SeverityBadge, btnClass, inputClass } from "@/components/ui";
import { fmtDateTime } from "@/lib/format";
import type { AlertRule, Settings, Severity, User } from "@/lib/types";

const RULE_LABELS: Record<string, string> = {
  temp_high: "Temperature high",
  humidity_high: "Humidity high",
  mq2_threshold: "MQ-2 gas threshold",
  water_detected: "Water detected",
  sensor_malfunction: "Sensor malfunction (over 2 h)",
  device_offline: "Device went offline",
};

const RULE_HINTS: Record<string, string> = {
  temp_high: "°C sustained before raising",
  humidity_high: "% RH sustained before raising",
  mq2_threshold: "raw ADC counts; preliminary indication only — not a certified safety alarm",
  water_detected: "binary rule: raises on any valid water_detected packet",
  sensor_malfunction: "consecutive invalid flags before raising",
  device_offline: "binary rule on the freshness monitor",
};

export default function SettingsPage() {
  const { can, user } = useAuth();
  const isAdmin = can("admin");
  const settings = useApi<Settings>(() => api.getSettings(), [], 30000);
  const [draft, setDraft] = useState<Map<string, AlertRule>>(new Map());
  const [freshness, setFreshness] = useState<number | null>(null);
  const [note, setNote] = useState<{ tone: "ok" | "err"; text: string } | null>(null);
  const [busy, setBusy] = useState(false);

  useEffect(() => {
    if (settings.data) {
      setDraft(new Map(settings.data.alert_rules.map((r) => [r.rule_key, { ...r }])));
      setFreshness(settings.data.device_freshness_timeout_seconds);
    }
  }, [settings.data]);

  function patch(key: string, field: keyof AlertRule, value: number | boolean | Severity) {
    setDraft((prev) => {
      const next = new Map(prev);
      const rule = next.get(key);
      if (rule) next.set(key, { ...rule, [field]: value } as AlertRule);
      return next;
    });
  }

  function patchFresh(v: string) {
    const n = Number(v);
    setFreshness(Number.isFinite(n) ? n : null);
  }

  async function saveRule(e: FormEvent<HTMLFormElement>, ruleKey: string) {
    e.preventDefault();
    const rule = draft.get(ruleKey);
    if (!rule) return;
    setBusy(true);
    setNote(null);
    try {
      await api.patchSettings({ rule_key: ruleKey, threshold: rule.threshold, hysteresis: rule.hysteresis, sustained: rule.sustained, severity: rule.severity, enabled: rule.enabled });
      await settings.refetch();
      setNote({ tone: "ok", text: `Saved rule "${ruleKey}".` });
    } catch (err) {
      setNote({ tone: "err", text: err instanceof ApiError ? err.message : "Failed to save." });
    } finally {
      setBusy(false);
    }
  }

  async function saveFreshness(e: FormEvent<HTMLFormElement>) {
    e.preventDefault();
    if (freshness === null) return;
    setBusy(true);
    setNote(null);
    try {
      await api.patchSettings({ device_freshness_timeout_seconds: freshness });
      await settings.refetch();
      setNote({ tone: "ok", text: "Saved freshness timeout." });
    } catch (err) {
      setNote({ tone: "err", text: err instanceof ApiError ? err.message : "Failed to save." });
    } finally {
      setBusy(false);
    }
  }

  if (!user) return null;
  if (settings.loading) return <PageShell title="Settings"><SkeletonTable rows={6} /></PageShell>;
  if (settings.error) return <PageShell title="Settings"><ErrorState error={settings.error} onRetry={settings.refetch} /></PageShell>;
  if (!settings.data) return <PageShell title="Settings"><EmptyState title="Not available" /></PageShell>;

  return (
    <PageShell title="Settings">
      <p className="text-muted mb-6 text-sm">
        Alert thresholds are evaluated continuously against incoming telemetry. Changes apply immediately to new packets.
      </p>
      {note && (
        <p
          role="status"
          className={`mb-4 rounded border px-3 py-2 text-sm ${note.tone === "ok" ? "border-subtle text-[color:var(--ok)]" : "border-[color:var(--crit)] text-[color:var(--crit)]"}`}
        >
          {note.text}
        </p>
      )}

      <div className="space-y-6">
        {settings.data.alert_rules.map((r) => {
          const d = draft.get(r.rule_key) ?? r;
          const numeric = RULE_HINTS[r.rule_key] ? !RULE_HINTS[r.rule_key].startsWith("binary") : true;
          return (
            <form key={r.rule_key} onSubmit={(e) => isAdmin && saveRule(e, r.rule_key)} className="border-subtle bg-surface rounded-lg border p-4">
              <div className="mb-3 flex flex-wrap items-center justify-between gap-2">
                <div className="flex items-center gap-2">
                  <SeverityBadge severity={d.severity} />
                  <span className="font-medium">{RULE_LABELS[r.rule_key] ?? r.rule_key}</span>
                  <span className="text-muted tabular text-xs">{r.rule_key}</span>
                </div>
                <label className="flex items-center gap-2 text-xs">
                  <input
                    type="checkbox"
                    checked={d.enabled}
                    disabled={!isAdmin}
                    onChange={(e) => patch(r.rule_key, "enabled", e.target.checked)}
                    aria-label={`Rule ${r.rule_key} enabled`}
                  />
                  <span className="text-muted uppercase tracking-wide">enabled</span>
                </label>
              </div>
              {numeric && (
                <div className="grid grid-cols-1 gap-3 sm:grid-cols-3">
                  <Field label={`Threshold — ${RULE_HINTS[r.rule_key] ?? ""}`}>
                    <input
                      className={inputClass}
                      type="number"
                      step="any"
                      disabled={!isAdmin}
                      value={d.threshold}
                      onChange={(e) => patch(r.rule_key, "threshold", Number(e.target.value))}
                      aria-label={`${r.rule_key} threshold`}
                    />
                  </Field>
                  <Field label="Hysteresis (clear margin)">
                    <input
                      className={inputClass}
                      type="number"
                      step="any"
                      min={0}
                      disabled={!isAdmin}
                      value={d.hysteresis}
                      onChange={(e) => patch(r.rule_key, "hysteresis", Number(e.target.value))}
                      aria-label={`${r.rule_key} hysteresis`}
                    />
                  </Field>
                  <Field label="Sustained readings (1–100)">
                    <input
                      className={inputClass}
                      type="number"
                      min={1}
                      max={100}
                      disabled={!isAdmin}
                      value={d.sustained}
                      onChange={(e) => patch(r.rule_key, "sustained", Number(e.target.value))}
                      aria-label={`${r.rule_key} sustained`}
                    />
                  </Field>
                </div>
              )}
              <div className="mt-3 flex flex-wrap items-center gap-3">
                <Field label="Severity">
                  <select
                    className={inputClass}
                    disabled={!isAdmin}
                    value={d.severity}
                    onChange={(e) => patch(r.rule_key, "severity", e.target.value as Severity)}
                    aria-label={`${r.rule_key} severity`}
                  >
                    {(["info", "warning", "critical"] as const).map((s) => (
                      <option key={s} value={s}>
                        {s}
                      </option>
                    ))}
                  </select>
                </Field>
                {isAdmin && (
                  <div className="ml-auto">
                    <button type="submit" disabled={busy} className="rounded bg-[color:var(--accent)] px-3 py-2 text-sm font-semibold text-black disabled:opacity-60">
                      Save rule
                    </button>
                  </div>
                )}
              </div>
            </form>
          );
        })}

        <form onSubmit={(e) => isAdmin && saveFreshness(e)} className="border-subtle bg-surface rounded-lg border p-4">
          <SectionTitle>Device freshness</SectionTitle>
          <div className="flex flex-wrap items-end gap-3">
            <Field label="Seconds without telemetry before a device is marked offline (60–86400)">
              <input
                className={`${inputClass} lg:w-64`}
                type="number"
                min={60}
                max={86400}
                disabled={!isAdmin}
                value={freshness ?? ""}
                onChange={(e) => patchFresh(e.target.value)}
                aria-label="Freshness timeout seconds"
              />
            </Field>
            {isAdmin && (
              <button type="submit" disabled={busy || freshness === null} className="rounded bg-[color:var(--accent)] px-3 py-2 text-sm font-semibold text-black disabled:opacity-60">
                Save freshness
              </button>
            )}
          </div>
          <p className="text-muted mt-2 text-xs">
            The backend monitor checks this window periodically; offline devices raise a device_offline alert which auto-clears when fresh telemetry arrives.
          </p>
        </form>
      </div>
      {!isAdmin && (
        <p className="text-muted mt-6 text-xs">Read-only — sign in with an admin account to change thresholds.</p>
      )}

      {isAdmin && <UsersPanel currentUserId={user.id} />}
    </PageShell>
  );
}

function UsersPanel({ currentUserId }: { currentUserId: number }) {
  const users = useApi<{ items: User[]; total: number }>(() => api.listUsers(), []);
  const [error, setError] = useState<string | null>(null);
  const [busy, setBusy] = useState(false);

  async function onCreate(e: FormEvent<HTMLFormElement>) {
    e.preventDefault();
    const fd = new FormData(e.currentTarget);
    const body = {
      username: String(fd.get("username")).trim(),
      password: String(fd.get("password")),
      role: String(fd.get("role")) as User["role"],
    };
    setBusy(true);
    setError(null);
    try {
      await api.createUser(body);
      e.currentTarget.reset();
      await users.refetch();
    } catch (err) {
      setError(err instanceof ApiError ? err.message : "Failed to create user.");
    } finally {
      setBusy(false);
    }
  }

  async function onRole(u: User, role: User["role"]) {
    try {
      await api.updateUser(u.id, { role });
      await users.refetch();
    } catch (err) {
      setError(err instanceof ApiError ? err.message : "Failed to update user.");
    }
  }

  async function onDeactivate(u: User) {
    if (!confirm(`Disable account ${u.username}?`)) return;
    try {
      await api.deleteUser(u.id);
      await users.refetch();
    } catch (err) {
      setError(err instanceof ApiError ? err.message : "Failed to deactivate user.");
    }
  }

  return (
    <div className="mt-10">
      <SectionTitle>Accounts</SectionTitle>
      <form onSubmit={onCreate} className="border-subtle bg-surface mb-4 grid grid-cols-1 gap-3 rounded-lg border p-4 sm:grid-cols-4">
        <Field label="Username">
          <input className={inputClass} name="username" required minLength={3} aria-label="New username" />
        </Field>
        <Field label="Password (min 8)">
          <input className={inputClass} name="password" type="password" required minLength={8} aria-label="New password" />
        </Field>
        <Field label="Role">
          <select className={inputClass} name="role" defaultValue="viewer" aria-label="Role">
            <option value="viewer">viewer</option>
            <option value="operator">operator</option>
            <option value="admin">admin</option>
          </select>
        </Field>
        <div className="flex items-end">
          <button type="submit" disabled={busy} className="w-full rounded bg-[color:var(--accent)] px-3 py-2 text-sm font-semibold text-black disabled:opacity-60">
            {busy ? "Creating…" : "Create user"}
          </button>
        </div>
      </form>
      {error && (
        <p role="alert" className="mb-4 text-sm text-[color:var(--crit)]">
          {error}
        </p>
      )}
      {users.loading ? (
        <SkeletonTable rows={3} />
      ) : users.error ? (
        <ErrorState error={users.error} onRetry={users.refetch} />
      ) : (
        <div className="border-subtle bg-surface overflow-x-auto rounded-lg border">
          <table className="w-full min-w-[560px] text-sm">
            <thead>
              <tr className="text-muted border-subtle border-b text-left text-xs uppercase tracking-wide">
                <th className="px-4 py-2.5 font-medium">Username</th>
                <th className="px-4 py-2.5 font-medium">Role</th>
                <th className="px-4 py-2.5 font-medium">Created</th>
                <th className="px-4 py-2.5 font-medium">Active</th>
                <th className="px-4 py-2.5 font-medium">Actions</th>
              </tr>
            </thead>
            <tbody>
              {(users.data?.items ?? []).map((u) => (
                <tr key={u.id} className="border-subtle border-b last:border-b-0">
                  <td className="px-4 py-3 font-medium">
                    {u.username}
                    {u.id === currentUserId && <span className="text-muted ml-2 text-xs">(you)</span>}
                  </td>
                  <td className="px-4 py-3">
                    <select
                      className="border-subtle bg-raised rounded border px-2 py-1 text-xs"
                      value={u.role}
                      disabled={u.id === currentUserId}
                      onChange={(e) => void onRole(u, e.target.value as User["role"])}
                      aria-label={`Role for ${u.username}`}
                    >
                      {(["viewer", "operator", "admin"] as const).map((r) => (
                        <option key={r} value={r}>
                          {r}
                        </option>
                      ))}
                    </select>
                  </td>
                  <td className="tabular text-muted px-4 py-3 text-xs">{fmtDateTime(u.created_at)}</td>
                  <td className="px-4 py-3 text-xs">{u.is_active ? "yes" : "no"}</td>
                  <td className="px-4 py-3">
                    {u.id !== currentUserId && u.is_active && (
                      <button onClick={() => void onDeactivate(u)} className="border-subtle rounded border px-2 py-1 text-xs hover:text-[color:var(--crit)]">
                        Disable
                      </button>
                    )}
                  </td>
                </tr>
              ))}
            </tbody>
          </table>
        </div>
      )}
    </div>
  );
}
