import clsx from "clsx";
import { Eye, EyeOff } from "lucide-react";
import { displayNumber } from "../lib/format";

export interface MaskedNumberProps {
  /** Number as the API returned it (masked by default, full when fetched with ?reveal=true). */
  value: string | null | undefined;
  /** Show `value` as is. Without it an unmasked number is masked on screen anyway. */
  revealed?: boolean;
  /**
   * When given, an eye button is shown. Reveal is audited server-side, so the caller must refetch with
   * `reveal: true` (and flip `revealed`) inside this handler instead of just toggling local state.
   */
  onToggleReveal?: () => void;
  className?: string;
}

/** Phone number in monospace, masked like +91•••••0002; "—" when missing. */
export function MaskedNumber({ value, revealed = false, onToggleReveal, className }: MaskedNumberProps) {
  const text = displayNumber(value, revealed);
  return (
    <span className={clsx("inline-flex items-center gap-1 font-mono", className)}>
      <span data-testid="masked-number">{text}</span>
      {onToggleReveal && value ? (
        <button
          type="button"
          onClick={onToggleReveal}
          className="rounded p-0.5 text-ink-faint hover:bg-black/5 hover:text-ink"
          aria-label={revealed ? "Hide number" : "Reveal number (audited)"}
          title={revealed ? "Hide number" : "Reveal number (audited)"}
        >
          {revealed ? <EyeOff size={14} /> : <Eye size={14} />}
        </button>
      ) : null}
    </span>
  );
}
