import { useMutation, useQuery } from "@tanstack/react-query";
import { useState, type ReactNode } from "react";

import { ApiError } from "../api/client";
import {
  listExtractedFields,
  revealCandidateContact,
  type Application,
  type CriterionResult,
  type ScreeningRun,
} from "../api/resources";
import { useAuth } from "../app/auth-context";
import { useToast } from "./toast";
import { Badge, Button, Drawer, Empty, ErrorNote, Loading, MatchBar, prettify, Spinner, toneFor } from "./ui";

type TierKey = "must_have" | "good_to_have" | "nice_to_have";

const TIER_LABELS: Record<TierKey, string> = {
  must_have: "Must Have (mandatory)",
  good_to_have: "Good to Have",
  nice_to_have: "Nice to Have",
};

/* Per-tier match percentage = awarded / max over that tier's criteria. Criteria without a
   tier are grouped under "Other". Mirrors the deterministic score the backend computed. */
function tierPercent(results: CriterionResult[], tier: TierKey | "other"): number | null {
  const inTier = results.filter((r) => (r.tier ?? "other") === tier);
  const max = inTier.reduce((s, r) => s + r.max_score, 0);
  if (inTier.length === 0 || max === 0) return null;
  const awarded = inTier.reduce((s, r) => s + r.awarded_score, 0);
  return (awarded / max) * 100;
}

function tierTone(pct: number | null): "ok" | "warn" | "danger" | "info" {
  if (pct === null) return "info";
  if (pct >= 70) return "ok";
  if (pct >= 40) return "warn";
  return "danger";
}

export function CandidateScorecardDrawer({
  app,
  run,
  onClose,
}: {
  app: Application;
  run: ScreeningRun | null;
  onClose: () => void;
}): ReactNode {
  const { hasPermission } = useAuth();
  const toast = useToast();
  const [tab, setTab] = useState<"resume" | "contact">("resume");
  const [contactError, setContactError] = useState<string | null>(null);

  const name =
    typeof app.answers["full_name"] === "string" ? (app.answers["full_name"] as string) : "Candidate";
  const results = run?.results ?? [];
  const canViewPii = hasPermission("candidate.view_pii");

  const reveal = useMutation({
    mutationFn: () => revealCandidateContact(app.candidate_id),
    onError: (e) =>
      setContactError(e instanceof ApiError ? e.message : "Could not reveal contact details."),
    onSuccess: () => toast.push("Contact details revealed — access was logged", { tone: "info" }),
  });

  // Resume-derived content: the fields extracted from the uploaded resume, with the exact
  // source span and confidence. Loaded only when the Resume tab is open.
  const fields = useQuery({
    queryKey: ["extracted-fields", app.id],
    queryFn: () => listExtractedFields(app.id),
    enabled: tab === "resume",
  });

  const tierBars: { key: TierKey; pct: number | null }[] = (
    ["must_have", "good_to_have", "nice_to_have"] as TierKey[]
  ).map((key) => ({ key, pct: tierPercent(results, key) }));

  return (
    <Drawer
      title={name}
      subtitle={
        <>
          <Badge tone={toneFor(app.state)}>{prettify(app.state)}</Badge>{" "}
          {run && <Badge tone={toneFor(run.recommendation)}>{prettify(run.recommendation)}</Badge>}
        </>
      }
      onClose={onClose}
    >
      {/* Overall score + categorised match bars */}
      {run ? (
        <>
          <div style={{ display: "flex", alignItems: "baseline", gap: 8, marginBottom: 4 }}>
            <span style={{ fontSize: "2rem", fontWeight: 700 }}>{Math.round(run.score)}</span>
            <span className="subtle">/ 100 overall fit score</span>
          </div>
          <p className="subtle" style={{ marginTop: 0, fontSize: "0.8rem" }}>
            Overall score and the tier bars below are on a 0–100 scale. The per-criterion
            table further down lists raw <strong>points</strong> (awarded / maximum weight),
            which sum into the overall score — not a second percentage.
          </p>

          {run.conflict_flagged && (
            <div className="conflict-banner" role="alert">
              ⚠️ <strong>Self-Assessment Conflict:</strong>{" "}
              {run.conflict_detail ?? "Claimed experience exceeds verified resume evidence."}{" "}
              Routed to human review — never auto-rejected.
            </div>
          )}

          {tierBars.map(({ key, pct }) =>
            pct === null ? null : (
              <MatchBar key={key} label={TIER_LABELS[key]} value={pct} tone={tierTone(pct)} />
            ),
          )}
          {tierBars.every((t) => t.pct === null) && (
            <p className="subtle">No tiered criteria on this run.</p>
          )}

          <SkillMatch results={results} />
        </>
      ) : (
        <p className="subtle">This candidate has not been screened yet.</p>
      )}

      {/* Action tabs */}
      <div className="btn-row" style={{ margin: "16px 0 12px" }}>
        <Button variant={tab === "resume" ? "primary" : "default"} small onClick={() => setTab("resume")}>
          📄 View Resume
        </Button>
        <Button variant={tab === "contact" ? "primary" : "default"} small onClick={() => setTab("contact")}>
          📞 View Contact Details
        </Button>
      </div>

      {tab === "resume" && (
        <>
          {(() => {
            const resumeField = fields.data?.find((f) => f.field_name === "resume_text");
            const resumeText = resumeField?.verified_value ?? resumeField?.extracted_value ?? "";
            const detailFields = (fields.data ?? []).filter((f) => f.field_name !== "resume_text");
            return (
              <>
                <div className="scorecard-section">
                  <h3>Resume</h3>
                  {fields.isLoading && <Loading label="Loading resume…" />}
                  {fields.error && <ErrorNote>Could not load the resume content.</ErrorNote>}
                  {fields.data && !resumeText && (
                    <Empty>
                      No readable resume text is stored for this candidate. The file may be an
                      image/scanned PDF (no text layer), or it was uploaded before resume text
                      was captured — re-run screening or re-upload to capture it.
                    </Empty>
                  )}
                  {resumeText && (
                    <pre
                      style={{
                        whiteSpace: "pre-wrap",
                        wordBreak: "break-word",
                        fontFamily: "inherit",
                        fontSize: "0.88rem",
                        lineHeight: 1.5,
                        maxHeight: 360,
                        overflowY: "auto",
                        margin: 0,
                        padding: 12,
                        background: "var(--surface-2, #f3f6fa)",
                        borderRadius: 8,
                        border: "1px solid var(--border)",
                      }}
                    >
                      {resumeText}
                    </pre>
                  )}
                </div>

                {detailFields.length > 0 && (
                  <div className="scorecard-section">
                    <h3>Key fields extracted from the resume</h3>
                    <div className="table-wrap">
                      <table className="data">
                        <thead>
                          <tr>
                            <th>Field</th>
                            <th>Value</th>
                            <th>Source span</th>
                            <th>Conf.</th>
                          </tr>
                        </thead>
                        <tbody>
                          {detailFields.map((f) => (
                            <tr key={f.id}>
                              <td>{prettify(f.field_name)}</td>
                              <td>{f.verified_value ?? f.extracted_value ?? "—"}</td>
                              <td>
                                {f.source_span ? (
                                  <span className="evidence-span">{f.source_span}</span>
                                ) : (
                                  <span className="subtle">—</span>
                                )}
                              </td>
                              <td>{Math.round(f.confidence * 100)}%</td>
                            </tr>
                          ))}
                        </tbody>
                      </table>
                    </div>
                  </div>
                )}
              </>
            );
          })()}

          <div className="scorecard-section">
            <h3>Evidence by scoring criterion</h3>
            {results.length === 0 && <p className="subtle">No criterion evidence to show.</p>}
          {(["must_have", "good_to_have", "nice_to_have", "other"] as (TierKey | "other")[]).map(
            (tier) => {
              const rows = results.filter((r) => (r.tier ?? "other") === tier);
              if (rows.length === 0) return null;
              const heading = tier === "other" ? "Other criteria" : TIER_LABELS[tier];
              return (
                <div key={tier} className="scorecard-section">
                  <h3>{heading}</h3>
                  <div className="table-wrap">
                    <table className="data">
                      <thead>
                        <tr>
                          <th>Criterion</th>
                          <th>Outcome</th>
                          <th>Evidence</th>
                          <th>Conf.</th>
                          <th>Points (awarded / max)</th>
                        </tr>
                      </thead>
                      <tbody>
                        {rows.map((r, i) => (
                          <tr key={`${r.criterion_name}-${i}`}>
                            <td>
                              {r.criterion_name}
                              {r.mandatory && <span title="Mandatory"> ★</span>}
                            </td>
                            <td>
                              <Badge tone={toneFor(r.outcome)}>{prettify(r.outcome)}</Badge>
                            </td>
                            <td>
                              {r.candidate_evidence ? (
                                <span className="evidence-span" title={r.evidence_source ?? undefined}>
                                  {r.candidate_evidence}
                                </span>
                              ) : (
                                <span className="subtle">—</span>
                              )}
                            </td>
                            <td>{r.confidence === null ? "—" : `${Math.round(r.confidence * 100)}%`}</td>
                            <td>
                              {r.awarded_score}/{r.max_score}
                            </td>
                          </tr>
                        ))}
                      </tbody>
                    </table>
                  </div>
                </div>
              );
            },
          )}
          </div>
        </>
      )}

      {tab === "contact" && (
        <div className="scorecard-section">
          <h3>Contact details</h3>
          {contactError && <ErrorNote>{contactError}</ErrorNote>}
          {!canViewPii ? (
            <p className="subtle">
              🔒 Revealing contact details needs the <strong>candidate.view_pii</strong> permission.
              Your role can see a masked profile only.
            </p>
          ) : reveal.data ? (
            <dl className="kv">
              <dt>Email</dt>
              <dd>{reveal.data.email}</dd>
              <dt>Phone</dt>
              <dd>{reveal.data.mobile ?? "—"}</dd>
              <dt>LinkedIn</dt>
              <dd>
                {reveal.data.linkedin ? (
                  <a href={reveal.data.linkedin} target="_blank" rel="noreferrer">
                    {reveal.data.linkedin}
                  </a>
                ) : (
                  "—"
                )}
              </dd>
            </dl>
          ) : (
            <>
              <p className="subtle" style={{ marginTop: 0 }}>
                Contact details are masked by default. Revealing them is recorded in the audit trail.
              </p>
              <Button
                variant="accent"
                small
                disabled={reveal.isPending}
                onClick={() => {
                  setContactError(null);
                  reveal.mutate();
                }}
              >
                {reveal.isPending ? <Spinner /> : "Unmask contact details"}
              </Button>
            </>
          )}
        </div>
      )}
    </Drawer>
  );
}

/* Categorised skill checklist derived from the JD-driven exact_skill criteria. Each skill
   shows ✓ matched (found & verified in the resume) or ✗ not confirmed (routed to review —
   never an auto-rejection), grouped by Must/Good/Nice-to-Have. */
function SkillMatch({ results }: { results: CriterionResult[] }): ReactNode {
  const skills = results.filter((r) => r.criterion_type === "exact_skill");
  if (skills.length === 0) return null;

  const tiers: { key: TierKey; label: string }[] = [
    { key: "must_have", label: TIER_LABELS.must_have },
    { key: "good_to_have", label: TIER_LABELS.good_to_have },
    { key: "nice_to_have", label: TIER_LABELS.nice_to_have },
  ];

  return (
    <div className="scorecard-section" style={{ marginTop: 16 }}>
      <h3>Skill match (from the JD)</h3>
      {tiers.map(({ key, label }) => {
        const rows = skills.filter((r) => (r.tier ?? "good_to_have") === key);
        if (rows.length === 0) return null;
        const matched = rows.filter((r) => r.outcome === "pass").length;
        return (
          <div key={key} style={{ marginBottom: 10 }}>
            <div className="subtle" style={{ fontSize: "0.82rem", marginBottom: 4 }}>
              {label} — {matched}/{rows.length} matched
            </div>
            <div className="btn-row">
              {rows.map((r, i) => {
                const ok = r.outcome === "pass";
                return (
                  <Badge key={`${r.criterion_name}-${i}`} tone={ok ? "ok" : "warn"}>
                    {ok ? "✓" : "✗"} {r.criterion_name}
                  </Badge>
                );
              })}
            </div>
          </div>
        );
      })}
      <p className="subtle" style={{ fontSize: "0.8rem", marginTop: 6 }}>
        ✗ means the skill was not confirmed in the resume — it is routed to human review, never an
        automatic rejection.
      </p>
    </div>
  );
}
