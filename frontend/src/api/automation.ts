/* Typed API wrappers for the long-term automation features: messages, SLA, offers, joining,
   policies + assistant, interview confirmation, journey, integrations, feedback summary,
   waitlist, privacy requests and the audit log. Everything here works locally; external
   connections are placeholders and report that honestly in their `state` fields. */

import { z } from "zod";

import { apiFetch, apiUpload, getAccessToken } from "./client";

const id = z.string();
const post = (body?: unknown): RequestInit => ({
  method: "POST",
  ...(body === undefined ? {} : { body: JSON.stringify(body) }),
});

// ------------------------------------------------------------------ messages

const channelStatus = z.object({ mode: z.string(), state: z.string(), message: z.string() });
export const notificationStatus = z.object({ email: channelStatus, whatsapp: channelStatus });
export type NotificationStatus = z.infer<typeof notificationStatus>;
export const getNotificationStatus = () =>
  apiFetch("/api/v1/notifications/status", notificationStatus);

export const delivery = z.object({
  id,
  campaign_id: id.nullable(),
  application_id: id.nullable(),
  onboarding_case_id: id.nullable(),
  template_key: z.string(),
  template_version: z.number(),
  channel: z.string(),
  recipient: z.string(),
  subject: z.string().nullable(),
  body: z.string(),
  status: z.string(),
  failure_reason: z.string().nullable(),
  manual_link: z.string().nullable(),
  created_at: z.string(),
});
export type Delivery = z.infer<typeof delivery>;

export const listDeliveries = (filter: { applicationId?: string; campaignId?: string }) => {
  const q = new URLSearchParams();
  if (filter.applicationId) q.set("application_id", filter.applicationId);
  if (filter.campaignId) q.set("campaign_id", filter.campaignId);
  return apiFetch(`/api/v1/notifications/deliveries?${q.toString()}`, z.array(delivery));
};

export const sendMessage = (body: {
  application_id: string;
  template_key: string;
  channel: "email" | "whatsapp";
}) => apiFetch("/api/v1/notifications/send", delivery, post(body));

export const messageTemplate = z.object({
  key: z.string(),
  label: z.string(),
  audience: z.string(),
  description: z.string(),
  subject: z.string(),
  body: z.string(),
  version: z.number(),
  placeholders: z.array(z.string()),
  is_built_in: z.boolean(),
});
export type MessageTemplate = z.infer<typeof messageTemplate>;
export const listTemplates = () =>
  apiFetch("/api/v1/notifications/templates", z.array(messageTemplate));
export const saveTemplate = (key: string, body: { subject: string; body: string }) =>
  apiFetch(`/api/v1/notifications/templates/${key}`, messageTemplate, {
    method: "PUT",
    body: JSON.stringify(body),
  });

// ----------------------------------------------------------------------- SLA

export const slaPolicy = z.object({
  campaign_id: id.nullable(),
  name: z.string(),
  window_hours: z.number(),
  at_risk_percent: z.number(),
  source: z.string(),
});
export type SlaPolicy = z.infer<typeof slaPolicy>;
export const getSlaPolicy = () => apiFetch("/api/v1/sla/policy", slaPolicy);
export const saveSlaPolicy = (body: { window_hours: number; at_risk_percent: number }) =>
  apiFetch("/api/v1/sla/policy", slaPolicy, { method: "PUT", body: JSON.stringify(body) });

export const slaSummary = z.object({
  window_hours: z.number(),
  on_track: z.number(),
  at_risk: z.number(),
  overdue: z.number(),
  paused: z.number(),
  completed: z.number(),
  note: z.string(),
});
export type SlaSummary = z.infer<typeof slaSummary>;
export const getSlaSummary = () => apiFetch("/api/v1/sla/summary", slaSummary);

export const slaItem = z.object({
  application_id: id,
  campaign_id: id,
  candidate_name: z.string(),
  state: z.string(),
  status: z.string(),
  hours_elapsed: z.number(),
  hours_remaining: z.number(),
  started_at: z.string(),
});
export type SlaItem = z.infer<typeof slaItem>;
export const listSlaItems = () => apiFetch("/api/v1/sla/applications", z.array(slaItem));

export const slaRunResult = z.object({
  reminders_recorded: z.number(),
  overdue_recorded: z.number(),
  messages: z.array(z.string()),
});
export const runSlaCheck = () => apiFetch("/api/v1/sla/run-check", slaRunResult, post());

// -------------------------------------------------------------------- offers

export const offer = z.object({
  id,
  application_id: id,
  campaign_id: id,
  status: z.string(),
  notes: z.string().nullable(),
  respond_by: z.string().nullable(),
  approved_at: z.string().nullable(),
  issued_at: z.string().nullable(),
  responded_at: z.string().nullable(),
  created_at: z.string(),
  candidate_name: z.string().nullable().optional(),
  delivery: delivery.nullable().optional(),
});
export type Offer = z.infer<typeof offer>;
export const listOffers = () => apiFetch("/api/v1/offers", z.array(offer));
export const createOffer = (body: { application_id: string; notes?: string; respond_by?: string }) =>
  apiFetch("/api/v1/offers", offer, post(body));
export const approveOffer = (offerId: string) =>
  apiFetch(`/api/v1/offers/${offerId}/approve`, offer, post());
export const issueOffer = (offerId: string, channel: "email" | "whatsapp" = "email") =>
  apiFetch(`/api/v1/offers/${offerId}/issue?channel=${channel}`, offer, post());
export const remindOffer = (offerId: string, channel: "email" | "whatsapp" = "email") =>
  apiFetch(`/api/v1/offers/${offerId}/remind?channel=${channel}`, offer, post());
export const respondOffer = (offerId: string, outcome: "accepted" | "declined") =>
  apiFetch(`/api/v1/offers/${offerId}/respond`, offer, post({ outcome }));
export const withdrawOffer = (offerId: string) =>
  apiFetch(`/api/v1/offers/${offerId}/withdraw`, offer, post());

// ---------------------------------------------------------- joining (onboarding)

export const joiningCase = z.object({
  id,
  application_id: id,
  campaign_id: id,
  candidate_name: z.string(),
  role_title: z.string(),
  status: z.string(),
  joining_date: z.string().nullable(),
  reporting_manager: z.string().nullable(),
  department: z.string().nullable(),
  work_location: z.string().nullable(),
  role_expectations: z.string().nullable(),
  content_approved: z.boolean(),
  documents_total: z.number(),
  documents_done: z.number(),
  open_flags: z.number(),
  created_at: z.string(),
});
export type JoiningCase = z.infer<typeof joiningCase>;

export const joiningDocument = z.object({
  id,
  name: z.string(),
  required: z.boolean(),
  status: z.string(),
  received_at: z.string().nullable(),
  name_on_document: z.string().nullable(),
  expiry_date: z.string().nullable(),
  note: z.string().nullable(),
});
export type JoiningDocument = z.infer<typeof joiningDocument>;

export const documentFlag = z.object({
  id,
  onboarding_document_id: id.nullable(),
  kind: z.string(),
  message: z.string(),
  status: z.string(),
  source: z.string(),
  resolution_reason: z.string().nullable(),
});
export type DocumentFlag = z.infer<typeof documentFlag>;

export const joiningCaseDetail = joiningCase.extend({
  documents: z.array(joiningDocument),
  flags: z.array(documentFlag),
  ai_verification_note: z.string(),
});
export type JoiningCaseDetail = z.infer<typeof joiningCaseDetail>;

export const listJoiningCases = () => apiFetch("/api/v1/onboarding/cases", z.array(joiningCase));
export const getJoiningCase = (caseId: string) =>
  apiFetch(`/api/v1/onboarding/cases/${caseId}`, joiningCaseDetail);
export const openJoiningCase = (body: {
  application_id: string;
  joining_date?: string;
  reporting_manager?: string;
  department?: string;
  work_location?: string;
  role_expectations?: string;
}) =>
  apiFetch(
    "/api/v1/onboarding/cases",
    z.object({ case: joiningCase, delivery: delivery.nullable() }),
    post(body),
  );
export const updateJoiningCase = (
  caseId: string,
  body: Partial<{
    joining_date: string | null;
    reporting_manager: string | null;
    department: string | null;
    work_location: string | null;
    role_expectations: string | null;
  }>,
) =>
  apiFetch(`/api/v1/onboarding/cases/${caseId}`, joiningCaseDetail, {
    method: "PATCH",
    body: JSON.stringify(body),
  });
export const approveJoiningContent = (caseId: string) =>
  apiFetch(`/api/v1/onboarding/cases/${caseId}/approve-content`, joiningCaseDetail, post());
export const receiveDocument = (
  caseId: string,
  documentId: string,
  body: { name_on_document?: string; expiry_date?: string; note?: string },
) =>
  apiFetch(
    `/api/v1/onboarding/cases/${caseId}/documents/${documentId}/receive`,
    joiningDocument,
    post(body),
  );
export const setDocumentStatus = (
  caseId: string,
  documentId: string,
  status: "accepted" | "waived" | "correction_requested" | "requested",
) =>
  apiFetch(
    `/api/v1/onboarding/cases/${caseId}/documents/${documentId}/status`,
    joiningDocument,
    post({ status }),
  );
export const verifyJoiningCase = (caseId: string) =>
  apiFetch(`/api/v1/onboarding/cases/${caseId}/verify`, z.array(documentFlag), post());
export const resolveFlag = (
  caseId: string,
  flagId: string,
  body: { action: "accepted" | "correction_requested" | "waived"; reason: string },
) =>
  apiFetch(`/api/v1/onboarding/cases/${caseId}/flags/${flagId}/resolve`, documentFlag, post(body));
export const remindDocuments = (caseId: string) =>
  apiFetch(`/api/v1/onboarding/cases/${caseId}/remind-documents`, delivery, post());
export const sendPrejoining = (caseId: string) =>
  apiFetch(`/api/v1/onboarding/cases/${caseId}/send-prejoining`, delivery, post());
export const sendWelcome = (caseId: string) =>
  apiFetch(`/api/v1/onboarding/cases/${caseId}/send-welcome`, delivery, post());
export const sendAnnouncement = (caseId: string, recipients: string[], joinerAgreed: boolean) =>
  apiFetch(
    `/api/v1/onboarding/cases/${caseId}/send-announcement`,
    z.object({ deliveries: z.array(delivery) }),
    post({ recipients, joiner_agreed: joinerAgreed }),
  );
export const markJoined = (caseId: string) =>
  apiFetch(`/api/v1/onboarding/cases/${caseId}/mark-joined`, joiningCaseDetail, post());
export const hrmsPreview = z.object({
  provider: z.string(),
  state: z.string(),
  message: z.string(),
  record: z.record(z.unknown()),
});
export const getHrmsPreview = (caseId: string) =>
  apiFetch(`/api/v1/onboarding/cases/${caseId}/hrms-preview`, hrmsPreview);

// ------------------------------------------------------- policies + assistant

export const indexStatusValue = z.enum(["not_indexed", "indexing", "ready", "failed"]);
export type IndexStatusValue = z.infer<typeof indexStatusValue>;

export const policy = z.object({
  id,
  family_id: id,
  title: z.string(),
  kind: z.string(),
  department: z.string().nullable(),
  body: z.string(),
  version: z.number(),
  status: z.string(),
  effective_date: z.string().nullable(),
  review_due_date: z.string().nullable().default(null),
  updated_at: z.string(),
  audience: z.array(z.string()).default(["everyone"]),
  index_status: indexStatusValue.default("not_indexed"),
  index_error: z.string().nullable().default(null),
  indexed_at: z.string().nullable().default(null),
  source_filename: z.string().nullable().default(null),
  has_file: z.boolean().default(false),
  acknowledged: z.boolean(),
  acknowledgement_count: z.number(),
});
export type Policy = z.infer<typeof policy>;
export type PolicyKind = "policy" | "sop" | "faq";
export const listPolicies = () => apiFetch("/api/v1/policies", z.array(policy));
export const createPolicy = (body: {
  title: string;
  kind: PolicyKind;
  department?: string;
  body: string;
  audience?: string[];
  review_due_date?: string;
  /* true (default on the server) = publish and sync now; false = keep as a draft. */
  publish?: boolean;
}) => apiFetch("/api/v1/policies", policy, post(body));
export const updatePolicy = (
  policyId: string,
  body: {
    title?: string;
    body?: string;
    department?: string;
    audience?: string[];
    review_due_date?: string | null;
  },
) =>
  apiFetch(`/api/v1/policies/${policyId}`, policy, { method: "PUT", body: JSON.stringify(body) });

export interface PolicyUpload {
  file: File;
  title: string;
  kind: PolicyKind;
  department?: string;
  audience?: string[];
  reviewDueDate?: string;
  confirmDuplicate?: boolean;
  /* true = publish and sync on upload (default); false = keep as a draft. */
  publish?: boolean;
}
export const uploadPolicy = (u: PolicyUpload) => {
  const form = new FormData();
  form.append("file", u.file);
  form.append("title", u.title);
  form.append("kind", u.kind);
  if (u.department) form.append("department", u.department);
  if (u.audience && u.audience.length) form.append("audience", u.audience.join(","));
  if (u.reviewDueDate) form.append("review_due_date", u.reviewDueDate);
  if (u.confirmDuplicate) form.append("confirm_duplicate", "true");
  form.append("publish", u.publish === false ? "false" : "true");
  return apiUpload("/api/v1/policies/upload", policy, form);
};
export const replacePolicyFile = (policyId: string, file: File, confirmDuplicate = false) => {
  const form = new FormData();
  form.append("file", file);
  if (confirmDuplicate) form.append("confirm_duplicate", "true");
  return apiUpload(`/api/v1/policies/${policyId}/file`, policy, form);
};
export const reindexPolicy = (policyId: string) =>
  apiFetch(`/api/v1/policies/${policyId}/reindex`, policy, post());
export const indexStatusRead = z.object({
  policy_id: id,
  status: z.string(),
  index_status: indexStatusValue,
  index_error: z.string().nullable(),
  indexed_at: z.string().nullable(),
  ingestion_job_id: z.string().nullable(),
  backend: z.string(),
});
export const getIndexStatus = (policyId: string) =>
  apiFetch(`/api/v1/policies/${policyId}/index-status`, indexStatusRead);
export const getOriginalLink = (policyId: string) =>
  apiFetch(
    `/api/v1/policies/${policyId}/original-link`,
    z.object({ url: z.string().nullable(), expires_in: z.number().nullable() }),
  );
/* "Open original": a short-lived signed link when the server has one (S3), otherwise the
   file is fetched with the session token and saved; it is never rendered in the page. */
export async function downloadPolicyOriginal(policyId: string): Promise<{ blob: Blob; filename: string }> {
  const token = getAccessToken();
  const resp = await fetch(`/api/v1/policies/${policyId}/original`, {
    headers: token ? { Authorization: `Bearer ${token}` } : {},
  });
  if (!resp.ok) throw new Error(`The file could not be downloaded (${resp.status}).`);
  const disposition = resp.headers.get("Content-Disposition") ?? "";
  const match = /filename\*=UTF-8''([^;]+)/i.exec(disposition);
  const filename = match?.[1] ? decodeURIComponent(match[1]) : "policy";
  return { blob: await resp.blob(), filename };
}
export const duplicatesDetail = z.object({
  duplicates: z.array(z.object({ id, title: z.string(), version: z.number(), status: z.string() })),
});
export const approvePolicy = (policyId: string) =>
  apiFetch(`/api/v1/policies/${policyId}/approve`, policy, post());
export const retirePolicy = (policyId: string) =>
  apiFetch(`/api/v1/policies/${policyId}/retire`, policy, post());
export const revisePolicy = (policyId: string) =>
  apiFetch(`/api/v1/policies/${policyId}/revise`, policy, post());
export const acknowledgePolicy = (policyId: string) =>
  apiFetch(`/api/v1/policies/${policyId}/acknowledge`, policy, post());

export const answerSource = z.object({
  ref: z.number().default(1),
  policy_id: id,
  title: z.string(),
  version: z.number(),
  page: z.number().nullable().default(null),
  excerpt: z.string().default(""),
});
export type AnswerSource = z.infer<typeof answerSource>;
export const askResponse = z.object({
  answered: z.boolean(),
  answer: z.string(),
  sources: z.array(answerSource),
  route_to_hr: z.boolean(),
  note: z.string(),
  outcome: z.string().default("answered"),
  answered_via: z.string().nullable().default(null),
  smart_search_unavailable: z.boolean().default(false),
  query_id: id.nullable().default(null),
});
export type AskResponse = z.infer<typeof askResponse>;
export const askAssistant = (question: string) =>
  apiFetch("/api/v1/assistant/ask", askResponse, post({ question }));
export const unansweredItem = z.object({
  id: id.optional(),
  question: z.string(),
  asked_at: z.string(),
});
export const listUnanswered = () =>
  apiFetch("/api/v1/assistant/unanswered", z.array(unansweredItem));
export const faqFromUnanswered = (queryId: string) =>
  apiFetch(`/api/v1/assistant/unanswered/${queryId}/faq-draft`, policy, post());

export const sendAnswerFeedback = (body: { query_id: string; helpful: boolean; comment?: string }) =>
  apiFetch(
    "/api/v1/assistant/feedback",
    z.object({ id, query_id: id, helpful: z.boolean() }),
    post(body),
  );

export const hrQuestion = z.object({
  id,
  question: z.string(),
  contact_preference: z.string(),
  status: z.enum(["open", "answered", "closed"]),
  answer: z.string().nullable(),
  answered_at: z.string().nullable(),
  created_at: z.string(),
});
export type HrQuestion = z.infer<typeof hrQuestion>;
export const hrInboxItem = hrQuestion.extend({
  asked_by: id,
  asked_by_name: z.string().nullable(),
  asked_by_email: z.string().nullable(),
});
export type HrInboxItem = z.infer<typeof hrInboxItem>;
/* idempotencyKey makes a double-click or a retry create ONE question. */
export const escalateToHr = (
  body: { question: string; contact_preference: "in_app" | "email" },
  idempotencyKey: string,
) =>
  apiFetch("/api/v1/assistant/escalate", hrQuestion, {
    ...post(body),
    headers: { "Idempotency-Key": idempotencyKey },
  });
export const listMyHrQuestions = () =>
  apiFetch("/api/v1/assistant/my-questions", z.array(hrQuestion));
export const listHrInbox = (status?: "open" | "answered" | "closed") =>
  apiFetch(`/api/v1/hr-questions${status ? `?status=${status}` : ""}`, z.array(hrInboxItem));
export const answerHrQuestion = (questionId: string, answer: string) =>
  apiFetch(`/api/v1/hr-questions/${questionId}/answer`, hrInboxItem, post({ answer }));
export const closeHrQuestion = (questionId: string) =>
  apiFetch(`/api/v1/hr-questions/${questionId}/close`, hrInboxItem, post());
export const faqFromHrQuestion = (questionId: string) =>
  apiFetch(`/api/v1/hr-questions/${questionId}/faq-draft`, policy, post());

const questionCount = z.object({ question: z.string(), count: z.number() });
export const assistantInsights = z.object({
  period_days: z.number(),
  total_questions: z.number(),
  answered: z.number(),
  not_found: z.number(),
  self_service: z.number(),
  guardrail_blocked: z.number(),
  by_backend: z.record(z.number()),
  helpful: z.number(),
  not_helpful: z.number(),
  not_helpful_rate: z.number().nullable(),
  top_questions: z.array(questionCount),
  top_unanswered: z.array(questionCount),
  open_hr_questions: z.number(),
  review_due: z.array(
    z.object({ policy_id: id, title: z.string(), version: z.number(), review_due_date: z.string() }),
  ),
});
export type AssistantInsights = z.infer<typeof assistantInsights>;
export const getAssistantInsights = (days = 30) =>
  apiFetch(`/api/v1/assistant/insights?days=${days}`, assistantInsights);

// ------------------------------------------------------ interview confirmation

export const linkIssued = z.object({
  url: z.string(),
  expires_at: z.string(),
  delivery: delivery.nullable(),
});
export const linkStatus = z.object({
  has_link: z.boolean(),
  state: z.string(),
  response: z.string().nullable(),
  responded_at: z.string().nullable(),
  expires_at: z.string().nullable(),
  invitation_status: z.string(),
  message: z.string(),
});
export type LinkStatus = z.infer<typeof linkStatus>;
export const suggestedSlot = z.object({
  slot_id: id,
  stage_name: z.string(),
  slot_date: z.string(),
  start_time: z.string(),
  location: z.string().nullable(),
  mode: z.string(),
  remaining: z.number(),
});
export type SuggestedSlot = z.infer<typeof suggestedSlot>;
const confBase = "/api/v1/interview-confirmations";
export const issueConfirmationLink = (
  invitationId: string,
  send: boolean,
  channel: "email" | "whatsapp" = "email",
) => apiFetch(`${confBase}/invitations/${invitationId}/link?send=${send}&channel=${channel}`, linkIssued, post());
export const remindInterview = (invitationId: string, channel: "email" | "whatsapp" = "email") =>
  apiFetch(`${confBase}/invitations/${invitationId}/remind?channel=${channel}`, delivery, post());
export const getLinkStatus = (invitationId: string) =>
  apiFetch(`${confBase}/invitations/${invitationId}/status`, linkStatus);
export const getSuggestedSlots = (invitationId: string) =>
  apiFetch(`${confBase}/invitations/${invitationId}/suggested-slots`, z.array(suggestedSlot));

export const publicPreview = z.object({
  state: z.string(),
  first_name: z.string(),
  role_title: z.string(),
  when: z.string(),
  where: z.string(),
  mode: z.string(),
  message: z.string(),
});
export type PublicPreview = z.infer<typeof publicPreview>;
export const getConfirmationPreview = (token: string) =>
  apiFetch(`${confBase}/public/${encodeURIComponent(token)}`, publicPreview);
export const respondToConfirmation = (
  token: string,
  response: "confirmed" | "declined" | "reschedule_requested",
) =>
  apiFetch(
    `${confBase}/public/${encodeURIComponent(token)}/respond`,
    z.object({ response: z.string(), message: z.string() }),
    post({ response }),
  );

// ---------------------------------------------------------------- integrations

export const integration = z.object({
  key: z.string(),
  name: z.string(),
  purpose: z.string(),
  state: z.string(),
  message: z.string(),
  needs: z.array(z.string()),
  used_by: z.array(z.string()),
});
export type Integration = z.infer<typeof integration>;
export const listIntegrations = () => apiFetch("/api/v1/integrations", z.array(integration));

// -------------------------------------------------------------------- journey

export const journeyStage = z.object({
  key: z.string(),
  label: z.string(),
  description: z.string(),
  owner: z.string(),
  status: z.string(),
  optional: z.boolean(),
  detail: z.string().nullable(),
  at: z.string().nullable(),
});
export type JourneyStage = z.infer<typeof journeyStage>;
export const journey = z.object({
  application_id: id,
  campaign_id: id,
  candidate_name: z.string(),
  role_title: z.string(),
  application_state: z.string(),
  current_stage: z.string().nullable(),
  next_step: z.string(),
  closed: z.boolean(),
  stages: z.array(journeyStage),
});
export type Journey = z.infer<typeof journey>;
export const getJourney = (applicationId: string) =>
  apiFetch(`/api/v1/journey/applications/${applicationId}`, journey);

// ----------------------------------------------------------- feedback summary

export const feedbackSummary = z.object({
  application_id: id,
  assessments_count: z.number(),
  recommendation_counts: z.record(z.number()),
  agreement: z.string(),
  criteria: z.array(
    z.object({
      name: z.string(),
      average: z.number(),
      lowest: z.number(),
      highest: z.number(),
      count: z.number(),
    }),
  ),
  notes: z.array(
    z.object({
      interviewer: z.string(),
      recommendation: z.string(),
      problem_solving_notes: z.string().nullable(),
      role_understanding_notes: z.string().nullable(),
      interview_notes: z.string().nullable(),
    }),
  ),
  conflicts_declared: z.number(),
  ai_summary_state: z.string(),
  ai_summary_note: z.string(),
  advisory_note: z.string(),
});
export type FeedbackSummary = z.infer<typeof feedbackSummary>;
export const getFeedbackSummary = (applicationId: string) =>
  apiFetch(`/api/v1/assessments/summary/${applicationId}`, feedbackSummary);

// ------------------------------------------------------------------- waitlist

export const waitlistEntry = z.object({
  id,
  application_id: id,
  campaign_id: id,
  reason: z.string(),
  status: z.string(),
  eligibility_state: z.string(),
  candidate_name: z.string(),
  created_at: z.string(),
});
export type WaitlistEntry = z.infer<typeof waitlistEntry>;
export const listWaitlist = (campaignId: string) =>
  apiFetch(`/api/v1/waitlist?campaign_id=${campaignId}`, z.array(waitlistEntry));
export const addToWaitlist = (body: { application_id: string; reason: string }) =>
  apiFetch(
    "/api/v1/waitlist",
    z.object({ id, application_id: id, campaign_id: id, reason: z.string(), status: z.string() }),
    post(body),
  );
export const reevaluateApplication = (body: {
  application_id: string;
  trigger: "reviewer_requested" | "new_verified_information";
  reason: string;
}) =>
  apiFetch(
    "/api/v1/waitlist/reevaluate",
    z.object({ new_run_id: id, previous_run_id: id.nullable(), result_changed: z.boolean() }),
    post(body),
  );

// ------------------------------------------------------------------- privacy

export const privacyRequest = z.object({
  id,
  candidate_id: id,
  request_type: z.string(),
  status: z.string(),
  candidate_email_masked: z.string(),
  detail: z.string().nullable(),
  created_at: z.string(),
  completed_at: z.string().nullable(),
});
export type PrivacyRequest = z.infer<typeof privacyRequest>;
export const listPrivacyRequests = () =>
  apiFetch("/api/v1/privacy/requests", z.array(privacyRequest));
export const createPrivacyRequest = (body: {
  candidate_email: string;
  request_type: string;
  detail?: string;
}) =>
  apiFetch(
    "/api/v1/privacy/requests",
    z.object({ id, candidate_id: id, request_type: z.string(), status: z.string() }),
    post(body),
  );
export const completePrivacyRequest = (requestId: string) =>
  apiFetch(
    `/api/v1/privacy/requests/${requestId}/complete`,
    z.object({ id, candidate_id: id, request_type: z.string(), status: z.string() }),
    post(),
  );

// --------------------------------------------------------------------- audit

export const auditEvent = z.object({
  id,
  sequence: z.number(),
  actor_role: z.string().nullable(),
  action: z.string(),
  entity_type: z.string(),
  entity_id: z.string().nullable(),
  reason: z.string().nullable(),
  occurred_at: z.string(),
  integrity_hash: z.string(),
});
export type AuditEvent = z.infer<typeof auditEvent>;
export const listAuditEvents = (limit = 50, offset = 0) =>
  apiFetch(`/api/v1/audit?limit=${limit}&offset=${offset}`, z.array(auditEvent));
