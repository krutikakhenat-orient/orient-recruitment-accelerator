import { QueryClient, QueryClientProvider } from "@tanstack/react-query";
import { render, screen, waitFor, within } from "@testing-library/react";
import userEvent from "@testing-library/user-event";
import { MemoryRouter } from "react-router-dom";
import { afterEach, beforeEach, describe, expect, it, vi } from "vitest";

import type { ReviewItem, SetupStep } from "../src/api/resources";
import { setAccessToken } from "../src/api/client";
import { App } from "../src/app/App";
import { AuthProvider } from "../src/app/auth-context";
import { ToastProvider } from "../src/components/toast";
import { isSettingUp, plainCampaignStatus, setupProgress } from "../src/lib/campaignStatus";
import {
  countByReason,
  daysWaiting,
  filterInbox,
  reasonInfo,
  sortOldestFirst,
  waitingLabel,
} from "../src/lib/reviewInbox";

/* The campaign "Set up this job" checklist + one-step open, and the Review inbox.
   All data is synthetic. */

// Relative to the real clock, because the rendered inbox measures waiting time from now.
const NOW = new Date();
const daysAgo = (n: number) => new Date(NOW.getTime() - n * 86_400_000).toISOString();

const item = (id: string, reason: string, created: string, campaign = "c1", app = `a-${id}`): ReviewItem => ({
  id,
  application_id: app,
  campaign_id: campaign,
  reason,
  detail: null,
  status: "open",
  screening_run_id: null,
  created_at: created,
});

const step = (key: string, status: SetupStep["status"]): SetupStep => ({
  key,
  title: `Step ${key}`,
  description: "Synthetic step",
  status,
  who: "Recruiter",
});

describe("plain campaign status", () => {
  it("maps internal states to a handful of HR phases", () => {
    expect(plainCampaignStatus("criteria_review").label).toBe("Setting up");
    expect(plainCampaignStatus("applications_open").label).toBe("Open for applications");
    expect(plainCampaignStatus("screening").label).toBe("Reviewing candidates");
    expect(plainCampaignStatus("interviewing").label).toBe("Interviewing");
    expect(plainCampaignStatus("cancelled").tone).toBe("danger");
    expect(isSettingUp("draft")).toBe(true);
    expect(isSettingUp("applications_open")).toBe(false);
  });

  it("finds the next setup step and counts progress", () => {
    const p = setupProgress([step("upload_jd", "done"), step("approve_jd", "needs_approver"), step("open", "waiting")]);
    expect(p.done).toBe(1);
    expect(p.total).toBe(3);
    expect(p.next?.key).toBe("approve_jd");
    expect(p.nextNumber).toBe(2);
    expect(setupProgress([step("open", "done")]).next).toBeNull();
  });
});

describe("review inbox helpers", () => {
  const items = [
    item("new", "borderline_score", daysAgo(0)),
    item("old", "missing_mandatory_evidence", daysAgo(5)),
    item("mid", "missing_mandatory_evidence", daysAgo(2)),
  ];

  it("sorts oldest first and labels waiting time", () => {
    expect(sortOldestFirst(items).map((i) => i.id)).toEqual(["old", "mid", "new"]);
    expect(waitingLabel(daysWaiting(daysAgo(0), NOW))).toBe("Today");
    expect(waitingLabel(daysWaiting(daysAgo(1), NOW))).toBe("1 day");
    expect(waitingLabel(daysWaiting(daysAgo(5), NOW))).toBe("5 days");
    expect(waitingLabel(daysWaiting(null, NOW))).toBe("—");
  });

  it("filters by reason and by overdue, and counts per reason", () => {
    expect(filterInbox(items, "all", NOW)).toHaveLength(3);
    expect(filterInbox(items, "overdue", NOW).map((i) => i.id)).toEqual(["old"]);
    expect(filterInbox(items, "missing_mandatory_evidence", NOW)).toHaveLength(2);
    expect(countByReason(items).get("missing_mandatory_evidence")).toBe(2);
  });

  it("explains reasons in plain words without treating missing evidence as absence", () => {
    expect(reasonInfo("missing_mandatory_evidence").label).toBe("Missing info");
    expect(reasonInfo("missing_mandatory_evidence").explain).toMatch(/may just be unstated/i);
    expect(reasonInfo("something_new").label).toBe("something new");
  });
});

// ---------------------------------------------------------------------------------------
// Rendered flows
// ---------------------------------------------------------------------------------------

const ADMIN_PERMS = [
  "application.review",
  "candidate.view",
  "campaign.edit",
  "campaign.publish",
  "campaign.create",
  "jd.upload",
  "jd.review",
  "jd.approve",
  "interview.approve",
  "waitlist.manage",
  "screening.execute",
];

type Route = (url: string, init?: RequestInit) => unknown;

function mockApi(route: Route, perms = ADMIN_PERMS, assigned: string[] = ["c1", "c2"]) {
  return vi.spyOn(globalThis, "fetch").mockImplementation((input, init) => {
    const url = typeof input === "string" ? input : input.toString();
    if (url.endsWith("/api/v1/auth/me")) {
      return Promise.resolve(
        json({
          user_id: "u1",
          organisation_id: "o1",
          email: "synthetic.admin@example.com",
          role_names: ["recruiter_admin"],
          permissions: perms,
          assigned_campaign_ids: assigned,
        }),
      );
    }
    const body = route(url, init);
    return Promise.resolve(json(body ?? []));
  });
}

function json(body: unknown): Response {
  return new Response(JSON.stringify(body), { status: 200, headers: { "Content-Type": "application/json" } });
}

const campaign = (id: string, name: string, state: string, extra: Record<string, unknown> = {}) => ({
  id,
  project_id: "p1",
  name,
  position_title: `${name} role`,
  number_of_openings: 1,
  state,
  approved_jd_version_id: null,
  approved_rule_set_version_id: null,
  approved_form_version_id: null,
  active_threshold_version_id: null,
  privacy_notice_version: null,
  version: 1,
  ...extra,
});

const application = (id: string, campaignId: string, fullName: string) => ({
  id,
  campaign_id: campaignId,
  candidate_id: `cand-${id}`,
  state: "under_review",
  answers: { full_name: fullName },
  version: 1,
});

function renderAt(path: string): void {
  vi.stubGlobal(
    "matchMedia",
    (query: string) =>
      ({
        matches: false,
        media: query,
        addEventListener: () => undefined,
        removeEventListener: () => undefined,
        addListener: () => undefined,
        removeListener: () => undefined,
        onchange: null,
        dispatchEvent: () => false,
      }) as unknown as MediaQueryList,
  );
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
  vi.unstubAllGlobals();
  localStorage.clear();
  setAccessToken("tok");
});
afterEach(() => {
  setAccessToken(null);
  vi.unstubAllGlobals();
});

describe("review inbox page", () => {
  it("lists items from every assigned job without choosing a campaign, oldest first", async () => {
    mockApi((url) => {
      if (url.endsWith("/api/v1/campaigns")) return [campaign("c1", "SYNTHETIC Analyst", "applications_open"), campaign("c2", "SYNTHETIC Engineer", "applications_open")];
      if (url.includes("/reviews?campaign_id=c1")) return [item("r1", "borderline_score", daysAgo(1), "c1", "a1")];
      if (url.includes("/reviews?campaign_id=c2")) return [item("r2", "missing_mandatory_evidence", daysAgo(6), "c2", "a2")];
      if (url.includes("/applications?campaign_id=c1")) return [application("a1", "c1", "Synthetic Asha")];
      if (url.includes("/applications?campaign_id=c2")) return [application("a2", "c2", "Synthetic Ravi")];
      return [];
    });
    renderAt("/reviews");

    const list = await screen.findByRole("list", { name: "Candidates waiting for review" });
    await within(list).findByText("Synthetic Ravi");
    const rows = within(list).getAllByRole("listitem");
    expect(rows).toHaveLength(2);
    // Oldest (6 days, overdue) first.
    expect(rows[0]).toHaveTextContent("Synthetic Ravi");
    expect(rows[0]).toHaveTextContent("6 days");
    expect(rows[1]).toHaveTextContent("Synthetic Asha");
    expect(screen.queryByLabelText("Campaign")).not.toBeInTheDocument();

    // Filter chips narrow the list.
    await userEvent.click(screen.getByRole("button", { name: /^Missing info/ }));
    expect(within(list).getAllByRole("listitem")).toHaveLength(1);
    expect(within(list).getByText("Synthetic Ravi")).toBeInTheDocument();
  });

  it("needs a reason before a decision can be recorded", async () => {
    const fetchMock = mockApi((url, init) => {
      if (url.endsWith("/api/v1/campaigns")) return [campaign("c1", "SYNTHETIC Analyst", "applications_open")];
      if (url.includes("/reviews?campaign_id=c1")) return [item("r1", "borderline_score", daysAgo(0), "c1", "a1")];
      if (url.includes("/applications?campaign_id=c1")) return [application("a1", "c1", "Synthetic Asha")];
      if (url.includes("/reviews/r1/actions") && init?.method === "POST")
        return { id: "act1", review_item_id: "r1", action_type: "recommend_waitlist", reason: "x", resolves_item: true };
      return [];
    });
    renderAt("/reviews");
    await userEvent.click(await screen.findByRole("button", { name: /Synthetic Asha/ }));
    const waitlist = screen.getByRole("button", { name: "Waitlist" });
    expect(waitlist).toBeDisabled();
    await userEvent.type(screen.getByLabelText(/Your reason/), "Synthetic reason: strong backup");
    expect(waitlist).toBeEnabled();
    await userEvent.click(waitlist);
    await waitFor(() =>
      expect(fetchMock.mock.calls.some(([u, i]) => String(u).includes("/reviews/r1/actions") && i?.method === "POST")).toBe(true),
    );
  });

  it("shows an all-caught-up state when nothing is waiting", async () => {
    mockApi((url) => {
      if (url.endsWith("/api/v1/campaigns")) return [campaign("c1", "SYNTHETIC Analyst", "applications_open")];
      return [];
    });
    renderAt("/reviews");
    expect(await screen.findByText("All caught up.")).toBeInTheDocument();
  });
});

describe("campaign setup", () => {
  const setupStatus = (steps: SetupStep[], next: string | null) => ({
    campaign_id: "c1",
    is_open: false,
    next_step_key: next,
    steps,
    latest_jd_version_id: null,
    latest_jd_status: null,
    draft_form_version_id: null,
  });

  it("opens on the Setup tab with the next step highlighted", async () => {
    mockApi((url) => {
      if (url.includes("/campaigns/c1/setup-status"))
        return setupStatus(
          [step("upload_jd", "todo"), step("approve_jd", "waiting"), step("criteria", "waiting"), step("form", "todo"), step("open", "waiting")],
          "upload_jd",
        );
      if (url.endsWith("/api/v1/campaigns/c1")) return campaign("c1", "SYNTHETIC Analyst", "draft");
      return [];
    });
    renderAt("/campaigns/c1");
    expect(await screen.findByRole("heading", { name: "Set up this job" })).toBeInTheDocument();
    expect(screen.getByRole("tab", { name: /Setup/ })).toHaveAttribute("aria-selected", "true");
    expect(screen.getByText("0 of 5 done")).toBeInTheDocument();
    const current = screen.getByText("Step upload_jd").closest("li");
    expect(current).toHaveAttribute("aria-current", "step");
    expect(within(current as HTMLElement).getByText("Next step")).toBeInTheDocument();
    // No apply link while setting up.
    expect(screen.queryByLabelText("Public apply link")).not.toBeInTheDocument();
  });

  it("opens the job in one confirmed step", async () => {
    const fetchMock = mockApi((url, init) => {
      if (url.includes("/campaigns/c1/open-for-applications") && init?.method === "POST")
        return campaign("c1", "SYNTHETIC Analyst", "applications_open");
      if (url.includes("/campaigns/c1/setup-status"))
        return setupStatus(
          [step("upload_jd", "done"), step("approve_jd", "done"), step("criteria", "done"), step("form", "done"), step("open", "todo")],
          "open",
        );
      if (url.endsWith("/api/v1/campaigns/c1")) return campaign("c1", "SYNTHETIC Analyst", "draft");
      return [];
    });
    renderAt("/campaigns/c1");
    await userEvent.click(await screen.findByRole("button", { name: "Open for applications" }));
    const dialog = await screen.findByRole("dialog", { name: "Open this job for applications?" });
    await userEvent.click(within(dialog).getByRole("button", { name: "Open for applications" }));
    await waitFor(() =>
      expect(
        fetchMock.mock.calls.some(([u, i]) => String(u).includes("/open-for-applications") && i?.method === "POST"),
      ).toBe(true),
    );
  });

  it("shows the apply link at the top once the job is open, and starts on Candidates", async () => {
    mockApi((url) => {
      if (url.includes("/campaigns/c1/setup-status"))
        return { ...setupStatus([step("open", "done")], null), is_open: true };
      if (url.endsWith("/api/v1/campaigns/c1")) return campaign("c1", "SYNTHETIC Analyst", "applications_open");
      return [];
    });
    renderAt("/campaigns/c1");
    const link = await screen.findByLabelText("Public apply link");
    expect((link as HTMLInputElement).value).toMatch(/\/apply\/c1$/);
    expect(screen.getByRole("tab", { name: /Candidates/ })).toHaveAttribute("aria-selected", "true");
    expect(screen.getAllByText("Open for applications").length).toBeGreaterThan(0);
  });

  it("tells a recruiter that an admin opens the job", async () => {
    mockApi(
      (url) => {
        if (url.includes("/campaigns/c1/setup-status"))
          return setupStatus([step("form", "done"), step("open", "todo")], "open");
        if (url.endsWith("/api/v1/campaigns/c1")) return campaign("c1", "SYNTHETIC Analyst", "draft");
        return [];
      },
      ["campaign.edit", "jd.upload", "jd.review", "candidate.view", "screening.execute", "application.review"],
      ["c1"],
    );
    renderAt("/campaigns/c1");
    expect(await screen.findByText("A Recruiter Admin opens it")).toBeInTheDocument();
    expect(screen.queryByRole("button", { name: "Open for applications" })).not.toBeInTheDocument();
  });
});
