/* HR policy chatbot UI: chat flow, citations, not-found and escalation, fallback banner,
   feedback, rate-limit message, HR library states, upload checks, permission states and axe.
   All data is SYNTHETIC. */
import { QueryClient, QueryClientProvider } from "@tanstack/react-query";
import { render, screen, waitFor, within } from "@testing-library/react";
import userEvent from "@testing-library/user-event";
import axe from "axe-core";
import type { ReactNode } from "react";
import { MemoryRouter } from "react-router-dom";
import { afterEach, beforeEach, describe, expect, it, vi, type Mock } from "vitest";

import * as api from "../src/api/automation";
import { ApiError } from "../src/api/client";
import { ChatPanel } from "../src/components/hr-chat/ChatPanel";
import { HrChatLauncher } from "../src/components/hr-chat/HrChatLauncher";
import { UploadPolicyDialog } from "../src/components/hr-chat/UploadPolicyDialog";
import { ToastProvider } from "../src/components/toast";
import { PoliciesPage } from "../src/pages/PoliciesPage";

vi.mock("../src/api/automation", async (importOriginal) => {
  const actual = await importOriginal<typeof import("../src/api/automation")>();
  return {
    ...actual,
    askAssistant: vi.fn(),
    escalateToHr: vi.fn(),
    sendAnswerFeedback: vi.fn(),
    listPolicies: vi.fn(),
    listUnanswered: vi.fn(),
    listMyHrQuestions: vi.fn(),
    uploadPolicy: vi.fn(),
    reindexPolicy: vi.fn(),
    getIndexStatus: vi.fn(),
  };
});

const permissions = { current: new Set<string>() };
vi.mock("../src/app/auth-context", () => ({
  useAuth: () => ({ hasPermission: (p: string) => permissions.current.has(p) }),
}));

const m = api as unknown as Record<string, Mock>;

function wrap(ui: ReactNode): ReturnType<typeof render> {
  const qc = new QueryClient({ defaultOptions: { queries: { retry: false } } });
  return render(
    <QueryClientProvider client={qc}>
      <MemoryRouter>
        <ToastProvider>{ui}</ToastProvider>
      </MemoryRouter>
    </QueryClientProvider>,
  );
}

async function expectNoAxeViolations(node: Element): Promise<void> {
  // jsdom has no layout/canvas, so colour contrast cannot be measured here; "region" is a
  // page-level rule that does not apply to a component rendered on its own.
  const result = await axe.run(node, { rules: { "color-contrast": { enabled: false }, region: { enabled: false } } });
  expect(result.violations.map((v) => `${v.id}: ${v.help}`)).toEqual([]);
}

const ANSWERED: api.AskResponse = {
  answered: true,
  answer: "SYNTHETIC: Employees receive 20 days of paid annual leave. <b>bold?</b> [1]",
  sources: [{ ref: 1, policy_id: "p1", title: "SYNTHETIC Annual leave", version: 2, page: 3, excerpt: "" }],
  route_to_hr: false,
  note: "Answers come only from approved company HR policy.",
  outcome: "answered",
  answered_via: "bedrock_kb",
  smart_search_unavailable: false,
  query_id: "q1",
};
const NOT_FOUND: api.AskResponse = {
  ...ANSWERED,
  answered: false,
  answer: "I could not find this in the approved HR policies. Please ask HR directly.",
  sources: [],
  route_to_hr: true,
  outcome: "not_found",
};

function policy(over: Partial<api.Policy>): api.Policy {
  return {
    id: "p1", family_id: "f1", title: "SYNTHETIC Annual leave", kind: "policy", department: null,
    body: "SYNTHETIC text", version: 1, status: "approved", effective_date: null,
    review_due_date: null, updated_at: "2026-11-01T00:00:00Z", audience: ["everyone"],
    index_status: "ready", index_error: null, indexed_at: null, source_filename: null,
    has_file: true, acknowledged: false, acknowledgement_count: 0, ...over,
  };
}

async function ask(text: string): Promise<void> {
  const box = screen.getByLabelText("Your question");
  await userEvent.type(box, text);
  await userEvent.click(screen.getByRole("button", { name: "Ask" }));
}

beforeEach(() => {
  vi.clearAllMocks();
  permissions.current = new Set();
  m.listMyHrQuestions!.mockResolvedValue([]);
  m.listUnanswered!.mockResolvedValue([]);
});
afterEach(() => vi.restoreAllMocks());

describe("ChatPanel", () => {
  it("shows a cited answer as plain text, announces it and returns focus to the input", async () => {
    m.askAssistant!.mockResolvedValue(ANSWERED);
    const { container } = wrap(<ChatPanel />);
    await ask("How many days of annual leave?");

    const source = await screen.findByText(/SYNTHETIC Annual leave, version 2, page 3/);
    expect(source).toBeInTheDocument();
    // HTML in an answer is shown as text, never rendered as markup (Req 5.5).
    expect(container.querySelector("b")).toBeNull();
    expect(screen.getAllByText(/<b>bold\?<\/b>/).length).toBeGreaterThan(0);
    const live = container.querySelector('[aria-live="polite"]');
    expect(live?.textContent).toContain("20 days");
    expect(screen.getByLabelText("Your question")).toHaveFocus();
    expect(screen.getByLabelText("Your question")).toHaveValue("");
    await expectNoAxeViolations(container);
  });

  it("offers Send to HR when nothing is found and sends one question with an idempotency key", async () => {
    m.askAssistant!.mockResolvedValue(NOT_FOUND);
    m.escalateToHr!.mockResolvedValue({
      id: "h1", question: "Is there a pet policy?", contact_preference: "in_app", status: "open",
      answer: null, answered_at: null, created_at: "2026-11-13T00:00:00Z",
    });
    wrap(<ChatPanel />);
    await ask("Is there a pet policy?");
    await userEvent.click(await screen.findByRole("button", { name: "Send to HR" }));

    const dialog = await screen.findByRole("dialog", { name: /send your question to hr/i });
    expect(within(dialog).getByLabelText("Question")).toHaveValue("Is there a pet policy?");
    await expectNoAxeViolations(dialog);
    await userEvent.click(within(dialog).getByLabelText(/by email/i));
    await userEvent.click(within(dialog).getByRole("button", { name: "Send to HR" }));

    await waitFor(() => expect(m.escalateToHr).toHaveBeenCalledTimes(1));
    const [body, key] = m.escalateToHr!.mock.calls[0] as [unknown, string];
    expect(body).toEqual({ question: "Is there a pet policy?", contact_preference: "email" });
    expect(typeof key).toBe("string");
    expect(key.length).toBeGreaterThan(8);
    expect(await screen.findByText(/sent to hr/i)).toBeInTheDocument();
  });

  it("replies to a greeting plainly, without a Send to HR prompt", async () => {
    m.askAssistant!.mockResolvedValue({ ...NOT_FOUND, outcome: "greeting", route_to_hr: false,
      answer: "Hello! I answer questions from the company's approved HR policies." });
    wrap(<ChatPanel />);
    await ask("hi");
    // Shown in the answer and announced once in the live region.
    expect((await screen.findAllByText(/Hello! I answer questions/)).length).toBeGreaterThan(0);
    expect(screen.queryByRole("button", { name: /send to hr/i })).not.toBeInTheDocument();
    expect(screen.queryByText(/was this helpful/i)).not.toBeInTheDocument();
  });

  it("shows the smart-search-unavailable banner on a keyword fallback", async () => {
    m.askAssistant!.mockResolvedValue({ ...ANSWERED, answered_via: "keyword", smart_search_unavailable: true });
    wrap(<ChatPanel />);
    await ask("How many days of annual leave?");
    expect(await screen.findByText(/smart search is unavailable/i)).toBeInTheDocument();
  });

  it("records not-helpful feedback with a comment", async () => {
    m.askAssistant!.mockResolvedValue(ANSWERED);
    m.sendAnswerFeedback!.mockResolvedValue({ id: "f1", query_id: "q1", helpful: false });
    wrap(<ChatPanel />);
    await ask("How many days of annual leave?");
    await userEvent.click(await screen.findByRole("button", { name: /no/i }));
    await userEvent.type(screen.getByLabelText(/what was missing/i), "Carry-forward rule");
    await userEvent.click(screen.getByRole("button", { name: /send feedback/i }));
    await waitFor(() =>
      expect(m.sendAnswerFeedback).toHaveBeenCalledWith({
        query_id: "q1", helpful: false, comment: "Carry-forward rule",
      }),
    );
    expect(await screen.findByText(/thanks for the feedback/i)).toBeInTheDocument();
  });

  it("explains a rate limit and keeps the page usable", async () => {
    m.askAssistant!.mockRejectedValue(
      new ApiError("rate_limited", "You have asked a lot of questions in a short time. Please wait a minute.",
        null, { status: 429 }),
    );
    wrap(<ChatPanel />);
    await ask("What is the leave policy?");
    expect(await screen.findByRole("alert")).toHaveTextContent(/wait a minute/i);
    expect(screen.getByLabelText("Your question")).toBeEnabled();
  });
});

describe("Policies page", () => {
  it("shows clearly what is synced, with the failure reason and a retry", async () => {
    permissions.current = new Set(["campaign.approve"]);
    m.listPolicies!.mockResolvedValue([
      policy({ id: "p1", title: "SYNTHETIC Leave", index_status: "ready" }),
      policy({ id: "p2", title: "SYNTHETIC Travel", index_status: "failed",
        index_error: "1 file(s) could not be indexed." }),
      policy({ id: "p3", title: "SYNTHETIC Draft", status: "draft", index_status: "not_indexed" }),
    ]);
    m.reindexPolicy!.mockResolvedValue(policy({ id: "p2", index_status: "indexing" }));
    const { container } = wrap(<PoliciesPage />);

    expect(await screen.findByText("Synced to chatbot")).toBeInTheDocument();
    expect(screen.getByText("Sync failed")).toBeInTheDocument();
    expect(screen.getByText(/1 file\(s\) could not be indexed/)).toBeInTheDocument();
    // One summary line tells HR the overall state.
    const summary = container.querySelector(".sync-summary");
    expect(summary).toHaveTextContent(/1 of 2 published policies are synced to the chatbot/);
    expect(summary).toHaveTextContent(/1 needs a sync/);
    // Plain status words; a draft shows no sync badge.
    expect(screen.getAllByText("Published")).toHaveLength(2);
    expect(screen.getByText("Draft")).toBeInTheDocument();
    expect(screen.getByRole("button", { name: "Publish" })).toBeInTheDocument();
    expect(screen.getByRole("button", { name: "Upload file" })).toBeInTheDocument();
    expect(screen.getByRole("tab", { name: "HR inbox" })).toBeInTheDocument();
    await userEvent.click(screen.getByRole("button", { name: "Retry sync" }));
    await waitFor(() => expect(m.reindexPolicy).toHaveBeenCalledWith("p2"));
    await expectNoAxeViolations(container);
  });

  it("gives employees the chatbot and library but no management actions", async () => {
    m.listPolicies!.mockResolvedValue([policy({})]);
    wrap(<PoliciesPage />);
    expect(await screen.findByLabelText("Your question")).toBeInTheDocument();
    expect(screen.queryByRole("button", { name: "Upload file" })).not.toBeInTheDocument();
    expect(screen.queryByRole("tab", { name: "HR inbox" })).not.toBeInTheDocument();
    expect(screen.queryByText("Synced to chatbot")).not.toBeInTheDocument();
  });
});

describe("HrChatLauncher (employee screen)", () => {
  it("opens the chat from the floating button, answers, and returns focus on close", async () => {
    m.askAssistant!.mockResolvedValue(ANSWERED);
    const { container } = wrap(<HrChatLauncher />);
    await userEvent.click(screen.getByRole("button", { name: /ask hr a policy question/i }));
    const panel = await screen.findByRole("dialog", { name: "Ask HR" });
    await expectNoAxeViolations(panel);
    await ask("How many days of annual leave?");
    expect(await within(panel).findByText(/SYNTHETIC Annual leave, version 2/)).toBeInTheDocument();
    await userEvent.click(within(panel).getByRole("button", { name: /close panel/i }));
    expect(screen.queryByRole("dialog")).not.toBeInTheDocument();
    expect(screen.getByRole("button", { name: /ask hr a policy question/i })).toHaveFocus();
    expect(container).toBeTruthy();
  });
});

describe("UploadPolicyDialog", () => {
  it("rejects an unsupported file before sending it", async () => {
    const { container } = wrap(<UploadPolicyDialog onClose={vi.fn()} onDone={vi.fn()} />);
    await expectNoAxeViolations(container);
    const input = screen.getByLabelText("File");
    await userEvent.upload(input, new File(["MZ"], "tool.exe", { type: "application/octet-stream" }),
      { applyAccept: false });
    expect(await screen.findByRole("alert")).toHaveTextContent(/only pdf, docx, txt and md/i);
    expect(screen.getByRole("button", { name: "Publish" })).toBeDisabled();
    expect(m.uploadPolicy).not.toHaveBeenCalled();
  });

  it("publishes by default; Save as draft is opt-in", async () => {
    m.uploadPolicy!.mockResolvedValue(policy({}));
    wrap(<UploadPolicyDialog onClose={vi.fn()} onDone={vi.fn()} />);
    await userEvent.upload(screen.getByLabelText("File"),
      new File(["SYNTHETIC leave text"], "leave.txt", { type: "text/plain" }));
    await userEvent.click(screen.getByRole("button", { name: "Publish" }));
    await waitFor(() => expect(m.uploadPolicy).toHaveBeenCalledTimes(1));
    expect(m.uploadPolicy!.mock.calls[0]![0]).toMatchObject({ publish: true });

    await userEvent.click(screen.getByLabelText(/save as draft/i));
    await userEvent.click(screen.getByRole("button", { name: "Save draft" }));
    await waitFor(() => expect(m.uploadPolicy).toHaveBeenCalledTimes(2));
    expect(m.uploadPolicy!.mock.calls[1]![0]).toMatchObject({ publish: false });
  });

  it("warns about a duplicate and uploads only after confirmation", async () => {
    const onDone = vi.fn();
    m.uploadPolicy!
      .mockRejectedValueOnce(new ApiError("conflict", "This file has already been uploaded.", null, {
        status: 409,
        details: { duplicates: [{ id: "p1", title: "SYNTHETIC Leave", version: 1, status: "approved" }] },
      }))
      .mockResolvedValueOnce(policy({ status: "draft" }));
    wrap(<UploadPolicyDialog onClose={vi.fn()} onDone={onDone} />);
    await userEvent.upload(screen.getByLabelText("File"),
      new File(["SYNTHETIC leave text"], "leave.txt", { type: "text/plain" }));
    expect(screen.getByLabelText("Title")).toHaveValue("leave");
    await userEvent.click(screen.getByRole("button", { name: "Publish" }));

    expect(await screen.findByText(/already been uploaded as: SYNTHETIC Leave/)).toBeInTheDocument();
    await userEvent.click(screen.getByRole("button", { name: /upload anyway/i }));
    await waitFor(() => expect(onDone).toHaveBeenCalled());
    expect(m.uploadPolicy!.mock.calls[1]![0]).toMatchObject({ title: "leave", confirmDuplicate: true });
  });
});
