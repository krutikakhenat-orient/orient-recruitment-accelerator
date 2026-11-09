import { useQuery } from "@tanstack/react-query";
import { CheckCircle2, Flag } from "lucide-react";
import { Link } from "react-router-dom";
import { useMemo, useState, type ReactNode } from "react";

import {
  getHrDashboard,
  listApplications,
  listCampaigns,
  listPendingJdVersions,
  listPendingRuleSets,
  type Application,
} from "../api/resources";
import { useAuth } from "../app/auth-context";
import { HowItWorksCard } from "../components/FlowDiagram";
import { JourneyButton } from "../components/JourneyButton";
import {
  Badge,
  Banner,
  Card,
  Empty,
  ErrorNote,
  Field,
  Loading,
  PageHeader,
  Stat,
  prettify,
  toneFor,
} from "../components/ui";

function greeting(): string {
  const h = new Date().getHours();
  return h < 12 ? "Good morning" : h < 18 ? "Good afternoon" : "Good evening";
}

// Cities offered in the candidate search filter.
const CITIES = ["Mumbai", "Pune", "Bangalore", "Turbhe", "Delhi", "Ahmedabad"];

// Every application state that means screening has completed (the candidate is at or past
// the screening gate). "Screened" is CUMULATIVE over these so it doesn't drop to 0 once a
// candidate advances to interview/attended/decision.
const POST_SCREENING_STATES = [
  "screened",
  "manual_review",
  "additional_info_requested",
  "interview_recommended",
  "interview_scheduled",
  "attended",
  "no_show",
  "assessed",
  "selected",
  "rejected",
  "hold",
  "waitlisted",
];

// HRMS KPI cards. Each sums one or more application-state buckets from the HR dashboard
// endpoint (applications_by_state), so the counts stay server-authoritative. Buckets are
// chosen so they read sensibly to a recruiter — "Screened" is cumulative; the rest reflect
// the candidate's current stage.
const KPI_CARDS: { label: string; states: string[]; hint: string }[] = [
  { label: "Total applicants", states: ["*"], hint: "All applications" },
  { label: "Screened", states: POST_SCREENING_STATES, hint: "Completed deterministic screening" },
  { label: "In review", states: ["manual_review", "additional_info_requested"], hint: "Awaiting a human decision" },
  {
    label: "Shortlisted",
    states: ["interview_recommended", "interview_scheduled", "attended", "assessed"],
    hint: "Progressing to/through interview",
  },
  { label: "Scheduled interviews", states: ["interview_scheduled"], hint: "Slot confirmed" },
  { label: "Attended", states: ["attended", "assessed"], hint: "Interview done" },
  { label: "On hold / waitlist", states: ["hold", "waitlisted"], hint: "Parked for later" },
  { label: "Selected / closed", states: ["selected", "rejected", "no_show", "withdrawn"], hint: "Final outcomes" },
];

export function DashboardPage(): ReactNode {
  const { actor, hasPermission } = useAuth();
  const canReview = hasPermission("application.review") || hasPermission("campaign.approve");
  const isApprover = hasPermission("jd.approve") || hasPermission("rule.approve");
  const canViewCandidates = hasPermission("candidate.view");

  const dash = useQuery({
    queryKey: ["hr-dashboard"],
    queryFn: getHrDashboard,
    enabled: canReview,
  });
  const campaigns = useQuery({ queryKey: ["campaigns"], queryFn: listCampaigns });
  const pendingJds = useQuery({
    queryKey: ["pending-jds"],
    queryFn: listPendingJdVersions,
    enabled: hasPermission("jd.approve"),
  });
  const pendingRules = useQuery({
    queryKey: ["pending-rulesets"],
    queryFn: listPendingRuleSets,
    enabled: hasPermission("rule.approve"),
  });
  const pendingCount = (pendingJds.data?.length ?? 0) + (pendingRules.data?.length ?? 0);

  return (
    <>
      <PageHeader
        title={greeting()}
        description={`Signed in as ${actor?.email ?? ""} · ${actor?.role_names.map(prettify).join(", ") || "no roles"}`}
      />

      <NeedsYou
        approvals={isApprover ? pendingCount : 0}
        reviewItems={canReview ? (dash.data?.open_review_items ?? 0) : 0}
        loading={canReview && dash.isLoading}
      />
      <HowItWorksCard />
      {canReview && (
        <>
          {dash.isLoading && <Loading label="Loading dashboard…" />}
          {dash.data && (
            <HrmsControlCenter
              activeCampaigns={dash.data.active_campaigns}
              openReviewItems={dash.data.open_review_items}
              byState={dash.data.applications_by_state}
            />
          )}
          {canViewCandidates && <CandidateSearch />}
        </>
      )}

      <Card
        title="Campaigns"
        description="Your most recent job openings and where each one stands."
        actions={
          <Link to="/campaigns" className="btn btn--sm">
            View all
          </Link>
        }
      >
        {campaigns.isLoading && <Loading />}
        {campaigns.error && <ErrorNote>Could not load campaigns.</ErrorNote>}
        {campaigns.data && campaigns.data.length === 0 && (
          <Empty>No campaigns yet. Create a project and campaign to begin.</Empty>
        )}
        {campaigns.data && campaigns.data.length > 0 && (
          <div className="table-wrap">
            <table className="data">
              <thead>
                <tr>
                  <th>Campaign</th>
                  <th>Position</th>
                  <th>Openings</th>
                  <th>State</th>
                </tr>
              </thead>
              <tbody>
                {campaigns.data.slice(0, 6).map((c) => (
                  <tr key={c.id}>
                    <td>
                      <Link to={`/campaigns/${c.id}`}>{c.name}</Link>
                    </td>
                    <td>{c.position_title}</td>
                    <td>{c.number_of_openings}</td>
                    <td>
                      <Badge tone={toneFor(c.state)}>{prettify(c.state)}</Badge>
                    </td>
                  </tr>
                ))}
              </tbody>
            </table>
          </div>
        )}
      </Card>

      <Banner>
        AI may extract and recommend, but it never makes the hiring decision. Screening is deterministic and
        reproducible, and low-confidence data goes to human review.
      </Banner>
    </>
  );
}

/* "Needs you": the first thing a user sees is what is waiting on them, with a direct action. */
function NeedsYou({
  approvals,
  reviewItems,
  loading,
}: {
  approvals: number;
  reviewItems: number;
  loading: boolean;
}): ReactNode {
  const items = [
    {
      key: "approvals",
      count: approvals,
      icon: <CheckCircle2 size={16} aria-hidden="true" />,
      title: "Job descriptions and rule-sets awaiting your approval",
      meta: "Approvals need a different person from the creator",
      to: "/approvals",
      cta: "Review approvals",
    },
    {
      key: "reviews",
      count: reviewItems,
      icon: <Flag size={16} aria-hidden="true" />,
      title: "Applications waiting for a human review",
      meta: "Missing evidence, low confidence or conflicting data",
      to: "/reviews",
      cta: "Open review inbox",
    },
  ].filter((i) => i.count > 0);
  const total = items.reduce((s, i) => s + i.count, 0);

  return (
    <Card
      title={`Needs you${total > 0 ? ` · ${total}` : ""}`}
      description="Things that are waiting for you. Press the button to go straight to them."
      actions={total > 0 ? <Badge tone="warn">{total} open</Badge> : undefined}
    >
      {loading && <Loading />}
      {!loading && items.length === 0 && <Empty>You are all caught up. Nothing is waiting on you.</Empty>}
      {items.length > 0 && (
        <ul className="todo-list">
          {items.map((i) => (
            <li key={i.key} className="todo">
              <span className="todo__icon">{i.icon}</span>
              <div className="todo__body">
                <div className="todo__title">
                  {i.count} · {i.title}
                </div>
                <div className="todo__meta">{i.meta}</div>
              </div>
              <div className="todo__actions">
                <Link to={i.to} className="btn btn--primary btn--sm">
                  {i.cta}
                </Link>
              </div>
            </li>
          ))}
        </ul>
      )}
    </Card>
  );
}

/* Pipeline overview: live KPI figures from the server's applications-by-state counts, plus a
   segmented funnel (Applied → Screened → Shortlisted → Interviewed → Closed). */
function HrmsControlCenter({
  activeCampaigns,
  openReviewItems,
  byState,
}: {
  activeCampaigns: number;
  openReviewItems: number;
  byState: Record<string, number>;
}): ReactNode {
  const total = Object.values(byState).reduce((a, b) => a + b, 0);
  const countFor = (states: string[]): number =>
    states.includes("*") ? total : states.reduce((sum, s) => sum + (byState[s] ?? 0), 0);

  const funnel = [
    { label: "Applied", n: total },
    { label: "Screened", n: countFor(POST_SCREENING_STATES) },
    { label: "Shortlisted", n: countFor(["interview_recommended", "interview_scheduled", "attended", "assessed"]) },
    { label: "Interviewed", n: countFor(["attended", "assessed"]) },
    { label: "Selected", n: countFor(["selected"]) },
  ];
  const max = Math.max(1, total);

  return (
    <Card
      title="Pipeline"
      description="How many applications are at each stage across the campaigns you can see."
      actions={
        <div className="btn-row">
          <Badge tone="info">{activeCampaigns} open positions</Badge>
          <Badge tone={openReviewItems > 0 ? "warn" : "neutral"}>{openReviewItems} open review items</Badge>
        </div>
      }
    >
      <div className="funnel-grid">
        {funnel.map((f) => (
          <div key={f.label}>
            <div className="row row--between text-muted">
              <span>{f.label}</span>
              <strong>{f.n}</strong>
            </div>
            <div
              className="funnel"
              role="progressbar"
              aria-label={`${f.label}: ${f.n} of ${total}`}
              aria-valuemin={0}
              aria-valuemax={total}
              aria-valuenow={f.n}
            >
              <div className="funnel__seg" style={{ width: `${(f.n / max) * 100}%` }} />
            </div>
          </div>
        ))}
      </div>
      <div className="mb-4" />      <div className="grid grid--4">
        {KPI_CARDS.map((kpi) => (
          <Stat key={kpi.label} label={kpi.label} value={countFor(kpi.states)} hint={kpi.hint} />
        ))}
      </div>
    </Card>
  );
}
/* Candidate search / filter bar. Loads applications across visible campaigns and filters
   by candidate name (from the application's own answers) and state. Masked data only — no
   PII is shown here; contact details require the audited reveal on the scorecard. */
function CandidateSearch(): ReactNode {
  const campaigns = useQuery({ queryKey: ["campaigns"], queryFn: listCampaigns });
  const campaignIds = (campaigns.data ?? []).map((c) => c.id);

  const apps = useQuery({
    queryKey: ["all-applications", campaignIds],
    enabled: campaignIds.length > 0,
    queryFn: async () => {
      const lists = await Promise.all(campaignIds.map((id) => listApplications(id).catch(() => [])));
      return lists.flat();
    },
  });

  const [term, setTerm] = useState("");
  const [city, setCity] = useState("");

  const nameOf = (a: Application): string =>
    typeof a.answers["full_name"] === "string" ? (a.answers["full_name"] as string) : "Candidate";
  // A candidate's city comes from their application answers (the form's location field).
  const cityOf = (a: Application): string => {
    const raw = a.answers["current_location"] ?? a.answers["city"] ?? a.answers["location"];
    return typeof raw === "string" ? raw : "";
  };
  const campaignName = useMemo(() => {
    const m = new Map<string, string>();
    for (const c of campaigns.data ?? []) m.set(c.id, c.name);
    return m;
  }, [campaigns.data]);

  const filtered = (apps.data ?? []).filter((a) => {
    const matchesTerm = term.trim() === "" || nameOf(a).toLowerCase().includes(term.trim().toLowerCase());
    const matchesCity = city === "" || cityOf(a).trim().toLowerCase() === city.toLowerCase();
    return matchesTerm && matchesCity;
  });

  return (
    <Card
      title="Candidate search"
      description="Find anyone who applied. Click Journey to see where they are and what happens next."
    >
      <div className="grid grid--2" style={{ alignItems: "end" }}>
        <Field label="Search by name" htmlFor="cand-search">
          <input
            id="cand-search"
            value={term}
            onChange={(e) => setTerm(e.target.value)}
            placeholder="Start typing a candidate name…"
          />
        </Field>
        <Field label="Filter by city" htmlFor="cand-city">
          <select id="cand-city" value={city} onChange={(e) => setCity(e.target.value)}>
            <option value="">All cities</option>
            {CITIES.map((c) => (
              <option key={c} value={c}>
                {c}
              </option>
            ))}
          </select>
        </Field>
      </div>

      {apps.isLoading && <Loading />}
      {apps.data && filtered.length === 0 && (
        <Empty>No candidates match. Clear the filters or share a campaign apply link.</Empty>
      )}
      {filtered.length > 0 && (
        <div className="table-wrap">
          <table className="data">
            <thead>
              <tr>
                <th>Candidate</th>
                <th>Campaign</th>
                <th>City</th>
                <th>Status</th>
                <th />
              </tr>
            </thead>
            <tbody>
              {filtered.slice(0, 25).map((a) => (
                <tr key={a.id}>
                  <td>{nameOf(a)}</td>
                  <td>{campaignName.get(a.campaign_id) ?? a.campaign_id.slice(0, 8)}</td>
                  <td>{cityOf(a) || <span className="subtle">—</span>}</td>
                  <td>
                    <Badge tone={toneFor(a.state)}>{prettify(a.state)}</Badge>
                  </td>
                  <td style={{ textAlign: "right" }}>
                    <div className="btn-row" style={{ justifyContent: "flex-end" }}>
                      <JourneyButton applicationId={a.id} />
                      <Link to={`/campaigns/${a.campaign_id}`} className="btn btn--sm">
                        Open campaign
                      </Link>
                    </div>
                  </td>
                </tr>
              ))}
            </tbody>
          </table>
          {filtered.length > 25 && (
            <p className="subtle">Showing first 25 of {filtered.length}. Refine your search.</p>
          )}
        </div>
      )}
    </Card>
  );
}


