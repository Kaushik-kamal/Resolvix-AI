import type { ReactNode } from "react";
import { Navigate, useLocation } from "react-router-dom";
import { ErrorState, LoadingState } from "../components";
import { useAuth } from "./AuthContext";

/** Route guard: shows a loader while /v1/auth/me is in flight and sends anonymous users to /login. */
export function RequireAuth({ children }: { children: ReactNode }) {
  const { status, error, refetch } = useAuth();
  const location = useLocation();

  if (status === "loading") return <LoadingState label="Checking session…" className="mt-24" />;
  if (status === "error") {
    return <ErrorState title="Cannot reach the ops API" error={error} onRetry={refetch} className="mt-24" />;
  }
  if (status === "anonymous") {
    return <Navigate to="/login" replace state={{ from: location.pathname + location.search }} />;
  }
  return <>{children}</>;
}
