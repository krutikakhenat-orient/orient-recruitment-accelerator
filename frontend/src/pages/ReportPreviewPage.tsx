import { useQuery } from "@tanstack/react-query";
import { useMemo, useState, type ReactNode } from "react";
import { Link, useNavigate, useParams } from "react-router-dom";

import {
  campaignExportPath,
  downloadCampaignExport,
  getCampaignReport,
  type CampaignReport,
  type CandidateReportRow,
} from "../api/resources";
import { useAuth } from "../app/auth-context";
import { useToast } from "../components/toast";
import { Badge, Button, Card, Empty, ErrorNote, Loading } from "../components/ui";

/* In-app preview of a campaign's HR report — the SAME data the Excel download renders
   (one shared backend model, GET /reports/campaigns/{id}/report). HR can read, search and
   scroll the table without opening Excel, then download the real .xlsx or go back.

   The preview never re-implements the report: it renders exactly the rows/columns the
   backend produced, so preview and download can never drift apart. */

function triggerBrowserDownload(blob: Blob, filename: string): void {
  const url = URL.createObjectURL(blob);
  const a = document.createElement("a");
  a.href = url;
  a.download = filename;
  document.body.appendChild(a);
  a.click();
  a.remove();
  URL.revokeObjectURL(url);
}

function scoreTone(value: number | null): "ok" | "warn" | "danger" | "neutral" {
  if (value === null) return "neutral";
  if (value >= 70) return "ok";
  if (value >= 45) return "warn";
  return "danger";
}

function ScorePill({ value }: { value: number | null }): ReactNode {
  if (value === null) return <span className="report-muted">—</span>;
  return (
    <span className={`score-pill score-pill--${scoreTone(value)}`}>{value.toFixed(0)}%</span>
  );
}

function ListCell({ items }: { items: string[] }): ReactNode {
  if (items.length === 0) return <span className="report-muted">—</span>;
  return (
    <ul className="report-cell-list">
      {items.map((s, i) => (
        <li key={`${s}-${i}`}>{s}</li>
      ))}
    </ul>
  );
}

function CandidatesTable({
  report,
  campaignId,
  query,
}: {
  report: CampaignReport;
  campaignId: string;
  query: string;
}): ReactNode {
  const rows = useMemo(() => {
    const q = query.trim().toLowerCase();
    if (!q) return report.rows;
    return report.rows.filter((r) => {
      const haystack = [
        r.candidate_name,
        r.email ?? "",
        r.phone ?? "",
        r.applied_position,
        r.status_label,
        r.relevant_skills.join(" "),
        r.key_strengths.join(" "),
        r.missing_requirements.join(" "),
      ]
        .join(" ")
        .toLowerCase();
      return haystack.includes(q);
    });
  }, [report.rows, query]);

  if (report.rows.length === 0) {
    return <Empty>No candidates have applied to this campaign yet.</Empty>;
  }
  if (rows.length === 0) {
    return <Empty>No candidates match &ldquo;{query}&rdquo;.</Empty>;
  }

  return (
    <div className="report-table-wrap fade-in">
      <table className="report">
        <thead>
          <tr>
            <th>Rank</th>
            <th>Candidate</th>
            <th>Email</th>
            <th>Contact</th>
            <th>Status</th>
            <th>Overall score</th>
            <th>JD skills match</th>
            <th>Relevant skills &amp; experience</th>
            <th>Key strengths</th>
            <th>Missing / unverified</th>
            <th>Resume</th>
            <th>Summary</th>
          </tr>
        </thead>
        <tbody>
          {rows.map((r: CandidateReportRow) => {
            const missing = [
              ...r.missing_requirements.map((m) => `Missing: ${m}`),
              ...r.unverified_requirements.map((u) => `Needs verification: ${u}`),
            ];
            return (
              <tr key={r.application_id}>
                <td className="num">{r.rank ?? "—"}</td>
                <td>{r.candidate_name}</td>
                <td>{r.email ?? <span className="report-muted">—</span>}</td>
                <td>{r.phone ?? <span className="report-muted">—</span>}</td>
                <td>
                  <Badge tone={r.manual_review_required ? "warn" : "info"}>{r.status_label}</Badge>
                </td>
                <td className="num">
                  <ScorePill value={r.overall_score} />
                </td>
                <td className="num">
                  <ScorePill value={r.jd_skills_match} />
                </td>
                <td>
                  {r.experience_summary && (
                    <div className="subtle" style={{ marginBottom: 4 }}>
                      Experience: {r.experience_summary}
                    </div>
                  )}
                  <ListCell items={r.relevant_skills} />
                </td>
                <td>
                  <ListCell items={r.key_strengths} />
                </td>
                <td>
                  <ListCell items={missing} />
                </td>
                <td>
                  {r.resume_available ? (
                    <Link to={`/resume/${r.application_id}`}>Download</Link>
                  ) : (
                    <span className="report-muted">Unavailable</span>
                  )}
                </td>
                <td>
                  <Link to={`/campaigns/${campaignId}/candidates/${r.application_id}`}>
                    View summary
                  </Link>
                </td>
              </tr>
            );
          })}
        </tbody>
      </table>
    </div>
  );
}

function SummarySheet({ report }: { report: CampaignReport }): ReactNode {
  const s = report.summary;
  const facts: [string, ReactNode][] = [
    ["Campaign", s.campaign_name],
    ["Position / role", s.position_title],
    ["Job description role", s.jd_role ?? "Not provided"],
    ["Campaign status", s.status_label],
    ["Number of openings", s.number_of_openings],
    ["Total candidates", s.total_candidates],
    ["Scored candidates", s.scored_candidates],
    ["Awaiting screening", s.unscored_candidates],
    ["Contact details", s.contact_unmasked ? "Unmasked (PII access logged)" : "Masked"],
    ["Generated at", s.generated_at],
  ];
  return (
    <div className="fade-in">
      <dl className="kv" style={{ gridTemplateColumns: "200px 1fr", rowGap: 10 }}>
        {facts.map(([k, v]) => (
          <div key={k} style={{ display: "contents" }}>
            <dt>{k}</dt>
            <dd>{v}</dd>
          </div>
        ))}
      </dl>
      <p className="subtle" style={{ marginTop: 16 }}>
        {s.score_note}
      </p>
    </div>
  );
}

export function ReportPreviewPage(): ReactNode {
  const { id = "" } = useParams();
  const navigate = useNavigate();
  const { token } = useAuth();
  const toast = useToast();
  const [sheet, setSheet] = useState<"candidates" | "summary">("candidates");
  const [query, setQuery] = useState("");
  const [downloading, setDownloading] = useState(false);
  const [error, setError] = useState<string | null>(null);

  const report = useQuery({
    queryKey: ["campaign-report", id],
    queryFn: () => getCampaignReport(id),
  });

  async function handleDownload(): Promise<void> {
    const authToken = token();
    if (!authToken) return;
    setError(null);
    setDownloading(true);
    try {
      const result = await downloadCampaignExport(id, authToken);
      if (result === null) {
        setError("This campaign could not be exported (not found or not accessible).");
        return;
      }
      triggerBrowserDownload(result.blob, `campaign-${id}-report.xlsx`);
      toast.push("Excel report downloaded.", { tone: "ok" });
    } catch (e) {
      setError(e instanceof Error ? e.message : "Could not download the Excel report.");
    } finally {
      setDownloading(false);
    }
  }

  return (
    <div className="report-page">
      <div className="page-head">
        <div className="btn-row" style={{ marginBottom: 8 }}>
          <Button variant="ghost" small onClick={() => navigate(`/campaigns/${id}`)}>
            ← Back to campaign
          </Button>
        </div>
        <h1>Campaign report preview</h1>
        <p>
          {report.data
            ? `${report.data.summary.campaign_name} · ${report.data.summary.position_title}`
            : "Loading the report…"}
        </p>
      </div>

      {report.isLoading && (
        <Card>
          <Loading label="Preparing the report…" />
        </Card>
      )}
      {report.error && (
        <Card>
          <ErrorNote>
            Could not load the report. You may not be assigned to this campaign, or it does not
            exist.
          </ErrorNote>
        </Card>
      )}

      {report.data && (
        <Card
          title={
            <span>
              Report{" "}
              <span className="subtle" style={{ fontWeight: 400 }}>
                (same data as the Excel download)
              </span>
            </span>
          }
          actions={
            <div className="btn-row">
              <a
                className="btn btn--sm"
                href={campaignExportPath(id)}
                onClick={(e) => {
                  // Prefer the authenticated blob download (the raw href would 401 without a
                  // bearer header); fall back to letting the href open only if JS is disabled.
                  e.preventDefault();
                  void handleDownload();
                }}
              >
                {downloading ? "Downloading…" : "⤓ Download Excel"}
              </a>
            </div>
          }
        >
          {error && <ErrorNote>{error}</ErrorNote>}

          <div className="sheet-tabs" role="tablist" aria-label="Report sheets">
            <button
              type="button"
              role="tab"
              aria-selected={sheet === "candidates"}
              className={`sheet-tab ${sheet === "candidates" ? "sheet-tab--active" : ""}`}
              onClick={() => setSheet("candidates")}
            >
              Candidates ({report.data.rows.length})
            </button>
            <button
              type="button"
              role="tab"
              aria-selected={sheet === "summary"}
              className={`sheet-tab ${sheet === "summary" ? "sheet-tab--active" : ""}`}
              onClick={() => setSheet("summary")}
            >
              Summary
            </button>
          </div>

          {sheet === "candidates" && (
            <>
              <div className="report-toolbar">
                <div className="report-toolbar__search">
                  <label htmlFor="report-search" className="sr-only" style={{ display: "none" }}>
                    Search candidates
                  </label>
                  <input
                    id="report-search"
                    type="search"
                    placeholder="Search by name, email, skill, status…"
                    value={query}
                    onChange={(e) => setQuery(e.target.value)}
                  />
                </div>
                <span className="subtle">
                  Overall score is the deterministic fit score; JD skills match is derived from
                  the job description&rsquo;s skill criteria.
                </span>
              </div>
              <CandidatesTable report={report.data} campaignId={id} query={query} />
            </>
          )}

          {sheet === "summary" && <SummarySheet report={report.data} />}
        </Card>
      )}
    </div>
  );
}
