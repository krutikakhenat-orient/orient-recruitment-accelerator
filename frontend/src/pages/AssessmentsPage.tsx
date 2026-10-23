import { useMutation, useQuery, useQueryClient } from "@tanstack/react-query";
import { useEffect, useMemo, useRef, useState, type ReactNode } from "react";

import { ApiError } from "../api/client";
import {
  checkInInvitation,
  checkOutInvitation,
  downloadResume,
  getApplication,
  getAssessmentForApplication,
  getPanelDashboard,
  listExtractedFields,
  submitAssessment,
  type PanelInterview,
} from "../api/resources";
import { useAuth } from "../app/auth-context";
import { useToast } from "../components/toast";
import { Badge, Button, Card, Drawer, Empty, ErrorNote, Field, Loading, prettify } from "../components/ui";
import {
  HIDDEN_ANSWER_KEYS,
  isSalaryKey,
  prettyFieldKey,
  renderAnswerValue,
} from "../lib/applicationFields";

/* Interview Panel view. On interview day the panel CHECKS a candidate IN (which opens their
   assessment), records a structured assessment, then CHECKS them OUT when finished. They
   never see screening scores or other candidates' records. The candidate detail opens on the
   SAME page as a slide-over with three tabs: Assessment, Resume, Application Form. */

const RECOMMENDATIONS = [
  { value: "proceed", label: "Proceed" },
  { value: "hold", label: "Hold" },
  { value: "do_not_proceed", label: "Do not proceed" },
];

// The interviewer scorecard skills, each rated 1–5 (from the Interviewer Assessment Form).
const RATING_SKILLS: { key: string; label: string }[] = [
  { key: "communication", label: "Communication Skills" },
  { key: "confidence_poise", label: "Confidence & Poise" },
  { key: "technical", label: "Technical Knowledge" },
  { key: "problem_solving", label: "Problem Solving Ability" },
  { key: "role_understanding", label: "Understanding of Role/Industry" },
  { key: "decision_making", label: "Decision Making" },
  { key: "attitude", label: "Attitude & Enthusiasm" },
  { key: "willingness_to_learn", label: "Willingness to Learn" },
];

export function AssessmentsPage(): ReactNode {
  const dash = useQuery({ queryKey: ["panel-dashboard"], queryFn: getPanelDashboard });
  // The candidate whose detail view (3 tabs) is open.
  const [openItem, setOpenItem] = useState<PanelInterview | null>(null);

  const interviews = dash.data?.interviews ?? [];
  // Keep the open item's data in sync with refreshed dashboard rows (e.g. after check-in).
  const liveOpenItem = useMemo(
    () => (openItem ? interviews.find((i) => i.application_id === openItem.application_id) ?? openItem : null),
    [openItem, interviews],
  );

  const toCheckIn = interviews.filter((i) => i.stage === "to_check_in");
  const inProgress = interviews.filter((i) => i.stage === "to_assess" || i.stage === "to_check_out");
  const completed = interviews.filter((i) => i.stage === "completed");

  return (
    <>
      <div className="page-head">
        <h1>My Assigned Interviews</h1>
        <p>
          On interview day, <strong>check the candidate in</strong> when they arrive — this opens
          their assessment. Record your assessment, then <strong>check them out</strong> when the
          interview is finished. You do not see screening scores; your verdict is one input the
          hiring team weighs.
        </p>
      </div>

      {/* Panel KPI cards. */}
      <div className="kpi-row" style={{ display: "flex", gap: 12, flexWrap: "wrap", marginBottom: 16 }}>
        <KpiCard label="To check in" value={dash.data?.to_check_in ?? 0} tone="warn" />
        <KpiCard label="To assess" value={dash.data?.to_assess ?? 0} tone="info" />
        <KpiCard label="To check out" value={dash.data?.to_check_out ?? 0} tone="info" />
        <KpiCard label="Completed" value={dash.data?.completed ?? 0} tone="ok" />
      </div>

      {dash.isLoading && <Loading />}
      {dash.error && <ErrorNote>Could not load your interview list.</ErrorNote>}

      <Card title="Scheduled — waiting to check in">
        {toCheckIn.length === 0 ? (
          <Empty>No candidates are waiting to be checked in.</Empty>
        ) : (
          <div className="table-wrap">
            <table className="data">
              <thead>
                <tr>
                  <th>Candidate</th>
                  <th>Status</th>
                  <th />
                </tr>
              </thead>
              <tbody>
                {toCheckIn.map((i) => (
                  <CheckInRow key={i.application_id} item={i} onOpen={() => setOpenItem(i)} />
                ))}
              </tbody>
            </table>
          </div>
        )}
      </Card>

      <Card title="In progress — checked in">
        {inProgress.length === 0 ? (
          <Empty>
            No interviews are in progress. A candidate appears here once you check them in.
          </Empty>
        ) : (
          <div className="table-wrap">
            <table className="data">
              <thead>
                <tr>
                  <th>Candidate</th>
                  <th>Status</th>
                  <th />
                </tr>
              </thead>
              <tbody>
                {inProgress.map((i) => (
                  <tr key={i.application_id}>
                    <td><strong>{i.candidate_name}</strong></td>
                    <td>
                      {i.stage === "to_assess" ? (
                        <Badge tone="info">Checked in — assessment pending</Badge>
                      ) : (
                        <Badge tone="ok">Assessed — ready to check out</Badge>
                      )}
                    </td>
                    <td style={{ textAlign: "right" }}>
                      <Button variant="primary" small onClick={() => setOpenItem(i)}>
                        Open
                      </Button>
                    </td>
                  </tr>
                ))}
              </tbody>
            </table>
          </div>
        )}
      </Card>

      {completed.length > 0 && (
        <Card title="Completed — checked out">
          <div className="table-wrap">
            <table className="data">
              <thead>
                <tr><th>Candidate</th><th>Status</th><th /></tr>
              </thead>
              <tbody>
                {completed.map((i) => (
                  <tr key={i.application_id}>
                    <td><strong>{i.candidate_name}</strong></td>
                    <td><Badge tone="ok">Interview completed</Badge></td>
                    <td style={{ textAlign: "right" }}>
                      <Button variant="default" small onClick={() => setOpenItem(i)}>
                        Review
                      </Button>
                    </td>
                  </tr>
                ))}
              </tbody>
            </table>
          </div>
        </Card>
      )}

      {liveOpenItem && (
        <CandidateDetail item={liveOpenItem} onClose={() => setOpenItem(null)} />
      )}
    </>
  );
}

function KpiCard({ label, value, tone }: { label: string; value: number; tone: "ok" | "warn" | "info" | "neutral" }): ReactNode {
  return (
    <div className="card" style={{ padding: "12px 16px", minWidth: 150, flex: "1 1 150px" }}>
      <div style={{ fontSize: "1.8rem", fontWeight: 700 }}>{value}</div>
      <div className="subtle" style={{ fontSize: "0.85rem" }}>
        <Badge tone={tone}>{label}</Badge>
      </div>
    </div>
  );
}

/* A scheduled candidate: the only action is Check In. Checking in does NOT mark attendance
   on its own — it records that the interview started and opens the assessment (the detail
   view with the three tabs). */
function CheckInRow({ item, onOpen }: { item: PanelInterview; onOpen: () => void }): ReactNode {
  const toast = useToast();
  const qc = useQueryClient();
  const [error, setError] = useState<string | null>(null);

  const checkIn = useMutation({
    mutationFn: () => {
      if (!item.invitation_id) throw new Error("No interview invitation found for this candidate.");
      return checkInInvitation(item.invitation_id);
    },
    onSuccess: async () => {
      await qc.invalidateQueries({ queryKey: ["panel-dashboard"] });
      toast.push("Checked in — assessment opened", { tone: "ok" });
      onOpen();
    },
    onError: (e) => setError(e instanceof ApiError ? e.message : "Could not check the candidate in."),
  });

  return (
    <tr>
      <td><strong>{item.candidate_name}</strong></td>
      <td><Badge tone="warn">Scheduled</Badge></td>
      <td style={{ textAlign: "right" }}>
        {error && <ErrorNote>{error}</ErrorNote>}
        <Button
          variant="accent"
          small
          disabled={checkIn.isPending}
          onClick={() => { setError(null); checkIn.mutate(); }}
        >
          {checkIn.isPending ? "Checking in…" : "Check In"}
        </Button>
      </td>
    </tr>
  );
}

type DetailTab = "assessment" | "resume" | "application";

/* The candidate detail slide-over with three tabs — all for the SAME candidate. */
function CandidateDetail({ item, onClose }: { item: PanelInterview; onClose: () => void }): ReactNode {
  const [tab, setTab] = useState<DetailTab>("assessment");
  // Guard against closing with unsaved assessment edits.
  const [dirty, setDirty] = useState(false);

  const attemptClose = (): void => {
    if (dirty && !window.confirm("You have unsaved assessment changes. Discard them and close?")) {
      return;
    }
    onClose();
  };

  const alreadyAssessed = item.has_assessment === true || item.stage === "to_check_out" || item.stage === "completed";

  return (
    <Drawer
      title={item.candidate_name}
      subtitle={<Badge tone="info">{stageLabel(item.stage)}</Badge>}
      onClose={attemptClose}
    >
      <div className="btn-row" style={{ marginBottom: 12 }}>
        <Button variant={tab === "assessment" ? "primary" : "default"} small onClick={() => setTab("assessment")}>
          📝 Assessment
        </Button>
        <Button variant={tab === "resume" ? "primary" : "default"} small onClick={() => setTab("resume")}>
          📄 Resume
        </Button>
        <Button variant={tab === "application" ? "primary" : "default"} small onClick={() => setTab("application")}>
          🗂 Application Form
        </Button>
      </div>

      {tab === "assessment" && (
        <AssessmentTab item={item} alreadyAssessed={alreadyAssessed} onDirtyChange={setDirty} />
      )}
      {tab === "resume" && <ResumeTab applicationId={item.application_id} />}
      {tab === "application" && <ApplicationFormTab applicationId={item.application_id} />}
    </Drawer>
  );
}

function stageLabel(stage: string): string {
  switch (stage) {
    case "to_check_in":
      return "Scheduled";
    case "to_assess":
      return "Checked in";
    case "to_check_out":
      return "Assessed";
    case "completed":
      return "Checked out";
    default:
      return prettify(stage);
  }
}

/* Tab A — Assessment. Rehydrates any previously-saved assessment so values survive tab
   switches/refreshes, validates required fields, warns on unsaved changes, submits via the
   backend, and shows saved/submitted status. After submission, offers Check Out. */
function AssessmentTab({
  item,
  alreadyAssessed,
  onDirtyChange,
}: {
  item: PanelInterview;
  alreadyAssessed: boolean;
  onDirtyChange: (dirty: boolean) => void;
}): ReactNode {
  const toast = useToast();
  const qc = useQueryClient();
  const [error, setError] = useState<string | null>(null);

  // Load the saved assessment (if any) to rehydrate the form.
  const saved = useQuery({
    queryKey: ["assessment", item.application_id],
    queryFn: () => getAssessmentForApplication(item.application_id),
  });

  const [recommendation, setRecommendation] = useState("");
  const [scores, setScores] = useState<Record<string, number>>(
    Object.fromEntries(RATING_SKILLS.map((s) => [s.key, 3])),
  );
  const [notes, setNotes] = useState("");
  const [conflict, setConflict] = useState(false);
  const [conflictDetail, setConflictDetail] = useState("");
  const [showErrors, setShowErrors] = useState(false);
  const seeded = useRef(false);

  // Seed the form once from the saved assessment (if present). After seeding, the form is
  // read-only (assessment already submitted; reassessment is not part of the workflow).
  useEffect(() => {
    if (seeded.current) return;
    if (saved.data) {
      const sc = saved.data.criteria_scores ?? {};
      setScores(
        Object.fromEntries(
          RATING_SKILLS.map((s) => [s.key, Number(sc[s.key] ?? 3) || 3]),
        ),
      );
      setRecommendation(saved.data.recommendation ?? "");
      setNotes(saved.data.interview_notes ?? "");
      setConflict(saved.data.conflict_declared ?? false);
      setConflictDetail(saved.data.conflict_detail ?? "");
      seeded.current = true;
    } else if (saved.isFetched && !saved.data) {
      seeded.current = true;
    }
  }, [saved.data, saved.isFetched]);

  const submitted = Boolean(saved.data) || alreadyAssessed;
  const readOnly = submitted;

  const setScore = (key: string, value: number): void => {
    setScores((prev) => ({ ...prev, [key]: value }));
    if (!readOnly) { onDirtyChange(true); }
  };

  const valid = recommendation !== "" && (!conflict || conflictDetail.trim() !== "");

  const submit = useMutation({
    mutationFn: () =>
      submitAssessment({
        application_id: item.application_id,
        recommendation,
        criteria_scores: scores,
        interview_notes: notes.trim() || null,
        conflict_declared: conflict,
        conflict_detail: conflict ? conflictDetail.trim() : null,
      }),
    onSuccess: async () => {
      onDirtyChange(false);
      await qc.invalidateQueries({ queryKey: ["assessment", item.application_id] });
      await qc.invalidateQueries({ queryKey: ["panel-dashboard"] });
      toast.push("Assessment submitted", { tone: "ok" });
    },
    onError: (e) => setError(e instanceof ApiError ? e.message : "Could not submit the assessment."),
  });

  const checkOut = useMutation({
    mutationFn: () => {
      if (!item.invitation_id) throw new Error("No interview invitation found for this candidate.");
      return checkOutInvitation(item.invitation_id);
    },
    onSuccess: async () => {
      await qc.invalidateQueries({ queryKey: ["panel-dashboard"] });
      toast.push("Checked out — interview completed", { tone: "ok" });
    },
    onError: (e) => setError(e instanceof ApiError ? e.message : "Could not check the candidate out."),
  });

  if (saved.isLoading) return <Loading label="Loading assessment…" />;

  const canCheckOut = submitted && item.stage !== "completed";

  return (
    <div>
      {error && <ErrorNote>{error}</ErrorNote>}
      <div style={{ marginBottom: 8 }}>
        {submitted ? (
          <Badge tone="ok">Assessment submitted</Badge>
        ) : (
          <Badge tone="warn">Draft — not yet submitted</Badge>
        )}
      </div>

      <p className="subtle" style={{ marginTop: 0 }}>
        Rate each skill on a scale of 1 (low) to 5 (high).
      </p>
      <div className="grid grid--2">
        {RATING_SKILLS.map((s) => (
          <Field key={s.key} label={`${s.label} (1–5)`} htmlFor={`${s.key}-${item.application_id}`}>
            <input
              id={`${s.key}-${item.application_id}`}
              type="number"
              min={1}
              max={5}
              value={scores[s.key]}
              disabled={readOnly}
              onChange={(e) => setScore(s.key, Number(e.target.value))}
            />
          </Field>
        ))}
      </div>

      <Field
        label="Recommendation *"
        htmlFor={`rec-${item.application_id}`}
        error={showErrors && recommendation === "" ? "Choose a recommendation." : undefined}
      >
        <select
          id={`rec-${item.application_id}`}
          value={recommendation}
          disabled={readOnly}
          onChange={(e) => { setRecommendation(e.target.value); if (!readOnly) onDirtyChange(true); }}
        >
          <option value="">Choose…</option>
          {RECOMMENDATIONS.map((r) => (
            <option key={r.value} value={r.value}>{r.label}</option>
          ))}
        </select>
      </Field>

      <Field label="Remarks / any other feedback (optional)" htmlFor={`notes-${item.application_id}`}>
        <textarea
          id={`notes-${item.application_id}`}
          rows={3}
          value={notes}
          disabled={readOnly}
          onChange={(e) => { setNotes(e.target.value); if (!readOnly) onDirtyChange(true); }}
          placeholder="What stood out, strengths, concerns"
        />
      </Field>

      <div className="checkbox-row">
        <input
          id={`conf-${item.application_id}`}
          type="checkbox"
          checked={conflict}
          disabled={readOnly}
          onChange={(e) => { setConflict(e.target.checked); if (!readOnly) onDirtyChange(true); }}
        />
        <label htmlFor={`conf-${item.application_id}`}>I have a conflict of interest with this candidate</label>
      </div>
      {conflict && (
        <Field
          label="Conflict detail (required)"
          htmlFor={`cd-${item.application_id}`}
          error={showErrors && conflict && conflictDetail.trim() === "" ? "A conflict detail is required." : undefined}
        >
          <input
            id={`cd-${item.application_id}`}
            value={conflictDetail}
            disabled={readOnly}
            onChange={(e) => { setConflictDetail(e.target.value); if (!readOnly) onDirtyChange(true); }}
            placeholder="Briefly describe the conflict"
          />
        </Field>
      )}

      {!submitted && (
        <div className="btn-row" style={{ marginTop: 8, alignItems: "center" }}>
          <Button
            variant="primary"
            small
            disabled={submit.isPending}
            onClick={() => {
              setError(null);
              setShowErrors(true);
              if (!valid) return;
              submit.mutate();
            }}
          >
            {submit.isPending ? "Submitting…" : "Submit assessment"}
          </Button>
          {showErrors && !valid && (
            <span className="subtle">Fill the required fields to submit.</span>
          )}
        </div>
      )}

      {canCheckOut && (
        <div className="btn-row" style={{ marginTop: 16, alignItems: "center" }}>
          <Button
            variant="accent"
            small
            disabled={checkOut.isPending}
            onClick={() => { setError(null); checkOut.mutate(); }}
          >
            {checkOut.isPending ? "Checking out…" : "Check Out — finish interview"}
          </Button>
          <span className="subtle">
            Checking out completes the interview and makes it visible to the recruiter.
          </span>
        </div>
      )}
      {item.stage === "completed" && (
        <p className="subtle" style={{ marginTop: 16 }}>
          This interview is complete (checked out).
        </p>
      )}
    </div>
  );
}

/* Tab B — Resume. Fetches the candidate's resume through the authenticated, authorised
   download endpoint and previews it (PDF inline via an object URL; others as a download).
   Shows a clear message when no resume is on file. The resume belongs to this application
   only (the server scopes the download to the application's campaign). */
function ResumeTab({ applicationId }: { applicationId: string }): ReactNode {
  const { token } = useAuth();
  const [url, setUrl] = useState<string | null>(null);
  const [contentType, setContentType] = useState<string>("");
  const [text, setText] = useState<string | null>(null);
  const [state, setState] = useState<"loading" | "ready" | "missing" | "error">("loading");
  const [message, setMessage] = useState<string>("");

  useEffect(() => {
    let revoked = false;
    let objectUrl: string | null = null;
    setState("loading");
    setText(null);
    // downloadResume returns null on 404 (no resume on file) so we show a clear message.
    downloadResume(applicationId, token() ?? "")
      .then(async (res) => {
        if (revoked) return;
        if (!res) {
          setState("missing");
          return;
        }
        objectUrl = URL.createObjectURL(res.blob);
        setUrl(objectUrl);
        setContentType(res.contentType);
        // A plain-text resume (the extracted-text fallback) is previewed inline.
        if (res.contentType.includes("text/plain")) {
          setText(await res.blob.text());
        }
        setState("ready");
      })
      .catch((e: unknown) => {
        if (revoked) return;
        setMessage(e instanceof Error ? e.message : "Could not load the resume.");
        setState("error");
      });
    return () => {
      revoked = true;
      if (objectUrl) URL.revokeObjectURL(objectUrl);
    };
  }, [applicationId, token]);

  if (state === "loading") return <Loading label="Loading resume…" />;
  if (state === "missing") {
    return (
      <Empty>
        No resume is available for this candidate. It may not have been uploaded, or the file is
        not yet available.
      </Empty>
    );
  }
  if (state === "error") return <ErrorNote>{message}</ErrorNote>;

  const isPdf = contentType.includes("pdf");
  const isText = contentType.includes("text/plain");
  return (
    <div className="scorecard-section">
      <div className="btn-row" style={{ marginBottom: 8 }}>
        <a className="btn btn--default btn--sm" href={url ?? "#"} download={`resume-${applicationId}`}>
          Download resume
        </a>
        {url && (
          <a className="btn btn--ghost btn--sm" href={url} target="_blank" rel="noreferrer">
            Open in new tab ↗
          </a>
        )}
      </div>
      {isPdf && url ? (
        <iframe
          title="Candidate resume"
          src={url}
          style={{ width: "100%", height: 480, border: "1px solid var(--border)", borderRadius: 8 }}
        />
      ) : isText && text !== null ? (
        <pre
          style={{
            whiteSpace: "pre-wrap",
            wordBreak: "break-word",
            maxHeight: 480,
            overflow: "auto",
            padding: 12,
            border: "1px solid var(--border)",
            borderRadius: 8,
            background: "var(--surface, #fff)",
            fontFamily: "inherit",
            fontSize: 14,
            lineHeight: 1.6,
          }}
        >
          {text}
        </pre>
      ) : (
        <p className="subtle">
          Preview is available for PDF resumes. Use <strong>Download resume</strong> to view this
          file ({contentType || "unknown type"}).
        </p>
      )}
    </div>
  );
}

/* Tab C — Application Form. Shows the candidate's submitted answers (preserved original
   data) plus the values extracted from their resume, clearly distinguishing verified from
   unverified/conflicting extracted information. The submitted answers are never overwritten
   by extracted values here. */
function ApplicationFormTab({ applicationId }: { applicationId: string }): ReactNode {
  const app = useQuery({ queryKey: ["application", applicationId], queryFn: () => getApplication(applicationId) });
  const extracted = useQuery({
    queryKey: ["extracted-fields", applicationId],
    queryFn: () => listExtractedFields(applicationId),
  });

  if (app.isLoading) return <Loading label="Loading application…" />;
  if (app.error || !app.data) return <ErrorNote>Could not load the application form.</ErrorNote>;

  const answers = app.data.answers ?? {};
  const entries = Object.entries(answers).filter(([k]) => !HIDDEN_ANSWER_KEYS.has(k));

  // Extracted fields excluding the raw resume text and skill:* flags (those belong to the
  // scorecard, not the application-form view).
  const extractedRows = (extracted.data ?? []).filter(
    (f) => f.field_name !== "resume_text" && !f.field_name.startsWith("skill:"),
  );

  return (
    <div>
      <div className="scorecard-section">
        <h3>Submitted application form</h3>
        <p className="subtle" style={{ marginTop: 0 }}>
          The details the candidate submitted. This is the original submission and is never
          overwritten by extracted values.
        </p>
        {entries.length === 0 ? (
          <Empty>No form answers were recorded for this application.</Empty>
        ) : (
          <div className="table-wrap">
            <table className="data">
              <thead>
                <tr><th>Field</th><th>Response</th></tr>
              </thead>
              <tbody>
                {entries.map(([k, v]) => (
                  <tr key={k}>
                    <td style={{ whiteSpace: "nowrap", fontWeight: 600 }}>
                      {prettyFieldKey(k)}
                      {isSalaryKey(k) && <span className="subtle"> (₹)</span>}
                    </td>
                    <td>{renderAnswerValue(k, v)}</td>
                  </tr>
                ))}
              </tbody>
            </table>
          </div>
        )}
      </div>

      <div className="scorecard-section">
        <h3>Information extracted from the resume</h3>
        <p className="subtle" style={{ marginTop: 0 }}>
          Extracted values are suggestions from the uploaded document. Each is marked{" "}
          <strong>verified</strong> or <strong>unverified / needs review</strong> — unverified
          information is never treated as confirmed.
        </p>
        {extracted.isLoading && <Loading label="Loading extracted fields…" />}
        {extracted.error && <ErrorNote>Could not load extracted information.</ErrorNote>}
        {extracted.data && extractedRows.length === 0 && (
          <Empty>No extracted fields are available for this application.</Empty>
        )}
        {extractedRows.length > 0 && (
          <div className="table-wrap">
            <table className="data">
              <thead>
                <tr><th>Field</th><th>Extracted value</th><th>Status</th></tr>
              </thead>
              <tbody>
                {extractedRows.map((f) => {
                  const verified = f.status === "verified" || f.status === "corrected";
                  return (
                    <tr key={f.id}>
                      <td>{prettify(f.field_name)}</td>
                      <td>{f.verified_value ?? f.extracted_value ?? <span className="subtle">Not provided</span>}</td>
                      <td>
                        <Badge tone={verified ? "ok" : "warn"}>
                          {verified ? "✓ Verified" : `⚑ ${prettify(f.status)}`}
                        </Badge>
                      </td>
                    </tr>
                  );
                })}
              </tbody>
            </table>
          </div>
        )}
      </div>
    </div>
  );
}
