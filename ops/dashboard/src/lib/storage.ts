/** localStorage wrappers: private windows, blocked storage and quota errors must never break the page. */

export function readStorage(key: string): string | null {
  try {
    return window.localStorage.getItem(key);
  } catch {
    return null;
  }
}

export function writeStorage(key: string, value: string): boolean {
  try {
    window.localStorage.setItem(key, value);
    return true;
  } catch {
    return false;
  }
}

export const MUTE_KEY = "resolvix.alertsMuted";

export function readMuted(): boolean {
  return readStorage(MUTE_KEY) === "1";
}

export function writeMuted(muted: boolean): void {
  writeStorage(MUTE_KEY, muted ? "1" : "0");
}
