import { useQuery } from "@tanstack/react-query";
import { Route } from "lucide-react";
import { useState, type ReactNode } from "react";
import { Link } from "react-router-dom";

import { getFeedbackSummary, getJourney } from "../api/automation";
import { useAuth } from "../app/auth-context";
import { JourneyTracker } from "./JourneyTracker";
import { MessagePanel } from "./Messages";
import { Banner, Button, Drawer, ErrorNote, Loading, Tabs, prettify } from "./ui";

/* "Journey" button: opens a side panel showing where one candidate is in the whole process,
   what happens next, what they were sent, and what the interviewers said. */

function FeedbackBlock({ applicationId }: { applicationId: string }): ReactNode {
  const summary = useQuery({
    queryKey: ["feedback-summary", applicationId],
    queryFn: () => getFeedbackSummary(applicationId),
  });
  if (summary.isLoading) return <Loading />;
  if (summary.error || !summary.data) {
    return <ErrorNote>The interview feedback summary could not be loaded.</ErrorNote>;
  }
  const s = summary.data;
  if (s.assessments_count === 0) {
    return <p className="hint-line">No interviewer has recorded feedback for this candidate yet.</p>;
  }
  return (
    <div>
      <Banner>{s.advisory_note}</Banner>
      <p>
        <strong>{s.assessments_count}</strong> interviewer(s). They{" "}
        {s.agreement === "all_agree" ? "agree" : s.agreement === "mixed" ? "differ" : "gave one view"}:{" "}
        {Object.entries(s.recommendation_counts)
          .map(([k, v]) => `${prettify(k)} ${v}`)
          .join(", ")}
        .
      </p>
      {s.criteria.length > 0 && (
        <div className="table-wrap">
          <table className="data">
            <thead>
              <tr>
                <th>Criterion</th>
                <th>Average</th>
                <th>Lowest</th>
                <th>Highest</th>
              </tr>
            </thead>
            <tbody>
              {s.criteria.map((c) => (
                <tr key={c.name}>
                  <td>{prettify(c.name)}</td>
                  <td>{c.average}</td>
                  <td>{c.lowest}</td>
                  <td>{c.highest}</td>
                </tr>
              ))}
            </tbody>
          </table>
        </div>
      )}
      {s.notes.map((n) => (
        <div className="msg" key={n.interviewer}>
          <div className="msg__title">
            {n.interviewer}: {prettify(n.recommendation)}
          </div>
          {[n.problem_solving_notes, n.role_understanding_notes, n.interview_notes]
            .filter(Boolean)
            .map((t, i) => (
              <p className="msg__body" key={i}>
                {t}
              </p>
            ))}
        </div>
      ))}
      <p className="hint-line">{s.ai_summary_note}</p>
    </div>
  );
}

export function JourneyDrawer({
  applicationId,
  onClose,
}: {
  applicationId: string;
  onClose: () => void;
}): ReactNode {
  const { hasPermission } = useAuth();
  const [tab, setTab] = useState("journey");
  const journey = useQuery({
    queryKey: ["journey", applicationId],
    queryFn: () => getJourney(applicationId),
  });
  const data = journey.data;
  return (
    <Drawer
      title={data ? data.candidate_name : "Candidate journey"}
      subtitle={data ? `${data.role_title} · ${prettify(data.application_state)}` : undefined}
      onClose={onClose}
    >
      <p className="hint-line">
        Follow this candidate from applying to joining. Nothing here changes their status.
      </p>
      <Tabs
        label="Candidate journey sections"
        value={tab}
        onChange={setTab}
        tabs={[
          { id: "journey", label: "Journey" },
          { id: "messages", label: "Messages" },
          ...(hasPermission("candidate.view") ? [{ id: "feedback", label: "Interview feedback" }] : []),
        ]}
      />
      {journey.isLoading && <Loading label="Loading journey…" />}
      {journey.error && <ErrorNote>The journey could not be loaded. You may not have access.</ErrorNote>}
      {tab === "journey" && data && (
        <>
          <JourneyTracker journey={data} />
          <Link className="btn btn--sm" to={`/campaigns/${data.campaign_id}/candidates/${data.application_id}`}>
            Open full candidate summary
          </Link>
        </>
      )}
      {tab === "messages" && <MessagePanel applicationId={applicationId} />}
      {tab === "feedback" && <FeedbackBlock applicationId={applicationId} />}
    </Drawer>
  );
}

export function JourneyButton({ applicationId }: { applicationId: string }): ReactNode {
  const [open, setOpen] = useState(false);
  return (
    <>
      <Button
        small
        onClick={() => setOpen(true)}
        title="See every step for this candidate and what happens next"
      >
        <Route size={14} aria-hidden="true" /> Journey
      </Button>
      {open && <JourneyDrawer applicationId={applicationId} onClose={() => setOpen(false)} />}
    </>
  );
}
