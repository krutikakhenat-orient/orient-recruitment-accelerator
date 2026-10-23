import { useMutation, useQuery, useQueryClient } from "@tanstack/react-query";
import { useState, type ReactNode } from "react";

import { ApiError } from "../api/client";
import {
  listPendingDecisions,
  recordDecision,
  type AssessmentSummary,
  type PendingDecision,
} from "../api/resources";
import { useAuth } from "../app/auth-context";
import { useToast } from "../components/toast";
import { Badge, Button, Card, Empty, ErrorNote, Field, Loading, prettify, toneFor } from "../components/ui";

/* Hiring Decisions inbox: candidates the interview panel has assessed, now awaiting the
   final select / reject / hold. This is the handoff from the panel to the decision-maker.
   Selecting or rejecting needs hiring_decision.approve (Recruiter Admin); Hold needs only
   hiring_decision.recommend (Hiring Manager too). */

export function DecisionsPage(): ReactNode {
  const pending = useQuery({ queryKey: ["pending-decisions"], queryFn: listPendingDecisions });

  return (
    <>
      <div className="page-head">
        <h1>Hiring Decisions</h1>
        <p>
          Candidates the interview panel has assessed, waiting for a final decision. Review the
          panel&rsquo;s verdict, then select, reject, or hold. Every decision is audited and may
          trigger a candidate communication.
        </p>
      </div>

      <Card title="Awaiting a decision">
        {pending.isLoading && <Loading />}
        {pending.error && (
          <ErrorNote>Could not load pending decisions (you may lack the required role).</ErrorNote>
        )}
        {pending.data && pending.data.length === 0 && (
          <Empty>
            No candidates are awaiting a hiring decision. Candidates appear here once the interview
            panel submits their assessment.
          </Empty>
        )}
        {pending.data && pending.data.length > 0 && (
          <div style={{ display: "grid", gap: 14 }}>
            {pending.data.map((d) => (
              <DecisionCard key={d.application_id} item={d} />
            ))}
          </div>
        )}
      </Card>
    </>
  );
}

function avg(scores: AssessmentSummary["criteria_scores"]): string {
  const nums = Object.values(scores).filter((v): v is number => typeof v === "number");
  if (nums.length === 0) return "—";
  return (nums.reduce((a, b) => a + b, 0) / nums.length).toFixed(1);
}

function DecisionCard({ item }: { item: PendingDecision }): ReactNode {
  const toast = useToast();
  const qc = useQueryClient();
  const { hasPermission } = useAuth();
  const [reason, setReason] = useState("");
  const [error, setError] = useState<string | null>(null);

  const canApprove = hasPermission("hiring_decision.approve"); // select / reject
  const canRecommend = hasPermission("hiring_decision.recommend"); // hold

  const decide = useMutation({
    mutationFn: (decisionType: string) =>
      recordDecision(item.application_id, decisionType, reason.trim() || "Recorded via decisions inbox"),
    onSuccess: () => {
      void qc.invalidateQueries({ queryKey: ["pending-decisions"] });
      toast.push("Decision recorded", { tone: "ok" });
    },
    onError: (e) => setError(e instanceof ApiError ? e.message : "Could not record the decision."),
  });

  return (
    <div className="card" style={{ padding: 16 }}>
      <div className="card__head">
        <h2 style={{ margin: 0, fontSize: "1.05rem" }}>{item.candidate_name}</h2>
        <Badge tone="info">Assessed · awaiting decision</Badge>
      </div>
      {error && <ErrorNote>{error}</ErrorNote>}

      <h3 style={{ margin: "4px 0 8px", fontSize: "0.95rem" }}>Interview panel assessment</h3>
      {item.assessments.length === 0 ? (
        <p className="subtle">No assessment on record.</p>
      ) : (
        <div className="table-wrap">
          <table className="data">
            <thead>
              <tr>
                <th>Panel recommendation</th>
                <th>Avg score (1–5)</th>
                <th>Conflict</th>
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
                  <td>{a.conflict_declared ? <Badge tone="warn">Declared</Badge> : "—"}</td>
                  <td className="subtle">{a.interview_notes ?? "—"}</td>
                </tr>
              ))}
            </tbody>
          </table>
        </div>
      )}

      <Field label="Reason (recorded in the audit trail)" htmlFor={`dr-${item.application_id}`}>
        <input
          id={`dr-${item.application_id}`}
          value={reason}
          onChange={(e) => setReason(e.target.value)}
          placeholder="Why this decision?"
        />
      </Field>

      <div className="btn-row" style={{ marginTop: 8 }}>
        <Button
          variant="accent"
          small
          disabled={!canApprove || decide.isPending}
          title={canApprove ? undefined : "Selecting needs the Recruiter Admin role"}
          onClick={() => { setError(null); decide.mutate("select"); }}
        >
          ✓ Select (hire)
        </Button>
        <Button
          variant="danger"
          small
          disabled={!canApprove || decide.isPending}
          title={canApprove ? undefined : "Rejecting needs the Recruiter Admin role"}
          onClick={() => { setError(null); decide.mutate("reject"); }}
        >
          Reject
        </Button>
        <Button
          variant="default"
          small
          disabled={!canRecommend || decide.isPending}
          onClick={() => { setError(null); decide.mutate("hold"); }}
        >
          Hold
        </Button>
      </div>
      {!canApprove && canRecommend && (
        <p className="subtle" style={{ marginTop: 6 }}>
          You can recommend a hold. The final select/reject is made by a Recruiter Admin.
        </p>
      )}
    </div>
  );
}
