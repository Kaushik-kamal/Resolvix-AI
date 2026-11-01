import clsx from "clsx";
import { X } from "lucide-react";
import { useEffect, useRef, type ReactNode } from "react";

export interface DrawerProps {
  open: boolean;
  onClose: () => void;
  title: ReactNode;
  subtitle?: ReactNode;
  /** content next to the close button (status chips, priority badge) */
  headerExtra?: ReactNode;
  children: ReactNode;
  /** sticky area at the bottom (action buttons) */
  footer?: ReactNode;
  /** panel width: md 480px, lg 640px (default), xl 820px */
  size?: "md" | "lg" | "xl";
}

const WIDTHS = { md: "max-w-[480px]", lg: "max-w-[640px]", xl: "max-w-[820px]" } as const;

const FOCUSABLE =
  'a[href], button:not([disabled]), input:not([disabled]):not([type="hidden"]), select:not([disabled]), textarea:not([disabled]), [tabindex]:not([tabindex="-1"])';

/** Tabbable descendants of the dialog in DOM order (hidden / aria-hidden subtrees are skipped). */
function tabbables(root: HTMLElement): HTMLElement[] {
  return Array.from(root.querySelectorAll<HTMLElement>(FOCUSABLE)).filter(
    (el) => !el.closest('[hidden], [aria-hidden="true"], [inert]') && el.tabIndex !== -1,
  );
}

/**
 * Right-hand slide-over. Closes on Escape, backdrop click or the X button; locks page scroll while open and returns
 * focus to the element that opened it. Tab / Shift+Tab cycle inside the dialog (focus trap, L10) and focus that
 * somehow lands outside is pulled back in. Render it unconditionally and drive it with `open`.
 */
export function Drawer({ open, onClose, title, subtitle, headerExtra, children, footer, size = "lg" }: DrawerProps) {
  const panelRef = useRef<HTMLDivElement>(null);
  // Keep the latest onClose in a ref so an inline arrow function from the parent does not re-run the effect
  // (which would steal focus from inputs inside the drawer on every parent render).
  const onCloseRef = useRef(onClose);
  useEffect(() => {
    onCloseRef.current = onClose;
  });

  useEffect(() => {
    if (!open) return;
    const previouslyFocused = document.activeElement as HTMLElement | null;
    panelRef.current?.focus();
    const onKey = (event: KeyboardEvent) => {
      if (event.key === "Escape") {
        event.stopPropagation();
        onCloseRef.current();
        return;
      }
      if (event.key !== "Tab") return;
      const panel = panelRef.current;
      if (!panel) return;
      const items = tabbables(panel);
      if (items.length === 0) {
        event.preventDefault();
        panel.focus();
        return;
      }
      const first = items[0]!;
      const last = items[items.length - 1]!;
      const active = document.activeElement as HTMLElement | null;
      const inside = !!active && panel.contains(active);
      if (event.shiftKey) {
        if (!inside || active === first || active === panel) {
          event.preventDefault();
          last.focus();
        }
      } else if (!inside || active === last) {
        event.preventDefault();
        first.focus();
      }
    };
    const onFocusIn = (event: FocusEvent) => {
      const panel = panelRef.current;
      if (panel && event.target instanceof Node && !panel.contains(event.target)) panel.focus();
    };
    document.addEventListener("keydown", onKey);
    document.addEventListener("focusin", onFocusIn);
    const previousOverflow = document.body.style.overflow;
    document.body.style.overflow = "hidden";
    return () => {
      document.removeEventListener("keydown", onKey);
      document.removeEventListener("focusin", onFocusIn);
      document.body.style.overflow = previousOverflow;
      previouslyFocused?.focus?.();
    };
  }, [open]);

  if (!open) return null;
  return (
    <div className="fixed inset-0 z-40 flex justify-end">
      <div className="absolute inset-0 animate-fadein bg-black/30" onClick={onClose} data-testid="drawer-backdrop" />
      <div
        ref={panelRef}
        role="dialog"
        aria-modal="true"
        aria-label={typeof title === "string" ? title : undefined}
        tabIndex={-1}
        className={clsx(
          "relative flex h-full w-full animate-slidein flex-col bg-surface shadow-xl outline-none",
          WIDTHS[size],
        )}
      >
        <header className="flex items-start justify-between gap-3 border-b border-line px-5 py-4">
          <div className="min-w-0">
            <h2 className="truncate text-base font-semibold text-ink">{title}</h2>
            {subtitle ? <div className="mt-0.5 text-xs text-ink-soft">{subtitle}</div> : null}
          </div>
          <div className="flex shrink-0 items-center gap-2">
            {headerExtra}
            <button type="button" onClick={onClose} className="btn btn-ghost btn-sm" aria-label="Close panel">
              <X size={16} aria-hidden />
            </button>
          </div>
        </header>
        <div className="min-h-0 flex-1 overflow-y-auto px-5 py-4">{children}</div>
        {footer ? <footer className="border-t border-line bg-bg px-5 py-3">{footer}</footer> : null}
      </div>
    </div>
  );
}
