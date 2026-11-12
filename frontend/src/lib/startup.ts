// Backend startup state. The database pauses itself when idle (Aurora Serverless auto-pause) and
// takes a few seconds to resume. While it resumes the API answers 503 `service_starting`; the UI
// then shows "We are starting up" instead of a blank page, and requests retry on their own.

import { useSyncExternalStore } from "react";

export type StartupState = "ready" | "starting";
export type ProbeResult = "ready" | "starting" | "unavailable";

export const SERVICE_STARTING_CODE = "service_starting";
export const STATUS_PATH = "/api/v1/system/status";
const DEFAULT_RETRY_MS = 3000;

let state: StartupState = "ready";
const listeners = new Set<() => void>();

function setState(next: StartupState): void {
  if (state === next) return;
  state = next;
  listeners.forEach((fn) => fn());
}

export function markStarting(): void {
  setState("starting");
}

export function markReady(): void {
  setState("ready");
}

export function getStartupState(): StartupState {
  return state;
}

export function subscribeStartup(fn: () => void): () => void {
  listeners.add(fn);
  return () => listeners.delete(fn);
}

export function useStartupState(): StartupState {
  return useSyncExternalStore(subscribeStartup, getStartupState, getStartupState);
}

/** Wait time the server asked for (Retry-After seconds), clamped to 1-10 s. */
export function retryDelayMs(resp: Response): number {
  const seconds = Number(resp.headers.get("Retry-After"));
  if (!Number.isFinite(seconds) || seconds <= 0) return DEFAULT_RETRY_MS;
  return Math.min(Math.max(seconds, 1), 10) * 1000;
}

/** True if a 503 body is the API's "we are starting up" envelope. */
export function isServiceStarting(status: number, body: unknown): boolean {
  if (status !== 503 || typeof body !== "object" || body === null) return false;
  const error = (body as { error?: { code?: unknown } }).error;
  return error?.code === SERVICE_STARTING_CODE;
}

// Only these mean "not ready yet". Anything else (200, or e.g. 404 from an older backend that has
// no status endpoint) lets the app open, so the gate can never lock users out.
const NOT_READY_STATUSES = new Set([502, 503, 504]);

/** One status check. Never waits for the database; a paused database answers "starting". */
export async function probeBackend(signal?: AbortSignal): Promise<ProbeResult> {
  try {
    const resp = await fetch(STATUS_PATH, { credentials: "same-origin", signal: signal ?? null });
    if (!NOT_READY_STATUSES.has(resp.status)) return "ready";
    const body: unknown = await resp.json().catch(() => null);
    return isServiceStarting(resp.status, body) ? "starting" : "unavailable";
  } catch (err) {
    if (err instanceof DOMException && err.name === "AbortError") throw err;
    return "unavailable";
  }
}

export function sleep(ms: number): Promise<void> {
  return new Promise((resolve) => setTimeout(resolve, ms));
}

// How long one request keeps retrying while the database resumes before it gives up and shows
// its normal error. Resumes usually take 4-30 s.
export const STARTING_RETRY_LIMIT_MS = 60_000;

/**
 * `fetch` for our own API that waits out a database resume: on 503 `service_starting` it shows
 * "We are starting up", waits as the server asks, and sends the same request again. Safe for
 * uploads and other writes: the server answers service_starting only when it could not reach
 * the database at all, so nothing was saved. Do not use for third-party URLs.
 */
export async function startupFetch(input: RequestInfo | URL, init?: RequestInit): Promise<Response> {
  const since = Date.now();
  let waited = false;
  for (;;) {
    const resp = await fetch(input, init);
    if (resp.status === 503 && Date.now() - since < STARTING_RETRY_LIMIT_MS) {
      const body: unknown = await resp.clone().json().catch(() => null);
      if (isServiceStarting(resp.status, body)) {
        markStarting();
        waited = true;
        await sleep(retryDelayMs(resp));
        continue;
      }
    }
    if (resp.ok || waited) markReady();
    return resp;
  }
}
