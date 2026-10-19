"use client";

import { createContext, useCallback, useContext, useEffect, useMemo, useState } from "react";
import type { ReactNode } from "react";
import { api, ApiError } from "./lib/api";
import type { Role, User } from "./lib/types";

interface AuthState {
  user: User | null;
  loading: boolean;
  can: (min: Role) => boolean;
  login: (username: string, password: string) => Promise<void>;
  logout: () => Promise<void>;
}

const rank: Record<Role, number> = { viewer: 0, operator: 1, admin: 2 };

const AuthContext = createContext<AuthState>({
  user: null,
  loading: true,
  can: () => false,
  login: async () => {
    throw new Error("AuthProvider missing");
  },
  logout: async () => undefined,
});

export function AuthProvider({ children }: { children: ReactNode }) {
  const [user, setUser] = useState<User | null>(null);
  const [loading, setLoading] = useState(true);

  useEffect(() => {
    let dead = false;
    api
      .me()
      .then((u) => {
        if (!dead) setUser(u);
      })
      .catch(() => {
        if (!dead) setUser(null);
      })
      .finally(() => {
        if (!dead) setLoading(false);
      });
    return () => {
      dead = true;
    };
  }, []);

  const login = useCallback(async (username: string, password: string) => {
    const { user: u } = await api.login(username, password);
    setUser(u);
  }, []);

  const logout = useCallback(async () => {
    await api.logout();
    setUser(null);
  }, []);

  const can = useCallback(
    (min: Role) => (user ? rank[user.role] >= rank[min] : false),
    [user],
  );

  const value = useMemo(
    () => ({ user, loading, can, login, logout }),
    [user, loading, can, login, logout],
  );
  return <AuthContext.Provider value={value}>{children}</AuthContext.Provider>;
}

export function useAuth() {
  return useContext(AuthContext);
}

export function isAuthError(e: unknown): e is ApiError {
  return e instanceof ApiError;
}
