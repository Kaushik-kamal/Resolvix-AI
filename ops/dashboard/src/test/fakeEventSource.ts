import type { EventSourceCtor, EventSourceLike } from "../lib/sse";

/**
 * Controllable EventSource for tests. Every constructed instance is recorded in `FakeEventSource.instances`.
 *   const es = FakeEventSource.last();   es.open();   es.emit("alert.p1", {...});   es.fail();
 */
export class FakeEventSource implements EventSourceLike {
  static instances: FakeEventSource[] = [];
  static reset(): void {
    FakeEventSource.instances = [];
  }
  static last(): FakeEventSource {
    const last = FakeEventSource.instances[FakeEventSource.instances.length - 1];
    if (!last) throw new Error("no FakeEventSource has been created yet");
    return last;
  }

  readyState = 0; // CONNECTING
  onopen: ((ev: Event) => unknown) | null = null;
  onerror: ((ev: Event) => unknown) | null = null;
  closed = false;
  private listeners = new Map<string, Set<(ev: MessageEvent) => unknown>>();

  constructor(
    public url: string,
    public init?: { withCredentials?: boolean },
  ) {
    FakeEventSource.instances.push(this);
  }

  addEventListener(type: string, listener: (ev: MessageEvent) => unknown): void {
    if (!this.listeners.has(type)) this.listeners.set(type, new Set());
    this.listeners.get(type)!.add(listener);
  }
  removeEventListener(type: string, listener: (ev: MessageEvent) => unknown): void {
    this.listeners.get(type)?.delete(listener);
  }
  close(): void {
    this.closed = true;
    this.readyState = 2;
  }

  /** The server accepted the connection. */
  open(): void {
    this.readyState = 1;
    this.onopen?.(new Event("open"));
  }
  /** Deliver a named event; objects are JSON-encoded like the server does, strings are sent raw. */
  emit(type: string, data: unknown): void {
    const raw = typeof data === "string" ? data : JSON.stringify(data);
    const event = new MessageEvent(type, { data: raw });
    this.listeners.get(type)?.forEach((listener) => listener(event));
  }
  /** Connection error (server down, 401, network drop). */
  fail(): void {
    this.readyState = 2;
    this.onerror?.(new Event("error"));
  }
}

export const FakeEventSourceCtor = FakeEventSource as unknown as EventSourceCtor;
