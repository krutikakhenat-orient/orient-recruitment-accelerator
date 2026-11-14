/* Sections of the candidate page that used to live on the campaign's Interviews tab and the
   Hiring Decisions page, now shown for ONE candidate:

   - PanelInterviewSection: invite to a panel interview, see the invitation, the candidate's
     confirmation, attendance.
   - DecisionSection: the panel's assessment and the hiring decision (select / reject / hold).

   Permissions are unchanged and still enforced by the server: inviting needs
   interview.approve + interview.schedule; select/reject needs hiring_decision.approve; hold
   needs hiring_decision.recommend. Every decision needs a reason and is audited. */

import { useMutation, useQuery, useQueryClient } from "@tanstack/react-query";
import { Lock } from "lucide-react";
import { useState, type ReactNode } from "react";
import { Link } from "react-router-dom";

import { ApiError } from "../api/client";
import {
  listInvitations,
  listPendingDecisions,
  recordDecision,
  recordWalkInInterview,
  type AssessmentSummary,
} from "../api/resources";
import { useAuth } from "../app/auth-context";
import { ConfirmationControls } from "./ConfirmationControls";
import { useToast } from "./toast";
import { Badge, Button, Card, Empty, ErrorNote, Field, Loading, prettify, toneFor } from "./ui";

const INVITABLE = new Set(["screened", "manual_review", "interview_recommended", "no_show"]);
// Same states the Hiring Decisions inbox lists: the interview is finished (checked out, or a
// legacy "attended" record), or the candidate was put on hold.
const DECIDABLE = new Set(["checked_out", "attended", "hold"]);

function refreshCandidate(qc: ReturnType<typeof useQueryClient>, campaignId: string, applicationId: string): void {
  for (const key of [
    ["application", applicationId],
    ["journey", applicationId],
    ["applications", campaignId],
    ["invitations", campaignId],
    ["pending-decisions"],
  ]) {
    void qc.invalidateQueries({ queryKey: key });
  }
}

export function PanelInterviewSection({
  campaignId,
  applicationId,
  state,
  name,
}: {
  campaignId: string;
  applicationId: string;
  state: string;
  name: string;
}): ReactNode {
  const toast = useToast();
  const qc = useQueryClient();
  const { hasPermission, canAccessCampaign } = useAuth();
  const assigned = canAccessCampaign(campaignId);
  const canInvite = hasPermission("interview.approve") && hasPermission("interview.schedule") && assigned;
  const invites = useQuery({
    queryKey: ["invitations", campaignId],
    queryFn: () => listInvitations(campaignId),
  });
  const [reason, setReason] = useState("");
  const [error, setError] = useState<string | null>(null);
  // Under review (below the automatic bar): inviting overrides screening, so the server
  // requires a reason. Same rule as the old "Select for interview" button.
  const needsReason = state === "manual_review";

  const invite = useMutation({
    mutationFn: () => recordWalkInInterview(applicationId, needsReason ? reason.trim() : undefined),
    onSuccess: () => {
      setReason("");
      refreshCandidate(qc, campaignId, applicationId);
      toast.push(`${name} is now on the interview panel's list`, { tone: "ok" });
    },
    onError: (e) => setError(e instanceof ApiError ? e.message : "Could not invite this candidate."),
  });

  const mine = (invites.data ?? []).filter((i) => i.application_id === applicationId);
  const canInviteNow = INVITABLE.has(state) && mine.every((i) => i.attendance !== "pending");

  return (
    <Card
      title="Panel interview"
      description="An interview with people. The candidate gets a personal link to confirm; their reply tells the interviewer."
    >
      {error && <ErrorNote>{error}</ErrorNote>}
      {invites.isLoading && <Loading />}
      {mine.length > 0 && (
        <div className="table-wrap">
          <table className="data">
            <thead>
              <tr>
                <th>Invitation</th>
                <th>Slot</th>
                <th>Attendance</th>
                <th />
              </tr>
            </thead>
            <tbody>
              {mine.map((inv) => (
                <tr key={inv.id}>
                  <td>
                    <Badge tone={toneFor(inv.status)}>{prettify(inv.status)}</Badge>
                  </td>
                  <td className="subtle">{inv.slot_id ? "Booked (walk-in)" : "Not booked"}</td>
                  <td>
                    <Badge tone={toneFor(inv.attendance)}>{prettify(inv.attendance)}</Badge>
                  </td>
                  <td style={{ textAlign: "right" }}>
                    {inv.attendance === "pending" && <ConfirmationControls invitationId={inv.id} />}
                  </td>
                </tr>
              ))}
            </tbody>
          </table>
          <p className="subtle" style={{ marginTop: 8 }}>
            On the day, the interview panel checks the candidate in and submits their assessment
            from <Link to="/assessments">My interviews</Link>.
          </p>
        </div>
      )}
      {!invites.isLoading && mine.length === 0 && !canInviteNow && (
        <Empty>No panel interview yet. Candidates can be invited once they have been screened.</Empty>
      )}
      {canInviteNow &&
        (canInvite ? (
          <div style={{ marginTop: mine.length > 0 ? 12 : 0 }}>
            {needsReason && (
              <Field
                label="Why invite this candidate? * (they are under review; saved in the audit trail)"
                htmlFor="invite-reason"
              >
                <textarea
                  id="invite-reason"
                  rows={2}
                  value={reason}
                  onChange={(e) => setReason(e.target.value)}
                  placeholder="e.g. Strong relevant project experience the automatic skill match missed."
                />
              </Field>
            )}
            <Button
              variant="primary"
              disabled={invite.isPending || (needsReason && !reason.trim())}
              onClick={() => {
                setError(null);
                invite.mutate();
              }}
            >
              {invite.isPending ? "Inviting…" : "Invite to panel interview"}
            </Button>
          </div>
        ) : (
          <p className="subtle">
            <Lock size={14} aria-hidden="true" className="inline-icon" />
            Inviting needs the Recruiter Admin role and assignment to this job.
          </p>
        ))}
    </Card>
  );
}

function avg(scores: AssessmentSummary["criteria_scores"]): string {
  const nums = Object.values(scores).filter((v): v is number => typeof v === "number");
  if (nums.length === 0) return "—";
  return (nums.reduce((a, b) => a + b, 0) / nums.length).toFixed(1);
}

export function DecisionSection({
  campaignId,
  applicationId,
  state,
}: {
  campaignId: string;
  applicationId: string;
  state: string;
}): ReactNode {
  const toast = useToast();
  const qc = useQueryClient();
  const { hasPermission } = useAuth();
  const canApprove = hasPermission("hiring_decision.approve");
  const canRecommend = hasPermission("hiring_decision.recommend");
  const decidable = DECIDABLE.has(state);
  const pending = useQuery({
    queryKey: ["pending-decisions"],
    queryFn: listPendingDecisions,
    enabled: decidable && (canApprove || canRecommend),
  });
  const [reason, setReason] = useState("");
  const [error, setError] = useState<string | null>(null);

  const decide = useMutation({
    mutationFn: (type: string) => recordDecision(applicationId, type, reason.trim()),
    onSuccess: () => {
      setReason("");
      refreshCandidate(qc, campaignId, applicationId);
      toast.push("Decision recorded", { tone: "ok" });
    },
    onError: (e) => setError(e instanceof ApiError ? e.message : "Could not record the decision."),
  });

  const item = (pending.data ?? []).find((d) => d.application_id === applicationId);

  return (
    <Card
      title="Hiring decision"
      description="Made by a person after reading the interviewers' assessment. Every decision needs a reason and is recorded."
    >
      {["selected", "rejected", "waitlisted", "withdrawn"].includes(state) && (
        <p className="mt-0">
          Decision on record: <Badge tone={toneFor(state)}>{prettify(state)}</Badge>
          {state === "selected" && (
            <>
              {" "}
              Next: <Link to="/offers">prepare the offer in Offers &amp; joining →</Link>
            </>
          )}
        </p>
      )}
      {!decidable && !["selected", "rejected", "waitlisted", "withdrawn"].includes(state) && (
        <Empty>The decision is made after the interview panel has assessed the candidate.</Empty>
      )}
      {decidable && (
        <>
          {error && <ErrorNote>{error}</ErrorNote>}
          {!canApprove && !canRecommend && (
            <p className="subtle">
              <Lock size={14} aria-hidden="true" className="inline-icon" />
              Recording a decision needs the Recruiter Admin role.
            </p>
          )}
          {(canApprove || canRecommend) && (
            <>
              <h3 style={{ margin: "0 0 8px", fontSize: "0.95rem" }}>What the interviewers said</h3>
              {pending.isLoading && <Loading />}
              {!pending.isLoading && (!item || item.assessments.length === 0) && (
                <p className="subtle">No assessment on record yet.</p>
              )}
              {item && item.assessments.length > 0 && (
                <div className="table-wrap">
                  <table className="data">
                    <thead>
                      <tr>
                        <th>Recommendation</th>
                        <th>Average score (1–5)</th>
                        <th>Conflict declared</th>
                        <th>Notes</th>
                      </tr>
                    </thead>
                    <tbody>
                      {item.assessments.map((a, i) => (
                        <tr key={i}>
                          <td>
                            <Badge tone={toneFor(a.recommendation)}>{prettify(a.recommendation)}</Badge>
                          </td>
                          <td>{avg(a.criteria_scores)}</td>
                          <td>{a.conflict_declared ? <Badge tone="warn">Yes</Badge> : "No"}</td>
                          <td className="subtle">{a.interview_notes ?? "—"}</td>
                        </tr>
                      ))}
                    </tbody>
                  </table>
                </div>
              )}
              <Field label="Reason for the decision * (saved in the audit trail)" htmlFor="decision-reason">
                <input
                  id="decision-reason"
                  value={reason}
                  onChange={(e) => setReason(e.target.value)}
                  placeholder="Why this decision?"
                />
              </Field>
              <div className="btn-row" style={{ marginTop: 8 }}>
                <Button
                  variant="accent"
                  small
                  disabled={!canApprove || !reason.trim() || decide.isPending}
                  title={canApprove ? undefined : "Selecting needs the Recruiter Admin role"}
                  onClick={() => {
                    setError(null);
                    decide.mutate("select");
                  }}
                >
                  Select (hire)
                </Button>
                <Button
                  variant="danger"
                  small
                  disabled={!canApprove || !reason.trim() || decide.isPending}
                  title={canApprove ? undefined : "This needs the Recruiter Admin role"}
                  onClick={() => {
                    setError(null);
                    if (window.confirm("Record 'not selected' for this candidate? This closes their application.")) {
                      decide.mutate("reject");
                    }
                  }}
                >
                  Not selected
                </Button>
                {state !== "hold" && (
                  <Button
                    variant="default"
                    small
                    disabled={!canRecommend || !reason.trim() || decide.isPending}
                    onClick={() => {
                      setError(null);
                      decide.mutate("hold");
                    }}
                  >
                    Put on hold
                  </Button>
                )}
              </div>
            </>
          )}
        </>
      )}
    </Card>
  );
}
