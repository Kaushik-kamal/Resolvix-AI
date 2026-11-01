/**
 * Router-state contract to /kb. "Draft KB entry" on a gap cluster (source "gap") and "Create KB draft from resolution"
 * in the ticket drawer (source "ticket") navigate to /kb with `state: { [KB_DRAFT_STATE_KEY]: KbDraftSeed }`; the KB
 * page reads it once and opens the editor prefilled.
 */
import type { GapCluster } from "../../api/types";

export const KB_DRAFT_STATE_KEY = "kbDraft";

export interface KbDraftSeed {
  source: "gap" | "ticket";
  /** gap cluster id; empty for a ticket seed (see ticketId) */
  clusterId: string;
  label: string;
  /** department key of the cluster or ticket, null when there is none */
  department: string | null;
  /** gap: the cluster's example questions. ticket: the ticket summary. The user reviews them. */
  questionVariants: string[];
  /** suggested id prefix (2-4 capital letters); the user finishes the number, e.g. "TRA-" -> "TRA-012" */
  idPrefix: string;
  /** optional prefill for "Answer (English)" (ticket seeds: the resolution text). Absent in gap seeds. */
  answerEn?: string;
  /** optional prefill for "Source title" (ticket seeds: "Resolved ticket <id>") */
  sourceTitle?: string;
  /** the ticket a "ticket" seed came from */
  ticketId?: string;
}

/** "exam_cell" -> "EC", "transport" -> "TRA", missing -> "GEN". Always matches [A-Z]{2,4}. */
export function suggestIdPrefix(department: string | null | undefined): string {
  const key = (department ?? "").toLowerCase();
  const words = key.split(/[^a-z]+/).filter(Boolean);
  if (words.length >= 2) {
    return words
      .slice(0, 4)
      .map((w) => w.charAt(0))
      .join("")
      .toUpperCase();
  }
  const word = words[0] ?? "";
  if (word.length >= 2) return word.slice(0, 3).toUpperCase();
  return "GEN";
}

export function buildDraftSeed(
  cluster: Pick<GapCluster, "cluster_id" | "label" | "department" | "examples">,
): KbDraftSeed {
  const seen = new Set<string>();
  const variants: string[] = [];
  for (const example of cluster.examples ?? []) {
    const text = String(example).trim();
    if (text && !seen.has(text)) {
      seen.add(text);
      variants.push(text);
    }
  }
  return {
    source: "gap",
    clusterId: cluster.cluster_id,
    label: cluster.label,
    department: cluster.department ?? null,
    questionVariants: variants,
    idPrefix: suggestIdPrefix(cluster.department),
  };
}

/** Longest question variant / answer prefill we seed (the form validates the real limits; this keeps seeds sane). */
const MAX_SEED_TEXT = 2000;

/**
 * Seed for "Create KB draft from resolution" in the ticket drawer: department from the ticket, question variants from
 * the ticket summary, the answer prefilled from the resolution text and the source title "Resolved ticket <id>".
 */
export function buildTicketDraftSeed(
  ticket: { ticket_id: string; department?: string | null; summary?: string | null },
  resolution: string | null,
): KbDraftSeed {
  const summary = (ticket.summary ?? "").trim().slice(0, MAX_SEED_TEXT);
  return {
    source: "ticket",
    clusterId: "",
    ticketId: ticket.ticket_id,
    label: `Resolved ticket ${ticket.ticket_id}`,
    department: ticket.department ?? null,
    questionVariants: summary ? [summary] : [],
    idPrefix: suggestIdPrefix(ticket.department),
    answerEn: (resolution ?? "").trim().slice(0, MAX_SEED_TEXT),
    sourceTitle: `Resolved ticket ${ticket.ticket_id}`,
  };
}

/** Validate router state coming from `useLocation().state` (anything can be there after a reload or a foreign link). */
export function readDraftSeed(state: unknown): KbDraftSeed | null {
  if (!state || typeof state !== "object") return null;
  const raw = (state as Record<string, unknown>)[KB_DRAFT_STATE_KEY];
  if (!raw || typeof raw !== "object") return null;
  const seed = raw as Partial<KbDraftSeed>;
  const isTicket = seed.source === "ticket";
  if (!Array.isArray(seed.questionVariants)) return null;
  if (isTicket ? typeof seed.ticketId !== "string" : typeof seed.clusterId !== "string") return null;
  const base = {
    clusterId: typeof seed.clusterId === "string" ? seed.clusterId : "",
    label: typeof seed.label === "string" ? seed.label : typeof seed.clusterId === "string" ? seed.clusterId : (seed.ticketId ?? ""),
    department: typeof seed.department === "string" ? seed.department : null,
    questionVariants: seed.questionVariants.filter((q): q is string => typeof q === "string"),
    idPrefix: typeof seed.idPrefix === "string" && /^[A-Z]{2,4}$/.test(seed.idPrefix) ? seed.idPrefix : "GEN",
  };
  const out: KbDraftSeed = { source: isTicket ? "ticket" : "gap", ...base };
  if (typeof seed.answerEn === "string") out.answerEn = seed.answerEn;
  if (typeof seed.sourceTitle === "string") out.sourceTitle = seed.sourceTitle;
  if (isTicket) out.ticketId = seed.ticketId;
  return out;
}
