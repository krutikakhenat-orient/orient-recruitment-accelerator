import { useMutation, useQueries, useQuery, useQueryClient } from "@tanstack/react-query";
import { AlertTriangle, CheckCircle2, ChevronDown, ChevronRight, Clock, FileText } from "lucide-react";
import { useMemo, useState, type ReactNode } from "react";
import { Link } from "react-router-dom";

import { ApiError } from "../api/client";
import {
  listApplications,
  listCampaigns,
  listReviews,
  listScreeningRuns,
  recordReviewAction,
  type Application,
  type Campaign,
  type ReviewItem,
  type ScreeningRun,
} from "../api/resources";
import { useAuth } from "../app/auth-context";
import { CandidateScorecardDrawer } from "../components/CandidateScorecardDrawer";
import { JourneyButton } from "../components/JourneyButton";
import { useToast } from "../components/toast";
import { Badge, Button, Card, Empty, ErrorNote, Loading, PageHeader, Stat } from "../components/ui";
import {
  OVERDUE_DAYS,
  countByReason,
  daysWaiting,
  filterInbox,
  reasonInfo,
  sortOldestFirst,
  waitingLabel,
  type InboxFilter,
} from "../lib/reviewInbox";

// Reviewer actions. These are advisory routing decisions — the inbox advances or parks a
// flagged candidate; the final hire/reject decision happens later with approval authority
// (so there is deliberately NO reject here). Each action that moves the application names
// the permission the server enforces, so a button the reviewer cannot use is disabled with
// an explanation (four-eyes) instead of failing with a 403.
type ReviewActionDef = {
  type: string;
  label: string;
  /** One line under the button: what it does. */
  explain: string;
  resolves: boolean;
  variant: "accent" | "default" | "danger";
  permission?: string;
  lockedHint?: string;
};

const ACTIONS: ReviewActionDef[] = [
  {
    type: "recommend_interview",
    label: "Select for interview",
    explain: "Moves them to the interview list.",
    resolves: true,
    variant: "accent",
    permission: "interview.approve",
    lockedHint: "Needs a Recruiter Admin (interview approval).",
  },
  {
    type: "recommend_waitlist",
    label: "Waitlist",
    explain: "Keeps them as a backup.",
    resolves: true,
    variant: "default",
    permission: "waitlist.manage",
    lockedHint: "Needs waitlist permission.",
  },
  {
    type: "request_clarification",
    label: "Ask for info",
    explain: "Notes that you need more from the candidate. Stays in your inbox.",
    resolves: false,
    variant: "default",
    permission: "application.review",
  },
  {
    type: "escalate_hiring_manager",
    label: "Ask hiring manager",
    explain: "Flags it for the hiring manager. Stays in your inbox.",
    resolves: false,
    variant: "default",
  },
];

type Row = { item: ReviewItem; campaign: Campaign | undefined };

export function ReviewQueuePage(): ReactNode {
  const { hasPermission, canAccessCampaign } = useAuth();
  const canReview = hasPermission("application.review");
  const campaigns = useQuery({ queryKey: ["campaigns"], queryFn: listCampaigns });
  const [filter, setFilter] = useState<InboxFilter>("all");
  const [jobFilter, setJobFilter] = useState("");
  const [expanded, setExpanded] = useState<string | null>(null);
  const [inspect, setInspect] = useState<{ app: Application; run: ScreeningRun | null } | null>(null);

  // The inbox covers every job you're assigned to, so nobody has to pick a campaign first.
  const myCampaigns = useMemo(
    () => (campaigns.data ?? []).filter((c) => canAccessCampaign(c.id)),
    [campaigns.data, canAccessCampaign],
  );
  const campaignById = useMemo(() => new Map(myCampaigns.map((c) => [c.id, c])), [myCampaigns]);

  const reviewQueries = useQueries({
    queries: myCampaigns.map((c) => ({
      queryKey: ["reviews", c.id],
      queryFn: () => listReviews(c.id),
      enabled: canReview,
    })),
  });
  const loadingReviews = reviewQueries.some((q) => q.isLoading);
  const failedJobs = reviewQueries.filter((q) => q.isError).length;

  const allRows: Row[] = useMemo(() => {
    const items = reviewQueries.flatMap((q) => q.data ?? []).filter((i) => i.status === "open");
    return sortOldestFirst(items).map((item) => ({ item, campaign: campaignById.get(item.campaign_id) }));
    // reviewQueries is a new array each render; key on the data it carries.
    // eslint-disable-next-line react-hooks/exhaustive-deps
  }, [reviewQueries.map((q) => q.dataUpdatedAt).join(","), campaignById]);

  // Candidate names come from each job's applications. Only load jobs that have items.
  const jobsWithItems = useMemo(
    () => [...new Set(allRows.map((r) => r.item.campaign_id))],
    [allRows],
  );
  const appQueries = useQueries({
    queries: jobsWithItems.map((cid) => ({
      queryKey: ["applications", cid],
      queryFn: () => listApplications(cid),
    })),
  });
  const appById = useMemo(() => {
    const m = new Map<string, Application>();
    for (const q of appQueries) for (const a of q.data ?? []) m.set(a.id, a);
    return m;
    // eslint-disable-next-line react-hooks/exhaustive-deps
  }, [appQueries.map((q) => q.dataUpdatedAt).join(",")]);

  const now = new Date();
  const items = allRows.map((r) => r.item);
  const inJob = jobFilter ? allRows.filter((r) => r.item.campaign_id === jobFilter) : allRows;
  const visibleItems = new Set(filterInbox(inJob.map((r) => r.item), filter, now).map((i) => i.id));
  const visible = inJob.filter((r) => visibleItems.has(r.item.id));
  const counts = countByReason(jobFilter ? inJob.map((r) => r.item) : items);
  const overdue = filterInbox(items, "overdue", now).length;

  const openResume = async (applicationId: string): Promise<void> => {
    const app = appById.get(applicationId);
    if (!app) return;
    const runs = await listScreeningRuns(applicationId).catch(() => []);
    setInspect({ app, run: runs[0] ?? null });
  };

  return (
    <>
      <PageHeader
        title="Review inbox"
        description={
          <>
            Candidates waiting for a person to decide, across all your jobs. Oldest first. Screening
            never rejects anyone on its own &mdash; you decide.
          </>
        }
      />

      {!canReview ? (
        <Card>
          <Empty>Your role doesn&rsquo;t review candidates, so there&rsquo;s nothing here for you.</Empty>
        </Card>
      ) : (
        <>
          <div className="grid grid--3 inbox-stats">
            <Stat label="Waiting for you" value={items.length} hint="Open items across your jobs" />
            <Stat label={`Waiting ${OVERDUE_DAYS}+ days`} value={overdue} hint="Handle these first" />
            <Stat label="Jobs with items" value={jobsWithItems.length} hint={`of ${myCampaigns.length} assigned to you`} />
          </div>

          <Card>
            <div className="inbox-toolbar">
              <div className="chips" role="group" aria-label="Filter by reason">
                <FilterChip active={filter === "all"} onClick={() => setFilter("all")} label="All" count={inJob.length} />
                {overdue > 0 && (
                  <FilterChip
                    active={filter === "overdue"}
                    onClick={() => setFilter("overdue")}
                    label={`Waiting ${OVERDUE_DAYS}+ days`}
                    count={filterInbox(inJob.map((r) => r.item), "overdue", now).length}
                  />
                )}
                {[...counts.entries()].map(([reason, n]) => (
                  <FilterChip
                    key={reason}
                    active={filter === reason}
                    onClick={() => setFilter(reason)}
                    label={reasonInfo(reason).label}
                    count={n}
                  />
                ))}
              </div>
              {jobsWithItems.length > 1 && (
                <label className="inbox-job-filter">
                  <span className="sr-only">Filter by job</span>
                  <select className="filter-select" value={jobFilter} onChange={(e) => setJobFilter(e.target.value)}>
                    <option value="">All jobs</option>
                    {jobsWithItems.map((cid) => (
                      <option key={cid} value={cid}>
                        {campaignById.get(cid)?.name ?? "Job"}
                      </option>
                    ))}
                  </select>
                </label>
              )}
            </div>

            {(campaigns.isLoading || loadingReviews) && <Loading label="Loading your inbox…" />}
            {failedJobs > 0 && (
              <ErrorNote>
                Could not load {failedJobs} job{failedJobs === 1 ? "" : "s"}. The rest are shown below.
              </ErrorNote>
            )}

            {!campaigns.isLoading && !loadingReviews && myCampaigns.length === 0 && (
              <Empty>
                You&rsquo;re not assigned to any jobs yet. Open a job from <Link to="/campaigns">Campaigns</Link> and
                choose <strong>Assign me</strong> under Settings.
              </Empty>
            )}

            {!loadingReviews && myCampaigns.length > 0 && items.length === 0 && (
              <div className="inbox-empty" role="status">
                <CheckCircle2 size={28} aria-hidden="true" />
                <div>
                  <strong>All caught up.</strong>
                  <div className="subtle">
                    Nothing is waiting. New items arrive here when screening flags a candidate for a person to check.
                  </div>
                </div>
              </div>
            )}

            {items.length > 0 && visible.length === 0 && <Empty>Nothing matches this filter.</Empty>}

            {visible.length > 0 && (
              <ul className="inbox-list" aria-label="Candidates waiting for review">
                {visible.map(({ item, campaign }) => (
                  <InboxRow
                    key={item.id}
                    item={item}
                    campaign={campaign}
                    app={appById.get(item.application_id)}
                    days={daysWaiting(item.created_at, now)}
                    open={expanded === item.id}
                    onToggle={() => setExpanded(expanded === item.id ? null : item.id)}
                    onViewResume={() => void openResume(item.application_id)}
                  />
                ))}
              </ul>
            )}
          </Card>
        </>
      )}

      {inspect && <CandidateScorecardDrawer app={inspect.app} run={inspect.run} onClose={() => setInspect(null)} />}
    </>
  );
}

function FilterChip({
  active,
  onClick,
  label,
  count,
}: {
  active: boolean;
  onClick: () => void;
  label: string;
  count: number;
}): ReactNode {
  return (
    <button type="button" className="chip-toggle" aria-pressed={active} onClick={onClick}>
      {label} <span className="chip-count">{count}</span>
    </button>
  );
}

function nameFor(app: Application | undefined): string {
  if (!app) return "Candidate";
  const n = app.answers["full_name"];
  return typeof n === "string" && n.trim() ? n : "Candidate";
}

function initials(name: string): string {
  const parts = name.trim().split(/\s+/).filter(Boolean);
  return (parts.slice(0, 2).map((p) => p[0]?.toUpperCase() ?? "").join("") || "?").slice(0, 2);
}

function InboxRow({
  item,
  campaign,
  app,
  days,
  open,
  onToggle,
  onViewResume,
}: {
  item: ReviewItem;
  campaign: Campaign | undefined;
  app: Application | undefined;
  days: number | null;
  open: boolean;
  onToggle: () => void;
  onViewResume: () => void;
}): ReactNode {
  const toast = useToast();
  const qc = useQueryClient();
  const { hasPermission } = useAuth();
  const [error, setError] = useState<string | null>(null);
  const [reason, setReason] = useState("");
  const name = nameFor(app);
  const info = reasonInfo(item.reason);
  const overdue = (days ?? 0) >= OVERDUE_DAYS;
  const panelId = `inbox-panel-${item.id}`;

  const act = useMutation({
    mutationFn: (a: ReviewActionDef) =>
      recordReviewAction(item.id, {
        action_type: a.type,
        reason: reason.trim(),
        resolves_item: a.resolves,
      }),
    onSuccess: (_r, a) => {
      setReason("");
      void qc.invalidateQueries({ queryKey: ["reviews", item.campaign_id] });
      toast.push(a.resolves ? `${name}: done — removed from your inbox` : `${name}: noted`, { tone: "ok" });
    },
    onError: (e) => setError(e instanceof ApiError ? e.message : "Could not record the decision."),
  });

  return (
    <li className={`inbox-row${open ? " inbox-row--open" : ""}${overdue ? " inbox-row--overdue" : ""}`}>
      <button type="button" className="inbox-row__head" aria-expanded={open} aria-controls={panelId} onClick={onToggle}>
        <span className="inbox-avatar" aria-hidden="true">
          {initials(name)}
        </span>
        <span className="inbox-row__main">
          <span className="inbox-row__title">
            {name}
            <span className="inbox-row__job"> · {campaign?.name ?? "Job"}</span>
          </span>
          <span className="inbox-row__why">
            <Badge tone={overdue ? "warn" : "info"}>{info.label}</Badge>
            <span className="subtle">{item.detail || info.explain}</span>
          </span>
        </span>
        <span className={`inbox-row__age${overdue ? " inbox-row__age--overdue" : ""}`}>
          {overdue ? <AlertTriangle size={14} aria-hidden="true" /> : <Clock size={14} aria-hidden="true" />}
          {waitingLabel(days)}
          {overdue && <span className="sr-only"> (overdue)</span>}
        </span>
        {open ? <ChevronDown size={16} aria-hidden="true" /> : <ChevronRight size={16} aria-hidden="true" />}
      </button>

      {open && (
        <div className="inbox-row__panel" id={panelId}>
          <p className="subtle mt-0">
            <strong>What to do:</strong> {info.explain}
          </p>
          <div className="btn-row">
            <Button variant="default" small disabled={!app} onClick={onViewResume}>
              <FileText size={14} aria-hidden="true" className="inline-icon" />
              View resume &amp; score
            </Button>
            <JourneyButton applicationId={item.application_id} />
            {campaign && (
              <Link className="btn btn--ghost btn--sm" to={`/campaigns/${campaign.id}`}>
                Open job
              </Link>
            )}
          </div>

          {error && <ErrorNote>{error}</ErrorNote>}
          <div className="field mt-2">
            <label htmlFor={`reason-${item.id}`}>Your reason (saved in the audit trail) *</label>
            <input
              id={`reason-${item.id}`}
              placeholder="e.g. Confirmed 4 years of Python from the resume"
              value={reason}
              onChange={(e) => setReason(e.target.value)}
            />
          </div>
          <div className="actions-grid">
            {ACTIONS.map((a) => {
              const allowed = !a.permission || hasPermission(a.permission);
              const hintId = `hint-${a.type}-${item.id}`;
              return (
                <div className="action" key={a.type}>
                  <Button
                    variant={a.variant}
                    small
                    disabled={act.isPending || !allowed || !reason.trim()}
                    aria-describedby={hintId}
                    title={!allowed ? a.lockedHint : !reason.trim() ? "Add a reason first" : undefined}
                    onClick={() => {
                      setError(null);
                      act.mutate(a);
                    }}
                  >
                    {a.label}
                  </Button>
                  <span id={hintId} className="action__hint">
                    {allowed ? a.explain : a.lockedHint}
                  </span>
                </div>
              );
            })}
          </div>
          {!reason.trim() && <p className="hint-line">Add a short reason to enable the buttons.</p>}
        </div>
      )}
    </li>
  );
}
