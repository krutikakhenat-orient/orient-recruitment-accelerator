import { useMutation, useQuery } from "@tanstack/react-query";
import { useState, type ReactNode } from "react";
import { Link, useNavigate, useParams } from "react-router-dom";

import { ApiError } from "../api/client";
import {
  downloadResume,
  getApplication,
  getCampaign,
  listExtractedFields,
  listScreeningRuns,
  revealCandidateContact,
  type CriterionResult,
  type ScreeningRun,
} from "../api/resources";
import { useAuth } from "../app/auth-context";
import { useToast } from "../components/toast";
import {
  Badge,
  Button,
  Card,
  Empty,
  ErrorNote,
  Loading,
  MatchBar,
  prettify,
  toneFor,
} from "../components/ui";

/* Candidate summary dashboard — the destination of the Excel "View summary" link
   (/campaigns/:id/candidates/:applicationId) and an in-app per-candidate report.

   Reuses the EXISTING backend data + scoring: the latest saved ScreeningRun (never
   re-scored), the application form answers, resume-extracted fields, and the audited
   contact-reveal endpoint. Strengths / relevant skills / missing + unverified requirements
   are derived from the saved criterion rows with the SAME rules the Excel report uses, so
   the summary and the report agree. AI/screening output is advisory and supports human
   review — it never decides the outcome. */

function scoreTone(value: number | null): "ok" | "warn" | "danger" | "info" {
  if (value === null) return "info";
  if (value >= 70) return "ok";
  if (value >= 45) return "warn";
  return "danger";
}

/* JD skills match % — derived from the exact_skill criteria only (awarded / max). Mirrors
   report_builder.jd_skills_match on the backend so the number matches the report. */
function jdSkillsMatch(results: CriterionResult[]): number | null {
  const skill = results.filter((r) => r.criterion_type === "exact_skill");
  const max = skill.reduce((s, r) => s + r.max_score, 0);
  if (skill.length === 0 || max === 0) return null;
  const awarded = skill.reduce((s, r) => s + r.awarded_score, 0);
  return Math.round((awarded / max) * 1000) / 10;
}

function deriveCriteria(results: CriterionResult[]): {
  relevant: string[];
  strengths: string[];
  missing: string[];
  unverified: string[];
} {
  const relevant: string[] = [];
  const strengthPairs: [number, string][] = [];
  const missing: string[] = [];
  const unverified: string[] = [];
  for (const c of results) {
    const outcome = (c.outcome ?? "").toLowerCase();
    if (outcome === "pass" && c.awarded_score > 0) {
      relevant.push(c.criterion_name);
      strengthPairs.push([c.awarded_score, c.criterion_name]);
    } else if (outcome === "fail" && (c.mandatory || c.tier === "must_have")) {
      missing.push(c.criterion_name);
    } else if (outcome === "manual_review") {
      unverified.push(c.criterion_name);
    }
  }
  strengthPairs.sort((a, b) => b[0] - a[0] || a[1].localeCompare(b[1]));
  return { relevant, strengths: strengthPairs.slice(0, 5).map(([, n]) => n), missing, unverified };
}

function PillGroup({
  items,
  kind,
  emptyText,
}: {
  items: string[];
  kind: "ok" | "missing" | "review";
  emptyText: string;
}): ReactNode {
  if (items.length === 0) return <p className="subtle">{emptyText}</p>;
  const icon = kind === "ok" ? "✓" : kind === "missing" ? "✕" : "⟳";
  return (
    <div className="pill-group">
      {items.map((s, i) => (
        <span key={`${s}-${i}`} className={`evidence-pill evidence-pill--${kind}`}>
          <span aria-hidden="true">{icon}</span> {s}
        </span>
      ))}
    </div>
  );
}

function ContactCard({
  candidateId,
}: {
  candidateId: string;
}): ReactNode {
  const { hasPermission } = useAuth();
  const toast = useToast();
  const [error, setError] = useState<string | null>(null);
  const canViewPii = hasPermission("candidate.view_pii");

  const reveal = useMutation({
    mutationFn: () => revealCandidateContact(candidateId),
    onError: (e) =>
      setError(e instanceof ApiError ? e.message : "Could not reveal contact details."),
    onSuccess: () => toast.push("Contact details revealed — access was logged", { tone: "info" }),
  });

  if (!canViewPii) {
    return (
      <p className="subtle">
        Contact details are masked. The elevated <strong>candidate.view_pii</strong> permission
        is required to reveal them (every reveal is logged).
      </p>
    );
  }
  return (
    <>
      {error && <ErrorNote>{error}</ErrorNote>}
      {!reveal.data ? (
        <Button variant="default" small disabled={reveal.isPending} onClick={() => reveal.mutate()}>
          {reveal.isPending ? "Revealing…" : "Reveal contact details"}
        </Button>
      ) : (
        <dl className="kv">
          <dt>Email</dt>
          <dd>{reveal.data.email}</dd>
          <dt>Phone</dt>
          <dd>{reveal.data.mobile ?? "—"}</dd>
          <dt>LinkedIn</dt>
          <dd>{reveal.data.linkedin ?? "—"}</dd>
        </dl>
      )}
    </>
  );
}

export function CandidateSummaryPage(): ReactNode {
  const { id = "", applicationId = "" } = useParams();
  const navigate = useNavigate();
  const { token } = useAuth();
  const toast = useToast();
  const [downloadError, setDownloadError] = useState<string | null>(null);
  const [downloading, setDownloading] = useState(false);

  const app = useQuery({
    queryKey: ["application", applicationId],
    queryFn: () => getApplication(applicationId),
  });
  const campaign = useQuery({
    queryKey: ["campaign", id],
    queryFn: () => getCampaign(id),
    enabled: Boolean(id),
  });
  const runs = useQuery({
    queryKey: ["screening-runs", applicationId],
    queryFn: () => listScreeningRuns(applicationId),
  });
  const fields = useQuery({
    queryKey: ["extracted-fields", applicationId],
    queryFn: () => listExtractedFields(applicationId),
  });

  const run: ScreeningRun | null = runs.data?.[0] ?? null;
  const results = run?.results ?? [];
  const derived = deriveCriteria(results);
  const jdMatch = jdSkillsMatch(results);

  const name =
    app.data && typeof app.data.answers?.["full_name"] === "string"
      ? (app.data.answers["full_name"] as string)
      : "Candidate";

  async function handleDownloadResume(): Promise<void> {
    const authToken = token();
    if (!authToken) return;
    setDownloadError(null);
    setDownloading(true);
    try {
      const result = await downloadResume(applicationId, authToken);
      if (result === null) {
        setDownloadError("No original resume is on file for this candidate.");
        return;
      }
      const suffix = result.contentType.includes("pdf")
        ? "pdf"
        : result.contentType.includes("word")
          ? "docx"
          : result.contentType.includes("text/plain")
            ? "txt"
            : "bin";
      const url = URL.createObjectURL(result.blob);
      const a = document.createElement("a");
      a.href = url;
      a.download = `resume-${applicationId}.${suffix}`;
      document.body.appendChild(a);
      a.click();
      a.remove();
      URL.revokeObjectURL(url);
      toast.push("Resume downloaded.", { tone: "ok" });
    } catch (e) {
      setDownloadError(e instanceof Error ? e.message : "Could not download the resume.");
    } finally {
      setDownloading(false);
    }
  }

  if (app.isLoading) {
    return (
      <div className="report-page">
        <Card>
          <Loading label="Loading candidate…" />
        </Card>
      </div>
    );
  }
  if (app.error || !app.data) {
    return (
      <div className="report-page">
        <Card>
          <ErrorNote>
            Could not load this candidate. You may not be assigned to the campaign, or the
            application does not exist.
          </ErrorNote>
          <div className="btn-row" style={{ marginTop: 12 }}>
            <Button variant="ghost" small onClick={() => navigate(`/campaigns/${id}`)}>
              ← Back to campaign
            </Button>
          </div>
        </Card>
      </div>
    );
  }

  const answers = app.data.answers ?? {};
  const experience =
    (answers["total_experience_years"] as string | number | undefined) ??
    (answers["experience"] as string | undefined);
  const education = answers["education"] as string | undefined;

  return (
    <div className="report-page">
      <div className="page-head">
        <div className="btn-row" style={{ marginBottom: 8 }}>
          <Button variant="ghost" small onClick={() => navigate(`/campaigns/${id}/report`)}>
            ← Back to report
          </Button>
          <Link className="btn btn--sm btn--ghost" to={`/campaigns/${id}`}>
            Campaign
          </Link>
        </div>
        <h1>{name}</h1>
        <p>Candidate summary · supports human review — screening never auto-decides hiring.</p>
      </div>

      {/* Scores + status */}
      <Card title="Overview">
        <div className="summary-head">
          <div className="summary-scores">
            <div>
              <div className="summary-score__value">
                {run && run.score != null ? `${Math.round(run.score)}%` : "—"}
              </div>
              <div className="summary-score__label">Overall fit score</div>
            </div>
            <div>
              <div className="summary-score__value">
                {jdMatch != null ? `${jdMatch}%` : "—"}
              </div>
              <div className="summary-score__label">JD skills match</div>
            </div>
          </div>
          <div className="pill-group">
            <Badge tone={toneFor(app.data.state)}>{prettify(app.data.state)}</Badge>
            {run && <Badge tone={toneFor(run.recommendation)}>{prettify(run.recommendation)}</Badge>}
            {run?.manual_review_required && <Badge tone="warn">Manual review</Badge>}
            {run?.conflict_flagged && <Badge tone="danger">Conflict flagged</Badge>}
          </div>
        </div>
        <p className="subtle" style={{ marginTop: 12 }}>
          The overall fit score is the saved deterministic screening result (0–100%). JD skills
          match is derived from the job description&rsquo;s skill criteria only. These are
          different measures and are advisory for a human decision.
        </p>
        {runs.isLoading && <Loading label="Loading screening result…" />}
        {!runs.isLoading && !run && (
          <Empty>This candidate has not been screened yet.</Empty>
        )}
      </Card>

      <div className="grid grid--2">
        {/* Strengths & skills */}
        <Card title="Relevant skills & strengths">
          <h3>Key strengths</h3>
          <PillGroup
            items={derived.strengths}
            kind="ok"
            emptyText="No standout strengths recorded yet."
          />
          <h3 style={{ marginTop: 16 }}>Relevant skills & experience</h3>
          <PillGroup
            items={derived.relevant}
            kind="ok"
            emptyText="No confirmed skills recorded yet."
          />
          {(experience || education) && (
            <dl className="kv" style={{ marginTop: 16 }}>
              {experience != null && experience !== "" && (
                <>
                  <dt>Experience</dt>
                  <dd>{String(experience)}</dd>
                </>
              )}
              {education && (
                <>
                  <dt>Education</dt>
                  <dd>{education}</dd>
                </>
              )}
            </dl>
          )}
        </Card>

        {/* Gaps */}
        <Card title="Requirements to confirm">
          <h3>Missing mandatory requirements</h3>
          <PillGroup
            items={derived.missing}
            kind="missing"
            emptyText="No mandatory requirement was marked not-confirmed."
          />
          <h3 style={{ marginTop: 16 }}>Needs human verification</h3>
          <PillGroup
            items={derived.unverified}
            kind="review"
            emptyText="Nothing routed to review."
          />
          <p className="subtle" style={{ marginTop: 14 }}>
            Missing evidence is not proof a candidate lacks a skill — these route to a person to
            verify, never an automatic rejection.
          </p>
        </Card>
      </div>

      {/* Per-criterion match bars */}
      {run && results.length > 0 && (
        <Card title="Score breakdown by criterion">
          {results.map((r, i) => {
            const pct = r.max_score > 0 ? (r.awarded_score / r.max_score) * 100 : 0;
            return (
              <MatchBar
                key={`${r.criterion_name}-${i}`}
                label={`${r.criterion_name} — ${prettify(r.outcome)}`}
                value={pct}
                tone={scoreTone(pct)}
              />
            );
          })}
          <p className="subtle" style={{ marginTop: 10 }}>
            Bars show awarded ÷ maximum points per criterion. Reasons and evidence for each
            decision are in the candidate&rsquo;s scorecard on the campaign page.
          </p>
        </Card>
      )}

      {/* Contact + resume */}
      <div className="grid grid--2">
        <Card title="Applied position & status">
          <dl className="kv">
            <dt>Position</dt>
            <dd>{campaign.data?.position_title ?? "—"}</dd>
            <dt>Status</dt>
            <dd>
              <Badge tone={toneFor(app.data.state)}>{prettify(app.data.state)}</Badge>
            </dd>
          </dl>
        </Card>
        <Card title="Contact & resume">
          <ContactCard candidateId={app.data.candidate_id} />
          <div className="btn-row" style={{ marginTop: 14 }}>
            <Button
              variant="default"
              small
              disabled={downloading}
              onClick={() => void handleDownloadResume()}
            >
              {downloading ? "Downloading…" : "⤓ Download original resume"}
            </Button>
          </div>
          {downloadError && (
            <p className="subtle" style={{ marginTop: 8 }}>
              {downloadError}
            </p>
          )}
          {fields.isLoading && <Loading label="Loading resume fields…" />}
        </Card>
      </div>
    </div>
  );
}
