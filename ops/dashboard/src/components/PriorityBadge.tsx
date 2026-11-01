import clsx from "clsx";
import type { Priority } from "../api/extra";

const STYLES: Record<Priority, string> = {
  P1: "bg-p1 text-white",
  P2: "bg-p2 text-white",
  P3: "bg-p3 text-white",
  P4: "bg-p4 text-ink",
};

export interface PriorityBadgeProps {
  priority: Priority | string | null | undefined;
  /** "sm" (default) fits a table cell, "md" suits headers. */
  size?: "sm" | "md";
  className?: string;
}

/** Coloured pill "P1".."P4" (P1 #B5603F, P2 #A97B49, P3 #6F8592, P4 #9CA9B1). Unknown values render a grey "?". */
export function PriorityBadge({ priority, size = "sm", className }: PriorityBadgeProps) {
  const known = priority && priority in STYLES;
  return (
    <span
      className={clsx(
        "inline-flex items-center justify-center rounded font-bold leading-none tracking-wide",
        size === "sm" ? "min-w-[2rem] px-1.5 py-1 text-[11px]" : "min-w-[2.5rem] px-2 py-1.5 text-xs",
        known ? STYLES[priority as Priority] : "bg-p4 text-ink",
        className,
      )}
      aria-label={known ? `Priority ${priority}` : "Priority unknown"}
      data-priority={known ? priority : "unknown"}
    >
      {known ? priority : "?"}
    </span>
  );
}
