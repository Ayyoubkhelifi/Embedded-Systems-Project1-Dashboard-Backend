"use client";

import { useCallback, useEffect, useRef, useState } from "react";
import type { DependencyList } from "react";
import { api, API_BASE, DEMO, getWsToken } from "@/lib/api";
import { demoSubscribe } from "@/mocks/demo";

export type WsStatus = "idle" | "connecting" | "open" | "closed" | "error" | "unauthorized";

export type Handler = (type: string, data: Record<string, unknown>) => void;

/** Poll-based fetch hook with loading/error/refetch. */
export function useApi<T>(fn: () => Promise<T>, deps: DependencyList, pollMs?: number) {
  const [data, setData] = useState<T | null>(null);
  const [error, setError] = useState<Error | null>(null);
  const [loading, setLoading] = useState(true);
  const fnRef = useRef(fn);
  fnRef.current = fn;

  const load = useCallback(async () => {
    try {
      const out = await fnRef.current();
      setData(out);
      setError(null);
    } catch (e) {
      setError(e as Error);
    } finally {
      setLoading(false);
    }
  }, []);

  useEffect(() => {
    let dead = false;
    setLoading(true);
    void load();
    let id: ReturnType<typeof setInterval> | undefined;
    if (pollMs) id = setInterval(() => void load(), pollMs);
    return () => {
      dead = true;
      if (id) clearInterval(id);
    };
  }, deps);

  return { data, error, loading, refetch: load };
}

/** WebSocket subscription with automatic reconnect/backoff + 20 s heartbeat. */
export function useWebSocket(handler: Handler, enabled: boolean = true) {
  const [status, setStatus] = useState<WsStatus>("idle");
  const handlerRef = useRef(handler);
  handlerRef.current = handler;
  const attemptRef = useRef(0);
  const [tick, setTick] = useState(0);

  const reconnect = useCallback(() => {
    attemptRef.current = 0;
    setTick((t) => t + 1);
  }, []);

  useEffect(() => {
    if (DEMO) {
      setStatus("open");
      const stop = demoSubscribe((type, data) => {
        handlerRef.current(type, data as Record<string, unknown>);
      });
      return stop;
    }
    if (!enabled) return undefined;
    if (!getWsToken()) {
      setStatus("unauthorized");
      return undefined;
    }

    const base = (process.env.NEXT_PUBLIC_WS_BASE_URL ?? API_BASE).replace(/^http/, "ws").replace(/\/$/, "");
    let socket: WebSocket | null = null;
    let backoffTimer: ReturnType<typeof setTimeout> | undefined;
    let pingTimer: ReturnType<typeof setInterval> | undefined;
    let closed = false;

    const clearTimers = () => {
      if (backoffTimer) clearTimeout(backoffTimer);
      if (pingTimer) clearInterval(pingTimer);
      backoffTimer = undefined;
      pingTimer = undefined;
    };

    const connect = () => {
      setStatus("connecting");
      socket = new WebSocket(`${base}/ws/telemetry?token=${encodeURIComponent(getWsToken())}`);

      socket.onopen = () => {
        setStatus("open");
        attemptRef.current = 0;
        pingTimer = setInterval(() => {
          if (socket?.readyState === WebSocket.OPEN) socket.send("ping");
        }, 20000);
      };
      socket.onmessage = (evt) => {
        try {
          const msg = JSON.parse(String(evt.data)) as { type: string; data: Record<string, unknown> };
          handlerRef.current(msg.type, msg.data);
        } catch {
          /* ignore malformed frames */
        }
      };
      socket.onclose = (evt) => {
        socket = null;
        clearTimers();
        if (closed) return;
        if (evt.code === 4401) {
          setStatus("unauthorized");
          return;
        }
        setStatus("error");
        const delay = Math.min(30000, 1000 * 2 ** attemptRef.current);
        attemptRef.current = Math.min(attemptRef.current + 1, 5);
        backoffTimer = setTimeout(connect, delay);
      };
      socket.onerror = () => socket?.close();
    };

    connect();
    return () => {
      closed = true;
      clearTimers();
      socket?.close();
      socket = null;
    };
    // eslint-disable-next-line react-hooks/exhaustive-deps
  }, [tick, enabled]);

  return { status, reconnect };
}

/** Small helper for pages that need `useApi` with an auth-error redirect. */
export function authRedirectOnError(error: unknown) {
  void api; // referenced to keep tree-shaking from dropping the module
  if (error && typeof error === "object" && "status" in error) {
    const { status, code } = error as { status: number; code: string };
    if (status === 401 || code === "TOKEN_EXPIRED") return true;
  }
  return false;
}
