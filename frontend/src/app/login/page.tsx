"use client";

import { FormEvent, useEffect, useState } from "react";
import { useRouter } from "next/navigation";
import { useAuth } from "@/auth";
import { DEMO } from "@/lib/api";
import { Field, inputClass } from "@/components/ui";

export default function LoginPage() {
  const router = useRouter();
  const { user, loading, login } = useAuth();
  const [username, setUsername] = useState("");
  const [password, setPassword] = useState("");
  const [error, setError] = useState<string | null>(null);
  const [busy, setBusy] = useState(false);

  useEffect(() => {
    if (!loading && user) router.replace("/");
  }, [loading, user, router]);

  async function onSubmit(e: FormEvent) {
    e.preventDefault();
    setBusy(true);
    setError(null);
    try {
      await login(username.trim(), password);
      router.replace("/");
    } catch (err) {
      const ae = err as { code?: string; message?: string };
      setError(
        ae.code === "BAD_CREDENTIALS" || ae.code === "NETWORK"
          ? (ae.message ?? "Invalid username or password.")
          : (ae.message ?? "Sign-in failed."),
      );
    } finally {
      setBusy(false);
    }
  }

  return (
    <div className="mx-auto flex min-h-screen max-w-md items-center px-4">
      <div className="w-full">
        <div className="mb-8">
          <div className="flex items-baseline gap-2">
            <span aria-hidden className="text-accent text-lg">▮</span>
            <h1 className="text-xl font-semibold tracking-tight">ESS Monitor</h1>
          </div>
          <p className="text-muted mt-1 text-sm">Environmental sensing — gateway telemetry & alerts.</p>
        </div>
        <form onSubmit={onSubmit} className="border-subtle bg-surface rounded-lg border p-6" noValidate>
          <div className="space-y-4">
            <Field label="Username">
              <input
                className={inputClass}
                autoComplete="username"
                value={username}
                onChange={(e) => setUsername(e.target.value)}
                required
                minLength={3}
                aria-label="Username"
              />
            </Field>
            <Field label="Password">
              <input
                className={inputClass}
                type="password"
                autoComplete="current-password"
                value={password}
                onChange={(e) => setPassword(e.target.value)}
                required
                minLength={8}
                aria-label="Password"
              />
            </Field>
            {error && (
              <p role="alert" className="text-sm text-[color:var(--crit)]">
                {error}
              </p>
            )}
            <button
              type="submit"
              disabled={busy || loading}
              className="w-full rounded bg-[color:var(--accent)] px-3 py-2 text-sm font-semibold text-black disabled:opacity-60"
            >
              {busy ? "Signing in…" : "Sign in"}
            </button>
            {DEMO && (
              <p className="text-muted text-xs">
                Demo mode: any credentials sign you in with simulated data.
              </p>
            )}
          </div>
        </form>
      </div>
    </div>
  );
}
