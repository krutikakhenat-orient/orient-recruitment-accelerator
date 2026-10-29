import { afterEach, beforeEach, describe, expect, it, vi } from "vitest";

import { setAccessToken } from "../src/api/client";
import {
  createInterviewAssignment,
  getPanelDashboard,
  listMyAssignments,
  removeInterviewAssignment,
} from "../src/api/resources";

/* Focused tests for the interviewer-assignment + panel-isolation API client that back the
   assignment-management UI and the interviewer panel. These verify the client talks to the
   correct authenticated endpoints and scopes the panel by stable campaign id (not name). */

function jsonResponse(body: unknown, status = 200): Response {
  return new Response(JSON.stringify(body), {
    status,
    headers: { "Content-Type": "application/json" },
  });
}

describe("interviewer assignment API client", () => {
  beforeEach(() => {
    vi.restoreAllMocks();
    setAccessToken("tok");
  });
  afterEach(() => setAccessToken(null));

  it("creates an assignment via the campaign-scoped endpoint", async () => {
    const fetchMock = vi.spyOn(globalThis, "fetch").mockResolvedValue(
      jsonResponse(
        {
          id: "11111111-1111-1111-1111-111111111111",
          organisation_id: "22222222-2222-2222-2222-222222222222",
          campaign_id: "33333333-3333-3333-3333-333333333333",
          stage_id: null,
          interviewer_id: "44444444-4444-4444-4444-444444444444",
          interviewer_name: "Synthetic Panelist",
          assigned_by: "55555555-5555-5555-5555-555555555555",
          is_active: true,
          created_at: "2026-10-08T00:00:00Z",
          updated_at: "2026-10-08T00:00:00Z",
        },
        201,
      ),
    );

    const result = await createInterviewAssignment(
      "33333333-3333-3333-3333-333333333333",
      { interviewer_id: "44444444-4444-4444-4444-444444444444", stage_id: null },
    );

    const [path, init] = fetchMock.mock.calls[0]!;
    expect(path).toBe(
      "/api/v1/interviews/campaigns/33333333-3333-3333-3333-333333333333/assignments",
    );
    expect((init as RequestInit).method).toBe("POST");
    expect(result.is_active).toBe(true);
  });

  it("removes an assignment via DELETE and tolerates a 204 (no body)", async () => {
    const fetchMock = vi
      .spyOn(globalThis, "fetch")
      .mockResolvedValue(new Response(null, { status: 204 }));
    await removeInterviewAssignment("11111111-1111-1111-1111-111111111111", "tok");
    const [path, init] = fetchMock.mock.calls[0]!;
    expect(path).toBe(
      "/api/v1/interviews/assignments/11111111-1111-1111-1111-111111111111",
    );
    expect((init as RequestInit).method).toBe("DELETE");
    expect(new Headers((init as RequestInit).headers).get("Authorization")).toBe(
      "Bearer tok",
    );
  });

  it("surfaces a readable error when removal is forbidden", async () => {
    vi.spyOn(globalThis, "fetch").mockResolvedValue(
      jsonResponse(
        { error: { code: "permission_denied", message: "Not authorised", correlation_id: "x" } },
        403,
      ),
    );
    await expect(
      removeInterviewAssignment("11111111-1111-1111-1111-111111111111", "tok"),
    ).rejects.toThrow(/not authorised/i);
  });

  it("lists my assignments as campaign buckets", async () => {
    vi.spyOn(globalThis, "fetch").mockResolvedValue(
      jsonResponse([
        {
          campaign_id: "33333333-3333-3333-3333-333333333333",
          campaign_name: "Network Security Operations",
          stage_id: null,
          stage_name: null,
        },
      ]),
    );
    const mine = await listMyAssignments();
    expect(mine).toHaveLength(1);
    expect(mine[0]!.campaign_id).toBe("33333333-3333-3333-3333-333333333333");
  });

  it("requests the panel worklist scoped by stable campaign id", async () => {
    const fetchMock = vi.spyOn(globalThis, "fetch").mockResolvedValue(
      jsonResponse({
        to_check_in: 0, to_assess: 0, to_check_out: 0, completed: 0, total: 0,
        interviews: [],
      }),
    );
    await getPanelDashboard("33333333-3333-3333-3333-333333333333");
    const [path] = fetchMock.mock.calls[0]!;
    expect(path).toBe(
      "/api/v1/assessments/panel?campaign_id=33333333-3333-3333-3333-333333333333",
    );
  });

  it("requests the whole panel worklist when no campaign is given", async () => {
    const fetchMock = vi.spyOn(globalThis, "fetch").mockResolvedValue(
      jsonResponse({
        to_check_in: 0, to_assess: 0, to_check_out: 0, completed: 0, total: 0,
        interviews: [],
      }),
    );
    await getPanelDashboard();
    const [path] = fetchMock.mock.calls[0]!;
    expect(path).toBe("/api/v1/assessments/panel");
  });
});
