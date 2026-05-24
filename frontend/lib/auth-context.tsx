"use client";

/**
 * AuthProvider — single source of truth for the signed-in user.
 *
 * What it owns:
 *  - Bootstrapping: on mount, try one silent `/auth/refresh` to discover an
 *    existing session (the refresh cookie is HttpOnly so the client can't
 *    inspect it — only attempt-and-see).
 *  - `login()` / `logout()` helpers that update both the in-memory access
 *    token (via `lib/api.ts`) and the React state.
 *  - Exposing `{ user, tenantSlug, role, status }` for route guards and
 *    role-gated UI.
 *
 * What it deliberately does NOT do:
 *  - Persist the user object — `/auth/me` is the cheap source of truth.
 *  - Touch localStorage — Phase F moves the access token off it for XSS
 *    blast-radius reasons. The HttpOnly refresh cookie is what keeps sessions
 *    durable across page reloads.
 */

import {
  ReactNode,
  createContext,
  useCallback,
  useContext,
  useEffect,
  useMemo,
  useState,
} from "react";

import {
  bootstrapSession,
  clearAccessToken,
  login as apiLogin,
  logout as apiLogout,
  me as apiMe,
  type MeResponse,
} from "@/lib/api";

export type AuthUser = MeResponse;
export type AuthStatus = "loading" | "authenticated" | "unauthenticated";

type AuthContextValue = {
  user: AuthUser | null;
  status: AuthStatus;
  tenantSlug: string | null;
  role: AuthUser["role"] | null;
  /** POST /auth/login. Throws MfaRequiredError / ApiError on failure. */
  login: (input: {
    email?: string | null;
    password?: string | null;
    tenant_slug?: string | null;
    mfa_code?: string | null;
    mfa_token?: string | null;
  }) => Promise<void>;
  /** Best-effort POST /auth/logout + local state wipe. */
  logout: () => Promise<void>;
  /** Force-refresh the cached user object (e.g. after a role change). */
  refreshUser: () => Promise<AuthUser | null>;
};

const AuthContext = createContext<AuthContextValue | null>(null);

export function AuthProvider({ children }: { children: ReactNode }) {
  const [user, setUser] = useState<AuthUser | null>(null);
  const [status, setStatus] = useState<AuthStatus>("loading");

  useEffect(() => {
    let cancelled = false;
    bootstrapSession()
      .then((next) => {
        if (cancelled) return;
        setUser(next);
        setStatus(next ? "authenticated" : "unauthenticated");
      })
      .catch(() => {
        if (cancelled) return;
        setUser(null);
        setStatus("unauthenticated");
      });
    return () => {
      cancelled = true;
    };
  }, []);

  const login = useCallback<AuthContextValue["login"]>(async (input) => {
    await apiLogin(input);
    const next = await apiMe();
    setUser(next);
    setStatus("authenticated");
  }, []);

  const logout = useCallback<AuthContextValue["logout"]>(async () => {
    try {
      await apiLogout();
    } finally {
      clearAccessToken();
      setUser(null);
      setStatus("unauthenticated");
    }
  }, []);

  const refreshUser = useCallback<AuthContextValue["refreshUser"]>(async () => {
    try {
      const next = await apiMe();
      setUser(next);
      setStatus("authenticated");
      return next;
    } catch {
      setUser(null);
      setStatus("unauthenticated");
      return null;
    }
  }, []);

  const value = useMemo<AuthContextValue>(
    () => ({
      user,
      status,
      tenantSlug: user?.tenant_slug ?? null,
      role: user?.role ?? null,
      login,
      logout,
      refreshUser,
    }),
    [user, status, login, logout, refreshUser],
  );

  return <AuthContext.Provider value={value}>{children}</AuthContext.Provider>;
}

export function useAuth(): AuthContextValue {
  const ctx = useContext(AuthContext);
  if (!ctx) {
    throw new Error("useAuth must be used inside <AuthProvider>");
  }
  return ctx;
}

/**
 * Pure helper: does this role satisfy the requirement?
 *
 * We use a numeric ordering rather than a Set so callers can express
 * "compliance and up" without listing every role.
 */
const ROLE_RANK: Record<AuthUser["role"], number> = {
  advisor: 0,
  compliance: 1,
  admin: 2,
  owner: 3,
};

export function hasAtLeastRole(
  role: AuthUser["role"] | null | undefined,
  required: AuthUser["role"],
): boolean {
  if (!role) return false;
  return ROLE_RANK[role] >= ROLE_RANK[required];
}
