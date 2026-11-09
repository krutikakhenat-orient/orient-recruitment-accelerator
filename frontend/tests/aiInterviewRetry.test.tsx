import { QueryClient, QueryClientProvider } from "@tanstack/react-query";
import { render, screen, waitFor, within } from "@testing-library/react";
import userEvent from "@testing-library/user-event";
import { MemoryRouter } from "react-router-dom";
import { afterEach, beforeEach, describe, expect, it, vi } from "vitest";

import type { AiInterview } from "../src/api/aiInterviews";
import { setAccessToken } from "../src/api/client";
import { AuthProvider } from "../src/app/auth-context";
import { AiInterviewsPanel, attemptInfo, endedEarly } from "../src/components/AiInterviewsPanel";
import { ToastProvider } from "../src/components/toast";

/* Retrying an AI voice interview that ended early. All data is synthetic. */

// The AI interview client validates real UUIDs.
const C1 = "00000000-0000-4000-8000-0000000000c1";
const A1 = "00000000-0000-4000-8000-0000000000a1";
const S1 = "00000000-0000-4000-8000-0000000000f1";
const S2 = "00000000-0000-4000-8000-0000000000f2";

const session = (id: string, extra: Partial<AiInterview> = {}): AiInterview => ({
  id,
  application_id: A1,
  campaign_id: C1,
  status: "completed",
  role_title: "Synthetic Analyst",
  questions: [
    { id: "q1", text: "Tell me about a SYNTHETIC project.", competency: "general", source: "job_description", evidence_ref: null },
  ],
  generated_by: "deterministic_fallback",
  approved_at: null,
  link_expires_at: null,
  consent_given_at: null,
  start_count: 1,
  completed_at: "2026-11-08T04:41:25Z",
  end_reason: "candidate_requested_stop",
  has_result: true,
  summary: { overview: "SYNTHETIC overview." },
  created_at: "2026-11-08T04:30:00Z",
  ...extra,
});

function json(body: unknown, status = 200): Response {
  return new Response(JSON.stringify(body), { status, headers: { "Content-Type": "application/json" } });
}

function mockApi(sessions: AiInterview[], perms: string[]) {
  return vi.spyOn(globalThis, "fetch").mockImplementation((input, init) => {
    const url = typeof input === "string" ? input : input.toString();
    if (url.endsWith("/api/v1/auth/me"))
      return Promise.resolve(
        json({
          user_id: "u1",
          organisation_id: "o1",
          email: "synthetic.admin@example.com",
          role_names: ["recruiter_admin"],
          permissions: perms,
          assigned_campaign_ids: [C1],
        }),
      );
    if (url.includes(`/sessions/${S1}/retry`) && init?.method === "POST") {
      // The server now lists the new attempt too, so its link can sit on that row.
      sessions = [
        ...sessions,
        session(S2, { status: "approved", end_reason: null, completed_at: null, created_at: "2026-11-08T05:00:00Z" }),
      ];
      return Promise.resolve(
        json(
          {
            session: session(S2, { status: "approved", end_reason: null, completed_at: null, created_at: "2026-11-08T05:00:00Z" }),
            link_url: "http://app.test/ai-interview/synthetic-token",
            link_expires_at: "2026-11-15T05:00:00Z",
          },
          201,
        ),
      );
    }
    if (url.includes(`/campaigns/${C1}/sessions`)) return Promise.resolve(json(sessions));
    return Promise.resolve(json([]));
  });
}

function renderPanel(): void {
  const qc = new QueryClient({ defaultOptions: { queries: { retry: false } } });
  render(
    <QueryClientProvider client={qc}>
      <MemoryRouter>
        <AuthProvider>
          <ToastProvider>
            <AiInterviewsPanel campaignId={C1} nameOf={() => "Synthetic Candidate"} offerable={[]} />
          </ToastProvider>
        </AuthProvider>
      </MemoryRouter>
    </QueryClientProvider>,
  );
}

beforeEach(() => {
  vi.restoreAllMocks();
  setAccessToken("tok");
});
afterEach(() => setAccessToken(null));

describe("AI interview retry", () => {
  it("numbers attempts and spots interviews that ended early", () => {
    const rows = [session(S1), session(S2, { status: "approved", created_at: "2026-11-08T05:00:00Z" })];
    const info = attemptInfo(rows);
    expect(info.get(S1)).toEqual({ attempt: 1, total: 2, latest: false });
    expect(info.get(S2)?.latest).toBe(true);
    expect(endedEarly(session(S1))).toBe(true);
    expect(endedEarly(session(S1, { end_reason: "completed" }))).toBe(false);
  });

  it("offers a retry with a reason and shows the new one-time link", async () => {
    const fetchMock = mockApi([session(S1)], ["interview.approve", "interview.schedule", "candidate.view"]);
    renderPanel();
    expect(await screen.findByText("Ended early")).toBeInTheDocument();
    expect(screen.getByText(/Candidate asked to stop/)).toBeInTheDocument();

    const retryButton = await screen.findByRole("button", { name: "Retry interview" });
    await waitFor(() => expect(retryButton).toBeEnabled());
    await userEvent.click(retryButton);
    const dialog = await screen.findByRole("dialog", { name: /Retry AI interview/ });
    const reason = within(dialog).getByLabelText("Reason");
    await userEvent.clear(reason);
    const submit = within(dialog).getByRole("button", { name: "Create new attempt & link" });
    expect(submit).toBeDisabled();
    await userEvent.type(reason, "SYNTHETIC: call dropped");
    await userEvent.click(submit);

    expect(await screen.findByLabelText(/Interview link for/)).toHaveValue(
      "http://app.test/ai-interview/synthetic-token",
    );
    const call = fetchMock.mock.calls.find(([u]) => String(u).includes(`/sessions/${S1}/retry`));
    expect(call && JSON.parse(String(call[1]?.body))).toEqual({ reason: "SYNTHETIC: call dropped" });
  });

  it("does not offer a retry on an older attempt, and locks it without approval rights", async () => {
    mockApi(
      [session(S1), session(S2, { created_at: "2026-11-08T05:00:00Z", end_reason: "completed" })],
      ["interview.schedule", "candidate.view"],
    );
    renderPanel();
    expect(await screen.findByText("A newer attempt exists.")).toBeInTheDocument();
    const retry = screen.getAllByRole("button", { name: "Retry interview" });
    expect(retry).toHaveLength(1);
    expect(retry[0]).toBeDisabled();
  });
});
