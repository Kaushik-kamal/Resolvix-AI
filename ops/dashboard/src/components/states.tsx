import clsx from "clsx";
import { AlertTriangle, Inbox, Loader2, RefreshCw } from "lucide-react";
import type { ReactNode } from "react";
import { isApiError } from "../api/client";

export interface LoadingStateProps {
  label?: string;
  /** "spinner" (default) or "skeleton" with `rows` grey bars. */
  variant?: "spinner" | "skeleton";
  rows?: number;
  className?: string;
}

export function LoadingState({ label = "Loading…", variant = "spinner", rows = 4, className }: LoadingStateProps) {
  if (variant === "skeleton") {
    return (
      <div role="status" aria-label={label} className={clsx("space-y-2 p-3", className)}>
        {Array.from({ length: rows }, (_, i) => (
          <div key={i} className="h-8 animate-pulse rounded bg-black/5" />
        ))}
        <span className="sr-only">{label}</span>
      </div>
    );
  }
  return (
    <div role="status" className={clsx("flex items-center justify-center gap-2 p-6 text-ink-soft", className)}>
      <Loader2 size={18} className="animate-spin" aria-hidden />
      <span>{label}</span>
    </div>
  );
}

export interface EmptyStateProps {
  title: string;
  hint?: ReactNode;
  icon?: ReactNode;
  action?: ReactNode;
  className?: string;
}

export function EmptyState({ title, hint, icon, action, className }: EmptyStateProps) {
  return (
    <div className={clsx("flex flex-col items-center justify-center gap-1 p-8 text-center", className)}>
      <div className="text-ink-faint">{icon ?? <Inbox size={28} aria-hidden />}</div>
      <p className="font-medium text-ink-soft">{title}</p>
      {hint ? <p className="max-w-md text-xs text-ink-faint">{hint}</p> : null}
      {action ? <div className="mt-2">{action}</div> : null}
    </div>
  );
}

export interface ErrorStateProps {
  /** An ApiError, Error or anything thrown; shown as "<code>: <message>". */
  error: unknown;
  title?: string;
  onRetry?: () => void;
  className?: string;
}

export function errorMessage(error: unknown): string {
  if (isApiError(error)) return `${error.message} (${error.code}${error.status ? `, HTTP ${error.status}` : ""})`;
  if (error instanceof Error) return error.message;
  return typeof error === "string" ? error : "Unknown error";
}

export function ErrorState({ error, title = "Could not load data", onRetry, className }: ErrorStateProps) {
  return (
    <div role="alert" className={clsx("flex flex-col items-center justify-center gap-1 p-8 text-center", className)}>
      <AlertTriangle size={28} className="text-p1" aria-hidden />
      <p className="font-medium text-ink">{title}</p>
      <p className="max-w-lg break-words text-xs text-ink-soft">{errorMessage(error)}</p>
      {onRetry ? (
        <button type="button" className="btn btn-secondary btn-sm mt-2" onClick={onRetry}>
          <RefreshCw size={12} aria-hidden /> Retry
        </button>
      ) : null}
    </div>
  );
}
