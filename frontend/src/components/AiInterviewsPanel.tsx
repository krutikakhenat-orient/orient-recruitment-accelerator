import { useMutation, useQuery, useQueryClient } from "@tanstack/react-query";
import { Fragment, useEffect, useState, type ReactNode } from "react";

import {
  aiRecordingVideoUrl,
  approveAiInterview,
  listAiRecordings,
  createAiInterviewDraft,
  getAiInterviewTranscript,
  listAiInterviews,
  parseAiSummary,
  planAiInterview,
  reissueAiInterviewLink,
  retryAiInterview,
  revokeAiInterview,
  type AiInterview,
  type ApproveResponse,
} from "../api/aiInterviews";
import { ApiError } from "../api/client";
import { useAuth } from "../app/auth-context";
import { Badge, Button, Card, Drawer, Empty, ErrorNote, Loading, Modal, prettify } from "./ui";
import { useToast } from "./toast";

/* Recruiter-side control of the AI voice interview for one campaign.

   Flow: screening drafts a session -> a recruiter drafts the questions (the agent plans them
   from the JD + resume) -> a person reviews/edits and APPROVES -> a single-use candidate link
   is shown ONCE -> the candidate interviews -> an ADVISORY summary appears here. There is no
   score, ranking or hiring verdict anywhere: people read the summary/transcript and decide. */

export interface OfferableApplication {
  id: string;
  label: string;
}

const STATUS_LABEL: Record<string, { text: string; tone: "ok" | "warn" | "info" | "neutral" | "danger" }> = {
  pending_plan: { text: "Needs questions", tone: "warn" },
  questions_ready: { text: "Awaiting your approval", tone: "warn" },
  approved: { text: "Link issued", tone: "info" },
  in_progress: { text: "Candidate in interview", tone: "info" },
  completed: { text: "Completed", tone: "ok" },
  expired: { text: "Link expired", tone: "neutral" },
  revoked: { text: "Revoked", tone: "danger" },
};

// How the agent says an interview ended, in plain words. Anything other than "completed"
// means the call ended before all questions were covered, so a retry is offered first.
export const END_REASON_LABEL: Record<string, string> = {
  completed: "All questions covered",
  candidate_requested_stop: "Candidate asked to stop",
  candidate_disconnected: "Call dropped",
  no_response: "No response from candidate",
  time_limit: "Time limit reached",
  error: "Technical problem",
};

export function endedEarly(row: AiInterview): boolean {
  return row.status === "completed" && (row.end_reason ?? "completed") !== "completed";
}

/* Attempt number for every row (1 = first) and which row is the latest per candidate. */
export function attemptInfo(rows: AiInterview[]): Map<string, { attempt: number; total: number; latest: boolean }> {
  const byApp = new Map<string, AiInterview[]>();
  for (const r of rows) byApp.set(r.application_id, [...(byApp.get(r.application_id) ?? []), r]);
  const info = new Map<string, { attempt: number; total: number; latest: boolean }>();
  for (const list of byApp.values()) {
    const sorted = [...list].sort((a, b) => Date.parse(a.created_at) - Date.parse(b.created_at));
    sorted.forEach((r, i) => info.set(r.id, { attempt: i + 1, total: sorted.length, latest: i === sorted.length - 1 }));
  }
  return info;
}

const RETRY_REASONS = [
  "The call dropped or had a technical problem",
  "Candidate stopped by mistake and asked to try again",
  "Candidate couldn't hear or be heard",
];

export function AiInterviewsPanel({
  campaignId,
  nameOf,
  offerable,
  applicationId,
}: {
  campaignId: string;
  nameOf: (applicationId: string) => string;
  offerable: OfferableApplication[];
  /** When set (the candidate page), show only this candidate's AI interviews. */
  applicationId?: string;
}): ReactNode {
  const toast = useToast();
  const qc = useQueryClient();
  const { hasPermission, canAccessCampaign } = useAuth();
  const assigned = canAccessCampaign(campaignId);
  const canPlan = hasPermission("interview.schedule") && assigned;
  const canApprove = hasPermission("interview.approve") && assigned;
  const canTranscript = hasPermission("candidate.view_pii") && assigned;

  const key = ["ai-interviews", campaignId];
  const sessions = useQuery({ queryKey: key, queryFn: () => listAiInterviews(campaignId) });
  const [error, setError] = useState<string | null>(null);
  // Links by session id. Each candidate has their own link, shown once under their row.
  // Kept in memory only: the server stores just a hash, so a lost link needs a new one.
  const [links, setLinks] = useState<Record<string, ApproveResponse>>({});
  const showLink = (r: ApproveResponse): void => setLinks((prev) => ({ ...prev, [r.session.id]: r }));
  const hideLink = (sessionId: string): void =>
    setLinks((prev) => Object.fromEntries(Object.entries(prev).filter(([id]) => id !== sessionId)));
  const [reviewing, setReviewing] = useState<AiInterview | null>(null);
  const [viewing, setViewing] = useState<AiInterview | null>(null);
  const [retrying, setRetrying] = useState<AiInterview | null>(null);
  const [offerId, setOfferId] = useState("");

  const refresh = (): void => {
    void qc.invalidateQueries({ queryKey: key });
  };
  const fail = (fallback: string) => (e: unknown): void =>
    setError(e instanceof ApiError ? e.message : fallback);

  const offer = useMutation({
    mutationFn: (applicationId: string) => createAiInterviewDraft(applicationId),
    onSuccess: () => {
      setOfferId("");
      refresh();
      toast.push("AI interview drafted", { tone: "ok" });
    },
    onError: fail("Could not offer an AI interview."),
  });
  const plan = useMutation({
    mutationFn: (id: string) => planAiInterview(id),
    onSuccess: (row) => {
      refresh();
      setReviewing(row);
      toast.push("Questions drafted — review them before approving", { tone: "ok" });
    },
    onError: fail("Could not draft the questions."),
  });
  const reissue = useMutation({
    mutationFn: (id: string) => reissueAiInterviewLink(id),
    onSuccess: (r) => {
      showLink(r);
      refresh();
    },
    onError: fail("Could not issue a new link."),
  });
  const revoke = useMutation({
    mutationFn: (id: string) => revokeAiInterview(id),
    onSuccess: () => {
      refresh();
      toast.push("Interview revoked", { tone: "ok" });
    },
    onError: fail("Could not revoke the interview."),
  });

  const rows = (sessions.data ?? []).filter(
    (r) => !applicationId || r.application_id === applicationId,
  );
  const attempts = attemptInfo(rows);
  // Mirrors the backend's LIVE_STATUSES: a revoked or expired session no longer blocks a new
  // offer for the same candidate (the server creates a fresh draft in that case).
  const haveSession = new Set(
    rows.filter((r) => r.status !== "revoked" && r.status !== "expired").map((r) => r.application_id),
  );
  const canOffer = offerable.filter((o) => !haveSession.has(o.id));

  return (
    <Card title="AI voice interviews">
      <p className="subtle" style={{ marginTop: 0 }}>
        An automated voice interview the candidate takes from a link. It is advisory only: it
        never scores, ranks or decides. A person must approve the questions before any link
        exists, and a person reads the result.
      </p>
      {error && <ErrorNote>{error}</ErrorNote>}

      {canPlan && applicationId && canOffer.length > 0 && (
        <div className="btn-row" style={{ margin: "8px 0 12px" }}>
          <Button
            variant="primary"
            disabled={offer.isPending}
            onClick={() => {
              setError(null);
              offer.mutate(canOffer[0]!.id);
            }}
          >
            {offer.isPending ? "Offering…" : "Offer an AI interview"}
          </Button>
          <span className="subtle">Then draft the questions and approve them to create the link.</span>
        </div>
      )}
      {canPlan && !applicationId && canOffer.length > 0 && (
        <div className="btn-row" style={{ margin: "8px 0 12px", alignItems: "end" }}>
          <div className="field" style={{ margin: 0 }}>
            <label htmlFor="ai-offer">Offer an AI interview to</label>
            <select id="ai-offer" value={offerId} onChange={(e) => setOfferId(e.target.value)}>
              <option value="">Choose a candidate…</option>
              {canOffer.map((o) => (
                <option key={o.id} value={o.id}>
                  {o.label}
                </option>
              ))}
            </select>
          </div>
          <Button
            disabled={!offerId || offer.isPending}
            onClick={() => {
              setError(null);
              offer.mutate(offerId);
            }}
          >
            Offer AI interview
          </Button>
        </div>
      )}

      {sessions.isLoading && <Loading />}
      {sessions.error && <ErrorNote>Could not load AI interviews.</ErrorNote>}
      {!sessions.isLoading && rows.length === 0 && (
        <Empty>
          No AI interviews yet. When AI interviews are enabled, candidates cleared for interview
          appear here automatically, or you can offer one above.
        </Empty>
      )}

      {rows.length > 0 && (
        <div className="table-wrap">
          <table className="data">
            <thead>
              <tr>
                <th>Candidate</th>
                <th>Status</th>
                <th>Details</th>
                <th>Actions</th>
              </tr>
            </thead>
            <tbody>
              {rows.map((r) => {
                const s = STATUS_LABEL[r.status] ?? { text: prettify(r.status), tone: "neutral" as const };
                const early = endedEarly(r);
                const a = attempts.get(r.id);
                const canRetryRow = r.status === "completed" && (a?.latest ?? true);
                const link = links[r.id];
                return (
                  <Fragment key={r.id}>
                  <tr>
                    <td>
                      {nameOf(r.application_id)}
                      {a && a.total > 1 && <div className="subtle">Attempt {a.attempt}</div>}
                    </td>
                    <td>
                      <Badge tone={early ? "warn" : s.tone}>{early ? "Ended early" : s.text}</Badge>
                    </td>
                    <td className="subtle">
                      {r.status === "approved" && r.link_expires_at
                        ? `Link expires ${new Date(r.link_expires_at).toLocaleString()}`
                        : r.status === "completed" && r.completed_at
                          ? `Finished ${new Date(r.completed_at).toLocaleString()}${
                              r.end_reason ? ` · ${END_REASON_LABEL[r.end_reason] ?? prettify(r.end_reason)}` : ""
                            }`
                          : r.questions.length > 0
                            ? `${r.questions.length} questions`
                            : "—"}
                      {canRetryRow && early && (
                        <div>Not all questions were covered. You can offer the candidate another try.</div>
                      )}
                      {r.status === "completed" && a && !a.latest && <div>A newer attempt exists.</div>}
                    </td>
                    <td>
                      <div className="btn-row">
                        {r.status === "pending_plan" && (
                          <Button
                            small
                            variant="primary"
                            disabled={!canPlan || plan.isPending}
                            onClick={() => {
                              setError(null);
                              plan.mutate(r.id);
                            }}
                          >
                            {plan.isPending ? "Drafting…" : "Draft questions"}
                          </Button>
                        )}
                        {r.status === "questions_ready" && (
                          <>
                            <Button
                              small
                              variant="primary"
                              disabled={!canApprove}
                              title={canApprove ? undefined : "Approving needs the Recruiter Admin role"}
                              onClick={() => setReviewing(r)}
                            >
                              Review &amp; approve
                            </Button>
                            <Button
                              small
                              disabled={!canPlan || plan.isPending}
                              onClick={() => {
                                setError(null);
                                plan.mutate(r.id);
                              }}
                            >
                              Redraft
                            </Button>
                          </>
                        )}
                        {(r.status === "approved" || r.status === "in_progress" || r.status === "expired") && (
                          <>
                            <Button
                              small
                              disabled={!canApprove || reissue.isPending}
                              title="Issues a new link; the old one stops working"
                              onClick={() => {
                                setError(null);
                                reissue.mutate(r.id);
                              }}
                            >
                              New link
                            </Button>
                            <Button
                              small
                              variant="danger"
                              disabled={!canApprove || revoke.isPending}
                              onClick={() => {
                                setError(null);
                                revoke.mutate(r.id);
                              }}
                            >
                              Revoke
                            </Button>
                          </>
                        )}
                        {r.status === "completed" && (
                          <Button small variant={early && canRetryRow ? "default" : "primary"} onClick={() => setViewing(r)}>
                            View result
                          </Button>
                        )}
                        {canRetryRow && (
                          <Button
                            small
                            variant={early ? "primary" : "default"}
                            disabled={!canApprove}
                            title={
                              canApprove
                                ? "Send the candidate a new link with the same questions. This attempt stays on record."
                                : "Offering another attempt needs the Recruiter Admin role"
                            }
                            onClick={() => {
                              setError(null);
                              setRetrying(r);
                            }}
                          >
                            Retry interview
                          </Button>
                        )}
                      </div>
                    </td>
                  </tr>
                  {link && (
                    <tr>
                      <td colSpan={4}>
                        <IssuedLink
                          issued={link}
                          name={nameOf(r.application_id)}
                          onClose={() => hideLink(r.id)}
                        />
                      </td>
                    </tr>
                  )}
                  </Fragment>
                );
              })}
            </tbody>
          </table>
        </div>
      )}

      {reviewing && (
        <ReviewQuestionsModal
          row={reviewing}
          canApprove={canApprove}
          nameOf={nameOf}
          onClose={() => setReviewing(null)}
          onApproved={(r) => {
            setReviewing(null);
            showLink(r);
            refresh();
          }}
          onError={(m) => setError(m)}
        />
      )}
      {retrying && (
        <RetryModal
          row={retrying}
          name={nameOf(retrying.application_id)}
          onClose={() => setRetrying(null)}
          onIssued={(r) => {
            setRetrying(null);
            showLink(r);
            refresh();
            toast.push("New attempt created. Copy the link and send it to the candidate.", { tone: "ok" });
          }}
        />
      )}
      {viewing && (
        <ResultDrawer
          row={viewing}
          name={nameOf(viewing.application_id)}
          canTranscript={canTranscript}
          onClose={() => setViewing(null)}
        />
      )}
    </Card>
  );
}

/* The link is shown once: only its hash is stored, so it cannot be recovered later. */
function IssuedLink({
  issued,
  name,
  onClose,
}: {
  issued: ApproveResponse;
  name: string;
  onClose: () => void;
}): ReactNode {
  const toast = useToast();
  return (
    <div className="card" role="status" style={{ margin: "4px 0" }}>
      <strong>Interview link for {name}</strong>
      <p className="subtle" style={{ margin: "4px 0 8px" }}>
        This link is for {name} only. Copy it now and send it to them. For security it is shown
        only once (create a new link if you lose it). Expires{" "}
        {new Date(issued.link_expires_at).toLocaleString()}.
      </p>
      <div className="btn-row">
        <input
          readOnly
          aria-label={`Interview link for ${name}`}
          value={issued.link_url}
          style={{ flex: 1, minWidth: 260 }}
          onFocus={(e) => e.currentTarget.select()}
        />
        <Button
          variant="primary"
          small
          onClick={() => {
            void navigator.clipboard
              .writeText(issued.link_url)
              .then(() => toast.push("Link copied", { tone: "ok" }))
              .catch(() => toast.push("Could not copy; select the link and copy it manually", { tone: "danger" }));
          }}
        >
          Copy link
        </Button>
        <Button small onClick={onClose}>
          Dismiss
        </Button>
      </div>
    </div>
  );
}

function ReviewQuestionsModal({
  row,
  canApprove,
  nameOf,
  onClose,
  onApproved,
  onError,
}: {
  row: AiInterview;
  canApprove: boolean;
  nameOf: (id: string) => string;
  onClose: () => void;
  onApproved: (r: ApproveResponse) => void;
  onError: (m: string) => void;
}): ReactNode {
  const [texts, setTexts] = useState<Record<string, string>>(
    Object.fromEntries(row.questions.map((q) => [q.id, q.text])),
  );
  const [dropped, setDropped] = useState<Set<string>>(new Set());
  const [reason, setReason] = useState("");

  const kept = row.questions.filter((q) => !dropped.has(q.id));
  const tooShort = kept.some((q) => (texts[q.id] ?? "").trim().length < 5);

  const approve = useMutation({
    mutationFn: () =>
      approveAiInterview(row.id, {
        questions: kept.map((q) => ({ id: q.id, text: (texts[q.id] ?? q.text).trim() })),
        ...(reason.trim() ? { reason: reason.trim() } : {}),
      }),
    onSuccess: onApproved,
    onError: (e) => onError(e instanceof ApiError ? e.message : "Could not approve the questions."),
  });

  return (
    <Modal
      title={`Review questions — ${nameOf(row.application_id)}`}
      onClose={onClose}
      footer={
        <>
          <Button onClick={onClose}>Cancel</Button>
          <Button
            variant="primary"
            disabled={!canApprove || kept.length === 0 || tooShort || approve.isPending}
            onClick={() => approve.mutate()}
          >
            {approve.isPending ? "Approving…" : "Approve & create link"}
          </Button>
        </>
      }
    >
      <p className="subtle" style={{ marginTop: 0 }}>
        The agent drafted these from the job description and the candidate&rsquo;s resume
        {row.generated_by === "deterministic_fallback" ? " (standard question set)" : ""}. Edit
        or remove anything that is unfair, irrelevant, or asks about personal characteristics.
        Approving releases a single-use link for the candidate.
      </p>
      <ol style={{ paddingLeft: 18 }}>
        {row.questions.map((q) => {
          const removed = dropped.has(q.id);
          return (
            <li key={q.id} style={{ marginBottom: 12, opacity: removed ? 0.5 : 1 }}>
              <label htmlFor={`q-${q.id}`} className="subtle">
                {prettify(q.competency)} · from {prettify(q.source)}
                {q.evidence_ref ? ` · ${q.evidence_ref}` : ""}
              </label>
              <textarea
                id={`q-${q.id}`}
                rows={2}
                style={{ width: "100%" }}
                disabled={removed}
                value={texts[q.id] ?? ""}
                onChange={(e) => setTexts({ ...texts, [q.id]: e.target.value })}
              />
              <Button
                small
                variant="ghost"
                onClick={() => {
                  const next = new Set(dropped);
                  if (removed) next.delete(q.id);
                  else next.add(q.id);
                  setDropped(next);
                }}
              >
                {removed ? "Restore question" : "Remove question"}
              </Button>
            </li>
          );
        })}
      </ol>
      <div className="field">
        <label htmlFor="ai-approve-reason">Note for the audit trail (optional)</label>
        <input
          id="ai-approve-reason"
          value={reason}
          onChange={(e) => setReason(e.target.value)}
          maxLength={500}
        />
      </div>
    </Modal>
  );
}

/* Offer another attempt. The finished attempt keeps its result; the candidate gets a new
   one-time link with the same approved questions. A reason is required for the audit trail. */
function RetryModal({
  row,
  name,
  onClose,
  onIssued,
}: {
  row: AiInterview;
  name: string;
  onClose: () => void;
  onIssued: (r: ApproveResponse) => void;
}): ReactNode {
  const [reason, setReason] = useState(endedEarly(row) ? (RETRY_REASONS[0] ?? "") : "");
  const retry = useMutation({
    mutationFn: () => retryAiInterview(row.id, reason.trim()),
    onSuccess: onIssued,
  });
  const ended = row.end_reason ? (END_REASON_LABEL[row.end_reason] ?? prettify(row.end_reason)) : "Unknown";

  return (
    <Modal
      title={`Retry AI interview — ${name}`}
      onClose={onClose}
      footer={
        <>
          <Button onClick={onClose}>Cancel</Button>
          <Button
            variant="primary"
            disabled={reason.trim().length < 3 || retry.isPending}
            onClick={() => retry.mutate()}
          >
            {retry.isPending ? "Creating…" : "Create new attempt & link"}
          </Button>
        </>
      }
    >
      {retry.error && (
        <ErrorNote>{retry.error instanceof ApiError ? retry.error.message : "Could not create a new attempt."}</ErrorNote>
      )}
      <p className="mt-0">
        Last attempt ended: <strong>{ended}</strong>
        {row.completed_at ? ` (${new Date(row.completed_at).toLocaleString()})` : ""}.
      </p>
      <ul className="next-list" style={{ margin: "0 0 12px" }}>
        <li>The candidate gets a new one-time link with the same {row.questions.length} approved questions.</li>
        <li>This attempt and its result stay on record. Nothing is deleted.</li>
        <li>Each candidate gets a limited number of attempts.</li>
      </ul>
      <fieldset className="field" style={{ border: 0, padding: 0, margin: 0 }}>
        <legend>Why another attempt? (saved in the audit trail) *</legend>
        <div className="chips" style={{ margin: "6px 0 8px" }}>
          {RETRY_REASONS.map((r) => (
            <button key={r} type="button" className="chip-toggle" aria-pressed={reason === r} onClick={() => setReason(r)}>
              {r}
            </button>
          ))}
        </div>
        <label htmlFor="ai-retry-reason" className="sr-only">
          Reason
        </label>
        <input
          id="ai-retry-reason"
          value={reason}
          maxLength={500}
          placeholder="Or type your own reason"
          onChange={(e) => setReason(e.target.value)}
        />
      </fieldset>
    </Modal>
  );
}

function ResultDrawer({
  row,
  name,
  canTranscript,
  onClose,
}: {
  row: AiInterview;
  name: string;
  canTranscript: boolean;
  onClose: () => void;
}): ReactNode {
  const summary = parseAiSummary(row.summary);
  const [showTranscript, setShowTranscript] = useState(false);
  const transcript = useQuery({
    queryKey: ["ai-transcript", row.id],
    queryFn: () => getAiInterviewTranscript(row.id),
    enabled: showTranscript,
  });

  return (
    <Drawer title={`AI interview — ${name}`} subtitle={row.role_title} onClose={onClose}>
      <p className="subtle" role="note">
        {summary?.advisory_notice ??
          "Advisory summary generated from the transcript. It is not a hiring decision, score or ranking. A person must read the transcript and decide."}
      </p>

      {endedEarly(row) && (
        <p className="flag">
          This interview ended early:{" "}
          <strong>{END_REASON_LABEL[row.end_reason ?? ""] ?? prettify(row.end_reason ?? "")}</strong>. Some questions
          may not have been covered. Close this and use <strong>Retry interview</strong> to offer another attempt.
        </p>
      )}
      {!summary && <ErrorNote>The summary could not be displayed.</ErrorNote>}
      {summary?.overview && (
        <>
          <h3 style={{ fontSize: "0.95rem" }}>Overview</h3>
          <p>{summary.overview}</p>
        </>
      )}
      {summary?.integrity_flags && summary.integrity_flags.length > 0 && (
        <>
          <h3 style={{ fontSize: "0.95rem" }}>Flags for the reviewer</h3>
          <ul>
            {summary.integrity_flags.map((f) => (
              <li key={f}>
                <Badge tone="warn">{prettify(f)}</Badge>
              </li>
            ))}
          </ul>
        </>
      )}
      {summary?.assessments && summary.assessments.length > 0 && (
        <>
          <h3 style={{ fontSize: "0.95rem" }}>Question by question</h3>
          {summary.assessments.map((a, i) => (
            <div key={i} className="card" style={{ marginBottom: 10 }}>
              <strong>{a.question_text}</strong>
              <div style={{ margin: "4px 0" }}>
                <Badge tone={a.coverage === "answered" ? "ok" : "warn"}>{prettify(a.coverage)}</Badge>{" "}
                {a.needs_human_review && <Badge tone="warn">Needs human review</Badge>}
              </div>
              <p style={{ margin: "4px 0" }}>{a.answer_summary}</p>
              {a.review_reason && <p className="subtle">{a.review_reason}</p>}
              {a.evidence_quotes && a.evidence_quotes.length > 0 && (
                <ul className="subtle">
                  {a.evidence_quotes.map((q, j) => (
                    <li key={j}>&ldquo;{q}&rdquo;</li>
                  ))}
                </ul>
              )}
            </div>
          ))}
        </>
      )}
      {summary?.topics_to_probe_next && summary.topics_to_probe_next.length > 0 && (
        <>
          <h3 style={{ fontSize: "0.95rem" }}>Worth probing in the next interview</h3>
          <ul>
            {summary.topics_to_probe_next.map((t) => (
              <li key={t}>{t}</li>
            ))}
          </ul>
        </>
      )}

      <RecordingsSection sessionId={row.id} canView={canTranscript} />

      <h3 style={{ fontSize: "0.95rem" }}>Transcript</h3>
      {!canTranscript && (
        <p className="subtle">Reading the raw transcript needs the Recruiter Admin role.</p>
      )}
      {canTranscript && !showTranscript && (
        <>
          <p className="subtle">Opening the transcript is recorded in the audit trail.</p>
          <Button small onClick={() => setShowTranscript(true)}>
            Show transcript
          </Button>
        </>
      )}
      {showTranscript && transcript.isLoading && <Loading />}
      {showTranscript && transcript.error && <ErrorNote>Could not load the transcript.</ErrorNote>}
      {transcript.data?.turns.map((t, i) => (
        <p key={i} style={{ margin: "6px 0" }}>
          <strong>{t.speaker === "agent" ? "Interviewer: " : "Candidate: "}</strong>
          {t.text}
          {(t.flags ?? []).length > 0 && (
            <>
              {" "}
              <Badge tone="warn">{(t.flags ?? []).map(prettify).join(", ")}</Badge>
            </>
          )}
        </p>
      ))}
    </Drawer>
  );
}

/* Video evidence the candidate agreed to. Evidence only: nothing analyses it and it plays no
   part in any summary or decision. Watching needs the Recruiter Admin role and is audited. */
function RecordingsSection({ sessionId, canView }: { sessionId: string; canView: boolean }): ReactNode {
  const recordings = useQuery({
    queryKey: ["ai-recordings", sessionId],
    queryFn: () => listAiRecordings(sessionId),
    enabled: canView,
  });
  const [playing, setPlaying] = useState<{ id: string; url: string; isBlob: boolean } | null>(null);
  const [loadingId, setLoadingId] = useState<string | null>(null);
  const [problem, setProblem] = useState<string | null>(null);

  // Release a local blob URL when the player closes or changes.
  useEffect(
    () => () => {
      if (playing?.isBlob) URL.revokeObjectURL(playing.url);
    },
    [playing],
  );

  if (!canView) {
    return (
      <>
        <h3 style={{ fontSize: "0.95rem" }}>Video recording</h3>
        <p className="subtle">Watching interview recordings needs the Recruiter Admin role.</p>
      </>
    );
  }
  const rows = recordings.data ?? [];
  if (!recordings.isLoading && rows.length === 0) return null;

  const watch = async (id: string): Promise<void> => {
    setProblem(null);
    setLoadingId(id);
    try {
      const { url, isBlob } = await aiRecordingVideoUrl(id);
      setPlaying({ id, url, isBlob });
    } catch (e) {
      setProblem(e instanceof Error ? e.message : "Could not load the recording.");
    } finally {
      setLoadingId(null);
    }
  };

  return (
    <>
      <h3 style={{ fontSize: "0.95rem" }}>Video recording</h3>
      <p className="subtle">
        Kept as evidence only, with the candidate&rsquo;s consent. It is not analysed and is not
        part of any assessment. Opening it is recorded in the audit trail.
      </p>
      {recordings.isLoading && <Loading />}
      {problem && <ErrorNote>{problem}</ErrorNote>}
      {rows.map((r) => (
        <div key={r.id} className="card" style={{ marginBottom: 10 }}>
          <div className="btn-row" style={{ alignItems: "center" }}>
            <span>
              Start {r.attempt_start} · {prettify(r.status)} ·{" "}
              {(r.bytes_total / (1024 * 1024)).toFixed(1)} MB
            </span>
            {r.status !== "deleted" && (
              <Button small disabled={loadingId === r.id} onClick={() => void watch(r.id)}>
                {loadingId === r.id ? "Loading…" : "Watch recording"}
              </Button>
            )}
          </div>
          <p className="subtle" style={{ margin: "4px 0 0" }}>
            {r.status === "deleted"
              ? "Deleted under the retention policy."
              : `Deleted automatically on ${new Date(r.delete_after).toLocaleDateString()}.`}
          </p>
          {playing?.id === r.id && (
            <video
              src={playing.url}
              controls
              playsInline
              aria-label={`Interview recording, start ${r.attempt_start}`}
              style={{ width: "100%", marginTop: 8, background: "#000" }}
            />
          )}
        </div>
      ))}
    </>
  );
}
