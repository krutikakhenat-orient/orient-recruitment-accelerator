import { useQuery } from "@tanstack/react-query";
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
import { Badge, Card, Empty, ErrorNote, Field, Loading, Stat, prettify, toneFor } from "../components/ui";

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
      <div className="page-head">
        <h1>Welcome back</h1>
        <p>
          Signed in as {actor?.email} · {actor?.role_names.map(prettify).join(", ") || "no roles"}
        </p>
      </div>

      {isApprover && pendingCount > 0 && (
        <Card
          title="Awaiting your approval"
          actions={<Badge tone="warn">{pendingCount} pending</Badge>}
        >
          <p className="subtle" style={{ marginTop: 0 }}>
            You have {pendingCount} item{pendingCount === 1 ? "" : "s"} (Job Descriptions and/or
            rule-sets) waiting for your decision.
          </p>
          <Link to="/approvals" className="btn btn--primary btn--sm">
            Review approvals →
          </Link>
        </Card>
      )}

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

      <Card title="Principles that govern this platform">
        <ul className="subtle" style={{ margin: 0, paddingLeft: 18, lineHeight: 1.9 }}>
          <li>AI may extract and recommend — it never makes the hiring decision.</li>
          <li>Screening is deterministic, version-controlled, and reproducible.</li>
          <li>No candidate is auto-rejected on a score; low-confidence data goes to human review.</li>
          <li>Every consequential action is audited; protected attributes never affect screening.</li>
        </ul>
      </Card>
    </>
  );
}

/* HRMS Control Center: live KPI cards derived from the server's applications-by-state
   counts, plus active-campaign and open-review indicators. */
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

  return (
    <Card
      title="HRMS Control Center"
      actions={
        <div className="btn-row">
          <Badge tone="info">{activeCampaigns} open positions</Badge>
          <Badge tone={openReviewItems > 0 ? "warn" : "neutral"}>{openReviewItems} open review items</Badge>
        </div>
      }
    >
      <p className="subtle" style={{ marginTop: 0 }}>
        Live pipeline across all campaigns you can see. Counts are computed server-side from
        application states.
      </p>
      <div className="grid grid--4">
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
    <Card title="Candidate search">
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
                    <Link to={`/campaigns/${a.campaign_id}`} className="btn btn--sm">
                      Open campaign
                    </Link>
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
