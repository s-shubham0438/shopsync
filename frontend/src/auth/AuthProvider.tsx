import { useQuery, useQueryClient } from "@tanstack/react-query";
import { createContext, useCallback, useContext, useMemo, type ReactNode } from "react";
import { Navigate, useLocation } from "react-router";

import { api, type User } from "@/api";
import { PageSpinner } from "@/components/ui/Spinner";
import { keys } from "@/hooks/queries";

interface AuthState {
  user: User | null;
  isLoading: boolean;
  setUser: (user: User | null) => void;
  logout: () => Promise<void>;
}

const AuthContext = createContext<AuthState | null>(null);

export function AuthProvider({ children }: { children: ReactNode }) {
  const qc = useQueryClient();
  const { data, isLoading } = useQuery({ queryKey: keys.me, queryFn: api.auth.me, staleTime: 5 * 60_000 });

  const setUser = useCallback((user: User | null) => qc.setQueryData(keys.me, user), [qc]);

  const logout = useCallback(async () => {
    await api.auth.logout();
    qc.setQueryData(keys.me, null);
    qc.removeQueries({ queryKey: keys.wishlist });
    qc.removeQueries({ queryKey: keys.alerts });
    qc.removeQueries({ queryKey: keys.searchHistory });
  }, [qc]);

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

/** Redirects to /login?next=… when signed out. */
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
