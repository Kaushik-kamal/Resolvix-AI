import clsx from "clsx";
import { useEventStream } from "../stream/EventStreamContext";

/** Visible SSE connection status in the header: Live / Connecting / Reconnecting (attempt n, next try in s). */
export function ConnectionPill() {
  const { state } = useEventStream();
  const seconds = state.retryInMs ? Math.ceil(state.retryInMs / 1000) : null;
  const label =
    state.status === "open"
      ? "Live"
      : state.status === "connecting"
        ? "Connecting…"
        : state.status === "reconnecting"
          ? `Reconnecting${seconds ? ` in ${seconds}s` : ""} (try ${state.attempt})`
          : "Disconnected";
  return (
    <span
      className="inline-flex items-center gap-1.5 rounded-full bg-black/20 px-2.5 py-1 text-xs"
      role="status"
      aria-live="polite"
      aria-label={`Live updates: ${label}`}
      data-connection={state.status}
    >
      <span
        className={clsx(
          "h-2 w-2 rounded-full",
          state.status === "open" && "bg-[#7FB98A]",
          state.status === "connecting" && "animate-pulse bg-accent-sand",
          state.status === "reconnecting" && "animate-pulse bg-[#E0A458]",
          state.status === "closed" && "bg-p1",
        )}
      />
      {label}
    </span>
  );
}
