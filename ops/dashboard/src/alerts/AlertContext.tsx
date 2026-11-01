import {
  createContext,
  useCallback,
  useContext,
  useEffect,
  useMemo,
  useRef,
  useState,
  type ReactNode,
} from "react";
import type { AlertP1Event } from "../api/extra";
import { playAlertBeep, primeAudio } from "../lib/beep";
import { readMuted, writeMuted } from "../lib/storage";
import { useStreamEvent } from "../stream/EventStreamContext";

/** How long a new P1 ticket card keeps flashing. */
export const FLASH_MS = 8000;

export interface AlertValue {
  /** Un-dismissed P1 alerts, newest first. */
  alerts: AlertP1Event[];
  dismiss: (ticketId: string) => void;
  dismissAll: () => void;
  muted: boolean;
  toggleMuted: () => void;
  /** true for FLASH_MS after an alert.p1 arrived for this ticket */
  isFlashing: (ticketId: string) => boolean;
}

const AlertContext = createContext<AlertValue>({
  alerts: [],
  dismiss: () => undefined,
  dismissAll: () => undefined,
  muted: false,
  toggleMuted: () => undefined,
  isFlashing: () => false,
});

/**
 * Turns `alert.p1` stream events into UI state: a banner list, a beep (unless muted) and a flash marker for the new
 * ticket. Must be rendered inside EventStreamProvider.
 */
export function AlertProvider({ children }: { children: ReactNode }) {
  const [alerts, setAlerts] = useState<AlertP1Event[]>([]);
  const [muted, setMuted] = useState<boolean>(() => readMuted());
  const [flashing, setFlashing] = useState<Set<string>>(() => new Set());
  const mutedRef = useRef(muted);
  const timers = useRef(new Set<ReturnType<typeof setTimeout>>());

  useEffect(() => {
    mutedRef.current = muted;
  }, [muted]);

  // Browsers keep audio locked until a user gesture: unlock it on the first click or key press.
  useEffect(() => {
    const unlock = () => {
      primeAudio();
      window.removeEventListener("pointerdown", unlock);
      window.removeEventListener("keydown", unlock);
    };
    window.addEventListener("pointerdown", unlock);
    window.addEventListener("keydown", unlock);
    const pending = timers.current;
    return () => {
      window.removeEventListener("pointerdown", unlock);
      window.removeEventListener("keydown", unlock);
      pending.forEach(clearTimeout);
      pending.clear();
    };
  }, []);

  useStreamEvent("alert.p1", (alert) => {
    setAlerts((prev) => [alert, ...prev.filter((a) => a.ticket_id !== alert.ticket_id)]);
    setFlashing((prev) => new Set(prev).add(alert.ticket_id));
    const timer = setTimeout(() => {
      timers.current.delete(timer);
      setFlashing((prev) => {
        const next = new Set(prev);
        next.delete(alert.ticket_id);
        return next;
      });
    }, FLASH_MS);
    timers.current.add(timer);
    if (!mutedRef.current) playAlertBeep();
  });

  const dismiss = useCallback((ticketId: string) => {
    setAlerts((prev) => prev.filter((a) => a.ticket_id !== ticketId));
  }, []);
  const dismissAll = useCallback(() => setAlerts([]), []);
  const toggleMuted = useCallback(() => {
    setMuted((prev) => {
      const next = !prev;
      writeMuted(next);
      return next;
    });
    primeAudio(); // the click that toggles the mute is a user gesture: unlock audio now
  }, []);
  const isFlashing = useCallback((ticketId: string) => flashing.has(ticketId), [flashing]);

  const value = useMemo(
    () => ({ alerts, dismiss, dismissAll, muted, toggleMuted, isFlashing }),
    [alerts, dismiss, dismissAll, muted, toggleMuted, isFlashing],
  );
  return <AlertContext.Provider value={value}>{children}</AlertContext.Provider>;
}

export function useAlerts(): AlertValue {
  return useContext(AlertContext);
}
