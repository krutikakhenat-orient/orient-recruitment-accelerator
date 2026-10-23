import { useQuery } from "@tanstack/react-query";
import type { ReactNode } from "react";

import { getManagementDashboard } from "../api/resources";
import { Badge, Card, ErrorNote, Loading, Stat, prettify, toneFor } from "../components/ui";

export function ManagementPage(): ReactNode {
  const dash = useQuery({ queryKey: ["management-dashboard"], queryFn: getManagementDashboard });

  return (
    <>
      <div className="page-head">
        <h1>Management Dashboard</h1>
        <p>
          Aggregated operational indicators. Small groups are suppressed to protect individuals, and
          no per-recruiter or per-interviewer rankings are shown.
        </p>
      </div>

      {dash.isLoading && <Loading />}
      {dash.error && <ErrorNote>Could not load the dashboard (requires approval or audit permission).</ErrorNote>}
      {dash.data && (
        <>
          <div className="grid grid--3" style={{ marginBottom: 16 }}>
            <Stat label="Open campaigns" value={dash.data.open_campaigns} />
            <Stat label="Total applications" value={dash.data.total_applications} />
            <Stat label="Selected candidates" value={dash.data.selected_candidates} hint="Suppressed if a small group" />
          </div>
          <Card title="Interview funnel">
            {Object.keys(dash.data.interview_funnel).length === 0 ? (
              <p className="subtle">No interview-stage data yet.</p>
            ) : (
              <div className="btn-row">
                {Object.entries(dash.data.interview_funnel).map(([stage, count]) => (
                  <Badge key={stage} tone={toneFor(stage)}>
                    {prettify(stage)}: {count}
                  </Badge>
                ))}
              </div>
            )}
          </Card>
        </>
      )}
    </>
  );
}
