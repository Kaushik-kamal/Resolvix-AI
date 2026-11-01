import clsx from "clsx";
import { Siren, X } from "lucide-react";
import { Link } from "react-router-dom";
import { useAlerts } from "../alerts/AlertContext";
import { MaskedNumber } from "../components";
import { humanize } from "../lib/format";
import { PROJECTOR_CLASSES, useProjectorMode } from "../lib/projector";

/**
 * Red banner for un-dismissed P1 alerts (alert.p1 events). Rendered under the header on every page so a P1 is never
 * missed on another tab of the app. Links open the ticket via /tickets?ticket=<id> (page contract, see COMPONENTS.md).
 * Projector mode (live board toggle) makes the banner text about 1.4x bigger.
 */
export function AlertBanner() {
  const { alerts, dismiss, dismissAll } = useAlerts();
  const [projector] = useProjectorMode();
  if (alerts.length === 0) return null;
  const visible = alerts.slice(0, 3);
  return (
    <div
      role="alert"
      aria-live="assertive"
      className={clsx("bg-p1 text-white shadow-md", projector && PROJECTOR_CLASSES.banner)}
      data-testid="p1-banner"
      data-projector={projector ? "true" : undefined}
    >
      <div className="mx-auto flex max-w-[1800px] flex-col gap-1 px-4 py-2">
        {visible.map((alert) => (
          <div key={alert.ticket_id} className="flex items-center gap-3">
            <Siren size={projector ? 26 : 18} className="shrink-0 animate-pulse" aria-hidden />
            <span className={clsx("rounded bg-white/20 px-1.5 py-0.5 font-bold", projector ? "text-base" : "text-xs")}>P1</span>
            <Link to={`/tickets?ticket=${encodeURIComponent(alert.ticket_id)}`} className="font-mono font-semibold underline">
              {alert.ticket_id}
            </Link>
            <span className={clsx("opacity-90", projector ? "text-base" : "text-xs")}>{humanize(alert.department)}</span>
            <span className="min-w-0 flex-1 truncate">{alert.summary}</span>
            <span className={clsx("hidden opacity-90 lg:inline", projector ? "text-base" : "text-xs")}>
              <MaskedNumber value={alert.caller_number} />
            </span>
            <button
              type="button"
              onClick={() => dismiss(alert.ticket_id)}
              className="rounded p-1 hover:bg-white/20"
              aria-label={`Dismiss alert ${alert.ticket_id}`}
            >
              <X size={16} aria-hidden />
            </button>
          </div>
        ))}
        {alerts.length > visible.length ? (
          <div className={clsx("flex items-center gap-2", projector ? "text-base" : "text-xs")}>
            <span>+{alerts.length - visible.length} more P1 alerts</span>
            <button type="button" onClick={dismissAll} className="underline">
              Dismiss all
            </button>
          </div>
        ) : null}
      </div>
    </div>
  );
}
