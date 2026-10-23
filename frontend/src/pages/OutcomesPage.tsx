import { useMutation, useQuery } from "@tanstack/react-query";
import { useMemo, useState, type ReactNode } from "react";

import { ApiError } from "../api/client";
import {
  listOutcomes,
  revealCandidateContact,
  type CandidateContact,
  type DecisionOutcome,
} from "../api/resources";
import { useAuth } from "../app/auth-context";
import { useToast } from "../components/toast";
import { Badge, Button, Card, Empty, ErrorNote, Field, Loading, prettify, toneFor } from "../components/ui";

const FILTERS: { key: string; label: string; states: string[] }[] = [
  { key: "all", label: "All", states: ["selected", "rejected", "hold"] },
  { key: "selected", label: "Selected", states: ["selected"] },
  { key: "rejected", label: "Rejected", states: ["rejected"] },
  { key: "hold", label: "On hold", states: ["hold"] },
];

/* Hiring outcomes overview (Recruiter Admin): every decided candidate — selected, rejected
   or on hold — with the decision reason. Contact details are masked until an explicit,
   audited reveal (candidate.view_pii). */
export function OutcomesPage(): ReactNode {
  const outcomes = useQuery({ queryKey: ["decision-outcomes"], queryFn: listOutcomes });
  const [filter, setFilter] = useState("all");
  const [term, setTerm] = useState("");

  const activeStates = FILTERS.find((f) => f.key === filter)?.states ?? ["selected", "rejected", "hold"];
  const rows = useMemo(() => {
    const data = outcomes.data ?? [];
    return data.filter(
      (o) =>
        activeStates.includes(o.outcome) &&
        (term.trim() === "" || o.candidate_name.toLowerCase().includes(term.trim().toLowerCase())),
    );
  }, [outcomes.data, activeStates, term]);

  const counts = useMemo(() => {
    const data = outcomes.data ?? [];
    return {
      selected: data.filter((o) => o.outcome === "selected").length,
      rejected: data.filter((o) => o.outcome === "rejected").length,
      hold: data.filter((o) => o.outcome === "hold").length,
    };
  }, [outcomes.data]);

  return (
    <>
      <div className="page-head">
        <h1>Hiring Outcomes</h1>
        <p>
          Every candidate with a final decision — selected, rejected, or on hold — with the reason.
          Contact details stay masked until you reveal them; each reveal is recorded in the audit
          trail.
        </p>
      </div>

      <Card
        title="Decided candidates"
        actions={
          <div className="btn-row">
            <Badge tone="ok">{counts.selected} selected</Badge>
            <Badge tone="danger">{counts.rejected} rejected</Badge>
            <Badge tone="warn">{counts.hold} on hold</Badge>
          </div>
        }
      >
        <div className="grid grid--2" style={{ alignItems: "end", marginBottom: 12 }}>
          <Field label="Filter by outcome" htmlFor="oc-filter">
            <select id="oc-filter" value={filter} onChange={(e) => setFilter(e.target.value)}>
              {FILTERS.map((f) => (
                <option key={f.key} value={f.key}>{f.label}</option>
              ))}
            </select>
          </Field>
          <Field label="Search by name" htmlFor="oc-search">
            <input
              id="oc-search"
              value={term}
              onChange={(e) => setTerm(e.target.value)}
              placeholder="Start typing a candidate name…"
            />
          </Field>
        </div>

        {outcomes.isLoading && <Loading />}
        {outcomes.error && <ErrorNote>Could not load outcomes.</ErrorNote>}
        {outcomes.data && rows.length === 0 && (
          <Empty>No candidates match. Decisions appear here once a hiring decision is recorded.</Empty>
        )}
        {rows.length > 0 && (
          <div className="table-wrap">
            <table className="data">
              <thead>
                <tr>
                  <th>Candidate</th>
                  <th>Campaign</th>
                  <th>Outcome</th>
                  <th>Reason</th>
                  <th>Contact</th>
                </tr>
              </thead>
              <tbody>
                {rows.map((o) => (
                  <OutcomeRow key={o.application_id} item={o} />
                ))}
              </tbody>
            </table>
          </div>
        )}
      </Card>
    </>
  );
}

function OutcomeRow({ item }: { item: DecisionOutcome }): ReactNode {
  const { hasPermission } = useAuth();
  const toast = useToast();
  const [error, setError] = useState<string | null>(null);
  const canViewPii = hasPermission("candidate.view_pii");

  const reveal = useMutation({
    mutationFn: () => revealCandidateContact(item.candidate_id),
    onError: (e) => setError(e instanceof ApiError ? e.message : "Could not reveal contact."),
    onSuccess: () => toast.push("Contact revealed — access was logged", { tone: "info" }),
  });
  const contact: CandidateContact | undefined = reveal.data;

  return (
    <tr>
      <td>{item.candidate_name}</td>
      <td>{item.campaign_name}</td>
      <td>
        <Badge tone={toneFor(item.outcome)}>{prettify(item.outcome)}</Badge>
      </td>
      <td className="subtle">{item.reason ?? "—"}</td>
      <td>
        {error && <ErrorNote>{error}</ErrorNote>}
        {contact ? (
          <div style={{ fontSize: "0.85rem", lineHeight: 1.5 }}>
            <div>{contact.email}</div>
            <div>{contact.mobile ?? "—"}</div>
            {contact.linkedin && (
              <a href={contact.linkedin} target="_blank" rel="noreferrer">
                LinkedIn
              </a>
            )}
          </div>
        ) : !canViewPii ? (
          <span className="subtle">🔒 Needs candidate.view_pii</span>
        ) : (
          <Button
            variant="default"
            small
            disabled={reveal.isPending}
            onClick={() => {
              setError(null);
              reveal.mutate();
            }}
          >
            {reveal.isPending ? "Revealing…" : "Reveal contact"}
          </Button>
        )}
      </td>
    </tr>
  );
}
