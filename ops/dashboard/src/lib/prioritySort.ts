import type { Priority } from "../api/extra";

export const PRIORITIES: readonly Priority[] = ["P1", "P2", "P3", "P4"];

/** P1 = 0 ... P4 = 3, anything unknown sorts last. */
export function priorityRank(priority: string | null | undefined): number {
  const index = PRIORITIES.indexOf(priority as Priority);
  return index === -1 ? PRIORITIES.length : index;
}

/** Epoch milliseconds of an API timestamp; unparsable or missing values count as 0 (oldest). */
function stamp(value: string | null | undefined): number {
  if (!value) return 0;
  const ms = Date.parse(/[zZ]|[+-]\d{2}:?\d{2}$/.test(value) ? value : `${value}Z`);
  return Number.isNaN(ms) ? 0 : ms;
}

interface Sortable {
  priority: string | null | undefined;
  created_at: string | null | undefined;
}

/** Compare two tickets: priority P1 -> P4 first, then newest created_at first. */
export function comparePriority(a: Sortable, b: Sortable): number {
  const byPriority = priorityRank(a.priority) - priorityRank(b.priority);
  if (byPriority !== 0) return byPriority;
  return stamp(b.created_at) - stamp(a.created_at);
}

/**
 * New array sorted P1 -> P4, then newest first. Never mutates its input; equal items keep their input order.
 * Works for tickets (priority + created_at) and any object with those two fields.
 */
export function prioritySort<T extends Sortable>(items: readonly T[]): T[] {
  return [...items].sort(comparePriority);
}

/** Groups already-sorted or unsorted items by priority, each group newest first. */
export function groupByPriority<T extends Sortable>(items: readonly T[]): Record<Priority, T[]> {
  const groups: Record<Priority, T[]> = { P1: [], P2: [], P3: [], P4: [] };
  for (const item of prioritySort(items)) {
    if (item.priority && item.priority in groups) groups[item.priority as Priority].push(item);
  }
  return groups;
}
