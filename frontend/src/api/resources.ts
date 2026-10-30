/* Typed API wrappers for the resource endpoints used by the portals.
   Schemas are intentionally permissive (passthrough) where the backend returns rich
   objects, validating just the fields the UI relies on. */

import { z } from "zod";

import { apiFetch } from "./client";

const uuid = z.string();

// ---------- Projects ----------
export const project = z
  .object({ id: uuid, name: z.string(), status: z.string(), department: z.string().nullable().optional() })
  .passthrough();
export type Project = z.infer<typeof project>;

export const listProjects = () => apiFetch("/api/v1/projects", z.array(project));
export const createProject = (body: Record<string, unknown>) =>
  apiFetch("/api/v1/projects", project, { method: "POST", body: JSON.stringify(body) });
// Edit a project's details (only provided fields change).
export const updateProject = (id: string, body: Record<string, unknown>) =>
  apiFetch(`/api/v1/projects/${id}`, project, { method: "PATCH", body: JSON.stringify(body) });
// Hard-delete a project AND every campaign inside it with all related data. Destructive +
// audited server-side; the UI requires a typed confirmation before calling this.
const projectDeleteResult = z
  .object({
    deleted_project_id: z.string(),
    campaigns_removed: z.number(),
    applications_removed: z.number(),
  })
  .passthrough();
export const deleteProject = (id: string) =>
  apiFetch(`/api/v1/projects/${id}`, projectDeleteResult, { method: "DELETE" });

// ---------- Campaigns ----------
export const campaign = z
  .object({
    id: uuid,
    project_id: uuid,
    name: z.string(),
    position_title: z.string(),
    number_of_openings: z.number(),
    state: z.string(),
    approved_jd_version_id: uuid.nullable(),
    approved_rule_set_version_id: uuid.nullable(),
    approved_form_version_id: uuid.nullable(),
    active_threshold_version_id: uuid.nullable(),
    privacy_notice_version: z.string().nullable(),
    version: z.number(),
  })
  .passthrough();
export type Campaign = z.infer<typeof campaign>;

export const listCampaigns = () => apiFetch("/api/v1/campaigns", z.array(campaign));
export const getCampaign = (id: string) => apiFetch(`/api/v1/campaigns/${id}`, campaign);
export const createCampaign = (body: Record<string, unknown>) =>
  apiFetch("/api/v1/campaigns", campaign, { method: "POST", body: JSON.stringify(body) });
const campaignDeleteResult = z
  .object({ deleted_campaign_id: z.string(), applications_removed: z.number() })
  .passthrough();
// Hard-delete a campaign and all records scoped to it. Destructive + audited server-side.
export const deleteCampaign = (id: string) =>
  apiFetch(`/api/v1/campaigns/${id}`, campaignDeleteResult, { method: "DELETE" });
export const transitionCampaign = (id: string, destination: string, reason: string) =>
  apiFetch(`/api/v1/campaigns/${id}/transition`, campaign, {
    method: "POST",
    body: JSON.stringify({ destination, reason }),
  });
const closureReadiness = z
  .object({
    pending_applications: z.number(),
    pending_interviews: z.number(),
    has_pending: z.boolean(),
  })
  .passthrough();
export type ClosureReadiness = z.infer<typeof closureReadiness>;
// Advisory pending-work counts to warn HR before completing/cancelling a campaign.
export const getClosureReadiness = (id: string) =>
  apiFetch(`/api/v1/campaigns/${id}/closure-readiness`, closureReadiness);
// Assign a staff user to a campaign (email omitted = self-assign).
export const assignToCampaign = (id: string, email?: string) =>
  apiFetch(`/api/v1/campaigns/${id}/assignments`, campaign, {
    method: "POST",
    body: JSON.stringify(email ? { email } : {}),
  });
// Dev-only: create+approve all artifacts and drive the campaign to applications_open.
export const devOpenCampaignNow = (id: string) =>
  apiFetch(`/api/v1/dev/campaigns/${id}/open-now`, campaign, { method: "POST" });

// ---------- Job descriptions ----------
export const jdVersion = z
  .object({
    id: uuid,
    version_number: z.number(),
    status: z.string(),
    position_title: z.string().nullable(),
    department: z.string().nullable(),
    responsibilities: z.array(z.string()),
    mandatory_skills: z.array(z.string()),
    desirable_skills: z.array(z.string()),
    extraction_draft: z.record(z.unknown()).nullable().optional(),
  })
  .passthrough();
export type JDVersion = z.infer<typeof jdVersion>;

export const approveJd = (versionId: string, changeReason: string) =>
  apiFetch(`/api/v1/job-descriptions/versions/${versionId}/approve`, jdVersion, {
    method: "POST",
    body: JSON.stringify({ change_reason: changeReason }),
  });
export const listJdVersions = (campaignId: string) =>
  apiFetch(`/api/v1/job-descriptions/versions?campaign_id=${campaignId}`, z.array(jdVersion));
export const listPendingJdVersions = () =>
  apiFetch("/api/v1/job-descriptions/versions/pending", z.array(jdVersion));
export const rejectJd = (versionId: string, changeReason: string) =>
  apiFetch(`/api/v1/job-descriptions/versions/${versionId}/reject`, jdVersion, {
    method: "POST",
    body: JSON.stringify({ change_reason: changeReason }),
  });
export const updateJdVersion = (versionId: string, body: Record<string, unknown>) =>
  apiFetch(`/api/v1/job-descriptions/versions/${versionId}`, jdVersion, {
    method: "PATCH",
    body: JSON.stringify(body),
  });

// ---------- Staff users (for four-eyes approver pickers + admin user management) ----------
// role_names is included so pickers can filter by role (e.g. the interviewer dropdown lists
// only Interview Panel members); is_active shows account status in the admin table. The
// backend returns these as non-sensitive identity metadata (never passwords/candidate data).
export const staffUser = z
  .object({
    id: uuid,
    email: z.string(),
    display_name: z.string(),
    is_active: z.boolean().optional(),
    role_names: z.array(z.string()).optional(),
  })
  .passthrough();
export type StaffUser = z.infer<typeof staffUser>;
// includeInactive=true is used by the admin user table (which shows status); pickers call it
// without the flag so they only ever see active users.
export const listUsers = (includeInactive = false) =>
  apiFetch(
    includeInactive ? "/api/v1/users?include_inactive=true" : "/api/v1/users",
    z.array(staffUser),
  );

// Soft-delete (deactivate) a staff user. Requires user.manage server-side. Returns on 204.
export async function deleteUser(userId: string, token: string): Promise<void> {
  const resp = await fetch(`/api/v1/users/${userId}`, {
    method: "DELETE",
    headers: { Authorization: `Bearer ${token}` },
  });
  if (!resp.ok && resp.status !== 204) {
    const body: unknown = await resp.json().catch(() => null);
    const msg =
      body && typeof body === "object" && "error" in body
        ? (body as { error: { message: string } }).error.message
        : `Could not delete the user (${resp.status})`;
    throw new Error(msg);
  }
}

// Upload is multipart; handled directly (not JSON).
export async function uploadJd(campaignId: string, file: File, token: string): Promise<JDVersion> {
  const form = new FormData();
  form.append("campaign_id", campaignId);
  form.append("file", file);
  const resp = await fetch("/api/v1/job-descriptions/upload", {
    method: "POST",
    headers: { Authorization: `Bearer ${token}` },
    body: form,
  });
  const body: unknown = await resp.json().catch(() => null);
  if (!resp.ok) {
    const msg =
      body && typeof body === "object" && "error" in body
        ? (body as { error: { message: string } }).error.message
        : `Upload failed (${resp.status})`;
    throw new Error(msg);
  }
  return jdVersion.parse(body);
}

// ---------- Forms ----------
export const formVersion = z
  .object({
    id: uuid,
    version_number: z.number(),
    status: z.string(),
    compensation_enabled: z.boolean(),
    fields: z.array(
      z.object({
        key: z.string(),
        label: z.string(),
        field_class: z.string(),
        field_type: z.string(),
        required: z.boolean(),
        order_index: z.number(),
        options: z.array(z.string()).nullable(),
      }),
    ),
  })
  .passthrough();
export type FormVersion = z.infer<typeof formVersion>;

export const createFormDraft = (campaignId: string, compensationEnabled: boolean) =>
  apiFetch("/api/v1/forms/drafts", formVersion, {
    method: "POST",
    body: JSON.stringify({ campaign_id: campaignId, compensation_enabled: compensationEnabled }),
  });
export const approveForm = (versionId: string) =>
  apiFetch(`/api/v1/forms/versions/${versionId}/approve`, formVersion, { method: "POST" });

// ---------- Rules & thresholds ----------
export const ruleSetVersion = z
  .object({ id: uuid, version_number: z.number(), status: z.string(), rules: z.array(z.record(z.unknown())) })
  .passthrough();
export type RuleSetVersion = z.infer<typeof ruleSetVersion>;

export const createRuleSetVersion = (campaignId: string, name: string, rules: unknown[]) =>
  apiFetch("/api/v1/rules/rule-sets/versions", ruleSetVersion, {
    method: "POST",
    body: JSON.stringify({ campaign_id: campaignId, name, rules }),
  });
// Draft a tiered skill rule-set derived from the campaign's approved JD.
export const createRuleSetFromJd = (campaignId: string) =>
  apiFetch("/api/v1/rules/rule-sets/versions/from-jd", ruleSetVersion, {
    method: "POST",
    body: JSON.stringify({ campaign_id: campaignId }),
  });
export const approveRuleSet = (versionId: string) =>
  apiFetch(`/api/v1/rules/rule-sets/versions/${versionId}/approve`, ruleSetVersion, {
    method: "POST",
  });
export const rejectRuleSet = (versionId: string, changeReason: string) =>
  apiFetch(`/api/v1/rules/rule-sets/versions/${versionId}/reject`, ruleSetVersion, {
    method: "POST",
    body: JSON.stringify({ change_reason: changeReason }),
  });

export const pendingRuleSet = z
  .object({
    id: uuid,
    rule_set_id: uuid,
    campaign_id: uuid,
    name: z.string(),
    version_number: z.number(),
    status: z.string(),
    rules: z.array(z.record(z.unknown())),
  })
  .passthrough();
export type PendingRuleSet = z.infer<typeof pendingRuleSet>;
export const listPendingRuleSets = () =>
  apiFetch("/api/v1/rules/rule-sets/versions/pending", z.array(pendingRuleSet));

export const thresholdVersion = z
  .object({
    id: uuid,
    version_number: z.number(),
    status: z.string(),
    review_below: z.number(),
    recommend_at_or_above: z.number(),
    change_reason: z.string(),
  })
  .passthrough();
export type ThresholdVersion = z.infer<typeof thresholdVersion>;

export const changeThreshold = (body: Record<string, unknown>) =>
  apiFetch("/api/v1/rules/thresholds/change", thresholdVersion, {
    method: "POST",
    body: JSON.stringify(body),
  });

// ---------- Applications & screening ----------
export const application = z
  .object({
    id: uuid,
    campaign_id: uuid,
    candidate_id: uuid,
    state: z.string(),
    answers: z.record(z.unknown()),
    version: z.number(),
  })
  .passthrough();
export type Application = z.infer<typeof application>;

export const getApplication = (id: string) => apiFetch(`/api/v1/applications/${id}`, application);

// ---------- Candidate (masked by default; PII revealed via an audited endpoint) ----------
export const candidateContact = z
  .object({
    id: uuid,
    full_name: z.string(),
    email: z.string(),
    mobile: z.string().nullable(),
    linkedin: z.string().nullable(),
  })
  .passthrough();
export type CandidateContact = z.infer<typeof candidateContact>;

// Reveal a candidate's unmasked contact details. Requires candidate.view_pii; the server
// writes an audit event for every call.
export const revealCandidateContact = (candidateId: string) =>
  apiFetch(`/api/v1/candidates/${candidateId}/contact`, candidateContact);

// Fields extracted from a candidate's resume (value + the matched source span + confidence).
// This is the resume-derived content shown in the scorecard's "View Resume" tab.
export const extractedField = z
  .object({
    id: uuid,
    field_name: z.string(),
    extracted_value: z.string().nullable(),
    verified_value: z.string().nullable(),
    source_span: z.string().nullable(),
    extraction_method: z.string(),
    confidence: z.number(),
    status: z.string(),
  })
  .passthrough();
export type ExtractedField = z.infer<typeof extractedField>;
export const listExtractedFields = (applicationId: string) =>
  apiFetch(`/api/v1/applications/${applicationId}/extracted-fields`, z.array(extractedField));

// A campaign's application plus its latest screening summary, for the ranked HR table.
// The latest-run fields are embedded by the backend so the table can rank candidates
// (score desc, unscored last) WITHOUT one screening-runs call per row.
export const rankedApplication = application.extend({
  rank: z.number().nullable().optional(),
  scored: z.boolean().optional(),
  score: z.number().nullable().optional(),
  recommendation: z.string().nullable().optional(),
  manual_review_required: z.boolean().nullable().optional(),
  conflict_flagged: z.boolean().nullable().optional(),
  latest_run_id: uuid.nullable().optional(),
});
export type RankedApplication = z.infer<typeof rankedApplication>;

export const listApplications = (campaignId: string) =>
  apiFetch(`/api/v1/applications?campaign_id=${campaignId}`, z.array(rankedApplication));

// Walk-in drive: bulk-ingest multiple resumes for a campaign (multipart). Safe pipeline
// per file (validate + scan + quarantine). Requires screening.execute + campaign access.
export const walkInIntakeResult = z.object({
  filename: z.string(),
  accepted: z.boolean(),
  application_id: uuid.nullable(),
  duplicate: z.boolean(),
  detail: z.string(),
  score: z.number().nullable().optional(),
  manual_review: z.boolean().optional(),
});
export const walkInIntakeResponse = z.object({
  campaign_id: uuid,
  total: z.number(),
  accepted: z.number(),
  rejected: z.number(),
  results: z.array(walkInIntakeResult),
});
export type WalkInIntakeResponse = z.infer<typeof walkInIntakeResponse>;

export async function bulkIntakeWalkInResumes(
  campaignId: string,
  consentAttested: boolean,
  files: File[],
  token: string,
): Promise<WalkInIntakeResponse> {
  const form = new FormData();
  form.append("campaign_id", campaignId);
  form.append("consent_attested", String(consentAttested));
  for (const f of files) form.append("files", f);
  const resp = await fetch("/api/v1/applications/walk-in-intake", {
    method: "POST",
    headers: { Authorization: `Bearer ${token}` },
    body: form,
  });
  const body: unknown = await resp.json().catch(() => null);
  if (!resp.ok) {
    const msg =
      body && typeof body === "object" && "error" in body
        ? (body as { error: { message: string } }).error.message
        : `Bulk intake failed (${resp.status})`;
    throw new Error(msg);
  }
  return walkInIntakeResponse.parse(body);
}

export const criterionResult = z.object({
  criterion_name: z.string(),
  criterion_type: z.string(),
  mandatory: z.boolean(),
  tier: z.string().nullable().optional(),
  outcome: z.string(),
  expected: z.string().nullable(),
  candidate_evidence: z.string().nullable(),
  evidence_source: z.string().nullable(),
  confidence: z.number().nullable(),
  max_score: z.number(),
  awarded_score: z.number(),
  reason: z.string(),
});
export const screeningRun = z
  .object({
    id: uuid,
    application_id: uuid,
    score: z.number(),
    eligibility_outcome: z.string(),
    confidence_status: z.string(),
    recommendation: z.string(),
    manual_review_required: z.boolean(),
    conflict_flagged: z.boolean().optional(),
    conflict_detail: z.string().nullable().optional(),
    input_data_hash: z.string(),
    engine_version: z.string(),
    completed_at: z.string().nullable(),
    results: z.array(criterionResult),
  })
  .passthrough();
export type ScreeningRun = z.infer<typeof screeningRun>;
export type CriterionResult = z.infer<typeof criterionResult>;

export const runScreening = (applicationId: string) =>
  apiFetch(`/api/v1/screening/applications/${applicationId}/run`, screeningRun, { method: "POST" });
export const listScreeningRuns = (applicationId: string) =>
  apiFetch(`/api/v1/screening/applications/${applicationId}/runs`, z.array(screeningRun));

// Repair a campaign whose candidates are stuck at 0/100 because its approved rule-set had
// no JD-derived skill criteria. Regenerates criteria from the approved JD (four-eyes
// preserved server-side) and re-screens every application as a NEW immutable run. Requires
// rule.approve + campaign access. Nothing is reset or deleted.
export const rescoreSummary = z.object({
  rescored: z.number(),
  criteria_count: z.number(),
  progressed: z.number(),
});
export type RescoreSummary = z.infer<typeof rescoreSummary>;

export const rescoreCampaign = (campaignId: string) =>
  apiFetch(`/api/v1/screening/campaigns/${campaignId}/rescore`, rescoreSummary, {
    method: "POST",
  });

// ---------- Review ----------
export const reviewItem = z
  .object({
    id: uuid,
    application_id: uuid,
    campaign_id: uuid,
    reason: z.string(),
    detail: z.string().nullable(),
    status: z.string(),
    screening_run_id: uuid.nullable(),
  })
  .passthrough();
export type ReviewItem = z.infer<typeof reviewItem>;

export const listReviews = (campaignId: string) =>
  apiFetch(`/api/v1/reviews?campaign_id=${campaignId}`, z.array(reviewItem));

export const reviewAction = z
  .object({
    id: uuid,
    review_item_id: uuid,
    action_type: z.string(),
    reason: z.string(),
    resolves_item: z.boolean(),
  })
  .passthrough();
export const recordReviewAction = (
  reviewItemId: string,
  body: { action_type: string; reason: string; resolves_item?: boolean },
) =>
  apiFetch(`/api/v1/reviews/${reviewItemId}/actions`, reviewAction, {
    method: "POST",
    body: JSON.stringify(body),
  });

// ---------- Interviews ----------
export const interviewStage = z
  .object({ id: uuid, campaign_id: uuid, name: z.string(), sequence: z.number() })
  .passthrough();
export type InterviewStage = z.infer<typeof interviewStage>;

export const interviewSlot = z
  .object({
    id: uuid,
    stage_id: uuid,
    slot_date: z.string(),
    start_time: z.string(),
    location: z.string().nullable(),
    mode: z.string(),
    capacity: z.number(),
    confirmed_count: z.number(),
  })
  .passthrough();
export type InterviewSlot = z.infer<typeof interviewSlot>;

export const interviewInvitation = z
  .object({
    id: uuid,
    application_id: uuid,
    campaign_id: uuid,
    stage_id: uuid.nullable(),
    slot_id: uuid.nullable(),
    status: z.string(),
    attendance: z.string(),
    checked_in_at: z.string().nullable().optional(),
    checked_out_at: z.string().nullable().optional(),
    auto_invite: z.boolean(),
  })
  .passthrough();
export type InterviewInvitation = z.infer<typeof interviewInvitation>;

export const listStages = (campaignId: string) =>
  apiFetch(`/api/v1/interviews/stages?campaign_id=${campaignId}`, z.array(interviewStage));
export const listSlots = (campaignId: string) =>
  apiFetch(`/api/v1/interviews/slots?campaign_id=${campaignId}`, z.array(interviewSlot));
export const listInvitations = (campaignId: string) =>
  apiFetch(`/api/v1/interviews/invitations?campaign_id=${campaignId}`, z.array(interviewInvitation));
export const createStage = (campaignId: string, name: string, sequence: number) =>
  apiFetch("/api/v1/interviews/stages", interviewStage, {
    method: "POST",
    body: JSON.stringify({ campaign_id: campaignId, name, sequence }),
  });
export const createSlot = (body: Record<string, unknown>) =>
  apiFetch("/api/v1/interviews/slots", interviewSlot, {
    method: "POST",
    body: JSON.stringify(body),
  });
export const approveInvitation = (applicationId: string, stageId?: string) =>
  apiFetch("/api/v1/interviews/invitations/approve", interviewInvitation, {
    method: "POST",
    body: JSON.stringify(stageId ? { application_id: applicationId, stage_id: stageId } : { application_id: applicationId }),
  });
export const recordAttendance = (invitationId: string, attended: boolean) =>
  apiFetch(`/api/v1/interviews/invitations/${invitationId}/attendance`, interviewInvitation, {
    method: "POST",
    body: JSON.stringify({ attended }),
  });
// Interview Panel: check a candidate in on interview day (scheduled -> checked in). The
// server rejects a duplicate check-in and a candidate who is not currently scheduled.
export const checkInInvitation = (invitationId: string) =>
  apiFetch(`/api/v1/interviews/invitations/${invitationId}/check-in`, interviewInvitation, {
    method: "POST",
  });
// Interview Panel: check a candidate out once finished (assessed -> checked out). The
// server requires the assessment to be submitted first and rejects a duplicate check-out.
export const checkOutInvitation = (invitationId: string) =>
  apiFetch(`/api/v1/interviews/invitations/${invitationId}/check-out`, interviewInvitation, {
    method: "POST",
  });
// Express path: approve + auto-schedule in one call. The candidate then appears on the
// Interview Panel's list immediately. `reason` is REQUIRED by the server when the candidate
// is under review (below the automatic 50% bar) — it records the override justification.
export const recordWalkInInterview = (applicationId: string, reason?: string) =>
  apiFetch("/api/v1/interviews/invitations/walk-in", interviewInvitation, {
    method: "POST",
    body: JSON.stringify(
      reason && reason.trim()
        ? { application_id: applicationId, reason: reason.trim() }
        : { application_id: applicationId },
    ),
  });

// ---------- Assessments (interview panel) ----------
export const assessableApplication = z
  .object({ application_id: uuid, campaign_id: uuid, candidate_name: z.string() })
  .passthrough();
export type AssessableApplication = z.infer<typeof assessableApplication>;
export const assessmentRead = z
  .object({ id: uuid, application_id: uuid, recommendation: z.string(), conflict_declared: z.boolean() })
  .passthrough();
export const listAssignableAssessments = () =>
  apiFetch("/api/v1/assessments/assignable", z.array(assessableApplication));
export const submitAssessment = (body: Record<string, unknown>) =>
  apiFetch("/api/v1/assessments", assessmentRead, {
    method: "POST",
    body: JSON.stringify(body),
  });

// The full saved assessment for an application, used to rehydrate the Assessment tab so
// entered values survive tab switches / refreshes. Returns null when none is saved yet.
export const assessmentDetail = z
  .object({
    id: uuid,
    application_id: uuid,
    campaign_id: uuid,
    panel_member_id: uuid,
    criteria_scores: z.record(z.union([z.number(), z.string()])),
    problem_solving_notes: z.string().nullable(),
    role_understanding_notes: z.string().nullable(),
    interview_notes: z.string().nullable(),
    recommendation: z.string(),
    conflict_declared: z.boolean(),
    conflict_detail: z.string().nullable(),
  })
  .passthrough();
export type AssessmentDetail = z.infer<typeof assessmentDetail>;
export const getAssessmentForApplication = (applicationId: string) =>
  apiFetch(
    `/api/v1/assessments/by-application/${applicationId}`,
    assessmentDetail.nullable(),
  );

// Secure resume download URL for an application (authenticated, authorised server-side).
// The file is served as an attachment; never a public bucket URL. Callers fetch it with the
// bearer token (see downloadResume) rather than navigating the browser directly.
export const resumeDownloadPath = (applicationId: string): string =>
  `/api/v1/documents/applications/${applicationId}/resume`;

// Fetch the resume as a Blob using the bearer token, so the Resume tab can preview/download
// it. Returns null when there is no resume on file (404) so the UI can show a clear message.
//
// By default this requests the ORIGINAL uploaded file only; a missing original yields 404
// (so extracted text is never mistaken for the original — used by the HR download action).
// Pass { allowTextFallback: true } to additionally accept the clearly-labelled extracted
// text when the original blob is unavailable (used by the Interview Panel preview tab).
export async function downloadResume(
  applicationId: string,
  token: string,
  opts: { allowTextFallback?: boolean } = {},
): Promise<{ blob: Blob; contentType: string; isOriginal: boolean } | null> {
  const url =
    resumeDownloadPath(applicationId) + (opts.allowTextFallback ? "?fallback=text" : "");
  const resp = await fetch(url, {
    headers: { Authorization: `Bearer ${token}` },
  });
  if (resp.status === 404) return null;
  if (!resp.ok) {
    const body: unknown = await resp.json().catch(() => null);
    const msg =
      body && typeof body === "object" && "error" in body
        ? (body as { error: { message: string } }).error.message
        : `Could not load the resume (${resp.status})`;
    throw new Error(msg);
  }
  const blob = await resp.blob();
  // X-Resume-Source distinguishes the original upload from the extracted-text fallback.
  const isOriginal = resp.headers.get("X-Resume-Source") !== "extracted-text-fallback";
  return {
    blob,
    contentType: resp.headers.get("Content-Type") ?? "application/octet-stream",
    isOriginal,
  };
}

// ---------- Campaign report (in-app preview = Excel download, one shared backend model) ----
export const reportColumn = z.object({ key: z.string(), label: z.string(), width: z.number() });
export const candidateReportRow = z
  .object({
    application_id: uuid,
    candidate_name: z.string(),
    email: z.string().nullable(),
    phone: z.string().nullable(),
    contact_masked: z.boolean(),
    applied_position: z.string(),
    status: z.string(),
    status_label: z.string(),
    scored: z.boolean(),
    overall_score: z.number().nullable(),
    jd_skills_match: z.number().nullable(),
    recommendation: z.string().nullable(),
    manual_review_required: z.boolean(),
    conflict_flagged: z.boolean(),
    relevant_skills: z.array(z.string()),
    key_strengths: z.array(z.string()),
    missing_requirements: z.array(z.string()),
    unverified_requirements: z.array(z.string()),
    experience_summary: z.string().nullable(),
    education_summary: z.string().nullable(),
    resume_available: z.boolean(),
    resume_filename: z.string().nullable(),
    rank: z.number().nullable(),
  })
  .passthrough();
export const campaignReport = z
  .object({
    summary: z
      .object({
        campaign_id: uuid,
        campaign_name: z.string(),
        position_title: z.string(),
        jd_role: z.string().nullable(),
        status: z.string(),
        status_label: z.string(),
        number_of_openings: z.number(),
        total_candidates: z.number(),
        scored_candidates: z.number(),
        unscored_candidates: z.number(),
        contact_unmasked: z.boolean(),
        generated_at: z.string(),
        score_note: z.string(),
      })
      .passthrough(),
    columns: z.array(reportColumn),
    rows: z.array(candidateReportRow),
  })
  .passthrough();
export type CampaignReport = z.infer<typeof campaignReport>;
export type CandidateReportRow = z.infer<typeof candidateReportRow>;
// The in-app report preview — the SAME data the Excel download renders (one backend model).
export const getCampaignReport = (campaignId: string) =>
  apiFetch(`/api/v1/reports/campaigns/${campaignId}/report`, campaignReport);

// Secure campaign Excel export (authenticated, authorised server-side). Served as an
// attachment; never a public bucket URL. Fetched with the bearer token like downloadResume.
export const campaignExportPath = (campaignId: string): string =>
  `/api/v1/reports/campaigns/${campaignId}/export`;

// Fetch the campaign export as a Blob using the bearer token so the UI can trigger a
// browser download. Returns null on 404 (campaign not found / not accessible).
export async function downloadCampaignExport(
  campaignId: string,
  token: string,
): Promise<{ blob: Blob; contentType: string } | null> {
  const resp = await fetch(campaignExportPath(campaignId), {
    headers: { Authorization: `Bearer ${token}` },
  });
  if (resp.status === 404) return null;
  if (!resp.ok) {
    const body: unknown = await resp.json().catch(() => null);
    const msg =
      body && typeof body === "object" && "error" in body
        ? (body as { error: { message: string } }).error.message
        : `Could not export the campaign (${resp.status})`;
    throw new Error(msg);
  }
  const blob = await resp.blob();
  return { blob, contentType: resp.headers.get("Content-Type") ?? "application/octet-stream" };
}

// The Interview Panel's own dashboard: interviews to attend / to assess / completed.
export const panelInterview = z
  .object({
    application_id: uuid,
    campaign_id: uuid,
    campaign_name: z.string().optional(),
    invitation_id: uuid.nullable(),
    candidate_name: z.string(),
    state: z.string(),
    stage: z.string(), // to_check_in | to_assess | to_check_out | completed
    has_assessment: z.boolean().optional(),
  })
  .passthrough();
export type PanelInterview = z.infer<typeof panelInterview>;
export const panelDashboard = z
  .object({
    to_check_in: z.number(),
    to_assess: z.number(),
    to_check_out: z.number(),
    completed: z.number(),
    total: z.number(),
    interviews: z.array(panelInterview),
  })
  .passthrough();
export type PanelDashboard = z.infer<typeof panelDashboard>;
export const getPanelDashboard = (campaignId?: string) =>
  apiFetch(
    campaignId
      ? `/api/v1/assessments/panel?campaign_id=${campaignId}`
      : "/api/v1/assessments/panel",
    panelDashboard,
  );

// ---------- Interviewer assignments (panel isolation) ----------
// Assignment METADATA only — these endpoints never return candidate profiles, resumes,
// scores, or scorecards. Managing assignments requires interview.assign server-side.
export const interviewAssignment = z
  .object({
    id: uuid,
    organisation_id: uuid,
    campaign_id: uuid,
    stage_id: uuid.nullable(),
    interviewer_id: uuid,
    interviewer_name: z.string().nullable().optional(),
    assigned_by: uuid,
    is_active: z.boolean(),
    created_at: z.string(),
    updated_at: z.string(),
  })
  .passthrough();
export type InterviewAssignment = z.infer<typeof interviewAssignment>;

export const listInterviewAssignments = (campaignId: string) =>
  apiFetch(
    `/api/v1/interviews/campaigns/${campaignId}/assignments`,
    z.array(interviewAssignment),
  );

export const createInterviewAssignment = (
  campaignId: string,
  body: { interviewer_id: string; stage_id?: string | null },
) =>
  apiFetch(
    `/api/v1/interviews/campaigns/${campaignId}/assignments`,
    interviewAssignment,
    { method: "POST", body: JSON.stringify(body) },
  );

// Soft-remove an assignment. Returns nothing (204); handled directly so a 204 with no body
// does not fail JSON parsing.
export async function removeInterviewAssignment(
  assignmentId: string,
  token: string,
): Promise<void> {
  const resp = await fetch(`/api/v1/interviews/assignments/${assignmentId}`, {
    method: "DELETE",
    headers: { Authorization: `Bearer ${token}` },
  });
  if (!resp.ok && resp.status !== 204) {
    const body: unknown = await resp.json().catch(() => null);
    const msg =
      body && typeof body === "object" && "error" in body
        ? (body as { error: { message: string } }).error.message
        : `Could not remove the assignment (${resp.status})`;
    throw new Error(msg);
  }
}

// The authenticated interviewer's own assignment buckets (campaign id + display label).
export const myAssignment = z
  .object({
    campaign_id: uuid,
    campaign_name: z.string(),
    stage_id: uuid.nullable().optional(),
    stage_name: z.string().nullable().optional(),
  })
  .passthrough();
export type MyAssignment = z.infer<typeof myAssignment>;
export const listMyAssignments = () =>
  apiFetch("/api/v1/interviews/my-assignments", z.array(myAssignment));

// Organisation-wide interviewer-assignment overview for the System Admin page. METADATA
// ONLY — no candidate profiles, resumes, contact details, scores, rankings, or assessments.
export const assignmentOverview = z
  .object({
    id: uuid,
    interviewer_id: uuid,
    interviewer_name: z.string().nullable().optional(),
    interviewer_email: z.string().nullable().optional(),
    interviewer_role_names: z.array(z.string()).optional(),
    campaign_id: uuid,
    campaign_name: z.string().nullable().optional(),
    stage_id: uuid.nullable().optional(),
    stage_name: z.string().nullable().optional(),
    is_active: z.boolean(),
  })
  .passthrough();
export type AssignmentOverview = z.infer<typeof assignmentOverview>;
export const listAllInterviewAssignments = () =>
  apiFetch("/api/v1/interviews/assignments", z.array(assignmentOverview));

// ---------- Hiring decisions (panel → decision-maker handoff) ----------
export const assessmentSummary = z.object({
  recommendation: z.string(),
  criteria_scores: z.record(z.union([z.number(), z.string()])),
  interview_notes: z.string().nullable().optional(),
  conflict_declared: z.boolean().optional(),
});
export const pendingDecision = z.object({
  application_id: uuid,
  campaign_id: uuid,
  candidate_name: z.string(),
  assessments: z.array(assessmentSummary),
});
export type PendingDecision = z.infer<typeof pendingDecision>;
export type AssessmentSummary = z.infer<typeof assessmentSummary>;
export const decisionRead = z
  .object({ id: uuid, application_id: uuid, decision_type: z.string(), status: z.string() })
  .passthrough();

export const listPendingDecisions = () =>
  apiFetch("/api/v1/decisions/pending", z.array(pendingDecision));

export const decisionOutcome = z.object({
  application_id: uuid,
  candidate_id: uuid,
  campaign_name: z.string(),
  candidate_name: z.string(),
  outcome: z.string(),
  reason: z.string().nullable().optional(),
});
export type DecisionOutcome = z.infer<typeof decisionOutcome>;
export const listOutcomes = () =>
  apiFetch("/api/v1/decisions/outcomes", z.array(decisionOutcome));
export const recordDecision = (applicationId: string, decisionType: string, reason: string) =>
  apiFetch("/api/v1/decisions", decisionRead, {
    method: "POST",
    body: JSON.stringify({ application_id: applicationId, decision_type: decisionType, reason }),
  });

// ---------- Reporting ----------
export const hrDashboard = z.object({
  active_campaigns: z.number(),
  applications_by_state: z.record(z.number()),
  open_review_items: z.number(),
});
export const managementDashboard = z.object({
  open_campaigns: z.number(),
  total_applications: z.number(),
  interview_funnel: z.record(z.number()),
  selected_candidates: z.string(),
});
export const getHrDashboard = () => apiFetch("/api/v1/reports/hr-dashboard", hrDashboard);
export const getManagementDashboard = () =>
  apiFetch("/api/v1/reports/management-dashboard", managementDashboard);

// ---------- Public application ----------

// A role shown in the consolidated careers dropdown. Public + unauthenticated: only the
// candidate-facing fields the backend chooses to expose.
export type PublicRole = {
  id: string;
  title: string;
  location: string | null;
  employment_type: string | null;
  work_mode: string | null;
};

// A field on a role's approved application form, as rendered dynamically by the public page.
export type PublicFormField = {
  key: string;
  label: string;
  field_class: string;
  field_type: string;
  required: boolean;
  order_index: number;
  options: string[] | null;
  item_schema: { key: string; label: string; field_type: string; required?: boolean }[] | null;
};

export type PublicForm = {
  id: string;
  version_number: number;
  compensation_enabled: boolean;
  fields: PublicFormField[];
};

async function publicGet<T>(path: string): Promise<T> {
  const resp = await fetch(path);
  const body: unknown = await resp.json().catch(() => null);
  if (!resp.ok) {
    const msg =
      body && typeof body === "object" && "error" in body
        ? (body as { error: { message: string } }).error.message
        : `Request failed (${resp.status})`;
    throw new Error(msg);
  }
  return body as T;
}

export const listOpenRoles = (): Promise<PublicRole[]> =>
  publicGet<PublicRole[]>("/api/v1/public/open-roles");

export const getPublicRoleForm = (campaignId: string): Promise<PublicForm> =>
  publicGet<PublicForm>(`/api/v1/public/campaigns/${campaignId}/form`);

export async function submitPublicApplication(
  campaignId: string,
  answers: Record<string, unknown>,
  resume: File,
): Promise<{ application_id: string; state: string; manual_review: boolean; message: string }> {
  const form = new FormData();
  form.append("answers", JSON.stringify(answers));
  form.append("resume", resume);
  const resp = await fetch(`/api/v1/public/campaigns/${campaignId}/apply`, {
    method: "POST",
    body: form,
  });
  const body: unknown = await resp.json().catch(() => null);
  if (!resp.ok) {
    const msg =
      body && typeof body === "object" && "error" in body
        ? (body as { error: { message: string } }).error.message
        : `Submission failed (${resp.status})`;
    throw new Error(msg);
  }
  return body as { application_id: string; state: string; manual_review: boolean; message: string };
}

// Public resume pre-fill: upload a resume and get suggested form answers (email / mobile /
// experience) to pre-populate. Read-only — nothing is stored. The candidate edits/completes.
export type ResumePreview = { extracted: boolean; fields: Record<string, string> };

export async function previewResume(resume: File): Promise<ResumePreview> {
  const form = new FormData();
  form.append("resume", resume);
  const resp = await fetch("/api/v1/public/resume-preview", { method: "POST", body: form });
  const body: unknown = await resp.json().catch(() => null);
  if (!resp.ok) {
    const msg =
      body && typeof body === "object" && "error" in body
        ? (body as { error: { message: string } }).error.message
        : `Resume read failed (${resp.status})`;
    throw new Error(msg);
  }
  return body as ResumePreview;
}

// Public, candidate-facing screening status for the application the candidate just
// submitted. Returns only a coarse status + the message to show — never the raw score.
export type PublicApplicationStatus = {
  status: "pending" | "scored" | "failed";
  message: string;
};

export const getPublicApplicationStatus = (
  applicationId: string,
): Promise<PublicApplicationStatus> =>
  publicGet<PublicApplicationStatus>(
    `/api/v1/public/applications/${applicationId}/status`,
  );

// ---------- Induction (employee onboarding) ----------
// The employee dashboard's two features: watch the developer-provisioned induction video,
// then obtain the completion certificate. Endpoint shapes mirror the backend (FEAT-001):
// completed/completed_at gate the certificate; the video stream + certificate are served as
// authenticated bytes, so they are fetched with the in-memory bearer token (never a bare
// <video src>, which cannot send the Authorization header) — same approach as downloadResume.
export const inductionStatus = z
  .object({
    has_video: z.boolean(),
    completed: z.boolean(),
    completed_at: z.string().nullable(),
  })
  .passthrough();
export type InductionStatus = z.infer<typeof inductionStatus>;
// Any authenticated actor may read their own status (an employee without a seeded video gets
// has_video=false); used to gate the dashboard and unlock the certificate.
export const getInductionStatus = () => apiFetch("/api/v1/induction/me", inductionStatus);

export const inductionVideoMeta = z
  .object({
    id: uuid,
    title: z.string(),
    description: z.string().nullable(),
    content_type: z.string(),
  })
  .passthrough();
export type InductionVideoMeta = z.infer<typeof inductionVideoMeta>;
export const getInductionVideoMeta = () =>
  apiFetch("/api/v1/induction/video", inductionVideoMeta);

export const inductionCompletion = z
  .object({ completed: z.boolean(), completed_at: z.string() })
  .passthrough();
export type InductionCompletion = z.infer<typeof inductionCompletion>;
// Idempotent server-side: a second call returns the same completed_at. Emits an audit event.
export const markInductionComplete = () =>
  apiFetch("/api/v1/induction/complete", inductionCompletion, { method: "POST" });

// Fetch the induction video as a Blob using the bearer token so it can be played via an
// object URL (tokens are in-memory only, so a plain <video src> cannot authenticate). Mirrors
// downloadResume. Content-Type comes from the response (the stored video's media type).
export async function fetchInductionVideoBlob(
  token: string,
): Promise<{ blob: Blob; contentType: string }> {
  const resp = await fetch("/api/v1/induction/video/stream", {
    headers: { Authorization: `Bearer ${token}` },
  });
  if (!resp.ok) {
    const body: unknown = await resp.json().catch(() => null);
    const msg =
      body && typeof body === "object" && "error" in body
        ? (body as { error: { message: string } }).error.message
        : `Could not load the induction video (${resp.status})`;
    throw new Error(msg);
  }
  const blob = await resp.blob();
  return { blob, contentType: resp.headers.get("Content-Type") ?? "video/mp4" };
}

// Fetch the completion certificate HTML using the bearer token. Only succeeds after a
// completion exists (the backend returns 4xx otherwise); the UI keeps this action locked
// until the status reports completed=true. Returns the HTML text so the UI can open it in a
// new tab for viewing/printing.
export async function fetchInductionCertificate(token: string): Promise<string> {
  const resp = await fetch("/api/v1/induction/certificate", {
    headers: { Authorization: `Bearer ${token}` },
  });
  if (!resp.ok) {
    const body: unknown = await resp.json().catch(() => null);
    const msg =
      body && typeof body === "object" && "error" in body
        ? (body as { error: { message: string } }).error.message
        : `Could not load the certificate (${resp.status})`;
    throw new Error(msg);
  }
  return resp.text();
}

// Fetch the completion certificate as a Blob using the bearer token so the UI can trigger a
// real browser download to the user's local disk (works after deployment, not just locally).
// Mirrors downloadResume/downloadCampaignExport: the Authorization header is sent explicitly
// and the caller creates an <a download> to save the file. Only succeeds after a completion
// exists (the backend returns 4xx otherwise); the UI keeps this action locked until the
// status reports completed=true. Returns the HTML bytes plus a filesystem-safe filename.
export async function downloadInductionCertificate(
  token: string,
): Promise<{ blob: Blob; filename: string }> {
  const resp = await fetch("/api/v1/induction/certificate", {
    headers: { Authorization: `Bearer ${token}` },
  });
  if (!resp.ok) {
    const body: unknown = await resp.json().catch(() => null);
    const msg =
      body && typeof body === "object" && "error" in body
        ? (body as { error: { message: string } }).error.message
        : `Could not load the certificate (${resp.status})`;
    throw new Error(msg);
  }
  const html = await resp.text();
  const blob = new Blob([html], { type: "text/html" });
  return { blob, filename: "induction-certificate.html" };
}
