import { useMutation, useQuery, useQueryClient } from "@tanstack/react-query";
import { useState, type ReactNode } from "react";

import { ApiError } from "../api/client";
import {
  getPanelDashboard,
  recordAttendance,
  submitAssessment,
  type PanelInterview,
} from "../api/resources";
import { useToast } from "../components/toast";
import { Badge, Button, Card, Empty, ErrorNote, Field, Loading } from "../components/ui";

/* Interview Panel view. The panel owns the candidate end-to-end once an interview is
   scheduled: they confirm attendance, then submit a structured assessment. They never see
   screening scores or other candidates' records. A small dashboard shows how many
   interviews are pending (to attend / to assess) and completed from their side. */

const RECOMMENDATIONS = [
  { value: "proceed", label: "Proceed" },
  { value: "hold", label: "Hold" },
  { value: "do_not_proceed", label: "Do not proceed" },
];

export function AssessmentsPage(): ReactNode {
  const dash = useQuery({ queryKey: ["panel-dashboard"], queryFn: getPanelDashboard });

  const toAttend = dash.data?.interviews.filter((i) => i.stage === "to_attend") ?? [];
  const toAssess = dash.data?.interviews.filter((i) => i.stage === "to_assess") ?? [];

  return (
    <>
      <div className="page-head">
        <h1>My Assigned Interviews</h1>
        <p>
          Confirm whether each candidate attended, then record your assessment — a
          recommendation and your notes. You do not see screening scores; your verdict is one
          input the hiring team weighs.
        </p>
      </div>

      {/* Panel KPI cards: pending vs completed from this panel's side. */}
      <div className="kpi-row" style={{ display: "flex", gap: 12, flexWrap: "wrap", marginBottom: 16 }}>
        <KpiCard label="To confirm attendance" value={dash.data?.to_attend ?? 0} tone="warn" />
        <KpiCard label="To assess" value={dash.data?.to_assess ?? 0} tone="info" />
        <KpiCard label="Completed" value={dash.data?.completed ?? 0} tone="ok" />
        <KpiCard label="Total assigned" value={dash.data?.total ?? 0} tone="neutral" />
      </div>

      {dash.isLoading && <Loading />}
      {dash.error && <ErrorNote>Could not load your interview list.</ErrorNote>}

      <Card title="Awaiting attendance confirmation">
        {toAttend.length === 0 ? (
          <Empty>No interviews waiting for you to confirm attendance.</Empty>
        ) : (
          <div className="table-wrap">
            <table className="data">
              <thead>
                <tr>
                  <th>Candidate</th>
                  <th>Did they attend?</th>
                </tr>
              </thead>
              <tbody>
                {toAttend.map((i) => (
                  <AttendanceRow key={i.application_id} item={i} />
                ))}
              </tbody>
            </table>
          </div>
        )}
      </Card>

      <Card title="Awaiting your assessment">
        {toAssess.length === 0 ? (
          <Empty>
            No candidates are waiting for an assessment right now. A candidate appears here once
            you confirm they attended.
          </Empty>
        ) : (
          <div style={{ display: "grid", gap: 14 }}>
            {toAssess.map((a) => (
              <AssessmentForm key={a.application_id} item={a} />
            ))}
          </div>
        )}
      </Card>
    </>
  );
}

function KpiCard({ label, value, tone }: { label: string; value: number; tone: "ok" | "warn" | "info" | "neutral" }): ReactNode {
  return (
    <div className="card" style={{ padding: "12px 16px", minWidth: 150, flex: "1 1 150px" }}>
      <div style={{ fontSize: "1.8rem", fontWeight: 700 }}>{value}</div>
      <div className="subtle" style={{ fontSize: "0.85rem" }}>
        <Badge tone={tone}>{label}</Badge>
      </div>
    </div>
  );
}

function AttendanceRow({ item }: { item: PanelInterview }): ReactNode {
  const toast = useToast();
  const qc = useQueryClient();
  const [error, setError] = useState<string | null>(null);

  const mark = useMutation({
    mutationFn: (attended: boolean) => {
      if (!item.invitation_id) throw new Error("No interview invitation found for this candidate.");
      return recordAttendance(item.invitation_id, attended);
    },
    onSuccess: (_d, attended) => {
      void qc.invalidateQueries({ queryKey: ["panel-dashboard"] });
      toast.push(attended ? "Marked attended" : "Marked no-show", { tone: "ok" });
    },
    onError: (e) => setError(e instanceof ApiError ? e.message : "Could not record attendance."),
  });

  return (
    <tr>
      <td><strong>{item.candidate_name}</strong></td>
      <td>
        {error && <ErrorNote>{error}</ErrorNote>}
        <div className="btn-row">
          <Button variant="accent" small disabled={mark.isPending} onClick={() => { setError(null); mark.mutate(true); }}>
            ✓ Attended
          </Button>
          <Button variant="default" small disabled={mark.isPending} onClick={() => { setError(null); mark.mutate(false); }}>
            No-show
          </Button>
        </div>
      </td>
    </tr>
  );
}

// The interviewer scorecard skills, each rated 1–5 (from the Interviewer Assessment Form).
const RATING_SKILLS: { key: string; label: string }[] = [
  { key: "communication", label: "Communication Skills" },
  { key: "confidence_poise", label: "Confidence & Poise" },
  { key: "technical", label: "Technical Knowledge" },
  { key: "problem_solving", label: "Problem Solving Ability" },
  { key: "role_understanding", label: "Understanding of Role/Industry" },
  { key: "decision_making", label: "Decision Making" },
  { key: "attitude", label: "Attitude & Enthusiasm" },
  { key: "willingness_to_learn", label: "Willingness to Learn" },
];

function AssessmentForm({ item }: { item: PanelInterview }): ReactNode {
  const toast = useToast();
  const qc = useQueryClient();
  const [error, setError] = useState<string | null>(null);
  const [recommendation, setRecommendation] = useState("");
  const [scores, setScores] = useState<Record<string, number>>(
    Object.fromEntries(RATING_SKILLS.map((s) => [s.key, 3])),
  );
  const [notes, setNotes] = useState("");
  const [conflict, setConflict] = useState(false);
  const [conflictDetail, setConflictDetail] = useState("");

  const setScore = (key: string, value: number): void =>
    setScores((prev) => ({ ...prev, [key]: value }));

  const submit = useMutation({
    mutationFn: () =>
      submitAssessment({
        application_id: item.application_id,
        recommendation,
        criteria_scores: scores,
        interview_notes: notes.trim() || null,
        conflict_declared: conflict,
        conflict_detail: conflict ? conflictDetail.trim() : null,
      }),
    onSuccess: () => {
      void qc.invalidateQueries({ queryKey: ["panel-dashboard"] });
      toast.push("Assessment submitted", { tone: "ok" });
    },
    onError: (e) => setError(e instanceof ApiError ? e.message : "Could not submit the assessment."),
  });

  const valid = recommendation !== "" && (!conflict || conflictDetail.trim() !== "");

  return (
    <div className="card" style={{ padding: 16 }}>
      <div className="card__head">
        <h2 style={{ margin: 0, fontSize: "1.05rem" }}>{item.candidate_name}</h2>
        <Badge tone="info">Interviewed</Badge>
      </div>
      {error && <ErrorNote>{error}</ErrorNote>}

      <p className="subtle" style={{ marginTop: 0 }}>
        Rate each skill on a scale of 1 (low) to 5 (high).
      </p>
      <div className="grid grid--2">
        {RATING_SKILLS.map((s) => (
          <Field key={s.key} label={`${s.label} (1–5)`} htmlFor={`${s.key}-${item.application_id}`}>
            <input
              id={`${s.key}-${item.application_id}`}
              type="number"
              min={1}
              max={5}
              value={scores[s.key]}
              onChange={(e) => setScore(s.key, Number(e.target.value))}
            />
          </Field>
        ))}
      </div>

      <Field label="Recommendation" htmlFor={`rec-${item.application_id}`}>
        <select id={`rec-${item.application_id}`} value={recommendation} onChange={(e) => setRecommendation(e.target.value)}>
          <option value="">Choose…</option>
          {RECOMMENDATIONS.map((r) => (
            <option key={r.value} value={r.value}>{r.label}</option>
          ))}
        </select>
      </Field>

      <Field label="Remarks / any other feedback (optional)" htmlFor={`notes-${item.application_id}`}>
        <textarea
          id={`notes-${item.application_id}`}
          rows={3}
          value={notes}
          onChange={(e) => setNotes(e.target.value)}
          placeholder="What stood out, strengths, concerns"
        />
      </Field>

      <div className="checkbox-row">
        <input id={`conf-${item.application_id}`} type="checkbox" checked={conflict} onChange={(e) => setConflict(e.target.checked)} />
        <label htmlFor={`conf-${item.application_id}`}>I have a conflict of interest with this candidate</label>
      </div>
      {conflict && (
        <Field label="Conflict detail (required)" htmlFor={`cd-${item.application_id}`}>
          <input id={`cd-${item.application_id}`} value={conflictDetail} onChange={(e) => setConflictDetail(e.target.value)} placeholder="Briefly describe the conflict" />
        </Field>
      )}

      <div className="btn-row" style={{ marginTop: 8, alignItems: "center" }}>
        <Button
          variant="primary"
          small
          disabled={!valid || submit.isPending}
          title={valid ? undefined : "Choose a recommendation first (and a conflict detail if a conflict is declared)"}
          onClick={() => { setError(null); submit.mutate(); }}
        >
          {submit.isPending ? "Submitting…" : "Submit assessment"}
        </Button>
        {recommendation === "" && (
          <span className="subtle">Choose a recommendation above to enable submit.</span>
        )}
        {conflict && conflictDetail.trim() === "" && (
          <span className="subtle">A conflict detail is required.</span>
        )}
      </div>
    </div>
  );
}
