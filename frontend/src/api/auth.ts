import { z } from "zod";

import { apiFetch, setAccessToken } from "./client";

const tokenPair = z.object({
  access_token: z.string(),
  refresh_token: z.string(),
  token_type: z.string(),
});

const actor = z.object({
  user_id: z.string(),
  organisation_id: z.string(),
  email: z.string(),
  role_names: z.array(z.string()),
  permissions: z.array(z.string()),
  assigned_campaign_ids: z.array(z.string()),
});

export type Actor = z.infer<typeof actor>;

export async function login(email: string, password: string): Promise<void> {
  const tokens = await apiFetch("/api/v1/auth/login", tokenPair, {
    method: "POST",
    body: JSON.stringify({ email, password }),
  });
  setAccessToken(tokens.access_token);
}

export async function fetchMe(): Promise<Actor> {
  // The API returns a set for permissions/campaigns; JSON serialises them as arrays.
  return apiFetch("/api/v1/auth/me", actor, { method: "GET" });
}

export function logout(): void {
  setAccessToken(null);
}
