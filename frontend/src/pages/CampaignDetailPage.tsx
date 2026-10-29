import { useMutation, useQuery, useQueryClient } from "@tanstack/react-query";
import { useEffect, useState, type ReactNode } from "react";
import { Link, useNavigate, useParams } from "react-router-dom";

import { ApiError } from "../api/client";
import {
  approveForm,
  approveJd,
  assignToCampaign,
  bulkIntakeWalkInResumes,
  createSlot,
  createStage,
  createFormDraft,
  createInterviewAssignment,
  devOpenCampaignNow,
  downloadCampaignExport,
  downloadResume,
  getCampaign,
  getClosureReadiness,
  listApplications,
  listInterviewAssignments,
  listInvitations,
  listJdVersions,
  listScreeningRuns,
  listSlots,
  listStages,
  listUsers,
  removeInterviewAssignment,
  recordWalkInInterview,
  rejectJd,
  rescoreCampaign,
  runScreening,
  transitionCampaign,
  updateJdVersion,
  uploadJd,
  type Application,
  type JDVersion,
  type RankedApplication,
  type ScreeningRun,
} from "../api/resources";
import { useAuth } from "../app/auth-context";
import { CandidateScorecardDrawer } from "../components/CandidateScorecardDrawer";
import { QrCode, qrDataUri } from "../components/QrCode";
import {
  HIDDEN_ANSWER_KEYS,
  prettyFieldKey,
  renderAnswerValue,
  SALARY_DISPLAY_KEYS,
} from "../lib/applicationFields";
import { useToast } from "../components/toast";
import {
  Badge,
  Button,
  Card,
  Empty,
  ErrorNote,
  Field,
  Loading,
  Modal,
  prettify,
  toneFor,
} from "../components/ui";

// NOTE: the standalone "form" tab was removed. The application form BUILDER now lives in
// the Job Description tab (campaign setup), and submitted application data is viewed via the
// Applications tab's "View form" action. The form feature/API/records are unchanged.
type Tab = "overview" | "jd" | "applications" | "interviews";

// Which permission each authoring tab's primary action needs, and a human label for the
// role that typically holds it. Used to show relevant guidance and gate actions.
// NOTE: there is deliberately no "rules" tab — scoring criteria and the default 50%
// threshold are generated and approved automatically when the JD is approved, so HR never
// configures a rule set by hand.
const TAB_META: Record<Tab, { permission: string | null; role: string; blurb: string }> = {
  overview: { permission: null, role: "All staff", blurb: "Status, lifecycle and the candidate apply link." },
  jd: { permission: "jd.upload", role: "Recruiter", blurb: "Upload the job description and build the candidate application form — scoring criteria are generated from the JD automatically." },
  applications: { permission: "screening.execute", role: "Recruiter", blurb: "View applications and run deterministic screening." },
  interviews: { permission: "interview.approve", role: "Recruiter Admin", blurb: "Select candidates for interview, manage stages and slots. Attendance is recorded by the interview panel." },
};

/* Trigger a browser "save file" for an already-fetched Blob, then release the object URL.
   Shared by the campaign Excel export and the per-candidate resume download so both use one
   safe pattern (an authenticated fetch -> Blob -> temporary anchor), never a direct link to
   storage. */
function triggerBrowserDownload(blob: Blob, filename: string): void {
  const url = URL.createObjectURL(blob);
  const anchor = document.createElement("a");
  anchor.href = url;
  anchor.download = filename;
  document.body.appendChild(anchor);
  anchor.click();
  anchor.remove();
  URL.revokeObjectURL(url);
}

const PREREQS: { key: string; label: string }[] = [
  { key: "approved_jd_version_id", label: "Approved JD" },
  { key: "approved_rule_set_version_id", label: "Approved rules" },
  { key: "approved_form_version_id", label: "Approved form" },
  { key: "active_threshold_version_id", label: "Active threshold" },
  { key: "privacy_notice_version", label: "Privacy notice" },
];

// Guided next transitions by current state. These MUST match the backend transition table
// in backend/app/modules/campaigns/states.py — invalid moves are rejected with 409.
// The permission each transition destination requires (mirrors states.py).
const TRANSITION_PERMISSION: Record<string, string> = {
  jd_uploaded: "jd.upload",
  jd_review: "jd.review",
  criteria_configuration: "jd.approve",
  criteria_review: "rule.create",
  approval_pending: "rule.approve",
  approved: "campaign.approve",
  published: "campaign.publish",
  applications_open: "campaign.publish",
  applications_closed: "campaign.pause",
  paused: "campaign.pause",
  screening: "screening.execute",
  human_review: "application.review",
  interview_planning: "interview.approve",
  interviewing: "interview.schedule",
  selection_review: "assessment.submit",
  completed: "hiring_decision.approve",
  closed: "campaign.edit",
  archived: "campaign.edit",
  cancelled: "campaign.edit",
};

const NEXT: Record<string, { to: string; label: string }[]> = {
  draft: [
    { to: "jd_uploaded", label: "Mark JD uploaded" },
    { to: "cancelled", label: "Cancel" },
  ],
  jd_uploaded: [
    { to: "jd_review", label: "Send JD to review" },
    { to: "cancelled", label: "Cancel" },
  ],
  jd_review: [
    { to: "criteria_configuration", label: "Approve JD → configure criteria" },
    { to: "cancelled", label: "Cancel" },
  ],
  criteria_configuration: [
    { to: "criteria_review", label: "Send criteria to review" },
    { to: "cancelled", label: "Cancel" },
  ],
  criteria_review: [
    { to: "approval_pending", label: "Approve criteria" },
    { to: "cancelled", label: "Cancel" },
  ],
  approval_pending: [
    { to: "approved", label: "Approve campaign" },
    { to: "cancelled", label: "Cancel" },
  ],
  approved: [
    { to: "published", label: "Publish" },
    { to: "cancelled", label: "Cancel" },
  ],
  published: [
    { to: "applications_open", label: "Open applications" },
    { to: "cancelled", label: "Cancel" },
  ],
  applications_open: [
    { to: "applications_closed", label: "Close applications" },
    { to: "paused", label: "Pause" },
    { to: "cancelled", label: "Cancel" },
  ],
  paused: [
    { to: "applications_open", label: "Resume" },
    { to: "cancelled", label: "Cancel" },
  ],
  applications_closed: [
    { to: "screening", label: "Begin screening" },
    { to: "cancelled", label: "Cancel" },
  ],
  screening: [
    { to: "human_review", label: "Start human review" },
    { to: "cancelled", label: "Cancel" },
  ],
  human_review: [
    { to: "interview_planning", label: "Plan interviews" },
    { to: "cancelled", label: "Cancel" },
  ],
  interview_planning: [
    { to: "interviewing", label: "Start interviewing" },
    { to: "cancelled", label: "Cancel" },
  ],
  interviewing: [
    { to: "selection_review", label: "Selection review" },
    { to: "cancelled", label: "Cancel" },
  ],
  selection_review: [
    { to: "completed", label: "Complete campaign" },
    { to: "cancelled", label: "Cancel" },
  ],
  completed: [{ to: "closed", label: "Close" }],
  // A closed campaign can be reopened by an authorised user (needs campaign.publish);
  // reopening lands back on applications_open. It can also be archived (terminal).
  closed: [
    { to: "applications_open", label: "Reopen" },
    { to: "archived", label: "Archive" },
  ],
};

// Destination states whose transition abandons/ends the campaign. When the user clicks one
// of these from a state where work may still be in flight, we first warn with the pending
// candidate/interview counts (advisory — the backend still owns the decision).
const CLOSURE_DESTINATIONS = new Set(["completed", "cancelled"]);

/* Explains why an action is unavailable: either you lack the role permission, or you are
   not assigned to this campaign. Returns null when the user can act. */
function AccessNote({
  campaignId,
  permission,
  role,
}: {
  campaignId: string;
  permission: string | null;
  role: string;
}): ReactNode {
  const { hasPermission, canAccessCampaign } = useAuth();
  const lacksPermission = permission !== null && !hasPermission(permission);
  const notAssigned = !canAccessCampaign(campaignId);
  if (!lacksPermission && !notAssigned) return null;
  return (
    <div className="hint-list" style={{ marginBottom: 12 }}>
      {lacksPermission && (
        <div>
          🔒 This action needs the <strong>{role}</strong> role. You're signed in with a
          different role, so it's read-only for you here.
        </div>
      )}
      {!lacksPermission && notAssigned && (
        <div>
          🔒 You're not assigned to this campaign yet. Use <strong>Assign me</strong> on the
          Overview tab, then try again.
        </div>
      )}
    </div>
  );
}

export function CampaignDetailPage(): ReactNode {
  const { id = "" } = useParams();
  const navigate = useNavigate();
  const { actor, hasPermission, refreshActor } = useAuth();
  const [tab, setTab] = useState<Tab>("overview");
  // Lets an approver drop out of Focus Mode into the full tabbed console if they want.
  const [forceFull, setForceFull] = useState(false);
  const campaign = useQuery({ queryKey: ["campaign", id], queryFn: () => getCampaign(id) });

  // Refresh the actor once on open so campaign assignments granted after login (e.g. by a
  // colleague or the dev opener) are reflected — otherwise approve buttons stay disabled.
  useEffect(() => {
    void refreshActor();
  }, [refreshActor]);

  // Interview Panel members have no campaign-management surface — send them straight to
  // their simplified "My Interviews" workspace.
  const isPanelOnly =
    actor != null &&
    hasPermission("assessment.submit") &&
    !hasPermission("candidate.view") &&
    !hasPermission("jd.review");
  useEffect(() => {
    if (isPanelOnly) navigate("/assessments", { replace: true });
  }, [isPanelOnly, navigate]);

  if (campaign.isLoading) return <Loading label="Loading campaign…" />;
  if (campaign.error || !campaign.data) return <ErrorNote>Could not load this campaign.</ErrorNote>;

  const c = campaign.data;

  // Focus Mode: a campaign awaiting JD review, opened by someone who can approve the JD,
  // gets a distraction-free review view (full JD + Approve / Request changes) with the
  // authoring tabs hidden until they explicitly switch to the full console.
  const focusJdReview = c.state === "jd_review" && hasPermission("jd.approve") && !forceFull;

  if (focusJdReview) {
    return (
      <>
        <div className="page-head">
          <Link to="/campaigns" className="subtle">
            ← Campaigns
          </Link>
          <h1 style={{ marginTop: 6 }}>{c.name}</h1>
          <p>
            {c.position_title} · {c.number_of_openings} opening(s) ·{" "}
            <Badge tone={toneFor(c.state)}>{prettify(c.state)}</Badge> ·{" "}
            <Badge tone="info">Focused JD review</Badge>
          </p>
        </div>
        <FocusedJdReview
          campaignId={id}
          onDone={() => void campaign.refetch()}
          onExitFocus={() => setForceFull(true)}
        />
      </>
    );
  }

  return (
    <>
      <div className="page-head">
        <Link to="/campaigns" className="subtle">
          ← Campaigns
        </Link>
        <h1 style={{ marginTop: 6 }}>{c.name}</h1>
        <p>
          {c.position_title} · {c.number_of_openings} opening(s) ·{" "}
          <Badge tone={toneFor(c.state)}>{prettify(c.state)}</Badge>
        </p>
      </div>

      <div className="btn-row" style={{ marginBottom: 6 }}>
        {(["overview", "jd", "applications", "interviews"] as Tab[]).map((t) => {
          const meta = TAB_META[t];
          const readOnly = meta.permission !== null && !hasPermission(meta.permission);
          const label =
            t === "jd" ? "Job Description & Form" : t === "applications" ? "Applications & Screening" : prettify(t);
          return (
            <Button key={t} variant={tab === t ? "primary" : "default"} small onClick={() => setTab(t)}>
              {label}
              {readOnly ? " 🔒" : ""}
            </Button>
          );
        })}
      </div>
      <p className="subtle" style={{ marginTop: 0, marginBottom: 16 }}>
        {TAB_META[tab].blurb} {TAB_META[tab].permission && <>· Primary action: <strong>{TAB_META[tab].role}</strong></>}
      </p>

      {tab === "overview" && <OverviewTab campaignId={id} />}
      {tab === "jd" && (
        <>
          <JdTab campaignId={id} />
          {/* The application-form builder now lives here (the standalone Form tab was
              removed). The feature, its API and records are unchanged. */}
          <FormTab campaignId={id} />
        </>
      )}
      {tab === "applications" && <ApplicationsTab campaignId={id} />}
      {tab === "interviews" && <InterviewsTab campaignId={id} />}
    </>
  );
}

/* Focus Mode JD review: full JD text + version metadata, with prominent Approve and
   Request-changes (reject) actions. Hides authoring tabs so an approver can focus on the
   decision. Approve/reject both require a reason (recorded in the audit trail). */
function FocusedJdReview({
  campaignId,
  onDone,
  onExitFocus,
}: {
  campaignId: string;
  onDone: () => void;
  onExitFocus: () => void;
}): ReactNode {
  const toast = useToast();
  const qc = useQueryClient();
  const { hasPermission, canAccessCampaign } = useAuth();
  const [error, setError] = useState<string | null>(null);
  const [rejectOpen, setRejectOpen] = useState(false);
  const [rejectReason, setRejectReason] = useState("");

  const assigned = canAccessCampaign(campaignId);
  const canApprove = hasPermission("jd.approve") && assigned;

  const versions = useQuery({
    queryKey: ["jd-versions", campaignId],
    queryFn: () => listJdVersions(campaignId),
  });
  const draft = versions.data?.find((v) => v.status === "draft") ?? null;

  const invalidate = (): void => {
    void qc.invalidateQueries({ queryKey: ["jd-versions", campaignId] });
    void qc.invalidateQueries({ queryKey: ["campaign", campaignId] });
    onDone();
  };

  const approve = useMutation({
    mutationFn: () => approveJd(draft!.id, "Approved via focused JD review"),
    onSuccess: () => {
      toast.push("Job description approved", { tone: "ok" });
      invalidate();
    },
    onError: (e) => setError(e instanceof ApiError ? e.message : "Could not approve the JD."),
  });

  const reject = useMutation({
    mutationFn: () => rejectJd(draft!.id, rejectReason.trim()),
    onSuccess: () => {
      setRejectOpen(false);
      setRejectReason("");
      toast.push("Change requested — JD returned to the recruiter", { tone: "info" });
      invalidate();
    },
    onError: (e) => setError(e instanceof ApiError ? e.message : "Could not reject the JD."),
  });

  if (versions.isLoading) return <Loading label="Loading job description…" />;
  if (!draft) {
    return (
      <Card title="No draft to review">
        <Empty>There is no draft job description awaiting review for this campaign.</Empty>
        <Button variant="default" small onClick={onExitFocus}>
          Open full campaign console
        </Button>
      </Card>
    );
  }

  return (
    <>
      {error && <ErrorNote>{error}</ErrorNote>}
      <div className="grid grid--2" style={{ alignItems: "start", gap: 16 }}>
        <Card title={`Job description — version ${draft.version_number}`}>
          <JdReadout draft={draft} />
        </Card>
        <div>
          <Card title="Version details">
            <dl className="kv">
              <dt>Version</dt>
              <dd>#{draft.version_number}</dd>
              <dt>Status</dt>
              <dd>
                <Badge tone={toneFor(draft.status)}>{prettify(draft.status)}</Badge>
              </dd>
              <dt>Position</dt>
              <dd>{draft.position_title ?? "—"}</dd>
              <dt>Department</dt>
              <dd>{draft.department ?? "—"}</dd>
            </dl>
          </Card>
          <Card title="Decision">
            {canApprove ? (
              <>
                <p className="subtle" style={{ marginTop: 0 }}>
                  Approving advances the campaign to criteria configuration. Requesting changes
                  returns the draft to the recruiter with your reason. Both are audited.
                </p>
                <div className="btn-row">
                  <Button
                    variant="accent"
                    disabled={approve.isPending || !draft.position_title}
                    title={draft.position_title ? undefined : "The draft needs a position title first"}
                    onClick={() => {
                      setError(null);
                      approve.mutate();
                    }}
                  >
                    {approve.isPending ? "Approving…" : "✓ Approve Job Description"}
                  </Button>
                  <Button variant="danger" disabled={reject.isPending} onClick={() => setRejectOpen(true)}>
                    Request changes / Reject
                  </Button>
                </div>
              </>
            ) : (
              <p className="subtle" style={{ marginTop: 0 }}>
                🔒 Approving a JD needs the <strong>jd.approve</strong> permission and campaign
                assignment.
              </p>
            )}
            <div style={{ marginTop: 12 }}>
              <Button variant="ghost" small onClick={onExitFocus}>
                Open full campaign console →
              </Button>
            </div>
          </Card>
        </div>
      </div>

      {rejectOpen && (
        <Modal
          title="Request changes to this JD"
          onClose={() => setRejectOpen(false)}
          footer={
            <>
              <Button variant="ghost" small onClick={() => setRejectOpen(false)}>
                Cancel
              </Button>
              <Button
                variant="danger"
                small
                disabled={!rejectReason.trim() || reject.isPending}
                onClick={() => {
                  setError(null);
                  reject.mutate();
                }}
              >
                {reject.isPending ? "Submitting…" : "Request changes"}
              </Button>
            </>
          }
        >
          <Field label="Reason (sent to the recruiter and recorded in the audit trail)" htmlFor="jd-reject-reason">
            <textarea
              id="jd-reject-reason"
              rows={4}
              value={rejectReason}
              onChange={(e) => setRejectReason(e.target.value)}
              placeholder="e.g. Please clarify the required years of experience and remove the salary line."
            />
          </Field>
        </Modal>
      )}
    </>
  );
}

/* Renders a JD draft's human-readable content: title/department, responsibilities, and
   mandatory/desirable skills. */
function JdReadout({ draft }: { draft: JDVersion }): ReactNode {
  return (
    <div>
      <h3 style={{ marginTop: 0 }}>{draft.position_title ?? "Untitled role"}</h3>
      {draft.department && <p className="subtle" style={{ marginTop: 0 }}>{draft.department}</p>}

      {draft.responsibilities.length > 0 && (
        <>
          <h4>Responsibilities</h4>
          <ul>
            {draft.responsibilities.map((r, i) => (
              <li key={i}>{r}</li>
            ))}
          </ul>
        </>
      )}

      {draft.mandatory_skills.length > 0 && (
        <>
          <h4>Must-have skills</h4>
          <div className="btn-row">
            {draft.mandatory_skills.map((s, i) => (
              <Badge key={i} tone="info">
                {s}
              </Badge>
            ))}
          </div>
        </>
      )}

      {draft.desirable_skills.length > 0 && (
        <>
          <h4 style={{ marginTop: 12 }}>Desirable skills</h4>
          <div className="btn-row">
            {draft.desirable_skills.map((s, i) => (
              <Badge key={i} tone="neutral">
                {s}
              </Badge>
            ))}
          </div>
        </>
      )}
    </div>
  );
}

/* Interviewer assignment management. Visible to holders of interview.assign (System Admin,
   who manages org-wide, and Recruiter Admin for campaigns they're assigned to). Shows ONLY
   assignment metadata — never candidate profiles, resumes, scores, or scorecards — so it is
   safe for System Admin, who has no candidate-content permission. Assign an interviewer to
   the whole campaign or a specific stage; remove with confirmation. The server enforces the
   permission, campaign scope, and interviewer eligibility; this UI never bypasses that. */
function InterviewerAssignmentsCard({
  campaignId,
  stages,
}: {
  campaignId: string;
  stages: { id: string; name: string }[];
}): ReactNode {
  const toast = useToast();
  const qc = useQueryClient();
  const { token, hasPermission } = useAuth();
  const [error, setError] = useState<string | null>(null);
  const [interviewerId, setInterviewerId] = useState("");
  const [stageId, setStageId] = useState("");

  // interview.assign is the only gate; object-level scope is enforced by the server.
  const canManage = hasPermission("interview.assign");

  const assignments = useQuery({
    queryKey: ["interview-assignments", campaignId],
    queryFn: () => listInterviewAssignments(campaignId),
    enabled: canManage,
  });
  // The interviewer picker lists staff accounts; the server rejects anyone who cannot
  // submit assessments, with a clear message.
  const users = useQuery({
    queryKey: ["staff-users"],
    queryFn: () => listUsers(),
    enabled: canManage,
  });

  const create = useMutation({
    mutationFn: () =>
      createInterviewAssignment(campaignId, {
        interviewer_id: interviewerId,
        stage_id: stageId || null,
      }),
    onSuccess: () => {
      setInterviewerId("");
      setStageId("");
      setError(null);
      void qc.invalidateQueries({ queryKey: ["interview-assignments", campaignId] });
      toast.push("Interviewer assigned.", { tone: "ok" });
    },
    onError: (e) =>
      setError(e instanceof ApiError ? e.message : "Could not assign the interviewer."),
  });

  const [removing, setRemoving] = useState<string | null>(null);
  async function handleRemove(assignmentId: string): Promise<void> {
    const authToken = token();
    if (!authToken) return;
    if (!window.confirm("Remove this interviewer assignment? Their submitted assessments are kept.")) {
      return;
    }
    setRemoving(assignmentId);
    setError(null);
    try {
      await removeInterviewAssignment(assignmentId, authToken);
      void qc.invalidateQueries({ queryKey: ["interview-assignments", campaignId] });
      toast.push("Assignment removed.", { tone: "ok" });
    } catch (e) {
      setError(e instanceof Error ? e.message : "Could not remove the assignment.");
    } finally {
      setRemoving(null);
    }
  }

  if (!canManage) return null;

  const rows = assignments.data ?? [];
  const userById = (id: string) => users.data?.find((u) => u.id === id);
  const nameFor = (id: string): string => userById(id)?.display_name ?? id.slice(0, 8);
  const emailFor = (id: string): string => userById(id)?.email ?? "—";
  // Only Interview Panel members are eligible interviewers — these are the users a System
  // Admin added to the "interview panel" role. The backend also rejects anyone without the
  // assessment permission, so this is a convenience filter, not the security boundary.
  const panelUsers = (users.data ?? []).filter((u) =>
    (u.role_names ?? []).includes("interview_panel"),
  );

  return (
    <Card title="Interviewer assignments">
      <p className="subtle" style={{ marginTop: 0 }}>
        Assign interview-panel members to this job. An interviewer sees only the candidates
        for jobs (and, if set, the stage) they are assigned to. This panel shows assignment
        details only — no candidate information.
      </p>
      {error && <ErrorNote>{error}</ErrorNote>}

      <div className="grid grid--2" style={{ alignItems: "end", marginBottom: 12 }}>
        <Field label="Interviewer" htmlFor="assign-interviewer">
          <select
            id="assign-interviewer"
            value={interviewerId}
            onChange={(e) => setInterviewerId(e.target.value)}
          >
            <option value="">Choose a panel member…</option>
            {panelUsers.map((u) => (
              <option key={u.id} value={u.id}>
                {u.display_name} ({u.email})
              </option>
            ))}
          </select>
          {/* Distinguish the three "empty dropdown" causes so a data problem is never
              silently shown as "no panel members exist" (which previously masked a stale
              backend that omitted role_names from GET /users). */}
          {users.isLoading && <span className="subtle">Loading interviewers…</span>}
          {users.isError && (
            <span className="subtle">
              Could not load staff users. Reload the page; if it persists the API may be
              unavailable.
            </span>
          )}
          {users.data && panelUsers.length === 0 && (
            <span className="subtle">
              No active Interview Panel members found. A System Admin creates them in
              Administration (assign the “interview panel” role).
            </span>
          )}
        </Field>
        <Field label="Stage (optional — whole job if blank)" htmlFor="assign-stage">
          <select id="assign-stage" value={stageId} onChange={(e) => setStageId(e.target.value)}>
            <option value="">Whole campaign</option>
            {stages.map((s) => (
              <option key={s.id} value={s.id}>{s.name}</option>
            ))}
          </select>
        </Field>
      </div>
      <Button
        variant="primary"
        small
        disabled={!interviewerId || create.isPending}
        onClick={() => create.mutate()}
      >
        {create.isPending ? "Assigning…" : "Assign interviewer"}
      </Button>

      <div style={{ marginTop: 16 }}>
        {assignments.isLoading && <Loading label="Loading assignments…" />}
        {assignments.error && <ErrorNote>Could not load assignments.</ErrorNote>}
        {assignments.data && rows.length === 0 && (
          <Empty>No interviewers are assigned to this job yet.</Empty>
        )}
        {rows.length > 0 && (
          <div className="table-wrap">
            <table className="data">
              <thead>
                <tr>
                  <th>Interviewer</th>
                  <th>Email</th>
                  <th>Stage</th>
                  <th>Status</th>
                  <th />
                </tr>
              </thead>
              <tbody>
                {rows.map((a) => (
                  <tr key={a.id}>
                    <td>{a.interviewer_name ?? nameFor(a.interviewer_id)}</td>
                    <td className="subtle">{emailFor(a.interviewer_id)}</td>
                    <td>
                      {a.stage_id
                        ? (stages.find((s) => s.id === a.stage_id)?.name ?? "Stage")
                        : "Whole campaign"}
                    </td>
                    <td>
                      <Badge tone={a.is_active ? "ok" : "neutral"}>
                        {a.is_active ? "Active" : "Inactive"}
                      </Badge>
                    </td>
                    <td style={{ textAlign: "right" }}>
                      <Button
                        variant="default"
                        small
                        disabled={removing === a.id}
                        onClick={() => void handleRemove(a.id)}
                      >
                        {removing === a.id ? "Removing…" : "Remove"}
                      </Button>
                    </td>
                  </tr>
                ))}
              </tbody>
            </table>
          </div>
        )}
      </div>
    </Card>
  );
}

function InterviewsTab({ campaignId }: { campaignId: string }): ReactNode {
  const toast = useToast();
  const qc = useQueryClient();
  const { hasPermission, canAccessCampaign } = useAuth();
  const [error, setError] = useState<string | null>(null);

  const assigned = canAccessCampaign(campaignId);
  const canSchedule = hasPermission("interview.schedule") && assigned;
  // Selecting a below-threshold candidate for interview needs BOTH approve + schedule
  // (the walk-in path issues the invitation and books a slot) plus campaign assignment.
  const canSelectForInterview =
    hasPermission("interview.approve") && hasPermission("interview.schedule") && assigned;

  // "Select for interview" override modal: picking a candidate who is under review (below
  // the automatic 50% bar) overrides the screening outcome, so the recruiter must record a
  // reason. The reason is sent to the server and written to the audit trail.
  const [selectFor, setSelectFor] = useState<Application | null>(null);
  const [selectReason, setSelectReason] = useState("");

  const apps = useQuery({ queryKey: ["applications", campaignId], queryFn: () => listApplications(campaignId) });
  const stages = useQuery({ queryKey: ["stages", campaignId], queryFn: () => listStages(campaignId) });
  const slots = useQuery({ queryKey: ["slots", campaignId], queryFn: () => listSlots(campaignId) });
  const invites = useQuery({ queryKey: ["invitations", campaignId], queryFn: () => listInvitations(campaignId) });

  // --- stage / slot creation ---
  const [stageName, setStageName] = useState("");
  const createStageM = useMutation({
    mutationFn: () => createStage(campaignId, stageName.trim(), (stages.data?.length ?? 0) + 1),
    onSuccess: () => {
      setStageName("");
      void qc.invalidateQueries({ queryKey: ["stages", campaignId] });
      toast.push("Stage created", { tone: "ok" });
    },
    onError: (e) => setError(e instanceof ApiError ? e.message : "Could not create stage."),
  });

  const [slotStageId, setSlotStageId] = useState("");
  const [slotDate, setSlotDate] = useState("");
  const [slotTime, setSlotTime] = useState("");
  const [slotLocation, setSlotLocation] = useState("");
  const [slotCapacity, setSlotCapacity] = useState(1);
  const createSlotM = useMutation({
    mutationFn: () =>
      createSlot({
        stage_id: slotStageId,
        slot_date: slotDate,
        start_time: slotTime,
        capacity: slotCapacity,
        ...(slotLocation.trim() ? { location: slotLocation.trim() } : {}),
      }),
    onSuccess: () => {
      void qc.invalidateQueries({ queryKey: ["slots", campaignId] });
      toast.push("Slot created", { tone: "ok" });
    },
    onError: (e) => setError(e instanceof ApiError ? e.message : "Could not create slot."),
  });

  // Candidates scoring >= 50% are progressed to the Interview Panel AUTOMATICALLY on submit
  // (backend auto_progress_to_interview). Candidates BELOW 50% stay here, under review, and
  // a Recruitment Admin can still manually "Select for interview" with a recorded reason —
  // this puts them on the SAME Interview Panel tab as the auto-progressed candidates.
  const selectForInterviewM = useMutation({
    mutationFn: (vars: { applicationId: string; reason?: string }) =>
      recordWalkInInterview(vars.applicationId, vars.reason),
    onSuccess: () => {
      setSelectFor(null);
      setSelectReason("");
      void qc.invalidateQueries({ queryKey: ["applications", campaignId] });
      void qc.invalidateQueries({ queryKey: ["invitations", campaignId] });
      toast.push("Candidate selected — now on the Interview Panel's list", { tone: "ok" });
    },
    onError: (e) =>
      setError(e instanceof ApiError ? e.message : "Could not select this candidate."),
  });

  const invitedAppIds = new Set((invites.data ?? []).map((i) => i.application_id));
  // Candidates eligible to be selected: screened or under manual review, not already invited.
  const eligible = (apps.data ?? []).filter(
    (a) => ["screened", "manual_review"].includes(a.state) && !invitedAppIds.has(a.id),
  );
  const nameOf = (a: Application): string =>
    typeof a.answers["full_name"] === "string" ? (a.answers["full_name"] as string) : a.id.slice(0, 8);
  const appById = new Map((apps.data ?? []).map((a) => [a.id, a]));

  return (
    <>
      <InterviewerAssignmentsCard campaignId={campaignId} stages={stages.data ?? []} />
      <AccessNote campaignId={campaignId} permission="interview.approve" role="Recruiter Admin / Hiring Manager" />
      {error && <ErrorNote>{error}</ErrorNote>}

      <Card title="Candidates for interview">
        <p className="subtle" style={{ marginTop: 0 }}>
          Candidates who score <strong>50% or above</strong> are added to the Interview Panel&rsquo;s
          list <strong>automatically</strong> — they appear directly on the Interview Panel tab.
          Candidates <strong>below 50%</strong> stay here under review; you can still{" "}
          <strong>Select for interview</strong> (a reason is required) to place them on the same
          Interview Panel tab. Nothing is sent to the candidate automatically; contact shortlisted
          candidates with the details on file.
        </p>
        {apps.isLoading && <Loading />}
        {!apps.isLoading && eligible.length === 0 && (
          <Empty>
            No candidates are awaiting a decision here. Candidates scoring 50%+ have already moved to
            the Interview Panel; there are no under-review candidates to select.
          </Empty>
        )}
        {eligible.length > 0 && (
          <div className="table-wrap">
            <table className="data">
              <thead>
                <tr><th>Candidate</th><th>State</th><th /></tr>
              </thead>
              <tbody>
                {eligible.map((a) => {
                  const underReview = a.state === "manual_review";
                  return (
                    <tr key={a.id}>
                      <td>{nameOf(a)}</td>
                      <td><Badge tone={toneFor(a.state)}>{prettify(a.state)}</Badge></td>
                      <td style={{ textAlign: "right" }}>
                        {canSelectForInterview ? (
                          <Button
                            variant="primary"
                            small
                            disabled={selectForInterviewM.isPending}
                            onClick={() => {
                              setError(null);
                              if (underReview) {
                                // Below the bar -> override requires a reason: open the modal.
                                setSelectReason("");
                                setSelectFor(a);
                              } else {
                                // Clean/screened -> no reason needed.
                                selectForInterviewM.mutate({ applicationId: a.id });
                              }
                            }}
                          >
                            Select for interview
                          </Button>
                        ) : (
                          <span className="subtle">🔒 Needs interview approve + schedule</span>
                        )}
                      </td>
                    </tr>
                  );
                })}
              </tbody>
            </table>
            <p className="subtle" style={{ marginTop: 8 }}>
              Candidates shown here are under the 50% bar or flagged for review. Selecting one for
              interview records your reason and places them on the Interview Panel tab, alongside the
              candidates who qualified automatically.
            </p>
          </div>
        )}
      </Card>

      {/* Override reason modal for selecting a below-threshold candidate. */}
      {selectFor && (
        <Modal
          title="Select candidate for interview"
          onClose={() => {
            setSelectFor(null);
            setSelectReason("");
          }}
        >
          <p className="subtle" style={{ marginTop: 0 }}>
            <strong>{nameOf(selectFor)}</strong> is under review (below the automatic 50%
            threshold). Selecting them for interview overrides the screening outcome, so a reason
            is required and will be recorded in the audit trail.
          </p>
          <Field label="Reason for selecting this candidate *" htmlFor="select-reason">
            <textarea
              id="select-reason"
              rows={3}
              value={selectReason}
              onChange={(e) => setSelectReason(e.target.value)}
              placeholder="e.g. Strong relevant project experience not captured by the automated skill match."
            />
          </Field>
          <div className="btn-row" style={{ marginTop: 12, justifyContent: "flex-end" }}>
            <Button
              variant="default"
              onClick={() => {
                setSelectFor(null);
                setSelectReason("");
              }}
            >
              Cancel
            </Button>
            <Button
              variant="primary"
              disabled={!selectReason.trim() || selectForInterviewM.isPending}
              onClick={() =>
                selectForInterviewM.mutate({
                  applicationId: selectFor.id,
                  reason: selectReason.trim(),
                })
              }
            >
              {selectForInterviewM.isPending ? "Selecting…" : "Confirm selection"}
            </Button>
          </div>
        </Modal>
      )}

      <Card title="Interview invitations">
        {invites.isLoading && <Loading />}
        {invites.data && invites.data.length === 0 && <Empty>No invitations yet.</Empty>}
        {invites.data && invites.data.length > 0 && (
          <div className="table-wrap">
            <table className="data">
              <thead>
                <tr><th>Candidate</th><th>Status</th><th>Slot</th><th>Attendance</th><th /></tr>
              </thead>
              <tbody>
                {invites.data.map((inv) => {
                  const app = appById.get(inv.application_id);
                  return (
                    <tr key={inv.id}>
                      <td>{app ? nameOf(app) : inv.application_id.slice(0, 8)}</td>
                      <td><Badge tone={toneFor(inv.status)}>{prettify(inv.status)}</Badge></td>
                      <td>
                        {/* Walk-in interviews are same-day; no manual slot assignment.
                            "Interview now (walk-in)" places the candidate with the panel
                            directly, so the Slot column is informational only. */}
                        {inv.slot_id ? (
                          <span className="subtle">walk-in</span>
                        ) : (
                          <span className="subtle">—</span>
                        )}
                      </td>
                      <td><Badge tone={toneFor(inv.attendance)}>{prettify(inv.attendance)}</Badge></td>
                      <td style={{ textAlign: "right" }}>
                        {/* Attendance is recorded by the Interview Panel (on their "My
                            Assigned Interviews" page), not here. A scheduled candidate is
                            now with the panel to confirm attendance and assess. */}
                        {inv.slot_id && inv.attendance === "pending" && (
                          <span className="subtle">With interview panel</span>
                        )}
                      </td>
                    </tr>
                  );
                })}
              </tbody>
            </table>
          </div>
        )}
      </Card>

      <Card title="Stages & slots">
        <p className="subtle" style={{ marginTop: 0 }}>
          Create interview stages (e.g. &ldquo;Technical Round&rdquo;) and capacity-limited time slots.
        </p>
        {!canSchedule && (
          <div className="hint-list" style={{ marginBottom: 12 }}>
            🔒 Scheduling (stages and slots) is done by the{" "}
            <strong>Recruiter / Recruiter Admin</strong>
            {hasPermission("interview.schedule")
              ? " — and you must be assigned to this campaign (use “Assign me” on the Overview tab)."
              : ". You're signed in with a different role, so this section is read-only for you. As Recruiter Admin you select candidates for interview above; the recruiter arranges the stages and slots."}
          </div>
        )}
        <div className="grid grid--2" style={{ alignItems: "end" }}>
          <Field label="New stage name" htmlFor="stage-name">
            <input id="stage-name" value={stageName} disabled={!canSchedule} onChange={(e) => setStageName(e.target.value)} placeholder="Technical Round" />
          </Field>
          <div>
            <Button variant="primary" small disabled={!canSchedule || !stageName.trim() || createStageM.isPending} onClick={() => { setError(null); createStageM.mutate(); }}>
              {createStageM.isPending ? "Creating…" : "Add stage"}
            </Button>
          </div>
        </div>
        <div className="btn-row" style={{ marginTop: 6 }}>
          {(stages.data ?? []).map((s) => (
            <Badge key={s.id} tone="info">{s.sequence}. {s.name}</Badge>
          ))}
        </div>

        <div className="grid grid--3" style={{ marginTop: 16, alignItems: "end" }}>
          <Field label="Stage" htmlFor="slot-stage">
            <select id="slot-stage" value={slotStageId} disabled={!canSchedule} onChange={(e) => setSlotStageId(e.target.value)}>
              <option value="">Select stage…</option>
              {(stages.data ?? []).map((s) => (<option key={s.id} value={s.id}>{s.name}</option>))}
            </select>
          </Field>
          <Field label="Date" htmlFor="slot-date">
            <input id="slot-date" type="date" value={slotDate} disabled={!canSchedule} onChange={(e) => setSlotDate(e.target.value)} />
          </Field>
          <Field label="Start time" htmlFor="slot-time">
            <input id="slot-time" type="time" value={slotTime} disabled={!canSchedule} onChange={(e) => setSlotTime(e.target.value)} />
          </Field>
          <Field label="Location (optional)" htmlFor="slot-loc">
            <input id="slot-loc" value={slotLocation} disabled={!canSchedule} onChange={(e) => setSlotLocation(e.target.value)} placeholder="Room 2 / video link" />
          </Field>
          <Field label="Capacity" htmlFor="slot-cap">
            <input id="slot-cap" type="number" min={1} value={slotCapacity} disabled={!canSchedule} onChange={(e) => setSlotCapacity(Number(e.target.value))} />
          </Field>
          <div>
            <Button variant="primary" small disabled={!canSchedule || !slotStageId || !slotDate || !slotTime || createSlotM.isPending} onClick={() => { setError(null); createSlotM.mutate(); }}>
              {createSlotM.isPending ? "Adding…" : "Add slot"}
            </Button>
          </div>
        </div>
        <div className="btn-row" style={{ marginTop: 6 }}>
          {(slots.data ?? []).map((s) => (
            <Badge key={s.id} tone={s.confirmed_count >= s.capacity ? "warn" : "neutral"}>
              {s.slot_date} {s.start_time} ({s.confirmed_count}/{s.capacity})
            </Badge>
          ))}
        </div>
      </Card>
    </>
  );
}

/* Map an application state to a human interview-status label + tone for Recruiter Admin.
   This lets the recruiter distinguish candidates who are scheduled, in progress (checked in
   but not yet checked out), and those who actually ATTENDED (checked out = interview
   completed). Returns null for states before the interview stage so the column stays empty.
   Legacy ATTENDED/NO_SHOW rows are also surfaced so historical records remain visible. */
function interviewStatus(state: string): { label: string; tone: "ok" | "warn" | "info" | "neutral" } | null {
  switch (state) {
    case "interview_recommended":
      return { label: "Interview recommended", tone: "info" };
    case "interview_scheduled":
      return { label: "Scheduled", tone: "info" };
    case "checked_in":
      return { label: "Checked in (in progress)", tone: "warn" };
    case "assessed":
      return { label: "Assessed — awaiting check-out", tone: "warn" };
    case "checked_out":
      return { label: "Interview attended (completed)", tone: "ok" };
    case "attended":
      return { label: "Attended (legacy)", tone: "ok" };
    case "no_show":
      return { label: "No-show (legacy)", tone: "neutral" };
    default:
      return null;
  }
}

function ApplicationsTab({ campaignId }: { campaignId: string }): ReactNode {
  const toast = useToast();
  const qc = useQueryClient();
  const { token, hasPermission, canAccessCampaign } = useAuth();
  const [error, setError] = useState<string | null>(null);
  // The application whose scorecard drawer is open, with its latest screening run.
  const [inspect, setInspect] = useState<{ app: Application; run: ScreeningRun | null } | null>(null);
  const apps = useQuery({
    queryKey: ["applications", campaignId],
    queryFn: () => listApplications(campaignId),
  });

  const assigned = canAccessCampaign(campaignId);
  const canScreen = hasPermission("screening.execute") && assigned;
  // Rescore regenerates the scoring criteria from the campaign's CURRENT approved JD and
  // re-screens every candidate. It needs rule.approve (the caller approves the regenerated
  // criteria) + campaign assignment. This is the ONLY action that picks up a newly-approved
  // JD's skills — the per-candidate "Screen" button re-runs against the EXISTING rules.
  const canRescore = hasPermission("rule.approve") && assigned;
  // Export downloads a read-only .xlsx of every candidate using the already-saved
  // scores/ranks (no rescoring). Mirrors the server check: candidate.view + assignment.
  const canExport = hasPermission("candidate.view") && assigned;
  const [exporting, setExporting] = useState(false);
  // The application whose submitted form-answers modal is open.
  const [formView, setFormView] = useState<Application | null>(null);

  async function handleExport(): Promise<void> {
    const authToken = token();
    if (!authToken) return;
    setError(null);
    setExporting(true);
    try {
      const result = await downloadCampaignExport(campaignId, authToken);
      if (result === null) {
        setError("This campaign could not be exported (not found or not accessible).");
        return;
      }
      triggerBrowserDownload(result.blob, `campaign-${campaignId}-export.xlsx`);
      toast.push("Campaign export downloaded.", { tone: "ok" });
    } catch (e) {
      setError(e instanceof Error ? e.message : "Could not export the campaign.");
    } finally {
      setExporting(false);
    }
  }

  const rescore = useMutation({
    mutationFn: () => rescoreCampaign(campaignId),
    onSuccess: (summary) => {
      void qc.invalidateQueries({ queryKey: ["applications", campaignId] });
      void qc.invalidateQueries({ queryKey: ["campaign", campaignId] });
      toast.push(
        `Rescored ${summary.rescored} candidate(s) against ${summary.criteria_count} criteria` +
          (summary.progressed ? ` · ${summary.progressed} progressed to interview` : ""),
        { tone: "ok" },
      );
    },
    onError: (e) =>
      setError(
        e instanceof ApiError
          ? e.message
          : "Could not rescore. Ensure the campaign has an approved JD with skills.",
      ),
  });

  return (
    <>
      <WalkInUploader campaignId={campaignId} canUpload={canScreen} />

      <Card
        title="Applications"
        actions={
          canRescore || canExport ? (
            <div style={{ display: "flex", gap: "0.5rem", flexWrap: "wrap" }}>
              {canExport && (
                <Link
                  className="btn btn--accent btn--sm"
                  to={`/campaigns/${campaignId}/report`}
                  title="Open the candidate report inside the app — read, search and scroll the same data as the Excel download, then download the .xlsx from there."
                >
                  👁 Preview Excel
                </Link>
              )}
              {canExport && (
                <Button
                  variant="default"
                  small
                  disabled={exporting}
                  title="Download an Excel workbook of every candidate in this campaign using the saved scores and ranks. Nothing is rescored or changed."
                  onClick={() => {
                    void handleExport();
                  }}
                >
                  {exporting ? "Exporting…" : "⤓ Export to Excel"}
                </Button>
              )}
              {canRescore && (
                <Button
                  variant="default"
                  small
                  disabled={rescore.isPending}
                  title="Regenerate scoring criteria from the current approved JD and re-screen every candidate. Existing runs are kept."
                  onClick={() => {
                    if (
                      window.confirm(
                        "Rescore this campaign?\n\nThis regenerates the scoring criteria from the " +
                          "CURRENT approved Job Description and re-screens every candidate. Existing " +
                          "screening runs are kept (nothing is deleted). Use this after approving a " +
                          "new JD so the new skills are picked up.",
                      )
                    ) {
                      setError(null);
                      rescore.mutate();
                    }
                  }}
                >
                  {rescore.isPending ? "Rescoring…" : "↻ Rescore from current JD"}
                </Button>
              )}
            </div>
          ) : undefined
        }
      >
        <AccessNote campaignId={campaignId} permission="candidate.view" role="Recruiter / HR" />
        {error && <ErrorNote>{error}</ErrorNote>}
        <p className="subtle" style={{ marginTop: 0 }}>
          Each submitted application can be screened against the approved rules. Screening is
          deterministic and never auto-rejects — low-confidence or borderline results are routed to
          the Review Queue for a person to decide. Open a candidate&rsquo;s{" "}
          <strong>Resume Score</strong> to inspect evidence and (with permission) contact details,
          or <strong>View form</strong> to see what the candidate submitted.
        </p>
        {apps.isLoading && <Loading />}
        {apps.error && <ErrorNote>Could not load applications (you may not be assigned to this campaign).</ErrorNote>}
        {apps.data && apps.data.length === 0 && (
          <Empty>No applications yet. Share the apply link from the Overview tab.</Empty>
        )}
        {apps.data && apps.data.length > 0 && (
          <div className="table-wrap">
            <table className="data">
              <thead>
                <tr>
                  <th>Rank</th>
                  <th>Applicant</th>
                  <th>Resume Score</th>
                  <th>Application form</th>
                  <th>Review status</th>
                  <th>Interview status</th>
                  <th />
                </tr>
              </thead>
              <tbody>
                {apps.data.map((a) => (
                  <ApplicationRow
                    key={a.id}
                    app={a}
                    canScreen={canScreen}
                    canDownloadResume={canExport}
                    onScreened={() => {
                      void qc.invalidateQueries({ queryKey: ["applications", campaignId] });
                      toast.push("Screening run completed", { tone: "ok" });
                    }}
                    onInspect={(run) => setInspect({ app: a, run })}
                    onViewForm={() => setFormView(a)}
                    onError={setError}
                  />
                ))}
              </tbody>
            </table>
            <p className="subtle" style={{ marginTop: 8 }}>
              Ranked by latest screening score within this campaign. Candidates awaiting
              screening (or whose screening could not score) appear last.
            </p>
          </div>
        )}
      </Card>

      {inspect && (
        <CandidateScorecardDrawer
          app={inspect.app}
          run={inspect.run}
          onClose={() => setInspect(null)}
        />
      )}

      {formView && (
        <ApplicationFormModal app={formView} onClose={() => setFormView(null)} />
      )}
    </>
  );
}

/* Shows everything the candidate entered on the application form, in submitted order.
   Read-only. Internal/technical keys are hidden; booleans render as Yes/No; repeating
   groups (education/work history) render as a small list; salary fields are formatted as
   currency. A dedicated compensation summary surfaces Current Salary and In-Hand Salary
   (and Expected) explicitly, showing "Not provided" when a value is genuinely missing.
   Nothing is computed or fabricated — it simply displays the stored answers. */
function ApplicationFormModal({ app, onClose }: { app: Application; onClose: () => void }): ReactNode {
  const answers = app.answers ?? {};
  const entries = Object.entries(answers).filter(([k]) => !HIDDEN_ANSWER_KEYS.has(k));
  const candidateName =
    typeof answers["full_name"] === "string" ? (answers["full_name"] as string) : "Candidate";

  return (
    <Modal title={`Application form — ${candidateName}`} onClose={onClose}>
      <p className="subtle" style={{ marginTop: 0 }}>
        The details this candidate submitted on the application form.
      </p>

      {/* Compensation summary: always surface the salary fields so Current / In-Hand salary
          are visible. A field the campaign's form did not collect shows "Not provided"
          rather than being hidden — missing is never shown as zero. */}
      <div className="scorecard-section" style={{ marginBottom: 12 }}>
        <h3 style={{ marginTop: 0 }}>Compensation</h3>
        <div className="table-wrap">
          <table className="data">
            <tbody>
              {SALARY_DISPLAY_KEYS.map((k) => (
                <tr key={k}>
                  <td style={{ whiteSpace: "nowrap", fontWeight: 600 }}>{prettyFieldKey(k)}</td>
                  <td>{renderAnswerValue(k, answers[k])}</td>
                </tr>
              ))}
            </tbody>
          </table>
        </div>
      </div>

      <h3>All submitted fields</h3>
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
                  <td style={{ whiteSpace: "nowrap", fontWeight: 600 }}>{prettyFieldKey(k)}</td>
                  <td>{renderAnswerValue(k, v)}</td>
                </tr>
              ))}
            </tbody>
          </table>
        </div>
      )}
    </Modal>
  );
}

/* Drag-and-drop bulk resume uploader for walk-in drives. Uploads multiple PDF/DOCX files
   through the safe document pipeline; requires a consent attestation and screening.execute
   + campaign assignment (enforced server-side). */
function WalkInUploader({ campaignId, canUpload }: { campaignId: string; canUpload: boolean }): ReactNode {
  const toast = useToast();
  const qc = useQueryClient();
  const { token } = useAuth();
  const [open, setOpen] = useState(false);
  const [files, setFiles] = useState<File[]>([]);
  const [over, setOver] = useState(false);
  const [consent, setConsent] = useState(false);
  const [error, setError] = useState<string | null>(null);
  const [busy, setBusy] = useState(false);
  const [results, setResults] = useState<
    { filename: string; accepted: boolean; detail: string; score: number | null }[] | null
  >(null);

  const addFiles = (list: FileList | null): void => {
    if (!list) return;
    setFiles((prev) => [...prev, ...Array.from(list)]);
  };

  const submit = async (): Promise<void> => {
    setBusy(true);
    setError(null);
    try {
      const resp = await bulkIntakeWalkInResumes(campaignId, consent, files, token() ?? "");
      setResults(
        resp.results.map((r) => ({
          filename: r.filename,
          accepted: r.accepted,
          detail: r.detail,
          score: r.score ?? null,
        })),
      );
      toast.push(`${resp.accepted}/${resp.total} applications created`, {
        tone: resp.rejected ? "info" : "ok",
      });
      setFiles([]);
      void qc.invalidateQueries({ queryKey: ["applications", campaignId] });
    } catch (e) {
      setError(e instanceof Error ? e.message : "Bulk intake failed.");
    } finally {
      setBusy(false);
    }
  };

  if (!canUpload) return null;

  return (
    <Card
      title="Walk-in drive — bulk resume intake"
      actions={
        <Button variant={open ? "default" : "primary"} small onClick={() => setOpen((o) => !o)}>
          {open ? "Hide" : "Bulk upload resumes"}
        </Button>
      }
    >
      <p className="subtle" style={{ marginTop: 0 }}>
        Collect many resumes at once at a walk-in drive. Each file is validated, scanned and
        quarantined. This does not create candidate records or run screening — a candidate&rsquo;s
        identity and consent are captured before their resume is processed further.
      </p>
      {open && (
        <>
          {error && <ErrorNote>{error}</ErrorNote>}
          <div
            className={`dropzone ${over ? "dropzone--over" : ""}`}
            onDragOver={(e) => {
              e.preventDefault();
              setOver(true);
            }}
            onDragLeave={() => setOver(false)}
            onDrop={(e) => {
              e.preventDefault();
              setOver(false);
              addFiles(e.dataTransfer.files);
            }}
          >
            <p style={{ margin: "0 0 8px" }}>Drag & drop PDF/DOCX resumes here, or</p>
            <label className="btn btn--default btn--sm" style={{ cursor: "pointer" }}>
              Choose files
              <input
                type="file"
                multiple
                accept=".pdf,.docx,.doc,.txt"
                style={{ display: "none" }}
                onChange={(e) => addFiles(e.target.files)}
              />
            </label>
          </div>

          {files.length > 0 && (
            <ul className="hint-list" style={{ marginTop: 12 }}>
              {files.map((f, i) => (
                <li key={`${f.name}-${i}`}>
                  {f.name}{" "}
                  <button
                    className="btn btn--ghost btn--sm"
                    onClick={() => setFiles((prev) => prev.filter((_, idx) => idx !== i))}
                    aria-label={`Remove ${f.name}`}
                  >
                    ✕
                  </button>
                </li>
              ))}
            </ul>
          )}

          <label style={{ display: "flex", gap: 8, alignItems: "center", margin: "12px 0" }}>
            <input type="checkbox" checked={consent} onChange={(e) => setConsent(e.target.checked)} />
            <span>
              I attest each walk-in candidate consented to their resume being processed for this
              campaign.
            </span>
          </label>

          <Button
            variant="accent"
            small
            disabled={busy || files.length === 0 || !consent}
            onClick={() => void submit()}
          >
            {busy ? "Uploading…" : `Create ${files.length || ""} application(s)`}
          </Button>

          {results && (
            <div className="table-wrap" style={{ marginTop: 14 }}>
              <table className="data">
                <thead>
                  <tr>
                    <th>File</th>
                    <th>Result</th>
                    <th>Score</th>
                    <th>Detail</th>
                  </tr>
                </thead>
                <tbody>
                  {results.map((r, i) => (
                    <tr key={`${r.filename}-${i}`}>
                      <td>{r.filename}</td>
                      <td>
                        <Badge tone={r.accepted ? "ok" : "danger"}>
                          {r.accepted ? "Created" : "Rejected"}
                        </Badge>
                      </td>
                      <td>
                        {r.score === null ? (
                          <span className="subtle">—</span>
                        ) : (
                          <strong>{Math.round(r.score)}</strong>
                        )}
                      </td>
                      <td className="subtle">{r.detail}</td>
                    </tr>
                  ))}
                </tbody>
              </table>
              <p className="subtle" style={{ marginTop: 8 }}>
                Each resume became an application and was screened. Open a candidate&rsquo;s
                <strong> Scorecard</strong> in the Applications table below to see the full
                breakdown. Walk-in candidate names are placeholders — correct them during review.
              </p>
            </div>
          )}
        </>
      )}
    </Card>
  );
}

function ApplicationRow({
  app,
  canScreen,
  canDownloadResume,
  onScreened,
  onInspect,
  onViewForm,
  onError,
}: {
  app: RankedApplication;
  canScreen: boolean;
  canDownloadResume: boolean;
  onScreened: () => void;
  onInspect: (run: ScreeningRun | null) => void;
  onViewForm: () => void;
  onError: (msg: string) => void;
}): ReactNode {
  const { token } = useAuth();
  const toast = useToast();
  // The list payload already carries the latest-run summary (rank/score/recommendation/
  // review flags) so the table ranks without a per-row fetch. The FULL run (with every
  // criterion) is loaded lazily only when the reviewer opens the scorecard.
  const [loadingCard, setLoadingCard] = useState(false);
  const [downloadingResume, setDownloadingResume] = useState(false);

  const screen = useMutation({
    mutationFn: () => runScreening(app.id),
    onSuccess: () => onScreened(),
    onError: (e) =>
      onError(e instanceof ApiError ? e.message : "Screening failed — is a rule set approved?"),
  });

  // Download this candidate's resume via the authenticated, authorised endpoint, keyed by
  // the APPLICATION id (not the candidate id) so the correct submission's resume is fetched.
  // The server enforces candidate.view + campaign assignment and only serves a CLEAN file;
  // we reuse the shared browser-download pattern and show a friendly message on 404/error.
  const handleDownloadResume = async (): Promise<void> => {
    const authToken = token();
    if (!authToken) return;
    setDownloadingResume(true);
    try {
      const result = await downloadResume(app.id, authToken);
      if (result === null) {
        onError("No resume is on file for this candidate, or it is not available to download.");
        return;
      }
      const suffix = result.contentType.includes("pdf")
        ? "pdf"
        : result.contentType.includes("word")
          ? "docx"
          : result.contentType.includes("text/plain")
            ? "txt"
            : "bin";
      triggerBrowserDownload(result.blob, `resume-${app.id}.${suffix}`);
      toast.push("Resume downloaded.", { tone: "ok" });
    } catch (e) {
      onError(e instanceof Error ? e.message : "Could not download the resume. Please try again.");
    } finally {
      setDownloadingResume(false);
    }
  };

  const openScorecard = async (): Promise<void> => {
    setLoadingCard(true);
    try {
      const runs = await listScreeningRuns(app.id).catch(() => []);
      onInspect(runs[0] ?? null);
    } finally {
      setLoadingCard(false);
    }
  };

  const name = typeof app.answers["full_name"] === "string" ? (app.answers["full_name"] as string) : "—";
  const hasRun = Boolean(app.latest_run_id);

  return (
    <tr>
      <td>{app.rank != null ? <strong>#{app.rank}</strong> : <span className="subtle">—</span>}</td>
      <td>{name}</td>
      <td>
        {app.scored && app.score != null ? (
          <strong>{Math.round(app.score)}/100</strong>
        ) : (
          <span className="subtle">{hasRun ? "Unable to score" : "Awaiting screening"}</span>
        )}
      </td>
      <td>
        <Button variant="default" small onClick={onViewForm}>
          View form
        </Button>
      </td>
      <td>
        {app.manual_review_required ? (
          <Badge tone="warn">Manual review</Badge>
        ) : hasRun ? (
          <Badge tone="ok">Cleared</Badge>
        ) : (
          <span className="subtle">—</span>
        )}
      </td>
      <td>
        {(() => {
          const status = interviewStatus(app.state);
          return status ? <Badge tone={status.tone}>{status.label}</Badge> : <span className="subtle">—</span>;
        })()}
      </td>
      <td style={{ textAlign: "right" }}>
        <div className="btn-row" style={{ justifyContent: "flex-end" }}>
          {canDownloadResume && (
            <Button
              variant="default"
              small
              disabled={downloadingResume}
              title="Download this candidate's uploaded resume. Served securely; requires the Recruiter/HR role and campaign assignment."
              onClick={() => void handleDownloadResume()}
            >
              {downloadingResume ? "Downloading…" : "⤓ Resume"}
            </Button>
          )}
          <Button variant="default" small disabled={loadingCard} onClick={() => void openScorecard()}>
            {loadingCard ? "Opening…" : "Resume Score"}
          </Button>
          <Button
            variant="accent"
            small
            disabled={!canScreen || screen.isPending}
            title={canScreen ? undefined : "Running screening needs the Recruiter role and campaign assignment"}
            onClick={() => screen.mutate()}
          >
            {screen.isPending ? "Screening…" : hasRun ? "Re-run" : "Run screening"}
          </Button>
        </div>
      </td>
    </tr>
  );
}

function OverviewTab({ campaignId }: { campaignId: string }): ReactNode {
  const toast = useToast();
  const qc = useQueryClient();
  const { hasPermission, canAccessCampaign, refreshActor } = useAuth();
  const campaign = useQuery({ queryKey: ["campaign", campaignId], queryFn: () => getCampaign(campaignId) });
  const [reason, setReason] = useState("");
  const [error, setError] = useState<string | null>(null);
  const [assignEmail, setAssignEmail] = useState("");

  const transition = useMutation({
    mutationFn: (destination: string) => transitionCampaign(campaignId, destination, reason || "state change"),
    onSuccess: () => {
      setReason("");
      void qc.invalidateQueries({ queryKey: ["campaign", campaignId] });
      void qc.invalidateQueries({ queryKey: ["campaigns"] });
      toast.push("Campaign advanced", { tone: "ok" });
    },
    onError: (e) => setError(e instanceof ApiError ? e.message : "Transition failed."),
  });

  // Drive a lifecycle transition. For closing/cancelling destinations, first fetch the
  // advisory pending-work counts and ask HR to confirm if candidates or interviews are
  // still in flight (Req 3). The warning never blocks: the backend remains authoritative
  // and the same transition runs either way. A readiness-fetch failure does not stop the
  // action — it falls through to the normal transition (which the server still guards).
  const requestTransition = async (destination: string): Promise<void> => {
    setError(null);
    if (CLOSURE_DESTINATIONS.has(destination)) {
      const verb = destination === "completed" ? "complete" : "cancel";
      try {
        const r = await getClosureReadiness(campaignId);
        if (r.has_pending) {
          const parts: string[] = [];
          if (r.pending_applications > 0)
            parts.push(
              `${r.pending_applications} candidate${r.pending_applications === 1 ? "" : "s"} still in progress`,
            );
          if (r.pending_interviews > 0)
            parts.push(
              `${r.pending_interviews} interview${r.pending_interviews === 1 ? "" : "s"} not yet concluded`,
            );
          const proceed = window.confirm(
            `This campaign still has ${parts.join(" and ")}. ` +
              `Records are preserved, but no further recruitment actions will be possible until it is reopened. ` +
              `${verb === "complete" ? "Complete" : "Cancel"} this campaign anyway?`,
          );
          if (!proceed) return;
        }
      } catch {
        // Advisory only — if the count can't be loaded, continue to the guarded transition.
      }
    }
    transition.mutate(destination);
  };

  const openNow = useMutation({
    mutationFn: () => devOpenCampaignNow(campaignId),
    onSuccess: async () => {
      await refreshActor(); // dev open-now also assigns the current user
      void qc.invalidateQueries({ queryKey: ["campaign", campaignId] });
      void qc.invalidateQueries({ queryKey: ["campaigns"] });
      toast.push("Campaign opened for applications", { tone: "ok" });
    },
    onError: (e) =>
      setError(
        e instanceof ApiError
          ? e.message
          : "Could not open the campaign (dev endpoint is only available locally).",
      ),
  });

  const assignSelf = useMutation({
    mutationFn: () => assignToCampaign(campaignId),
    onSuccess: async () => {
      await refreshActor();
      toast.push("You're now assigned to this campaign", { tone: "ok" });
    },
    onError: (e) => setError(e instanceof ApiError ? e.message : "Could not assign you."),
  });

  const assignOther = useMutation({
    mutationFn: () => assignToCampaign(campaignId, assignEmail.trim()),
    onSuccess: () => {
      setAssignEmail("");
      toast.push("User assigned to this campaign", { tone: "ok" });
    },
    onError: (e) => setError(e instanceof ApiError ? e.message : "Could not assign that user."),
  });

  if (!campaign.data) return <Loading />;
  const c = campaign.data;
  const nexts = NEXT[c.state] ?? [];
  const assigned = canAccessCampaign(campaignId);

  const applyPath = `/apply/${campaignId}`;
  const applyUrl = `${window.location.origin}${applyPath}`;
  const isOpen = c.state === "applications_open";
  const copyApplyLink = (): void => {
    void navigator.clipboard
      .writeText(applyUrl)
      .then(() => toast.push("Apply link copied", { tone: "ok" }))
      .catch(() => toast.push("Could not copy — select and copy manually", { tone: "danger" }));
  };

  return (
    <>
      <Card
        title="Candidate apply link"
        actions={<Badge tone={isOpen ? "ok" : "warn"}>{isOpen ? "Open" : "Not open yet"}</Badge>}
      >
        <p className="subtle" style={{ marginTop: 0 }}>
          Candidates apply here — no account needed. Share this public link (or the QR code) once
          the campaign is in the <strong>Applications open</strong> state. Submissions before then
          are rejected.
        </p>
        <div className="apply-link-layout">
          <div className="apply-link-layout__main">
            <div className="field">
              <label htmlFor="apply-url">Public application URL</label>
              <input id="apply-url" readOnly value={applyUrl} onFocus={(e) => e.currentTarget.select()} />
            </div>
            <div className="btn-row">
              <Button variant="primary" small onClick={copyApplyLink}>
                Copy public link
              </Button>
              <a
                className="btn btn--default btn--sm"
                href={`mailto:?subject=${encodeURIComponent(
                  `Apply: ${c.position_title}`,
                )}&body=${encodeURIComponent(
                  `Apply for ${c.position_title} here: ${applyUrl}`,
                )}`}
              >
                Share via email
              </a>
              <a className="btn btn--default btn--sm" href={applyPath} target="_blank" rel="noreferrer">
                Open apply page ↗
              </a>
            </div>
          </div>

          {/* Auto-generated QR for the public apply URL. Generated entirely in-browser, so
              the link never leaves the page. Candidates can scan it from a printed flyer or
              a shared screen; HR can copy the link or download the QR as an SVG. */}
          <div className="apply-qr">
            <QrCode value={applyUrl} size={168} title={`Apply: ${c.position_title}`} />
            <div className="apply-qr__caption">Scan to apply</div>
            <div className="btn-row apply-qr__actions">
              <Button variant="default" small onClick={copyApplyLink}>
                Copy link
              </Button>
              {(() => {
                const uri = qrDataUri(applyUrl);
                return uri ? (
                  <a
                    className="btn btn--default btn--sm"
                    href={uri}
                    download={`apply-qr-${c.position_title.replace(/\s+/g, "-").toLowerCase()}.svg`}
                  >
                    Download QR
                  </a>
                ) : null;
              })()}
            </div>
          </div>
        </div>
      </Card>

      <Card
        title="Team access"
        actions={<Badge tone={assigned ? "ok" : "warn"}>{assigned ? "You're assigned" : "Not assigned"}</Badge>}
      >
        <p className="subtle" style={{ marginTop: 0 }}>
          Only staff assigned to this campaign can act on it (upload JD, author rules, approve,
          etc.). Assign yourself to pick up work, or assign a colleague by email.
        </p>
        <div className="btn-row" style={{ marginBottom: 12 }}>
          <Button
            variant="primary"
            small
            disabled={assigned || assignSelf.isPending}
            onClick={() => {
              setError(null);
              assignSelf.mutate();
            }}
          >
            {assigned ? "You're assigned" : assignSelf.isPending ? "Assigning…" : "Assign me"}
          </Button>
        </div>
        {hasPermission("campaign.edit") && (
          <div className="grid grid--2" style={{ alignItems: "end" }}>
            <Field label="Assign a colleague (email)" htmlFor="assign-email">
              <input
                id="assign-email"
                type="email"
                value={assignEmail}
                onChange={(e) => setAssignEmail(e.target.value)}
                placeholder="synthetic.recruiter@example.com"
              />
            </Field>
            <div>
              <Button
                variant="default"
                small
                disabled={!assignEmail.trim() || assignOther.isPending}
                onClick={() => {
                  setError(null);
                  assignOther.mutate();
                }}
              >
                {assignOther.isPending ? "Assigning…" : "Assign user"}
              </Button>
            </div>
          </div>
        )}
      </Card>

      {!isOpen && (
        <Card title="Quick start (local dev)">
          {error && <ErrorNote>{error}</ErrorNote>}
          <p className="subtle" style={{ marginTop: 0 }}>
            Opening a campaign normally takes several approvals across multiple roles. For local
            evaluation, this one click creates and approves all five artifacts (JD, rules, form,
            threshold, privacy notice) and drives the campaign straight to{" "}
            <strong>Applications open</strong>, so you can test the candidate apply form right away.
            This action is only available in local/dev environments.
          </p>
          <Button
            variant="accent"
            small
            disabled={openNow.isPending}
            onClick={() => {
              setError(null);
              openNow.mutate();
            }}
          >
            {openNow.isPending ? "Opening…" : "Open this campaign now (dev)"}
          </Button>
        </Card>
      )}

      <Card title="Publication readiness">
        <p className="subtle" style={{ marginTop: 0 }}>
          A campaign cannot be published until all five governed artifacts are approved.
        </p>
        <div className="btn-row">
          {PREREQS.map((p) => (
            <Badge key={p.key} tone={c[p.key as keyof typeof c] ? "ok" : "neutral"}>
              {p.label}: {c[p.key as keyof typeof c] ? "ready" : "missing"}
            </Badge>
          ))}
        </div>
      </Card>

      <Card title="Lifecycle">
        {error && <ErrorNote>{error}</ErrorNote>}
        <p className="subtle" style={{ marginTop: 0 }}>
          Current state: <Badge tone={toneFor(c.state)}>{prettify(c.state)}</Badge>. Transitions are
          guarded — invalid moves are rejected and every change is audited.
        </p>
        {nexts.length === 0 ? (
          <p className="subtle">No guided transitions from this state in the simplified console.</p>
        ) : (
          <>
            <Field label="Reason (recorded in the audit trail)" htmlFor="t-reason">
              <input
                id="t-reason"
                value={reason}
                onChange={(e) => setReason(e.target.value)}
                placeholder="e.g. all artifacts approved"
              />
            </Field>
            <div className="btn-row">
              {nexts.map((n) => {
                const perm = TRANSITION_PERMISSION[n.to];
                const allowed = assigned && (!perm || hasPermission(perm));
                return (
                  <Button
                    key={n.to}
                    variant={n.to === "cancelled" ? "danger" : "primary"}
                    small
                    disabled={transition.isPending || !allowed}
                    title={
                      allowed
                        ? undefined
                        : !assigned
                          ? "You're not assigned to this campaign"
                          : `Needs the ${perm} permission`
                    }
                    onClick={() => {
                      void requestTransition(n.to);
                    }}
                  >
                    {n.label}
                  </Button>
                );
              })}
            </div>
          </>
        )}
      </Card>
    </>
  );
}

function JdTab({ campaignId }: { campaignId: string }): ReactNode {
  const toast = useToast();
  const qc = useQueryClient();
  const { token, hasPermission, canAccessCampaign } = useAuth();
  const [file, setFile] = useState<File | null>(null);
  const [uploaded, setUploaded] = useState<JDVersion | null>(null);
  const [error, setError] = useState<string | null>(null);
  const [busy, setBusy] = useState(false);

  const assigned = canAccessCampaign(campaignId);
  const canUpload = hasPermission("jd.upload") && assigned;
  const canApprove = hasPermission("jd.approve") && assigned;

  // Load existing JD versions so a reviewer can approve a draft they didn't upload.
  const versions = useQuery({
    queryKey: ["jd-versions", campaignId],
    queryFn: () => listJdVersions(campaignId),
    enabled: assigned && hasPermission("jd.review"),
  });

  // The draft to act on: a just-uploaded one takes priority, else the latest server draft.
  const serverDraft = versions.data?.find((v) => v.status === "draft") ?? null;
  const draft = uploaded ?? serverDraft;

  const upload = async (): Promise<void> => {
    if (!file) return;
    setBusy(true);
    setError(null);
    try {
      const v = await uploadJd(campaignId, file, token() ?? "");
      setUploaded(v);
      void qc.invalidateQueries({ queryKey: ["jd-versions", campaignId] });
      toast.push("JD uploaded & extracted", { tone: "ok" });
    } catch (e) {
      setError(e instanceof Error ? e.message : "Upload failed.");
    } finally {
      setBusy(false);
    }
  };

  const approve = useMutation({
    mutationFn: () => approveJd(draft?.id ?? "", "Reviewed and approved via console"),
    onSuccess: (v) => {
      setUploaded(v);
      void qc.invalidateQueries({ queryKey: ["jd-versions", campaignId] });
      void qc.invalidateQueries({ queryKey: ["campaign", campaignId] });
      toast.push("JD version approved (now immutable)", { tone: "ok" });
    },
    onError: (e) => setError(e instanceof ApiError ? e.message : "Approval failed."),
  });

  // Editable draft details. A position title is required before a JD can be approved.
  const [titleInput, setTitleInput] = useState("");
  const [deptInput, setDeptInput] = useState("");
  const canReview = hasPermission("jd.review") && assigned;
  const draftKey = draft?.id ?? "";
  // Seed the inputs from the loaded draft once (keyed by draft id).
  useEffect(() => {
    setTitleInput(draft?.position_title ?? "");
    setDeptInput(draft?.department ?? "");
  }, [draftKey]); // eslint-disable-line react-hooks/exhaustive-deps

  const saveDetails = useMutation({
    mutationFn: () =>
      updateJdVersion(draft?.id ?? "", {
        position_title: titleInput.trim(),
        ...(deptInput.trim() ? { department: deptInput.trim() } : {}),
      }),
    onSuccess: (v) => {
      setUploaded(v);
      void qc.invalidateQueries({ queryKey: ["jd-versions", campaignId] });
      toast.push("JD details saved", { tone: "ok" });
    },
    onError: (e) => setError(e instanceof ApiError ? e.message : "Could not save details."),
  });

  const hasTitle = Boolean((draft?.position_title ?? "").trim());

  return (
    <>
      <Card title="Upload a job description">
        {error && <ErrorNote>{error}</ErrorNote>}
        <AccessNote campaignId={campaignId} permission="jd.upload" role="Recruiter" />
        <p className="subtle" style={{ marginTop: 0 }}>
          PDF, DOCX, or TXT. The file is validated, scanned, and quarantined; a draft is then
          extracted for your review. Extraction is a suggestion only.
        </p>
        <input
          type="file"
          accept=".pdf,.docx,.txt"
          disabled={!canUpload}
          onChange={(e) => setFile(e.target.files?.[0] ?? null)}
        />
        <div className="btn-row" style={{ marginTop: 12 }}>
          <Button
            variant="primary"
            small
            disabled={!canUpload || !file || busy}
            onClick={() => void upload()}
          >
            {busy ? "Uploading…" : "Upload & extract"}
          </Button>
        </div>
      </Card>

      {draft && (
        <Card
          title={`Extracted draft — version ${draft.version_number}`}
          actions={<Badge tone={toneFor(draft.status)}>{prettify(draft.status)}</Badge>}
        >
          <p className="subtle" style={{ marginTop: 0 }}>
            Review and confirm the details below. A <strong>position title is required</strong>{" "}
            before the JD can be approved. Extraction is a suggestion only.
          </p>
          {draft.status === "draft" ? (
            <>
              <div className="grid grid--2">
                <Field label="Position title *" htmlFor="jd-title">
                  <input
                    id="jd-title"
                    value={titleInput}
                    disabled={!canReview}
                    onChange={(e) => setTitleInput(e.target.value)}
                    placeholder="e.g. Senior Python Engineer"
                  />
                </Field>
                <Field label="Department" htmlFor="jd-dept">
                  <input
                    id="jd-dept"
                    value={deptInput}
                    disabled={!canReview}
                    onChange={(e) => setDeptInput(e.target.value)}
                    placeholder="e.g. Engineering"
                  />
                </Field>
              </div>
              <dl className="kv">
                <dt>Mandatory skills</dt>
                <dd>{draft.mandatory_skills.join(", ") || "—"}</dd>
                <dt>Responsibilities</dt>
                <dd>{draft.responsibilities.slice(0, 4).join("; ") || "—"}</dd>
              </dl>
              <div className="btn-row" style={{ marginTop: 12 }}>
                <Button
                  variant="default"
                  small
                  disabled={!canReview || !titleInput.trim() || saveDetails.isPending}
                  onClick={() => {
                    setError(null);
                    saveDetails.mutate();
                  }}
                >
                  {saveDetails.isPending ? "Saving…" : "Save details"}
                </Button>
                <Button
                  variant="accent"
                  small
                  disabled={!canApprove || !hasTitle || approve.isPending}
                  title={
                    !canApprove
                      ? "Approving a JD needs the Recruiter Admin / Hiring Manager role"
                      : !hasTitle
                        ? "Save a position title first"
                        : undefined
                  }
                  onClick={() => approve.mutate()}
                >
                  {approve.isPending ? "Approving…" : "Approve JD version"}
                </Button>
              </div>
              {!hasTitle && (
                <p className="subtle" style={{ marginTop: 8 }}>
                  Enter a position title and click <strong>Save details</strong>, then{" "}
                  <strong>Approve JD version</strong>.
                </p>
              )}
            </>
          ) : (
            <dl className="kv">
              <dt>Position title</dt>
              <dd>{draft.position_title ?? "—"}</dd>
              <dt>Department</dt>
              <dd>{draft.department ?? "—"}</dd>
              <dt>Mandatory skills</dt>
              <dd>{draft.mandatory_skills.join(", ") || "—"}</dd>
              <dt>Responsibilities</dt>
              <dd>{draft.responsibilities.slice(0, 4).join("; ") || "—"}</dd>
            </dl>
          )}
        </Card>
      )}
    </>
  );
}

function FormTab({ campaignId }: { campaignId: string }): ReactNode {
  const toast = useToast();
  const qc = useQueryClient();
  const { hasPermission, canAccessCampaign } = useAuth();
  const [error, setError] = useState<string | null>(null);
  const [comp, setComp] = useState(false);
  const [formId, setFormId] = useState<string | null>(null);
  const [fields, setFields] = useState<string[]>([]);

  const assigned = canAccessCampaign(campaignId);
  const canEdit = hasPermission("campaign.edit") && assigned;

  const createDraft = useMutation({
    mutationFn: () => createFormDraft(campaignId, comp),
    onSuccess: (v) => {
      setFormId(v.id);
      setFields(v.fields.map((f) => f.label));
      toast.push("Form draft created", { tone: "ok" });
    },
    onError: (e) => setError(e instanceof ApiError ? e.message : "Could not create form."),
  });

  const approve = useMutation({
    mutationFn: () => approveForm(formId ?? ""),
    onSuccess: () => {
      void qc.invalidateQueries({ queryKey: ["campaign", campaignId] });
      toast.push("Form approved (immutable)", { tone: "ok" });
    },
    onError: (e) => setError(e instanceof ApiError ? e.message : "Approval failed."),
  });

  return (
    <>
      {error && <ErrorNote>{error}</ErrorNote>}
      <Card title="Application form">
        <AccessNote campaignId={campaignId} permission="campaign.edit" role="Recruiter" />
        <p className="subtle" style={{ marginTop: 0 }}>
          The form is generated from a safe schema. Protected attributes (age, gender, religion,
          disability, etc.) can never be added. Compensation fields are off unless explicitly enabled.
        </p>
        <div className="checkbox-row">
          <input id="comp" type="checkbox" checked={comp} disabled={!canEdit} onChange={(e) => setComp(e.target.checked)} />
          <label htmlFor="comp">Enable compensation fields for this campaign</label>
        </div>
        <div className="btn-row">
          <Button variant="primary" small disabled={!canEdit || createDraft.isPending} onClick={() => createDraft.mutate()}>
            {createDraft.isPending ? "Creating…" : "Create form draft"}
          </Button>
          {formId && (
            <Button variant="accent" small disabled={!canEdit || approve.isPending} onClick={() => approve.mutate()}>
              {approve.isPending ? "Approving…" : "Approve form"}
            </Button>
          )}
        </div>
        {fields.length > 0 && (
          <p className="subtle" style={{ marginTop: 12 }}>
            Fields: {fields.join(", ")}
          </p>
        )}
      </Card>
    </>
  );
}
