/* Employee portal: navigation, first-days checklist with live status, the home question box
   handing over to Ask HR, and policy search/read status. Axe on each page. SYNTHETIC data. */
import { QueryClient, QueryClientProvider } from "@tanstack/react-query";
import { render, screen, waitFor, within } from "@testing-library/react";
import userEvent from "@testing-library/user-event";
import axe from "axe-core";
import { MemoryRouter } from "react-router-dom";
import { beforeEach, describe, expect, it, vi, type Mock } from "vitest";

import * as automation from "../src/api/automation";
import * as resources from "../src/api/resources";
import { ToastProvider } from "../src/components/toast";
import { EmployeeShell } from "../src/pages/employee/EmployeeShell";

vi.mock("../src/api/automation", async (importOriginal) => {
  const actual = await importOriginal<typeof import("../src/api/automation")>();
  return { ...actual, listPolicies: vi.fn(), askAssistant: vi.fn(), listMyHrQuestions: vi.fn(),
    acknowledgePolicy: vi.fn() };
});
vi.mock("../src/api/resources", async (importOriginal) => {
  const actual = await importOriginal<typeof import("../src/api/resources")>();
  return { ...actual, getInductionStatus: vi.fn(), getInductionVideoMeta: vi.fn(),
    fetchInductionVideoBlob: vi.fn() };
});
vi.mock("../src/app/auth-context", () => ({
  useAuth: () => ({ signOut: vi.fn(), token: () => "tok", hasPermission: () => false }),
}));

const a = automation as unknown as Record<string, Mock>;
const r = resources as unknown as Record<string, Mock>;

function policy(over: Partial<automation.Policy>): automation.Policy {
  return {
    id: "p1", family_id: "f1", title: "SYNTHETIC Annual leave", kind: "policy", department: null,
    body: "SYNTHETIC: 20 days of paid leave.", version: 1, status: "approved", effective_date: null,
    review_due_date: null, updated_at: "2026-11-01T00:00:00Z", audience: ["everyone"],
    index_status: "ready", index_error: null, indexed_at: null, source_filename: null,
    has_file: false, acknowledged: false, acknowledgement_count: 0, ...over,
  };
}

function renderAt(path: string): ReturnType<typeof render> {
  const qc = new QueryClient({ defaultOptions: { queries: { retry: false } } });
  return render(
    <QueryClientProvider client={qc}>
      <MemoryRouter initialEntries={[path]}>
        <ToastProvider><EmployeeShell /></ToastProvider>
      </MemoryRouter>
    </QueryClientProvider>,
  );
}

async function noAxe(node: Element): Promise<void> {
  const res = await axe.run(node, { rules: { "color-contrast": { enabled: false } } });
  expect(res.violations.map((v) => `${v.id}: ${v.help}`)).toEqual([]);
}

beforeEach(() => {
  vi.clearAllMocks();
  r.getInductionStatus!.mockResolvedValue({ has_video: true, completed: false, completed_at: null });
  a.listPolicies!.mockResolvedValue([
    policy({ id: "p1", title: "SYNTHETIC Annual leave", acknowledged: true }),
    policy({ id: "p2", title: "SYNTHETIC Travel", body: "SYNTHETIC: book travel via HR." }),
    policy({ id: "p3", title: "SYNTHETIC Draft", status: "draft" }),
  ]);
  a.listMyHrQuestions!.mockResolvedValue([]);
});

describe("Employee portal", () => {
  it("home shows a clear checklist with live status and the four destinations", async () => {
    const { container } = renderAt("/");
    expect(await screen.findByRole("heading", { level: 1, name: "Welcome to Orient" })).toBeInTheDocument();
    const nav = screen.getByRole("navigation", { name: "Employee" });
    for (const name of ["Home", "Ask HR", "Policies", "Induction"]) {
      expect(within(nav).getByRole("link", { name })).toBeInTheDocument();
    }
    expect(within(nav).getByRole("link", { name: "Home" })).toHaveClass("is-active");
    await screen.findByText(/1 of 2 read/);
    const steps = container.querySelector(".emp-steps");
    expect(steps).toHaveTextContent(/Watch the induction video.*To do/);
    expect(steps).toHaveTextContent(/Get your certificate.*Locked/);
    // Drafts are not counted: 1 of the 2 published policies is read.
    expect(steps).toHaveTextContent(/1 of 2 read/);
    expect(screen.getByText("0 of 3 done")).toBeInTheDocument();
    await noAxe(container);
  });

  it("the home question box opens Ask HR and asks the question", async () => {
    a.askAssistant!.mockResolvedValue({
      answered: true, answer: "SYNTHETIC: 20 days of paid leave. [1]",
      sources: [{ ref: 1, policy_id: "p1", title: "SYNTHETIC Annual leave", version: 1, page: null, excerpt: "" }],
      route_to_hr: false, note: "Answers come only from approved company HR policy.", outcome: "answered",
      answered_via: "keyword", smart_search_unavailable: false, query_id: "q1",
    });
    renderAt("/");
    await userEvent.type(await screen.findByLabelText("Your question for HR"), "How much leave?");
    await userEvent.click(screen.getByRole("button", { name: "Ask" }));
    expect(await screen.findByRole("heading", { level: 1, name: "How can we help?" })).toBeInTheDocument();
    await waitFor(() => expect(a.askAssistant).toHaveBeenCalledWith("How much leave?"));
    expect(await screen.findByText(/SYNTHETIC Annual leave, version 1/)).toBeInTheDocument();
    // The full Ask HR page does not also show the floating chat button.
    expect(screen.queryByRole("button", { name: /ask hr a policy question/i })).not.toBeInTheDocument();
  });

  it("Ask HR offers example questions before the first one", async () => {
    const { container } = renderAt("/ask-hr");
    const group = await screen.findByRole("group", { name: "Example questions" });
    expect(within(group).getAllByRole("button").length).toBeGreaterThan(2);
    await noAxe(container);
  });

  it("policies can be searched and show read status in words", async () => {
    const { container } = renderAt("/policies");
    const list = await screen.findByRole("list", { name: "Policies" });
    expect(within(list).getAllByRole("listitem")).toHaveLength(2); // the draft is not shown
    expect(within(list).getByText("Read")).toBeInTheDocument();
    expect(within(list).getByText("To read")).toBeInTheDocument();
    expect(screen.getByText(/1 to read/)).toBeInTheDocument();
    await userEvent.type(screen.getByLabelText("Search policies"), "travel");
    expect(within(list).getAllByRole("listitem")).toHaveLength(1);
    await noAxe(container);
  });
});
