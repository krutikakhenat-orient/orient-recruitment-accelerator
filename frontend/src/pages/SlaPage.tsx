import { useMutation, useQuery, useQueryClient } from "@tanstack/react-query";
import { useEffect, useState, type ReactNode } from "react";

import {
  getSlaPolicy,
  getSlaSummary,
  listSlaItems,
  runSlaCheck,
  saveSlaPolicy,
} from "../api/automation";
import { ApiError } from "../api/client";
import { useAuth } from "../app/auth-context";
import { JourneyButton } from "../components/JourneyButton";
import { useToast } from "../components/toast";
import {
  Action,
  Banner,
  Button,
  Card,
  Empty,
  ErrorNote,
  Field,
  Loading,
  PageHeader,
  Stat,
  StatusBadge,
  prettify,
} from "../components/ui";

const STATUS_WORDS: Record<string, string> = {
  on_track: "On track",
  at_risk: "Getting close",
  overdue: "Overdue",
  paused: "Waiting for candidate",
};

/* Shortlisting clock: how long each application has been waiting for a shortlisting decision,
   compared with the target. It only reports and reminds; people make the decisions. */
export function SlaPage(): ReactNode {
  const qc = useQueryClient();
  const toast = useToast();
  const { hasPermission } = useAuth();
  const canRun = hasPermission("application.review");
  const canEdit = hasPermission("campaign.approve");
  const [error, setError] = useState<string | null>(null);
  const [notes, setNotes] = useState<string[]>([]);

  const summary = useQuery({ queryKey: ["sla-summary"], queryFn: getSlaSummary });
  const items = useQuery({ queryKey: ["sla-items"], queryFn: listSlaItems });
  const policy = useQuery({ queryKey: ["sla-policy"], queryFn: getSlaPolicy });

  const [hours, setHours] = useState(48);
  const [percent, setPercent] = useState(75);
  useEffect(() => {
    if (policy.data) {
      setHours(policy.data.window_hours);
      setPercent(policy.data.at_risk_percent);
    }
  }, [policy.data]);

  const refresh = (): void => {
    void qc.invalidateQueries({ queryKey: ["sla-summary"] });
    void qc.invalidateQueries({ queryKey: ["sla-items"] });
    void qc.invalidateQueries({ queryKey: ["sla-policy"] });
  };
  const run = useMutation({
    mutationFn: runSlaCheck,
    onSuccess: (r) => {
      setError(null);
      setNotes(r.messages.length ? r.messages : ["Nothing new to report right now."]);
      toast.push("Check finished", {
        tone: "ok",
        message: `${r.reminders_recorded} reminder(s), ${r.overdue_recorded} overdue notice(s)`,
      });
    },
    onError: (e) => setError(e instanceof ApiError ? e.message : "Could not run the check."),
  });
  const save = useMutation({
    mutationFn: () => saveSlaPolicy({ window_hours: hours, at_risk_percent: percent }),
    onSuccess: () => {
      setError(null);
      toast.push("Target saved", { tone: "ok" });
      refresh();
    },
    onError: (e) => setError(e instanceof ApiError ? e.message : "Could not save the target."),
  });

  const s = summary.data;
  return (
    <>
      <PageHeader
        title="Shortlisting clock"
        description="How long each application has waited for a shortlisting decision, compared with the target. It reports and reminds; people decide."
      />
      {error && <ErrorNote>{error}</ErrorNote>}

      {s && (
        <div className="status-strip">
          <Stat label="On track" value={s.on_track} hint="Within the target" />
          <Stat label="Getting close" value={s.at_risk} hint="Needs a decision soon" />
          <Stat label="Overdue" value={s.overdue} hint="Past the target" />
          <Stat label="Waiting for candidate" value={s.paused} hint="Clock is paused" />
          <Stat label="Already decided" value={s.completed} hint="No longer waiting" />
        </div>
      )}
      {summary.isLoading && <Loading />}

      <Card
        title="Applications waiting for a decision"
        description="Most urgent first. Open a candidate's journey to see what is blocking them."
        actions={
          canRun && (
            <Action
              label="Run reminder check"
              hint="Records one reminder or overdue notice per application. Automatic scheduling is not connected yet."
              variant="primary"
              busy={run.isPending}
              onClick={() => run.mutate()}
            />
          )
        }
      >
        {notes.length > 0 && <Banner>{notes.join(" ")}</Banner>}
        {items.isLoading && <Loading />}
        {items.data && items.data.length === 0 && (
          <Empty>No applications are waiting. Nice and clear.</Empty>
        )}
        {items.data && items.data.length > 0 && (
          <div className="table-wrap">
            <table className="data">
              <thead>
                <tr>
                  <th>Candidate</th>
                  <th>Status</th>
                  <th>Time used</th>
                  <th>Time left</th>
                  <th>Stage</th>
                  <th />
                </tr>
              </thead>
              <tbody>
                {items.data.map((i) => (
                  <tr key={i.application_id}>
                    <td>{i.candidate_name}</td>
                    <td>
                      <StatusBadge status={i.status} label={STATUS_WORDS[i.status] ?? prettify(i.status)} />
                    </td>
                    <td>{i.hours_elapsed} h</td>
                    <td>{i.hours_remaining >= 0 ? `${i.hours_remaining} h` : `${Math.abs(i.hours_remaining)} h late`}</td>
                    <td>{prettify(i.state)}</td>
                    <td style={{ textAlign: "right" }}>
                      <JourneyButton applicationId={i.application_id} />
                    </td>
                  </tr>
                ))}
              </tbody>
            </table>
          </div>
        )}
        {s && <p className="hint-line" style={{ marginTop: 10 }}>{s.note}</p>}
      </Card>

      <Card
        title="The target"
        description="How many hours a recruiter has to reach a shortlisting decision, and when to warn."
      >
        <div className="field-row">
          <Field label="Hours allowed" htmlFor="sla-hours" hint="The default is 48 hours.">
            <input id="sla-hours" type="number" min={1} max={720} value={hours}
              disabled={!canEdit} onChange={(e) => setHours(Number(e.target.value))} />
          </Field>
          <Field label="Warn when this much time is used (%)" htmlFor="sla-pct"
            hint="At 75%, an application is marked 'Getting close' after 36 of 48 hours.">
            <input id="sla-pct" type="number" min={1} max={99} value={percent}
              disabled={!canEdit} onChange={(e) => setPercent(Number(e.target.value))} />
          </Field>
        </div>
        {canEdit ? (
          <Button variant="primary" small disabled={save.isPending} onClick={() => save.mutate()}>
            {save.isPending ? "Saving…" : "Save target"}
          </Button>
        ) : (
          <p className="hint-line">Only an approver can change the target.</p>
        )}
      </Card>
    </>
  );
}
