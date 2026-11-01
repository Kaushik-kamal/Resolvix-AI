/**
 * Projector mode: bigger type on the live board (about 1.4x for ticket cards, the P1 banner and the counts row) for a
 * room display. The flag is persisted in localStorage (try/catch, see lib/storage.ts) and shared between the live
 * board toggle and the P1 banner through useSyncExternalStore.
 */
import { useCallback, useSyncExternalStore } from "react";
import { readStorage, writeStorage } from "./storage";

export const PROJECTOR_KEY = "resolvix.projector";

const listeners = new Set<() => void>();
let current: boolean | null = null; // memory copy: keeps working when localStorage is blocked

export function readProjector(): boolean {
  if (current === null) current = readStorage(PROJECTOR_KEY) === "1";
  return current;
}

export function writeProjector(on: boolean): void {
  current = on;
  writeStorage(PROJECTOR_KEY, on ? "1" : "0");
  listeners.forEach((listener) => listener());
}

/** Test helper: forget the memory copy so the next read goes to localStorage again. */
export function resetProjectorCache(): void {
  current = null;
  listeners.forEach((listener) => listener());
}

function subscribe(listener: () => void): () => void {
  listeners.add(listener);
  return () => {
    listeners.delete(listener);
  };
}

/** [projector on?, setter, toggle] */
export function useProjectorMode(): [boolean, (on: boolean) => void, () => void] {
  const on = useSyncExternalStore(subscribe, readProjector, () => false);
  const toggle = useCallback(() => writeProjector(!readProjector()), []);
  return [on, writeProjector, toggle];
}

/** Class names for the 1.4x variant. Kept in one place so tests (and the overflow check) can assert on them. */
export const PROJECTOR_CLASSES = {
  /** wrapper of the live board page */
  root: "projector-board",
  statValue: "text-5xl",
  statValueNormal: "text-3xl",
  statLabel: "text-base",
  statLabelNormal: "text-xs",
  statHint: "text-sm",
  statHintNormal: "text-[11px]",
  cardSummary: "text-lg",
  cardSummaryNormal: "text-[13px]",
  cardMeta: "text-base",
  cardMetaNormal: "text-xs",
  cardId: "text-base",
  cardIdNormal: "text-xs",
  columnTitle: "text-lg",
  columnTitleNormal: "text-sm",
  banner: "text-xl",
} as const;
