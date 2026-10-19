"use client";

import Link from "next/link";
import { usePathname, useRouter } from "next/navigation";
import { useAuth } from "@/auth";
import type { ReactNode } from "react";

const tabs = [
  { href: "/", label: "Overview" },
  { href: "/live", label: "Live" },
  { href: "/history", label: "History" },
  { href: "/devices", label: "Devices" },
  { href: "/alerts", label: "Alerts" },
  { href: "/settings", label: "Settings" },
];

export function Nav() {
  const pathname = usePathname();
  const router = useRouter();
  const { user, can, logout } = useAuth();

  return (
    <header className="border-b border-subtle bg-surface">
      <div className="mx-auto flex max-w-6xl flex-wrap items-center gap-x-6 gap-y-1 px-4 py-2.5">
        <Link href="/" className="mr-2 flex items-baseline gap-2 font-semibold tracking-tight">
          <span aria-hidden className="text-accent">▮</span>
          <span className="text-fg">ESS Monitor</span>
          <span className="text-muted text-xs font-normal">environmental telemetry</span>
        </Link>
        <nav aria-label="Primary" className="flex flex-1 flex-wrap gap-1">
          {tabs.map((t) => {
            const active = pathname === t.href || (t.href !== "/" && pathname.startsWith(t.href));
            return (
              <Link
                key={t.href}
                href={t.href}
                aria-current={active ? "page" : undefined}
                className={`rounded px-2.5 py-1.5 text-sm transition-colors ${
                  active ? "bg-raised text-fg" : "text-muted hover:text-fg"
                }`}
              >
                {t.label}
              </Link>
            );
          })}
        </nav>
        <div className="flex items-center gap-3 text-sm">
          {can("viewer") && user && (
            <span className="text-muted tabular text-xs">
              {user.username} · <span className="uppercase">{user.role}</span>
            </span>
          )}
          {user ? (
            <button
              onClick={() => logout().then(() => router.push("/login"))}
              className="border-subtle hover:bg-raised rounded border px-2.5 py-1 text-xs text-muted hover:text-fg"
            >
              Sign out
            </button>
          ) : (
            <Link href="/login" className="text-accent text-sm">
              Sign in
            </Link>
          )}
        </div>
      </div>
      {process.env.NEXT_PUBLIC_DEMO_MODE === "true" && (
        <div className="bg-raised text-muted border-t border-subtle px-4 py-1 text-center text-xs">
          Demo mode — data is simulated in-browser (NEXT_PUBLIC_DEMO_MODE=true)
        </div>
      )}
    </header>
  );
}

export function PageShell({ title, children, actions }: { title: string; children: ReactNode; actions?: ReactNode }) {
  return (
    <section aria-labelledby="page-title" className="mx-auto max-w-6xl px-4 py-6">
      <div className="mb-4 flex flex-wrap items-center justify-between gap-3">
        <h1 id="page-title" className="text-xl font-semibold tracking-tight">
          {title}
        </h1>
        {actions}
      </div>
      {children}
    </section>
  );
}
