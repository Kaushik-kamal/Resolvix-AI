/**
 * P1 alert beep generated with the WebAudio API (no audio files). Browsers only allow audio after a user gesture:
 * `primeAudio()` is called on the first click/keypress (see AlertProvider) and by the mute toggle.
 */

type AudioContextCtor = new () => AudioContext;

let context: AudioContext | null = null;

function ctor(): AudioContextCtor | null {
  if (typeof window === "undefined") return null;
  const w = window as unknown as { AudioContext?: AudioContextCtor; webkitAudioContext?: AudioContextCtor };
  return w.AudioContext ?? w.webkitAudioContext ?? null;
}

/** Create/resume the shared AudioContext. Safe to call repeatedly; returns false when audio is unavailable. */
export function primeAudio(): boolean {
  const Ctx = ctor();
  if (!Ctx) return false;
  try {
    if (!context) context = new Ctx();
    if (context.state === "suspended") void context.resume();
    return true;
  } catch {
    return false;
  }
}

/** Test hook: forget the shared context. */
export function resetAudioForTests(): void {
  context = null;
}

/**
 * Three short square-wave pulses (880 Hz / 660 Hz alternating), about 0.9 s in total.
 * Returns false when nothing was played (no WebAudio, or the context is still locked by the browser).
 */
export function playAlertBeep(): boolean {
  if (!primeAudio() || !context) return false;
  try {
    const ctx = context;
    const start = ctx.currentTime + 0.02;
    const pulses = [880, 660, 880];
    pulses.forEach((freq, i) => {
      const t0 = start + i * 0.3;
      const osc = ctx.createOscillator();
      const gain = ctx.createGain();
      osc.type = "square";
      osc.frequency.value = freq;
      gain.gain.setValueAtTime(0.0001, t0);
      gain.gain.exponentialRampToValueAtTime(0.18, t0 + 0.02);
      gain.gain.exponentialRampToValueAtTime(0.0001, t0 + 0.22);
      osc.connect(gain);
      gain.connect(ctx.destination);
      osc.start(t0);
      osc.stop(t0 + 0.24);
    });
    return true;
  } catch {
    return false;
  }
}
