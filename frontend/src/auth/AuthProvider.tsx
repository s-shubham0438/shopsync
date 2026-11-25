import { useQuery, useQueryClient } from "@tanstack/react-query";
import { createContext, useCallback, useContext, useEffect, useMemo, type ReactNode } from "react";
import { Navigate, useLocation } from "react-router";

import { api, ApiError, type User } from "@/api";
import { broadcastAuthChange, onAuthChangeElsewhere, onSessionExpired } from "@/api/session";
import { PageSpinner } from "@/components/ui/Spinner";
import { keys } from "@/hooks/queries";

interface AuthState {
  user: User | null;
  isLoading: boolean;
  /** Call after a successful sign-in with the user the API returned. */
  setUser: (user: User | null) => void;
  logout: () => Promise<void>;
}

const AuthContext = createContext<AuthState | null>(null);

/**
 * The signed-in user, restored from the session cookie via GET /auth/me.
 *
 * Route guards here are only for the UX: the backend authorises every request itself.
 */
export function AuthProvider({ children }: { children: ReactNode }) {
  const qc = useQueryClient();
  const { data, isLoading } = useQuery({
    queryKey: keys.me,
    queryFn: api.auth.me,
    staleTime: 5 * 60_000,
    retry: 1, // a 401 is not an error (me() resolves to null); only transient failures retry
  });

  const dropPrivateData = useCallback(() => {
    qc.removeQueries({ queryKey: keys.wishlist });
    qc.removeQueries({ queryKey: keys.alerts });
    qc.removeQueries({ queryKey: keys.searchHistory });
  }, [qc]);

  const setUser = useCallback(
    (user: User | null) => {
      qc.setQueryData(keys.me, user);
      if (!user) dropPrivateData();
      broadcastAuthChange();
    },
    [qc, dropPrivateData],
  );

  /**
   * Ends the session on the server first. If that fails (offline, server error) the user stays
   * signed in and the error is thrown: showing "signed out" while the session cookie still works
   * would be dangerous on a shared computer. A 401 means it was already over.
   */
  const logout = useCallback(async () => {
    try {
      await api.auth.logout();
    } catch (err) {
      if (!(err instanceof ApiError && err.status === 401)) throw err;
    }
    qc.setQueryData(keys.me, null);
    dropPrivateData();
    broadcastAuthChange();
  }, [qc, dropPrivateData]);

  useEffect(() => {
    const stopExpired = onSessionExpired(() => {
      qc.setQueryData(keys.me, null);
      dropPrivateData();
    });
    // Another tab signed in or out: re-check instead of trusting our cached user.
    const stopSync = onAuthChangeElsewhere(() => {
      dropPrivateData();
      void qc.invalidateQueries({ queryKey: keys.me });
    });
    return () => {
      stopExpired();
      stopSync();
    };
  }, [qc, dropPrivateData]);

  const value = useMemo(
    () => ({ user: data ?? null, isLoading, setUser, logout }),
    [data, isLoading, setUser, logout],
  );
  return <AuthContext value={value}>{children}</AuthContext>;
}

export function useAuth(): AuthState {
  const ctx = useContext(AuthContext);
  if (!ctx) throw new Error("useAuth must be used inside <AuthProvider>");
  return ctx;
}

export function displayName(user: User): string {
  if (user.full_name) return user.full_name;
  if (user.email) return user.email.split("@")[0]!;
  const m = user.phone?.match(/^\+91(\d{5})(\d{5})$/);
  if (m) return `+91 ${m[1]} ${m[2]}`;
  return user.phone || "there";
}

/** Redirects to /login?next=… when signed out (UX only; the API enforces access). */
export function RequireAuth({ children }: { children: ReactNode }) {
  const { user, isLoading } = useAuth();
  const location = useLocation();
  if (isLoading) return <PageSpinner />;
  if (!user) {
    const next = encodeURIComponent(location.pathname + location.search);
    return <Navigate to={`/login?next=${next}`} replace />;
  }
  return children;
}
