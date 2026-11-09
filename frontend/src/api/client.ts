// Typed API client. Reads tokens from in-memory state only (never localStorage),
// per steering/security.md ("No sensitive data in browser storage").

import { z } from "zod";

const errorEnvelope = z.object({
  error: z.object({
    code: z.string(),
    message: z.string(),
    correlation_id: z.string().nullable(),
    details: z.unknown().optional(),
  }),
});

export class ApiError extends Error {
  code: string;
  correlationId: string | null;
  constructor(code: string, message: string, correlationId: string | null) {
    super(message);
    this.code = code;
    this.correlationId = correlationId;
  }
}

let accessToken: string | null = null;

export function setAccessToken(token: string | null): void {
  accessToken = token;
}

export function getAccessToken(): string | null {
  return accessToken;
}

// The refresh token lives in an HttpOnly cookie that JavaScript cannot read. This call only
// asks the server to trade it for a fresh short-lived access token (kept in memory). The
// custom header is the CSRF guard the server requires on the cookie path.
let inflightRefresh: Promise<boolean> | null = null;

export function refreshSession(): Promise<boolean> {
  // Single-flight: concurrent callers share one request (refresh tokens rotate on use).
  inflightRefresh ??= (async () => {
    try {
      const resp = await fetch("/api/v1/auth/refresh", {
        method: "POST",
        headers: { "X-Requested-With": "ora-web" },
        credentials: "same-origin",
      });
      if (!resp.ok) return false;
      const body = (await resp.json().catch(() => null)) as { access_token?: unknown } | null;
      if (typeof body?.access_token !== "string") return false;
      accessToken = body.access_token;
      return true;
    } catch {
      return false;
    } finally {
      inflightRefresh = null;
    }
  })();
  return inflightRefresh;
}

export async function clearServerSession(): Promise<void> {
  try {
    await fetch("/api/v1/auth/logout", { method: "POST", credentials: "same-origin" });
  } catch {
    /* offline: the in-memory token is cleared by the caller regardless */
  }
}

const AUTH_PATHS = ["/api/v1/auth/login", "/api/v1/auth/refresh", "/api/v1/auth/logout"];

export async function apiFetch<T>(
  path: string,
  schema: z.ZodType<T>,
  init: RequestInit = {},
  retried = false,
): Promise<T> {
  const headers = new Headers(init.headers);
  headers.set("Content-Type", "application/json");
  if (accessToken) headers.set("Authorization", `Bearer ${accessToken}`);

  const resp = await fetch(path, { ...init, headers });

  // The short-lived access token expired mid-session: renew it once and retry, instead of
  // bouncing the user to the login screen.
  if (resp.status === 401 && !retried && accessToken && !AUTH_PATHS.includes(path)) {
    if (await refreshSession()) return apiFetch(path, schema, init, true);
  }

  const body: unknown = await resp.json().catch(() => null);

  if (!resp.ok) {
    const parsed = errorEnvelope.safeParse(body);
    if (parsed.success) {
      throw new ApiError(
        parsed.data.error.code,
        parsed.data.error.message,
        parsed.data.error.correlation_id,
      );
    }
    throw new ApiError("unknown_error", `Request failed (${resp.status})`, null);
  }

  return schema.parse(body);
}
