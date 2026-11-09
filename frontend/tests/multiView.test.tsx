import { QueryClient, QueryClientProvider } from "@tanstack/react-query";
import { render, screen, waitFor, within } from "@testing-library/react";
import userEvent from "@testing-library/user-event";
import { MemoryRouter } from "react-router-dom";
import { afterEach, beforeEach, describe, expect, it, vi } from "vitest";

import { setAccessToken } from "../src/api/client";
import { App } from "../src/app/App";
import { AuthProvider } from "../src/app/auth-context";
import { ToastProvider } from "../src/components/toast";

/* Tests for the multiple-views layer (Grid / List / Table, search, state filter, "Mine") on the
   Campaigns page and for the searchable, permission-filtered Settings directory. All data is
   synthetic. */

const PROJECT_ID = "11111111-1111-1111-1111-111111111111";
const MINE_ID = "aaaaaaaa-aaaa-aaaa-aaaa-aaaaaaaaaaaa";
const OTHER_ID = "bbbbbbbb-bbbb-bbbb-bbbb-bbbbbbbbbbbb";

function makeCampaign(id: string, name: string, position: string, state: string) {
  return {
    id,
    project_id: PROJECT_ID,
    name,
    position_title: position,
    number_of_openings: 2,
    state,
    approved_jd_version_id: null,
    approved_rule_set_version_id: null,
    approved_form_version_id: null,
    active_threshold_version_id: null,
    privacy_notice_version: null,
    version: 1,
  };
}

const CAMPAIGNS = [
  makeCampaign(MINE_ID, "Synthetic Backend Drive", "Backend Engineer", "applications_open"),
  makeCampaign(OTHER_ID, "Synthetic Design Drive", "Product Designer", "draft"),
];

function me(permissions: string[]) {
  return {
    user_id: "u1",
    organisation_id: "o1",
    email: "synthetic.user@example.com",
    role_names: ["recruiter_admin"],
    permissions,
    assigned_campaign_ids: [MINE_ID],
  };
}

function jsonResponse(body: unknown): Response {
  return new Response(JSON.stringify(body), {
    status: 200,
    headers: { "Content-Type": "application/json" },
  });
}

function mockApi(permissions: string[]): void {
  vi.spyOn(globalThis, "fetch").mockImplementation((input: RequestInfo | URL) => {
    const u = typeof input === "string" ? input : input.toString();
    if (u.endsWith("/api/v1/auth/me")) return Promise.resolve(jsonResponse(me(permissions)));
    if (u.endsWith("/api/v1/campaigns")) return Promise.resolve(jsonResponse(CAMPAIGNS));
    if (u.includes("/api/v1/users")) return Promise.resolve(jsonResponse([]));
    return Promise.resolve(jsonResponse({}));
  });
}

function renderAppAt(path: string): void {
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
  setAccessToken("tok");
});
afterEach(() => setAccessToken(null));

describe("Campaigns multiple views", () => {
  it("defaults to the table and switches to grid and list, remembering the choice", async () => {
    mockApi(["campaign.create", "candidate.view"]);
    renderAppAt("/campaigns");

    expect(await screen.findByRole("table")).toBeInTheDocument();
    const layout = screen.getByRole("radiogroup", { name: /layout/i });

    await userEvent.click(within(layout).getByRole("radio", { name: /grid/i }));
    expect(screen.queryByRole("table")).not.toBeInTheDocument();
    expect(screen.getAllByRole("article")).toHaveLength(2);
    expect(localStorage.getItem("orient.view.campaigns")).toBe("grid");

    await userEvent.click(within(layout).getByRole("radio", { name: /list/i }));
    expect(screen.queryByRole("article")).not.toBeInTheDocument();
    expect(screen.getByText("Synthetic Backend Drive")).toBeInTheDocument();
  });

  it("restores the saved layout on the next visit", async () => {
    localStorage.setItem("orient.view.campaigns", "grid");
    mockApi(["campaign.create", "candidate.view"]);
    renderAppAt("/campaigns");
    expect(await screen.findAllByRole("article")).toHaveLength(2);
  });

  it("filters by search text, by state, and by Mine", async () => {
    mockApi(["campaign.create", "candidate.view"]);
    renderAppAt("/campaigns");
    expect(await screen.findByText("Synthetic Backend Drive")).toBeInTheDocument();
    expect(screen.getByText("Synthetic Design Drive")).toBeInTheDocument();

    // Search by position title.
    await userEvent.type(screen.getByRole("searchbox", { name: /search campaigns/i }), "designer");
    await waitFor(() => expect(screen.queryByText("Synthetic Backend Drive")).not.toBeInTheDocument());
    expect(screen.getByText("Synthetic Design Drive")).toBeInTheDocument();
    await userEvent.clear(screen.getByRole("searchbox", { name: /search campaigns/i }));

    // Filter by state.
    await userEvent.selectOptions(screen.getByRole("combobox", { name: /filter by state/i }), "draft");
    await waitFor(() => expect(screen.queryByText("Synthetic Backend Drive")).not.toBeInTheDocument());
    await userEvent.selectOptions(screen.getByRole("combobox", { name: /filter by state/i }), "");

    // Mine = only campaigns the signed-in user is assigned to.
    await userEvent.click(screen.getByRole("button", { name: "Mine" }));
    await waitFor(() => expect(screen.queryByText("Synthetic Design Drive")).not.toBeInTheDocument());
    expect(screen.getByText("Synthetic Backend Drive")).toBeInTheDocument();
    expect(screen.getByRole("button", { name: "Mine" })).toHaveAttribute("aria-pressed", "true");
  });
});

describe("Settings directory", () => {
  it("lists only the destinations the user may open", async () => {
    mockApi(["user.manage"]);
    renderAppAt("/settings");
    expect(await screen.findByText("Users & roles")).toBeInTheDocument();
    expect(screen.getByText("Create a staff user")).toBeInTheDocument();
    // Needs privacy_request.manage / system.configure, which this user lacks.
    expect(screen.queryByText("Retention policy")).not.toBeInTheDocument();
    // Needs talent_pool.search.
    expect(screen.queryByText("Talent pool")).not.toBeInTheDocument();
  });

  it("filters the cards with the search box", async () => {
    mockApi(["user.manage", "system.configure"]);
    renderAppAt("/settings");
    expect(await screen.findByText("Retention policy")).toBeInTheDocument();
    await userEvent.type(screen.getByRole("searchbox", { name: /search settings/i }), "retention");
    await waitFor(() => expect(screen.queryByText("Users & roles")).not.toBeInTheDocument());
    expect(screen.getByText("Retention policy")).toBeInTheDocument();
  });

  it("opens the matching tab on the Privacy page from a directory link", async () => {
    mockApi(["system.configure"]);
    renderAppAt("/privacy?tab=rights");
    const selected = await screen.findByRole("tab", { name: "Candidate rights" });
    expect(selected).toHaveAttribute("aria-selected", "true");
    expect(screen.getByRole("tab", { name: "Retention policy" })).toHaveAttribute("aria-selected", "false");
  });
});
