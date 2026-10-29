import { QueryClient, QueryClientProvider } from "@tanstack/react-query";
import { render, screen, waitFor } from "@testing-library/react";
import userEvent from "@testing-library/user-event";
import { MemoryRouter } from "react-router-dom";
import { afterEach, beforeEach, describe, expect, it, vi } from "vitest";

import { setAccessToken } from "../src/api/client";
import { App } from "../src/app/App";
import { AuthProvider } from "../src/app/auth-context";
import { ToastProvider } from "../src/components/toast";

/* Tests for the in-app Excel report preview route (/campaigns/:id/report) and the candidate
   summary route (/campaigns/:id/candidates/:applicationId). They render the REAL <App/> at
   those paths with a mocked, authenticated session and assert the real report data shows,
   search filters it, and the summary opens the correct candidate. */

const CAMPAIGN_ID = "aaaaaaaa-aaaa-aaaa-aaaa-aaaaaaaaaaaa";
const APP_ID = "bbbbbbbb-bbbb-bbbb-bbbb-bbbbbbbbbbbb";
const APP_ID_2 = "cccccccc-cccc-cccc-cccc-cccccccccccc";

const ME = {
  user_id: "u1",
  organisation_id: "o1",
  email: "hr.admin@example.com",
  role_names: ["recruiter_admin"],
  permissions: ["candidate.view", "candidate.view_pii", "campaign.edit"],
  assigned_campaign_ids: [CAMPAIGN_ID],
};

const REPORT = {
  summary: {
    campaign_id: CAMPAIGN_ID,
    campaign_name: "Backend Engineer Drive",
    position_title: "Backend Engineer",
    jd_role: "Backend Engineer",
    status: "applications_open",
    status_label: "Applications open",
    number_of_openings: 2,
    total_candidates: 2,
    scored_candidates: 2,
    unscored_candidates: 0,
    contact_unmasked: true,
    generated_at: "2026-01-01 00:00:00 UTC",
    score_note: "Overall score is the saved fit score; JD skills match is derived.",
  },
  columns: [
    { key: "rank", label: "Rank", width: 7 },
    { key: "candidate_name", label: "Candidate name", width: 24 },
  ],
  rows: [
    {
      application_id: APP_ID,
      candidate_name: "Asha Verma",
      email: "asha.verma@example.com",
      phone: "+1 555 0100",
      contact_masked: false,
      applied_position: "Backend Engineer",
      status: "screened",
      status_label: "Screened",
      scored: true,
      overall_score: 82,
      jd_skills_match: 75,
      recommendation: "recommended_for_interview_review",
      manual_review_required: false,
      conflict_flagged: false,
      relevant_skills: ["Python", "PostgreSQL"],
      key_strengths: ["Python"],
      missing_requirements: [],
      unverified_requirements: [],
      experience_summary: "6",
      education_summary: "BSc",
      resume_available: true,
      resume_filename: "asha.pdf",
      rank: 1,
    },
    {
      application_id: APP_ID_2,
      candidate_name: "Boris Khan",
      email: "boris.khan@example.com",
      phone: null,
      contact_masked: false,
      applied_position: "Backend Engineer",
      status: "manual_review",
      status_label: "In human review",
      scored: true,
      overall_score: 38,
      jd_skills_match: 20,
      recommendation: "borderline_review",
      manual_review_required: true,
      conflict_flagged: false,
      relevant_skills: ["Bash"],
      key_strengths: ["Bash"],
      missing_requirements: ["Kubernetes"],
      unverified_requirements: ["Leadership"],
      experience_summary: "3",
      education_summary: null,
      resume_available: false,
      resume_filename: null,
      rank: 2,
    },
  ],
};

function jsonResponse(body: unknown, status = 200): Response {
  return new Response(JSON.stringify(body), {
    status,
    headers: { "Content-Type": "application/json" },
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

describe("in-app report preview", () => {
  beforeEach(() => {
    vi.restoreAllMocks();
    setAccessToken("tok");
    vi.spyOn(globalThis, "fetch").mockImplementation((input: RequestInfo | URL) => {
      const u = typeof input === "string" ? input : input.toString();
      if (u.endsWith("/api/v1/auth/me")) return Promise.resolve(jsonResponse(ME));
      if (u.endsWith(`/api/v1/reports/campaigns/${CAMPAIGN_ID}/report`)) {
        return Promise.resolve(jsonResponse(REPORT));
      }
      return Promise.resolve(jsonResponse({}, 200));
    });
  });
  afterEach(() => setAccessToken(null));

  it("renders the real report rows (scores, derived skills) for a campaign", async () => {
    renderAppAt(`/campaigns/${CAMPAIGN_ID}/report`);
    expect(await screen.findByText("Asha Verma")).toBeInTheDocument();
    expect(screen.getByText("Boris Khan")).toBeInTheDocument();
    // Overall score and JD skills match appear as distinct percentages.
    expect(screen.getByText("82%")).toBeInTheDocument();
    expect(screen.getByText("75%")).toBeInTheDocument();
    // Derived strengths/skills show.
    expect(screen.getAllByText("Python").length).toBeGreaterThan(0);
  });

  it("filters candidates by the search box", async () => {
    renderAppAt(`/campaigns/${CAMPAIGN_ID}/report`);
    expect(await screen.findByText("Asha Verma")).toBeInTheDocument();
    const search = screen.getByPlaceholderText(/search by name/i);
    await userEvent.type(search, "boris");
    await waitFor(() => {
      expect(screen.queryByText("Asha Verma")).not.toBeInTheDocument();
    });
    expect(screen.getByText("Boris Khan")).toBeInTheDocument();
  });

  it("shows the Download Excel action", async () => {
    renderAppAt(`/campaigns/${CAMPAIGN_ID}/report`);
    expect(await screen.findByText(/download excel/i)).toBeInTheDocument();
  });
});

describe("candidate summary route", () => {
  beforeEach(() => {
    vi.restoreAllMocks();
    setAccessToken("tok");
    vi.spyOn(globalThis, "fetch").mockImplementation((input: RequestInfo | URL) => {
      const u = typeof input === "string" ? input : input.toString();
      if (u.endsWith("/api/v1/auth/me")) return Promise.resolve(jsonResponse(ME));
      if (u.endsWith(`/api/v1/applications/${APP_ID}`)) {
        return Promise.resolve(
          jsonResponse({
            id: APP_ID,
            campaign_id: CAMPAIGN_ID,
            candidate_id: "cand-1",
            state: "screened",
            answers: { full_name: "Asha Verma", total_experience_years: "6", education: "BSc" },
            version: 1,
          }),
        );
      }
      if (u.endsWith(`/api/v1/campaigns/${CAMPAIGN_ID}`)) {
        return Promise.resolve(
          jsonResponse({
            id: CAMPAIGN_ID, project_id: "p1", name: "Backend Engineer Drive",
            position_title: "Backend Engineer", number_of_openings: 2, state: "applications_open",
            approved_jd_version_id: null, approved_rule_set_version_id: null,
            approved_form_version_id: null, active_threshold_version_id: null,
            privacy_notice_version: null, version: 1,
          }),
        );
      }
      if (u.endsWith(`/api/v1/screening/applications/${APP_ID}/runs`)) {
        return Promise.resolve(
          jsonResponse([
            {
              id: "run-1", application_id: APP_ID, rule_set_version_id: "rs-1",
              threshold_version_id: null, score: 82, eligibility_outcome: "eligible",
              confidence_status: "confirmed", recommendation: "recommended_for_interview_review",
              manual_review_required: false, conflict_flagged: false, conflict_detail: null,
              input_data_hash: "x", engine_version: "1.0.0", completed_at: "2026-01-01T00:00:00Z",
              results: [
                {
                  criterion_name: "Python", criterion_type: "exact_skill", mandatory: false,
                  tier: "good_to_have", outcome: "pass", expected: null,
                  candidate_evidence: "Python", evidence_source: "resume", confidence: 0.9,
                  max_score: 10, awarded_score: 8, reason: "found",
                },
                {
                  criterion_name: "Kubernetes", criterion_type: "exact_skill", mandatory: true,
                  tier: "must_have", outcome: "fail", expected: null,
                  candidate_evidence: null, evidence_source: null, confidence: null,
                  max_score: 10, awarded_score: 0, reason: "not found",
                },
              ],
            },
          ]),
        );
      }
      if (u.endsWith(`/api/v1/applications/${APP_ID}/extracted-fields`)) {
        return Promise.resolve(jsonResponse([]));
      }
      return Promise.resolve(jsonResponse({}, 200));
    });
  });
  afterEach(() => setAccessToken(null));

  it("opens the correct candidate with overall score + derived gaps", async () => {
    renderAppAt(`/campaigns/${CAMPAIGN_ID}/candidates/${APP_ID}`);
    // Correct candidate name in the heading.
    expect(await screen.findByRole("heading", { name: "Asha Verma" })).toBeInTheDocument();
    // Overall fit score rendered.
    await waitFor(() => expect(screen.getByText("82%")).toBeInTheDocument());
    // A must-have fail is surfaced as a missing requirement.
    expect(screen.getByText("Kubernetes")).toBeInTheDocument();
    // A passed skill is surfaced as a strength.
    expect(screen.getAllByText("Python").length).toBeGreaterThan(0);
  });
});
