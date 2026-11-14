/* Dashboard: "Your jobs, step by step".

   One row per job the signed-in user works on, showing in plain words:
     - where it stands (Setting up / Open for applications / ...),
     - whether candidates can see it yet,
     - how many setup steps are done, and the NEXT step with who does it,
     - one button that goes straight to that step.
   Data: GET /api/v1/campaigns/setup-overview (assigned jobs only; no candidate data). */

import { useQuery } from "@tanstack/react-query";
import { ArrowRight, Eye, EyeOff, Users } from "lucide-react";
import { useState, type ReactNode } from "react";
import { Link } from "react-router-dom";

import { getSetupOverview, type SetupOverviewItem } from "../api/resources";
import { useAuth } from "../app/auth-context";
import { SETUP_STATUS_LABEL, plainCampaignStatus, setupProgress } from "../lib/campaignStatus";
import { Badge, Card, Empty, ErrorNote, Loading } from "./ui";

type Filter = "setup" | "open" | "all";

const FILTER_LABEL: Record<Filter, string> = {
  setup: "Being set up",
  open: "Open to candidates",
  all: "All my jobs",
};

function isSetup(item: SetupOverviewItem): boolean {
  return item.setup.next_step_key !== null;
}

export function JobProgressCard(): ReactNode {
  const { hasPermission } = useAuth();
  const canSetUp = hasPermission("campaign.edit") || hasPermission("campaign.publish");
  const overview = useQuery({
    queryKey: ["setup-overview"],
    queryFn: getSetupOverview,
    enabled: canSetUp,
  });
  const [filter, setFilter] = useState<Filter>("setup");

  if (!canSetUp) return null;
  const items = overview.data ?? [];
  const counts: Record<Filter, number> = {
    setup: items.filter(isSetup).length,
    open: items.filter((i) => i.setup.is_open).length,
    all: items.length,
  };
  const shown = items.filter((i) =>
    filter === "all" ? true : filter === "setup" ? isSetup(i) : i.setup.is_open,
  );

  return (
    <Card
      title="Your jobs, step by step"
      description="What is done, what to do next, and whether candidates can see each job. Press the button to go straight to the next step."
      actions={
        <div className="seg" role="radiogroup" aria-label="Show jobs">
          {(Object.keys(FILTER_LABEL) as Filter[]).map((f) => (
            <button
              key={f}
              type="button"
              role="radio"
              aria-checked={filter === f}
              className="seg__btn"
              onClick={() => setFilter(f)}
            >
              {FILTER_LABEL[f]} · {counts[f]}
            </button>
          ))}
        </div>
      }
    >
      {overview.isLoading && <Loading />}
      {overview.error && <ErrorNote>Could not load your jobs.</ErrorNote>}
      {overview.data && items.length === 0 && (
        <Empty>
          You are not assigned to any job yet. Open a job from <Link to="/campaigns">Campaigns</Link>{" "}
          and choose <strong>Assign me</strong> under Settings.
        </Empty>
      )}
      {overview.data && items.length > 0 && shown.length === 0 && (
        <Empty>
          {filter === "setup"
            ? "Nothing to set up. Every job you work on is open or finished."
            : "No jobs in this view."}
        </Empty>
      )}
      {shown.length > 0 && (
        <ul className="job-progress">
          {shown.map((item) => (
            <JobRow key={item.campaign_id} item={item} />
          ))}
        </ul>
      )}
    </Card>
  );
}

function JobRow({ item }: { item: SetupOverviewItem }): ReactNode {
  const status = plainCampaignStatus(item.state);
  const progress = setupProgress(item.setup.steps);
  const pct = Math.round((progress.done / progress.total) * 100);
  const next = progress.next;
  const visible = item.setup.is_open;
  const to = `/campaigns/${item.campaign_id}`;

  return (
    <li className="job-progress__row">
      <div className="job-progress__main">
        <div className="job-progress__title">
          <Link to={to}>{item.position_title}</Link>
          <span className="subtle"> · {item.name}</span>
        </div>
        <div className="job-progress__badges">
          <Badge tone={status.tone}>{status.label}</Badge>
          <span className={`job-progress__vis job-progress__vis--${visible ? "on" : "off"}`}>
            {visible ? <Eye size={14} aria-hidden="true" /> : <EyeOff size={14} aria-hidden="true" />}
            {visible ? "Candidates can see and apply" : "Not visible to candidates yet"}
          </span>
        </div>
        <div className="job-progress__bar">
          <div
            className="progress"
            role="progressbar"
            aria-label={`Setup progress for ${item.position_title}`}
            aria-valuemin={0}
            aria-valuemax={progress.total}
            aria-valuenow={progress.done}
          >
            <div className="progress__fill" style={{ width: `${pct}%` }} />
          </div>
          <span className="subtle">
            {progress.done} of {progress.total} setup steps done
          </span>
        </div>
        <ol className="job-progress__steps" aria-label="Setup steps">
          {item.setup.steps.map((s, i) => (
            <li
              key={s.key}
              className={`job-progress__step job-progress__step--${s.status}${s.key === item.setup.next_step_key ? " job-progress__step--next" : ""}`}
              title={`${s.title}: ${SETUP_STATUS_LABEL[s.status]} (${s.who})`}
            >
              <span aria-hidden="true">{s.status === "done" ? "✓" : i + 1}</span>
              <span className="sr-only">
                Step {i + 1}, {s.title}: {SETUP_STATUS_LABEL[s.status]}.
              </span>
            </li>
          ))}
        </ol>
        {next ? (
          <p className="job-progress__next">
            <strong>
              Next ({progress.nextNumber} of {progress.total}): {next.title}
            </strong>
            <span className="subtle">
              {" "}
              · {SETUP_STATUS_LABEL[next.status]} · Who: {next.who}
            </span>
          </p>
        ) : (
          <p className="job-progress__next subtle">Setup is complete.</p>
        )}
      </div>
      <div className="job-progress__action">
        {next ? (
          <Link to={to} className="btn btn--accent btn--sm">
            {next.key === "open" ? "Open for applications" : "Continue setup"}{" "}
            <ArrowRight size={14} aria-hidden="true" className="inline-icon" />
          </Link>
        ) : (
          <Link to={to} className="btn btn--sm">
            <Users size={14} aria-hidden="true" className="inline-icon" />
            View candidates
          </Link>
        )}
      </div>
    </li>
  );
}
