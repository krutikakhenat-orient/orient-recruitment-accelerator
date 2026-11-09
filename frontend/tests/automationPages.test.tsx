import { QueryClient, QueryClientProvider } from "@tanstack/react-query";
import { render, screen, waitFor, within } from "@testing-library/react";
import userEvent from "@testing-library/user-event";
import { MemoryRouter } from "react-router-dom";
import { afterEach, beforeEach, describe, expect, it, vi } from "vitest";

import type { Journey } from "../src/api/automation";
import { setAccessToken } from "../src/api/client";
import { App } from "../src/app/App";
import { AuthProvider } from "../src/app/auth-context";
import { JourneyTracker } from "../src/components/JourneyTracker";
import { ToastProvider } from "../src/components/toast";
import { Action, toneFor } from "../src/components/ui";

/* Tests for the long-term automation UI: the public user guide, the candidate journey, the
   candidate's interview-confirmation page, one-line action hints, and the permission-filtered
   navigation. All data is synthetic. */

function jsonResponse(body: unknown, status = 200): Response {
  return new Response(JSON.stringify(body), {
    status,
    headers: { "Content-Type": "application/json" },
  });
}

function renderAt(path: string): void {
  const qc = new QueryClient({ defaultOptions: { queries: { retry: false } } });
  render(
    <QueryClientProvider client={qc}>
      <MemoryRouter initialEntries={[path]}>
        <AuthProvider>
          <ToastProvider>
            <App />
          </ToastProvider>
        </AuthProvider>
      </MemoryRouter>
    </QueryClientProvider>,
  );
}

beforeEach(() => {
  vi.restoreAllMocks();
  localStorage.clear();
  setAccessToken(null);
});
afterEach(() => setAccessToken(null));

describe("user guide", () => {
  it("is public and explains the journey, roles and placeholders", async () => {
    renderAt("/guide");
    expect(await screen.findByRole("heading", { name: "User guide" })).toBeInTheDocument();
    expect(screen.getByRole("heading", { name: "The candidate journey" })).toBeInTheDocument();
    // Shown as a diagram and as a table.
    expect(screen.getAllByText("Interview confirmed", { exact: false }).length).toBeGreaterThan(1);
    expect(screen.getByRole("list", { name: "How a job opening goes live" })).toBeInTheDocument();
    expect(screen.getByRole("list", { name: "Candidate journey" })).toBeInTheDocument();
    expect(screen.getByRole("heading", { name: "Messages and connections" })).toBeInTheDocument();
    expect(screen.getByText("Not sent: no provider connected")).toBeInTheDocument();
    // Signed-out visitors get a way back to sign in.
    expect(screen.getByRole("link", { name: "Go to sign in" })).toBeInTheDocument();
  });

  it("filters its content with the search box", async () => {
    renderAt("/guide");
    await screen.findByRole("heading", { name: "User guide" });
    await userEvent.type(screen.getByRole("searchbox", { name: /search this guide/i }), "waitlist");
    await waitFor(() =>
      expect(screen.queryByRole("heading", { name: "The candidate journey" })).not.toBeInTheDocument(),
    );
    expect(screen.getAllByText(/waitlist/i).length).toBeGreaterThan(0);

    await userEvent.clear(screen.getByRole("searchbox", { name: /search this guide/i }));
    await userEvent.type(screen.getByRole("searchbox", { name: /search this guide/i }), "zzzzqqq");
    expect(await screen.findByText(/nothing in the guide matches/i)).toBeInTheDocument();
  });
});

const JOURNEY: Journey = {
  application_id: "a1",
  campaign_id: "c1",
  candidate_name: "Synthetic Candidate",
  role_title: "Synthetic Engineer",
  application_state: "interview_scheduled",
  current_stage: "interview_confirmed",
  next_step: "Waiting for the candidate to confirm the interview.",
  closed: false,
  stages: [
    { key: "applied", label: "Applied", description: "Submitted the form.", owner: "Candidate", status: "done", optional: false, detail: null, at: null },
    { key: "pre_screening", label: "Short AI interview", description: "Optional.", owner: "Candidate", status: "skipped", optional: true, detail: "Not used for this candidate.", at: null },
    { key: "interview_confirmed", label: "Interview confirmed", description: "Candidate replies.", owner: "Candidate", status: "current", optional: false, detail: "Waiting for the candidate's reply.", at: null },
    { key: "offer", label: "Offer", description: "Sent later.", owner: "Recruiter admin", status: "upcoming", optional: false, detail: null, at: null },
  ],
};

describe("JourneyTracker", () => {
  it("shows what happens next and each step with words, not just colour", () => {
    render(<JourneyTracker journey={JOURNEY} />);
    const status = screen.getByRole("status");
    expect(within(status).getByText(/waiting for the candidate to confirm/i)).toBeInTheDocument();
    const list = screen.getByRole("list", { name: /journey of synthetic candidate/i });
    const items = within(list).getAllByRole("listitem");
    expect(items).toHaveLength(4);
    expect(within(items[0]!).getByText("Done")).toBeInTheDocument();
    expect(within(items[1]!).getByText("Not used")).toBeInTheDocument();
    expect(within(items[2]!).getByText("Now")).toBeInTheDocument();
    expect(within(items[3]!).getByText("Later")).toBeInTheDocument();
    expect(within(items[1]!).getByText("Optional")).toBeInTheDocument();
    expect(screen.getAllByText(/handled by/i).length).toBe(4);
  });
});

describe("candidate interview confirmation page", () => {
  const preview = {
    state: "open",
    first_name: "Synthetic",
    role_title: "Synthetic Engineer",
    when: "2026-12-01 at 10:00",
    where: "Head office",
    mode: "in person",
    message: "Please tell us whether you can attend.",
  };

  it("shows the invitation and records the candidate's reply", async () => {
    const fetchMock = vi.spyOn(globalThis, "fetch").mockImplementation((input, init) => {
      const url = typeof input === "string" ? input : input.toString();
      if (url.endsWith("/respond")) {
        expect(JSON.parse(String(init?.body))).toEqual({ response: "confirmed" });
        return Promise.resolve(jsonResponse({ response: "confirmed", message: "Thank you. Your attendance is confirmed." }));
      }
      return Promise.resolve(jsonResponse(preview));
    });
    renderAt("/confirm/some-token");
    expect(await screen.findByText(/hello synthetic/i)).toBeInTheDocument();
    expect(screen.getByText("Head office")).toBeInTheDocument();
    await userEvent.click(screen.getByRole("button", { name: /yes, i can attend/i }));
    expect(await screen.findByText(/your attendance is confirmed/i)).toBeInTheDocument();
    // The page needs no sign-in: no request carried a bearer token.
    const sentToken = fetchMock.mock.calls.some(([, init]) =>
      new Headers((init as RequestInit | undefined)?.headers).has("Authorization"),
    );
    expect(sentToken).toBe(false);
  });

  it("shows a generic message for an invalid or expired link", async () => {
    vi.spyOn(globalThis, "fetch").mockResolvedValue(
      jsonResponse({ error: { code: "not_found", message: "This link is not valid or has expired.", correlation_id: null } }, 404),
    );
    renderAt("/confirm/bad");
    expect(await screen.findByText(/not valid or has expired/i)).toBeInTheDocument();
    expect(screen.queryByRole("button", { name: /i can attend/i })).not.toBeInTheDocument();
  });
});

describe("shared building blocks", () => {
  it("gives every action a visible one-line explanation tied to the button", () => {
    render(<Action label="Run check" hint="Records one reminder per application." onClick={() => undefined} />);
    const button = screen.getByRole("button", { name: "Run check" });
    const hintId = button.getAttribute("aria-describedby");
    expect(hintId).toBeTruthy();
    expect(document.getElementById(hintId ?? "")?.textContent).toBe("Records one reminder per application.");
  });

  it("maps workflow statuses to tones", () => {
    expect(toneFor("overdue")).toBe("danger");
    expect(toneFor("at_risk")).toBe("warn");
    expect(toneFor("on_track")).toBe("ok");
    expect(toneFor("unconfigured")).toBe("warn");
    expect(toneFor("simulated")).toBe("info");
    expect(toneFor("planned")).toBe("neutral");
  });
});

describe("navigation follows permissions", () => {
  const ME = (permissions: string[]) => ({
    user_id: "u1",
    organisation_id: "o1",
    email: "synthetic.user@example.com",
    role_names: ["recruiter"],
    permissions,
    assigned_campaign_ids: [],
  });

  function mock(permissions: string[]): void {
    setAccessToken("tok");
    vi.spyOn(globalThis, "fetch").mockImplementation((input) => {
      const url = typeof input === "string" ? input : input.toString();
      if (url.endsWith("/api/v1/auth/me")) return Promise.resolve(jsonResponse(ME(permissions)));
      return Promise.resolve(jsonResponse([]));
    });
  }

  it("shows the new pages only to people who may use them, and the guide to everyone", async () => {
    mock(["candidate.view", "hiring_decision.recommend"]);
    renderAt("/");
    const nav = await screen.findByRole("navigation", { name: /primary navigation/i }).catch(() => null);
    const sidebar = nav ?? (await screen.findByLabelText(/primary navigation/i));
    expect(within(sidebar).getByRole("link", { name: /shortlisting clock/i })).toBeInTheDocument();
    expect(within(sidebar).getByRole("link", { name: /offers & joining/i })).toBeInTheDocument();
    expect(within(sidebar).getByRole("link", { name: /user guide/i })).toBeInTheDocument();
    // Needs audit.view / waitlist.manage / settings permissions this user lacks.
    expect(within(sidebar).queryByRole("link", { name: /audit log/i })).not.toBeInTheDocument();
    expect(within(sidebar).queryByRole("link", { name: /waitlist/i })).not.toBeInTheDocument();
    expect(within(sidebar).queryByRole("link", { name: /^settings$/i })).not.toBeInTheDocument();
  });
});
