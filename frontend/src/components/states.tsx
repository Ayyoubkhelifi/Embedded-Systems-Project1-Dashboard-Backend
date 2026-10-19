"use client";

import type { ReactNode } from "react";

export function Skeleton({ className = "" }: { className?: string }) {
  return (
    <div
      aria-hidden
      className={`animate-pulse rounded-md bg-[var(--border-subtle)] ${className}`}
    />
  );
}

export function SkeletonCards({ count = 4 }: { count?: number }) {
  return (
    <div className="grid grid-cols-1 gap-3 sm:grid-cols-2 lg:grid-cols-4" role="status" aria-label="Loading data">
      {Array.from({ length: count }).map((_, i) => (
        <div key={i} className="border-subtle bg-surface rounded-lg border p-4">
          <Skeleton className="h-3 w-24" />
          <Skeleton className="mt-3 h-7 w-32" />
          <Skeleton className="mt-2 h-3 w-20" />
        </div>
      ))}
    </div>
  );
}

export function SkeletonTable({ rows = 6 }: { rows?: number }) {
  return (
    <div className="border-subtle bg-surface rounded-lg border" role="status" aria-label="Loading table">
      <div className="border-subtle flex gap-4 border-b px-4 py-2.5">
        {Array.from({ length: 4 }).map((_, i) => (
          <Skeleton key={i} className="h-3 w-24 flex-1" />
        ))}
      </div>
      {Array.from({ length: rows }).map((_, r) => (
        <div key={r} className="border-subtle flex gap-4 border-b px-4 py-3 last:border-b-0">
          {Array.from({ length: 4 }).map((_, c) => (
            <Skeleton key={c} className="h-3 flex-1" />
          ))}
        </div>
      ))}
    </div>
  );
}

export function EmptyState({ title, detail }: { title: string; detail?: string }) {
  return (
    <div className="border-subtle bg-surface text-center rounded-lg border px-6 py-10">
      <div aria-hidden className="text-muted mb-2 text-2xl">
        ◌
      </div>
      <p className="font-medium">{title}</p>
      {detail && <p className="text-muted mt-1 text-sm">{detail}</p>}
    </div>
  );
}

export function ErrorState({ error, onRetry }: { error: unknown; onRetry?: () => void }) {
  const e = error as { code?: string; status?: number; message?: string } | null;
  return (
    <div role="alert" className="bg-surface rounded-lg border border-[color:var(--crit)] px-6 py-6">
      <p className="font-medium text-[color:var(--crit)]">Could not load data</p>
      <p className="text-muted mt-1 text-sm">
        {e?.message ?? "An unexpected error occurred."}
        {e?.code && e.code !== "HTTP_ERROR" && (
          <>
            <span className="px-1">·</span>
            <span className="tabular">{e.code}</span>
          </>
        )}
      </p>
      {onRetry && (
        <button
          onClick={onRetry}
          className="border-subtle hover:bg-raised mt-4 rounded border px-3 py-1.5 text-sm"
        >
          Retry
        </button>
      )}
    </div>
  );
}
