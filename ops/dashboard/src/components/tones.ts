export type Tone = "neutral" | "info" | "good" | "warn" | "bad";

/** Soft chip colours (background, text, border) per tone, taken from the Resolvix palette plus one muted green. */
export const TONE_CLASSES: Record<Tone, string> = {
  neutral: "bg-[#ECE7E1] text-accent-graphite border-[#DDD5CC]",
  info: "bg-[#E3EAEE] text-[#40596A] border-[#CBD8DF]",
  good: "bg-[#E2EDE4] text-[#3F6B49] border-[#C7DBCC]",
  warn: "bg-[#F5E9D8] text-[#80551F] border-[#E8D3B1]",
  bad: "bg-[#F6E1D9] text-[#8D3C21] border-[#EBC4B6]",
};

/** Tone for known status/outcome/mode words across tickets, calls, KB, gaps and SMS. */
const STATUS_TONES: Record<string, Tone> = {
  // tickets
  open: "warn",
  in_progress: "info",
  resolved: "good",
  closed: "neutral",
  // calls
  answered: "good",
  escalated: "warn",
  transferred: "info",
  emergency: "bad",
  abandoned: "neutral",
  failed: "bad",
  // kb
  draft: "warn",
  approved: "good",
  archived: "neutral",
  // gaps
  new: "info",
  needs_document: "warn",
  ignored: "neutral",
  // sms
  queued: "info",
  sent: "good",
  delivered: "good",
  suppressed: "neutral",
};

export function toneForStatus(status: string): Tone {
  return STATUS_TONES[status] ?? "neutral";
}
