import { useMutation, useQuery, useQueryClient } from "@tanstack/react-query";
import { useMemo, useState, type ReactNode } from "react";

import { ApiError } from "../api/client";
import {
  listApplications,
  listCampaigns,
  listReviews,
  listScreeningRuns,
  recordReviewAction,
  type Application,
  type ReviewItem,
  type ScreeningRun,
} from "../api/resources";
import { useAuth } from "../app/auth-context";
import { CandidateScorecardDrawer } from "../components/CandidateScorecardDrawer";
import { useToast } from "../components/toast";
import { Badge, Button, Card, Empty, ErrorNote, Field, Loading, prettify, toneFor } from "../components/ui";

// Reviewer actions. These are advisory routing decisions — the Review Queue advances or
// parks a flagged candidate; the final hire/reject decision happens later with approval
// authority (so there is deliberately NO reject here). Each action that moves the
// application names the permission the server enforces, so we can disable a button the
// signed-in reviewer is not allowed to use (four-eyes) instead of letting it 403.
type ReviewActionDef = {
  type: string;
  label: string;
  resolves: boolean;
  variant: "accent" | "default" | "danger";
  // Permission the backend requires for the state change this action performs; undefined
  // means the action only records a note and needs no extra authority.
  permission?: string;
  hint?: string;
};

const ACTIONS: ReviewActionDef[] = [
  {
    type: "recommend_interview",
    label: "✓ Select for interview",
    resolves: true,
    variant: "accent",
    permission: "interview.approve",
    hint: "Needs interview-approval authority (Recruiter Admin / Hiring Manager).",
  },
  {
    type: "recommend_waitlist",
    label: "Waitlist",
    resolves: true,
    variant: "default",
    permission: "waitlist.manage",
    hint: "Needs waitlist-management authority.",
  },
  {
    type: "request_clarification",
    label: "Request info",
    resolves: false,
    variant: "default",
    permission: "application.review",
  },
  { type: "escalate_hiring_manager", label: "Escalate", resolves: false, variant: "default" },
];

export function ReviewQueuePage(): ReactNode {
  const campaigns = useQuery({ queryKey: ["campaigns"], queryFn: listCampaigns });
  const [campaignId, setCampaignId] = useState("");
  // The application whose resume/scorecard drawer is open.
  const [inspect, setInspect] = useState<{ app: Application; run: ScreeningRun | null } | null>(null);

  const reviews = useQuery({
    queryKey: ["reviews", campaignId],
    queryFn: () => listReviews(campaignId),
    enabled: Boolean(campaignId),
  });

  // Load the campaign's applications so we can show candidate NAMES (not raw IDs) and open
  // a resume view for the person being reviewed.
  const apps = useQuery({
    queryKey: ["applications", campaignId],
    queryFn: () => listApplications(campaignId),
    enabled: Boolean(campaignId),
  });
  const appById = useMemo(() => {
    const m = new Map<string, Application>();
    for (const a of apps.data ?? []) m.set(a.id, a);
    return m;
  }, [apps.data]);

  const openResume = async (applicationId: string): Promise<void> => {
    const app = appById.get(applicationId);
    if (!app) return;
    const runs = await listScreeningRuns(applicationId).catch(() => []);
    setInspect({ app, run: runs[0] ?? null });
  };

  return (
    <>
      <div className="page-head">
        <h1>Human Review Queue</h1>
        <p>
          Candidates the system flagged for a person to look at. Open a candidate&rsquo;s resume,
          then choose what happens next. Screening never auto-rejects — the decision is yours.
        </p>
      </div>

      <Card title="Select a campaign">
        {campaigns.isLoading && <Loading />}
        <Field label="Campaign" htmlFor="rq-campaign">
          <select id="rq-campaign" value={campaignId} onChange={(e) => setCampaignId(e.target.value)}>
            <option value="">Choose a campaign…</option>
            {campaigns.data?.map((c) => (
              <option key={c.id} value={c.id}>
                {c.name} — {prettify(c.state)}
              </option>
            ))}
          </select>
        </Field>
      </Card>

      {campaignId && (
        <Card title="Candidates to review">
          {reviews.isLoading && <Loading />}
          {reviews.error && (
            <ErrorNote>Could not load review items (you may lack access to this campaign).</ErrorNote>
          )}
          {reviews.data && reviews.data.length === 0 && (
            <Empty>
              No candidates to review right now. They appear here after screening flags someone —
              run screening from a campaign&rsquo;s Applications &amp; Screening tab.
            </Empty>
          )}
          {reviews.data && reviews.data.length > 0 && (
            <div className="table-wrap">
              <table className="data">
                <thead>
                  <tr>
                    <th>Candidate</th>
                    <th>Why flagged</th>
                    <th>Resume</th>
                    <th>Decision</th>
                  </tr>
                </thead>
                <tbody>
                  {reviews.data.map((r) => (
                    <ReviewRow
                      key={r.id}
                      item={r}
                      campaignId={campaignId}
                      candidateName={nameFor(appById.get(r.application_id))}
                      canOpenResume={appById.has(r.application_id)}
                      onViewResume={() => void openResume(r.application_id)}
                    />
                  ))}
                </tbody>
              </table>
            </div>
          )}
        </Card>
      )}

      {inspect && (
        <CandidateScorecardDrawer app={inspect.app} run={inspect.run} onClose={() => setInspect(null)} />
      )}
    </>
  );
}

function nameFor(app: Application | undefined): string {
  if (!app) return "Candidate";
  const n = app.answers["full_name"];
  return typeof n === "string" && n.trim() ? n : "Candidate";
}

function ReviewRow({
  item,
  campaignId,
  candidateName,
  canOpenResume,
  onViewResume,
}: {
  item: ReviewItem;
  campaignId: string;
  candidateName: string;
  canOpenResume: boolean;
  onViewResume: () => void;
}): ReactNode {
  const toast = useToast();
  const qc = useQueryClient();
  const { hasPermission } = useAuth();
  const [error, setError] = useState<string | null>(null);
  const [reason, setReason] = useState("");

  const canReview = hasPermission("application.review");

  const act = useMutation({
    mutationFn: (a: { type: string; resolves: boolean }) =>
      recordReviewAction(item.id, {
        action_type: a.type,
        reason: reason.trim() || "Reviewed via console",
        resolves_item: a.resolves,
      }),
    onSuccess: () => {
      setReason("");
      void qc.invalidateQueries({ queryKey: ["reviews", campaignId] });
      toast.push("Decision recorded", { tone: "ok" });
    },
    onError: (e) => setError(e instanceof ApiError ? e.message : "Could not record the decision."),
  });

  return (
    <tr>
      <td>
        <strong>{candidateName}</strong>
      </td>
      <td>
        <Badge tone={toneFor(item.reason)}>{prettify(item.reason)}</Badge>
        <div className="subtle" style={{ marginTop: 4, fontSize: "0.82rem" }}>{item.detail ?? ""}</div>
      </td>
      <td>
        <Button variant="default" small disabled={!canOpenResume} onClick={onViewResume}>
          📄 View resume
        </Button>
      </td>
      <td>
        {error && <ErrorNote>{error}</ErrorNote>}
        {item.status === "open" ? (
          canReview ? (
            <div>
              <input
                aria-label="Reason for this decision"
                placeholder="Reason (recorded in the audit trail)"
                value={reason}
                onChange={(e) => setReason(e.target.value)}
                style={{ marginBottom: 6, width: "100%" }}
              />
              <div className="btn-row">
                {ACTIONS.map((a) => {
                  const allowed = !a.permission || hasPermission(a.permission);
                  return (
                    <Button
                      key={a.type}
                      variant={a.variant}
                      small
                      disabled={act.isPending || !allowed}
                      title={allowed ? undefined : a.hint}
                      onClick={() => {
                        setError(null);
                        act.mutate({ type: a.type, resolves: a.resolves });
                      }}
                    >
                      {a.label}
                    </Button>
                  );
                })}
              </div>
              {ACTIONS.some((a) => a.permission && !hasPermission(a.permission)) && (
                <div className="subtle" style={{ marginTop: 6, fontSize: "0.8rem" }}>
                  Some actions are greyed out because they need approval authority you
                  don&rsquo;t hold — a Recruiter Admin signs those off (four-eyes).
                </div>
              )}
            </div>
          ) : (
            <span className="subtle">🔒 Needs the reviewer role.</span>
          )
        ) : (
          <span className="subtle">Resolved</span>
        )}
      </td>
    </tr>
  );
}
