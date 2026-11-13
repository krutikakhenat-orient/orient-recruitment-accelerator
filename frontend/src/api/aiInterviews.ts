// AI voice-interview API (staff + candidate). The agent is ADVISORY: nothing here carries a
// score, rank or hiring verdict. See backend app/modules/ai_interviews.

import { z } from "zod";

import { apiFetch, getAccessToken } from "./client";

const uuid = z.string().uuid();

const question = z
  .object({
    id: z.string(),
    text: z.string(),
    competency: z.string(),
    source: z.string(),
    evidence_ref: z.string().nullish(),
  })
  .passthrough();
export type AiQuestion = z.infer<typeof question>;

export const aiInterview = z
  .object({
    id: uuid,
    application_id: uuid,
    campaign_id: uuid,
    status: z.string(),
    role_title: z.string(),
    questions: z.array(question),
    generated_by: z.string().nullish(),
    approved_at: z.string().nullish(),
    link_expires_at: z.string().nullish(),
    consent_given_at: z.string().nullish(),
    start_count: z.number(),
    completed_at: z.string().nullish(),
    end_reason: z.string().nullish(),
    has_result: z.boolean(),
    summary: z.record(z.unknown()).nullish(),
    created_at: z.string(),
  })
  .passthrough();
export type AiInterview = z.infer<typeof aiInterview>;

const approveResponse = z.object({
  session: aiInterview,
  link_url: z.string(),
  link_expires_at: z.string(),
});
export type ApproveResponse = z.infer<typeof approveResponse>;

const transcript = z.object({
  session_id: uuid,
  turns: z.array(
    z.object({
      speaker: z.string(),
      text: z.string(),
      question_id: z.string().nullish(),
      at: z.string().nullish(),
      flags: z.array(z.string()).default([]),
    }),
  ),
});
export type AiTranscript = z.infer<typeof transcript>;

// ---------- staff ----------
const base = "/api/v1/ai-interviews";

export const listAiInterviews = (campaignId: string) =>
  apiFetch(`${base}/campaigns/${campaignId}/sessions`, z.array(aiInterview));

export const createAiInterviewDraft = (applicationId: string) =>
  apiFetch(`${base}/applications/${applicationId}`, aiInterview, { method: "POST" });

export const planAiInterview = (id: string) =>
  apiFetch(`${base}/sessions/${id}/plan`, aiInterview, { method: "POST" });

export const approveAiInterview = (
  id: string,
  body: { questions?: { id: string; text: string }[]; reason?: string },
) =>
  apiFetch(`${base}/sessions/${id}/approve`, approveResponse, {
    method: "POST",
    body: JSON.stringify(body),
  });

export const reissueAiInterviewLink = (id: string) =>
  apiFetch(`${base}/sessions/${id}/link`, approveResponse, { method: "POST" });

// Offer another attempt after a finished interview. The finished attempt and its result are
// kept; the response carries the NEW attempt and its one-time link.
export const retryAiInterview = (id: string, reason: string) =>
  apiFetch(`${base}/sessions/${id}/retry`, approveResponse, {
    method: "POST",
    body: JSON.stringify({ reason }),
  });

export const revokeAiInterview = (id: string) =>
  apiFetch(`${base}/sessions/${id}/revoke`, aiInterview, { method: "POST" });

export const getAiInterviewTranscript = (id: string) =>
  apiFetch(`${base}/sessions/${id}/transcript`, transcript);

// ---------- candidate (public; the link token travels in the body, never the URL path) ----------
const preview = z.object({
  role_title: z.string(),
  status: z.string(),
  notice_version: z.string(),
  notice_text: z.string(),
  max_minutes: z.number(),
  text_input_allowed: z.boolean(),
  video_recording_offered: z.boolean().optional(),
  video_notice_version: z.string().nullish(),
  video_notice_text: z.string().nullish(),
});
export type AiInterviewPreview = z.infer<typeof preview>;

const start = z.object({
  interview_id: uuid,
  ws_url: z.string(),
  join_token: z.string(),
  recording_token: z.string().nullish(),
});
export type AiInterviewStart = z.infer<typeof start>;

export const previewAiInterview = (token: string) =>
  apiFetch(`${base}/public/preview`, preview, {
    method: "POST",
    body: JSON.stringify({ token }),
  });

export const startAiInterview = (
  token: string,
  noticeVersion: string,
  video?: { noticeVersion: string } | null,
) =>
  apiFetch(`${base}/public/start`, start, {
    method: "POST",
    body: JSON.stringify({
      token,
      consent: true,
      notice_version: noticeVersion,
      ...(video ? { video_consent: true, video_notice_version: video.noticeVersion } : {}),
    }),
  });

// ---------- video evidence (staff). Viewing needs candidate.view_pii and is audited. ----------
const recording = z.object({
  id: uuid,
  session_id: uuid,
  attempt_start: z.number(),
  status: z.string(),
  content_type: z.string(),
  bytes_total: z.number(),
  consent_given_at: z.string(),
  finished_at: z.string().nullish(),
  delete_after: z.string(),
  created_at: z.string(),
});
export type AiRecording = z.infer<typeof recording>;

export const listAiRecordings = (sessionId: string) =>
  apiFetch(`${base}/sessions/${sessionId}/recordings`, z.array(recording));

const playback = z.object({
  url: z.string().nullish(),
  content_type: z.string(),
  expires_in_seconds: z.number().nullish(),
});

/** A URL the <video> element can play: a signed link (AWS) or a local blob URL. */
export async function aiRecordingVideoUrl(recordingId: string): Promise<{ url: string; isBlob: boolean }> {
  const p = await apiFetch(`${base}/recordings/${recordingId}/playback`, playback);
  if (p.url) return { url: p.url, isBlob: false };
  // Local storage: the stream needs the auth header, which a <video> tag cannot send.
  const token = getAccessToken();
  const resp = await fetch(`${base}/recordings/${recordingId}/stream`, {
    headers: token ? { Authorization: `Bearer ${token}` } : {},
  });
  if (!resp.ok) {
    const body = (await resp.json().catch(() => null)) as { error?: { message?: string } } | null;
    throw new Error(body?.error?.message ?? "Could not load the recording.");
  }
  return { url: URL.createObjectURL(await resp.blob()), isBlob: true };
}

// ---------- advisory summary (rendered, never scored) ----------
const summaryView = z
  .object({
    overview: z.string().optional(),
    duration_seconds: z.number().optional(),
    end_reason: z.string().optional(),
    advisory_notice: z.string().optional(),
    topics_to_probe_next: z.array(z.string()).optional(),
    integrity_flags: z.array(z.string()).optional(),
    assessments: z
      .array(
        z
          .object({
            question_text: z.string(),
            coverage: z.string(),
            answer_summary: z.string(),
            evidence_quotes: z.array(z.string()).optional(),
            needs_human_review: z.boolean().optional(),
            review_reason: z.string().nullish(),
          })
          .passthrough(),
      )
      .optional(),
  })
  .passthrough();
export type AiSummaryView = z.infer<typeof summaryView>;

export function parseAiSummary(raw: unknown): AiSummaryView | null {
  const parsed = summaryView.safeParse(raw);
  return parsed.success ? parsed.data : null;
}
