import { afterEach, beforeEach, describe, expect, it, vi } from "vitest";

import { setAccessToken } from "../src/api/client";
import { listUsers, type StaffUser } from "../src/api/resources";

/* Root-cause guard for the interviewer dropdown.

   The dropdown on the campaign Interviews tab is populated by filtering the result of
   listUsers() to users whose role_names include "interview_panel". The dropdown was empty
   because a prior build dropped role_names from the parsed staff-user shape, so the filter
   matched nothing. These tests pin the contract end-to-end at the client boundary:
     1. listUsers() preserves role_names and is_active from the API response.
     2. The exact filter the UI applies selects interview_panel members and nothing else.

   The mocked response mirrors the real GET /api/v1/users payload (verified against the dev
   database): active users each carry role_names, interviewers carry ["interview_panel"]. */

function jsonResponse(body: unknown, status = 200): Response {
  return new Response(JSON.stringify(body), {
    status,
    headers: { "Content-Type": "application/json" },
  });
}

// The UI's selection rule, kept identical to CampaignDetailPage's panelUsers filter.
const isPanelMember = (u: StaffUser): boolean =>
  (u.role_names ?? []).includes("interview_panel");

const USERS = [
  {
    id: "11111111-1111-1111-1111-111111111111",
    organisation_id: "99999999-9999-9999-9999-999999999999",
    email: "panelist.one@example.com",
    display_name: "Panelist One",
    is_active: true,
    mfa_enabled: false,
    role_names: ["interview_panel"],
  },
  {
    id: "22222222-2222-2222-2222-222222222222",
    organisation_id: "99999999-9999-9999-9999-999999999999",
    email: "panelist.two@example.com",
    display_name: "Panelist Two",
    is_active: true,
    mfa_enabled: false,
    role_names: ["interview_panel"],
  },
  {
    id: "33333333-3333-3333-3333-333333333333",
    organisation_id: "99999999-9999-9999-9999-999999999999",
    email: "boss@example.com",
    display_name: "Recruiter Admin",
    is_active: true,
    mfa_enabled: false,
    role_names: ["recruiter_admin"],
  },
];

describe("interviewer dropdown source (listUsers + panel filter)", () => {
  beforeEach(() => {
    vi.restoreAllMocks();
    setAccessToken("tok");
  });
  afterEach(() => setAccessToken(null));

  it("calls the active-users endpoint and preserves role_names + is_active", async () => {
    const fetchMock = vi
      .spyOn(globalThis, "fetch")
      .mockResolvedValue(jsonResponse(USERS));

    const users = await listUsers();

    const [path] = fetchMock.mock.calls[0]!;
    expect(path).toBe("/api/v1/users");
    // role_names must survive zod parsing — this is the field the dropdown filters on.
    expect(users[0]!.role_names).toEqual(["interview_panel"]);
    expect(users[0]!.is_active).toBe(true);
  });

  it("filters to interview_panel members so the dropdown is populated", async () => {
    vi.spyOn(globalThis, "fetch").mockResolvedValue(jsonResponse(USERS));

    const users = await listUsers();
    const panelUsers = users.filter(isPanelMember);

    expect(panelUsers.map((u) => u.email)).toEqual([
      "panelist.one@example.com",
      "panelist.two@example.com",
    ]);
    // The recruiter admin (non-panel) is excluded.
    expect(panelUsers.some((u) => u.email === "boss@example.com")).toBe(false);
  });

  it("requests include_inactive only for the admin table variant", async () => {
    const fetchMock = vi
      .spyOn(globalThis, "fetch")
      .mockResolvedValue(jsonResponse(USERS));
    await listUsers(true);
    const [path] = fetchMock.mock.calls[0]!;
    expect(path).toBe("/api/v1/users?include_inactive=true");
  });

  it("yields an empty dropdown when the API omits role_names (stale-backend regression)", async () => {
    // Reproduces the real root cause: a stale server returned users WITHOUT role_names.
    // listUsers() still parses (role_names is optional), but the panel filter then matches
    // nothing — which is exactly why the dropdown was empty. This pins the observable
    // symptom so a correct backend (role_names present) is required for a populated list.
    const withoutRoleNames = USERS.map((u) => {
      const copy: Record<string, unknown> = { ...u };
      delete copy.role_names;
      return copy;
    });
    vi.spyOn(globalThis, "fetch").mockResolvedValue(jsonResponse(withoutRoleNames));

    const users = await listUsers();
    expect(users).toHaveLength(3);
    expect(users.every((u) => u.role_names === undefined)).toBe(true);
    expect(users.filter(isPanelMember)).toHaveLength(0);
  });
});
