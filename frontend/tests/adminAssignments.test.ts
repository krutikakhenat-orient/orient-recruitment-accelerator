import { afterEach, beforeEach, describe, expect, it, vi } from "vitest";

import { setAccessToken } from "../src/api/client";
import { listAllInterviewAssignments, listUsers } from "../src/api/resources";

/* Client tests backing the System Admin assigned-users overview (Issue 3) and the
   role-filtered interviewer dropdown root cause (Issue 1): confirm the client keeps
   role_names from /users and parses the org-wide assignment overview (metadata only). */

function jsonResponse(body: unknown, status = 200): Response {
  return new Response(JSON.stringify(body), {
    status,
    headers: { "Content-Type": "application/json" },
  });
}

describe("admin assignment overview + user roles API", () => {
  beforeEach(() => {
    vi.restoreAllMocks();
    setAccessToken("tok");
  });
  afterEach(() => setAccessToken(null));

  it("keeps role_names from GET /users (fixes the empty interviewer dropdown)", async () => {
    vi.spyOn(globalThis, "fetch").mockResolvedValue(
      jsonResponse([
        {
          id: "11111111-1111-1111-1111-111111111111",
          organisation_id: "22222222-2222-2222-2222-222222222222",
          email: "panel@example.com",
          display_name: "Panelist",
          is_active: true,
          mfa_enabled: false,
          role_names: ["interview_panel"],
        },
      ]),
    );
    const users = await listUsers();
    expect(users[0]!.role_names).toContain("interview_panel");
    // The dropdown filter the UI applies would now include this user.
    expect(
      users.filter((u) => (u.role_names ?? []).includes("interview_panel")),
    ).toHaveLength(1);
  });

  it("parses the org-wide assignment overview and requests the right endpoint", async () => {
    const fetchMock = vi.spyOn(globalThis, "fetch").mockResolvedValue(
      jsonResponse([
        {
          id: "aaaaaaaa-aaaa-aaaa-aaaa-aaaaaaaaaaaa",
          interviewer_id: "bbbbbbbb-bbbb-bbbb-bbbb-bbbbbbbbbbbb",
          interviewer_name: "Panelist",
          interviewer_email: "panel@example.com",
          interviewer_role_names: ["interview_panel"],
          campaign_id: "cccccccc-cccc-cccc-cccc-cccccccccccc",
          campaign_name: "Network Security Operations",
          stage_id: null,
          stage_name: null,
          is_active: true,
        },
      ]),
    );
    const rows = await listAllInterviewAssignments();
    const [path] = fetchMock.mock.calls[0]!;
    expect(path).toBe("/api/v1/interviews/assignments");
    expect(rows).toHaveLength(1);
    expect(rows[0]!.campaign_name).toBe("Network Security Operations");
    expect(rows[0]!.is_active).toBe(true);
    // Overview is metadata only — no candidate fields exist on the row.
    expect(rows[0]).not.toHaveProperty("resume");
    expect(rows[0]).not.toHaveProperty("criteria_scores");
  });
});
