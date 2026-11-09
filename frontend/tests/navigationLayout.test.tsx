import { QueryClient, QueryClientProvider } from "@tanstack/react-query";
import { render, screen, waitFor, within } from "@testing-library/react";
import userEvent from "@testing-library/user-event";
import { MemoryRouter } from "react-router-dom";
import { afterEach, beforeEach, describe, expect, it, vi } from "vitest";

import { setAccessToken } from "../src/api/client";
import { App } from "../src/app/App";
import { AuthProvider } from "../src/app/auth-context";
import { ToastProvider } from "../src/components/toast";
import { JOURNEY, OPENING_FLOW } from "../src/lib/guideContent";

/* Navigation layout: grouping and order of the menu, live task counts, the hamburger
   (collapse on desktop, drawer on mobile) and the "How hiring works" diagrams on the
   dashboard. All data is synthetic. */

const PERMS = [
  "application.review",
  "jd.approve",
  "rule.approve",
  "candidate.view",
  "campaign.create",
  "project.create",
  "hiring_decision.approve",
  "hiring_decision.recommend",
  "waitlist.manage",
  "talent_pool.search",
  "campaign.approve",
  "user.manage",
];

function json(body: unknown): Response {
  return new Response(JSON.stringify(body), { status: 200, headers: { "Content-Type": "application/json" } });
}

function mockApi(): void {
  vi.spyOn(globalThis, "fetch").mockImplementation((input) => {
    const url = typeof input === "string" ? input : input.toString();
    if (url.endsWith("/api/v1/auth/me")) {
      return Promise.resolve(
        json({
          user_id: "u1",
          organisation_id: "o1",
          email: "synthetic.admin@example.com",
          role_names: ["recruiter_admin"],
          permissions: PERMS,
          assigned_campaign_ids: [],
        }),
      );
    }
    if (url.includes("/reports/hr-dashboard")) {
      return Promise.resolve(json({ active_campaigns: 1, open_review_items: 3, applications_by_state: {} }));
    }
    if (url.endsWith("/job-descriptions/versions/pending")) {
      const jd = (id: string) => ({
        id,
        version_number: 1,
        status: "draft",
        position_title: "SYNTHETIC Role",
        department: null,
        responsibilities: [],
        mandatory_skills: [],
        desirable_skills: [],
      });
      return Promise.resolve(json([jd("jd1"), jd("jd2")]));
    }
    return Promise.resolve(json([]));
  });
}

function setMobile(mobile: boolean): void {
  vi.stubGlobal(
    "matchMedia",
    (query: string) =>
      ({
        matches: query.includes("max-width") ? mobile : false,
        media: query,
        addEventListener: () => undefined,
        removeEventListener: () => undefined,
        addListener: () => undefined,
        removeListener: () => undefined,
        onchange: null,
        dispatchEvent: () => false,
      }) as unknown as MediaQueryList,
  );
}

function renderApp(): void {
  const qc = new QueryClient({ defaultOptions: { queries: { retry: false } } });
  render(
    <QueryClientProvider client={qc}>
      <MemoryRouter initialEntries={["/"]}>
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

describe("menu", () => {
  it("is grouped by task, in journey order, with admin last", async () => {
    setMobile(false);
    mockApi();
    renderApp();
    const sidebar = await screen.findByLabelText("Primary navigation");
    await within(sidebar).findByRole("link", { name: /^dashboard$/i });
    const text = sidebar.textContent ?? "";
    const order = ["Home", "My tasks", "Hiring", "Candidates", "Reports & admin"].map((h) => text.indexOf(h));
    expect(order.every((i) => i >= 0)).toBe(true);
    expect([...order].sort((a, b) => a - b)).toEqual(order);
    // Hiring is in pipeline order: projects -> campaigns -> decisions -> offers.
    const links = within(sidebar).getAllByRole("link").map((l) => l.getAttribute("href"));
    const pipeline = ["/projects", "/campaigns", "/decisions", "/offers"].map((p) => links.indexOf(p));
    expect([...pipeline].sort((a, b) => a - b)).toEqual(pipeline);
    expect(links.indexOf("/settings")).toBeGreaterThan(links.indexOf("/offers"));
  });

  it("shows live counts on My tasks", async () => {
    setMobile(false);
    mockApi();
    renderApp();
    const sidebar = await screen.findByLabelText("Primary navigation");
    expect(await within(sidebar).findByRole("link", { name: "Review inbox, 3 waiting" })).toBeInTheDocument();
    // Two JD versions are pending (rule-sets return none in this mock).
    expect(await within(sidebar).findByRole("link", { name: "Approvals, 2 waiting" })).toBeInTheDocument();
  });
});

describe("hamburger", () => {
  it("collapses the sidebar to icons on desktop and remembers it", async () => {
    setMobile(false);
    mockApi();
    renderApp();
    const button = await screen.findByRole("button", { name: "Hide menu" });
    expect(button).toHaveAttribute("aria-expanded", "true");
    await userEvent.click(button);
    expect(screen.getByRole("button", { name: "Show menu" })).toHaveAttribute("aria-expanded", "false");
    expect(document.querySelector(".app-shell--collapsed")).not.toBeNull();
    expect(localStorage.getItem("orient.sidebar.collapsed")).toBe("1");
    // Links keep their accessible names even when only icons are visible.
    const sidebar = screen.getByLabelText("Primary navigation");
    expect(within(sidebar).getByRole("link", { name: /^campaigns$/i })).toBeInTheDocument();
    await userEvent.click(screen.getByRole("button", { name: "Show menu" }));
    expect(document.querySelector(".app-shell--collapsed")).toBeNull();
  });

  it("opens and closes a drawer on mobile, including with Escape", async () => {
    setMobile(true);
    mockApi();
    renderApp();
    const button = await screen.findByRole("button", { name: "Show menu" });
    await userEvent.click(button);
    expect(document.querySelector(".sidebar--open")).not.toBeNull();
    expect(screen.getByRole("button", { name: "Hide menu" })).toHaveAttribute("aria-expanded", "true");
    await userEvent.keyboard("{Escape}");
    await waitFor(() => expect(document.querySelector(".sidebar--open")).toBeNull());
  });
});

describe("How hiring works", () => {
  it("shows both diagrams on the dashboard and can be hidden", async () => {
    setMobile(false);
    mockApi();
    renderApp();
    const opening = await screen.findByRole("list", { name: "How a job opening goes live" });
    expect(within(opening).getAllByRole("listitem")).toHaveLength(OPENING_FLOW.length);
    expect(screen.getByRole("list", { name: "Statuses of a job opening" })).toBeInTheDocument();

    await userEvent.click(screen.getByRole("tab", { name: /candidate journey/i }));
    const journey = screen.getByRole("list", { name: "Candidate journey" });
    expect(within(journey).getAllByRole("listitem")).toHaveLength(JOURNEY.length);

    // Every step shows who does it in words, with a legend.
    expect(within(journey).getAllByText("Candidate").length).toBeGreaterThan(0);
    expect(screen.getByLabelText("Who does each step")).toBeInTheDocument();

    // Hide: the header and a clear Show button stay on screen.
    await userEvent.click(screen.getByRole("button", { name: /hide steps/i }));
    expect(screen.queryByRole("list", { name: "Candidate journey" })).not.toBeInTheDocument();
    expect(screen.getByRole("heading", { name: "How hiring works here" })).toBeInTheDocument();
    const show = screen.getByRole("button", { name: /show steps/i });
    expect(show).toHaveAttribute("aria-expanded", "false");
    expect(localStorage.getItem("orient.howItWorks.collapsed")).toBe("1");

    // Show again: the steps come back.
    await userEvent.click(show);
    expect(screen.getByRole("button", { name: /hide steps/i })).toHaveAttribute("aria-expanded", "true");
    expect(screen.getByRole("list", { name: "Candidate journey" })).toBeInTheDocument();
    expect(localStorage.getItem("orient.howItWorks.collapsed")).toBe("0");
  });

  it("starts collapsed when it was hidden before, and can still be opened", async () => {
    localStorage.setItem("orient.howItWorks.collapsed", "1");
    setMobile(false);
    mockApi();
    renderApp();
    await userEvent.click(await screen.findByRole("button", { name: /show steps/i }));
    expect(screen.getByRole("list", { name: "How a job opening goes live" })).toBeInTheDocument();
  });
});
