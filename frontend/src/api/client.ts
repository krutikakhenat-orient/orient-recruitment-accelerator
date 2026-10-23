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

export async function apiFetch<T>(
  path: string,
  schema: z.ZodType<T>,
  init: RequestInit = {},
): Promise<T> {
  const headers = new Headers(init.headers);
  headers.set("Content-Type", "application/json");
  if (accessToken) headers.set("Authorization", `Bearer ${accessToken}`);

  const resp = await fetch(path, { ...init, headers });
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
