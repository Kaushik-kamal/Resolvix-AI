import { useQuery, useQueryClient } from "@tanstack/react-query";
import { createContext, useCallback, useContext, useMemo, type ReactNode } from "react";
import { api, isApiError } from "../api/client";
import type { Me } from "../api/extra";
import { qk } from "../api/queryKeys";

export type AuthStatus = "loading" | "authenticated" | "anonymous" | "error";

export interface AuthValue {
  status: AuthStatus;
  user: Me | null;
  isAdmin: boolean;
  /** set when status is "error" (the API could not be reached) */
  error: unknown;
  login: (email: string, password: string) => Promise<Me>;
  logout: () => Promise<void>;
  refetch: () => void;
}

const AuthContext = createContext<AuthValue | null>(null);

/** GET /v1/auth/me; a 401 means "not signed in" (null), anything else is a real error. */
async function fetchMe(signal?: AbortSignal): Promise<Me | null> {
  try {
    return await api.me(signal);
  } catch (err) {
    if (isApiError(err) && err.status === 401) return null;
    throw err;
  }
}

export function AuthProvider({ children }: { children: ReactNode }) {
  const queryClient = useQueryClient();
  const query = useQuery({
    queryKey: qk.me,
    queryFn: ({ signal }) => fetchMe(signal),
    retry: false,
    staleTime: 5 * 60_000,
  });

  const login = useCallback(
    async (email: string, password: string) => {
      await api.login(email, password);
      const user = await fetchMe();
      if (!user) throw new Error("Signed in, but the session cookie was not accepted");
      queryClient.setQueryData(qk.me, user);
      return user;
    },
    [queryClient],
  );

  const logout = useCallback(async () => {
    try {
      await api.logout();
    } catch {
      /* the cookie may already be gone; leave the app either way */
    }
    queryClient.clear();
    queryClient.setQueryData(qk.me, null);
  }, [queryClient]);

  const value = useMemo<AuthValue>(() => {
    const user = query.data ?? null;
    const status: AuthStatus = query.isPending
      ? "loading"
      : query.isError
        ? "error"
        : user
          ? "authenticated"
          : "anonymous";
    return {
      status,
      user,
      isAdmin: user?.role === "admin",
      error: query.error,
      login,
      logout,
      refetch: () => void query.refetch(),
    };
  }, [query, login, logout]);

  return <AuthContext.Provider value={value}>{children}</AuthContext.Provider>;
}

export function useAuth(): AuthValue {
  const value = useContext(AuthContext);
  if (!value) throw new Error("useAuth must be used inside <AuthProvider>");
  return value;
}

/**
 * The signed-in user as cached by the auth guard (qk.me), without requiring an <AuthProvider>. Null while unknown.
 * `enabled: false` means this only reads and subscribes to the cache, it never fetches.
 */
export function useSessionUser(): Me | null {
  return useQuery<Me | null>({ queryKey: qk.me, queryFn: () => null, enabled: false }).data ?? null;
}
