"""Campaign Excel export (reporting module).

Builds a clean, HR-focused .xlsx workbook for ONE campaign from the SHARED campaign report
(``report_builder.build_campaign_report``) — the SAME structured data the in-app preview
renders, so the downloaded workbook and the preview always agree.

Strictly READ-ONLY with respect to scoring/ranking/persistence (the report builder only
SELECTs; it reuses ``list_ranked_for_campaign`` and never invokes the scoring engine).

Two sheets, both decision-relevant for HR:
  * "Candidates" — one row per candidate with the shared HR columns (name, real/masked
    email + phone, applied position, status, overall score, JD skills match, relevant
    skills & experience, key strengths, missing/unverified requirements, a Download Resume
    hyperlink, and a Candidate summary hyperlink). Frozen header, autofilter, sensible
    widths, status- and score-aware number formats.
  * "Summary" — campaign facts and a short legend distinguishing the overall score from the
    JD skills match.

Internal IDs (application/candidate UUIDs), raw technical metadata (rule-set/engine
versions, input hashes), and per-criterion debugging rows are intentionally NOT in the
HR workbook — the application id is only ever embedded inside the authenticated resume /
summary hyperlink targets, never shown as a column.

Contact PII: email/phone are MASKED unless the report was built with ``unmask_contact``
(caller holds candidate.view_pii, each reveal audited) — the export never decides this
itself; it renders whatever the shared report produced.

Resume + summary links: an .xlsx hyperlink cannot carry an Authorization header, so the
export emits links to authenticated SPA routes (``{app_base_url}/resume/{id}`` and
``{app_base_url}/campaigns/{campaign}/candidates/{id}``), never a storage key / public URL.
When no resume is on file the cell shows "Resume unavailable" (never a broken link).

Excel formula-injection: every string cell goes through ``_safe_cell`` (leading = + - @ tab
or CR is prefixed with a quote) so untrusted text can never execute as a formula.
"""

from __future__ import annotations

import io
import uuid
from typing import Any

from sqlalchemy.orm import Session

from app.core.config import get_settings
from app.modules.campaigns.models import Campaign
from app.modules.reporting.report_builder import (
    CampaignReport,
    CandidateReportRow,
    build_campaign_report,
)

NOT_PROVIDED = "Not provided"


def _safe_cell(value: Any) -> Any:
    """Neutralise spreadsheet-formula injection for string values.

    A cell whose text starts with '=', '+', '-', '@', or a leading tab/CR can be executed
    as a formula by Excel/Sheets. Prefix such untrusted strings with a single quote so they
    are treated as literal text. Non-string values (numbers, None) are returned unchanged.
    """
    if isinstance(value, str) and value and value[0] in ("=", "+", "-", "@", "\t", "\r"):
        return "'" + value
    return value


def _join(items: list[str], limit: int = 12) -> str:
    """Render a derived list (skills/strengths/requirements) as a readable multi-line cell.

    Each item on its own line (bullet) for readability in Excel; capped so a pathological
    criterion count cannot produce an enormous cell, with a "+N more" tail."""
    if not items:
        return NOT_PROVIDED
    shown = items[:limit]
    extra = len(items) - len(shown)
    text = "\n".join(f"• {s}" for s in shown)
    if extra > 0:
        text += f"\n(+{extra} more)"
    return text


def build_campaign_workbook_bytes(
    db: Session,
    *,
    organisation_id: uuid.UUID,
    campaign: Campaign,
    actor_id: uuid.UUID | None = None,
    unmask_contact: bool = False,
) -> bytes:
    """Build the HR .xlsx workbook for a campaign and return it as bytes.

    Read-only. ``campaign`` has already been loaded + authorised by the caller (router).
    When ``unmask_contact`` is True the shared report reveals real contact details through
    the audited path; otherwise contact stays masked.
    """
    report = build_campaign_report(
        db,
        organisation_id=organisation_id,
        campaign=campaign,
        actor_id=actor_id or uuid.uuid4(),
        unmask_contact=unmask_contact,
    )
    return workbook_bytes_from_report(report)


def workbook_bytes_from_report(report: CampaignReport) -> bytes:
    """Render a prepared ``CampaignReport`` to .xlsx bytes. Separated from data-loading so a
    caller that already holds the report (e.g. to also serve it as JSON) can render the same
    object without a second DB pass — guaranteeing preview/download consistency."""
    from openpyxl import Workbook
    from openpyxl.styles import Alignment, Font, PatternFill
    from openpyxl.utils import get_column_letter

    header_font = Font(bold=True, color="FFFFFF")
    header_fill = PatternFill("solid", fgColor="30426A")
    title_font = Font(bold=True, size=14, color="1F2A44")
    label_font = Font(bold=True)
    link_font = Font(color="2250C5", underline="single")
    wrap_top = Alignment(vertical="top", wrap_text=True)
    center = Alignment(horizontal="center", vertical="center")
    center_top = Alignment(horizontal="center", vertical="top")

    base_url = get_settings().app_base_url.rstrip("/")

    wb = Workbook()

    # ---------------------------------------------------------------- Sheet 1: Candidates --
    ws = wb.active
    ws.title = "Candidates"

    headers = [c.label for c in report.columns]
    ws.append(headers)

    # Column index lookups (1-based) for special formatting / hyperlinks.
    col_index = {c.key: i + 1 for i, c in enumerate(report.columns)}

    def cell_value_for(row: CandidateReportRow, key: str) -> Any:
        if key == "rank":
            return row.rank if row.rank is not None else NOT_PROVIDED
        if key == "candidate_name":
            return _safe_cell(row.candidate_name)
        if key == "email":
            return _safe_cell(row.email or NOT_PROVIDED)
        if key == "phone":
            return _safe_cell(row.phone or NOT_PROVIDED)
        if key == "applied_position":
            return _safe_cell(row.applied_position or NOT_PROVIDED)
        if key == "status_label":
            return _safe_cell(row.status_label)
        if key == "overall_score":
            return row.overall_score if row.overall_score is not None else NOT_PROVIDED
        if key == "jd_skills_match":
            return row.jd_skills_match if row.jd_skills_match is not None else NOT_PROVIDED
        if key == "relevant_skills":
            # Combine relevant skills with the experience summary for an HR-readable cell.
            parts = list(row.relevant_skills)
            text = _join(parts)
            if row.experience_summary:
                exp = f"Experience: {row.experience_summary}"
                text = exp if text == NOT_PROVIDED else f"{exp}\n{text}"
            return _safe_cell(text)
        if key == "key_strengths":
            return _safe_cell(_join(row.key_strengths))
        if key == "missing_requirements":
            combined = [f"Missing: {m}" for m in row.missing_requirements] + [
                f"Needs verification: {u}" for u in row.unverified_requirements
            ]
            return _safe_cell(_join(combined))
        if key in ("resume", "summary_link"):
            return ""  # hyperlink set separately below
        return ""

    for row in report.rows:
        ws.append([cell_value_for(row, c.key) for c in report.columns])
        excel_row = ws.max_row

        # Resume hyperlink → authenticated SPA route; "Resume unavailable" when none.
        rc = ws.cell(row=excel_row, column=col_index["resume"])
        if row.resume_available:
            rc.value = "Download Resume"
            rc.hyperlink = f"{base_url}/resume/{row.application_id}"
            rc.font = link_font
        else:
            rc.value = "Resume unavailable"

        # Candidate summary hyperlink → authenticated in-app summary route.
        sc = ws.cell(row=excel_row, column=col_index["summary_link"])
        sc.value = "View summary"
        sc.hyperlink = (
            f"{base_url}/campaigns/{report.summary.campaign_id}"
            f"/candidates/{row.application_id}"
        )
        sc.font = link_font

    # Header styling + freeze + autofilter.
    for cell in ws[1]:
        cell.font = header_font
        cell.fill = header_fill
        cell.alignment = Alignment(horizontal="center", vertical="center", wrap_text=True)
    ws.freeze_panes = "A2"
    last_col = get_column_letter(ws.max_column)
    ws.auto_filter.ref = f"A1:{last_col}{max(ws.max_row, 1)}"

    # Widths from the shared column definitions.
    for i, c in enumerate(report.columns, start=1):
        ws.column_dimensions[get_column_letter(i)].width = c.width

    # Numeric score columns: show as a number with a trailing %, centred. The values stay
    # numeric so HR can sort/filter them.
    for key in ("overall_score", "jd_skills_match"):
        idx = col_index[key]
        for r in ws.iter_rows(min_row=2, max_row=ws.max_row, min_col=idx, max_col=idx):
            for cell in r:
                if isinstance(cell.value, int | float):
                    cell.number_format = '0.0"%"'
                cell.alignment = center
    # Rank centred.
    ridx = col_index["rank"]
    for r in ws.iter_rows(min_row=2, max_row=ws.max_row, min_col=ridx, max_col=ridx):
        for cell in r:
            cell.alignment = center_top
    # Wrap the multi-line list columns.
    for key in ("relevant_skills", "key_strengths", "missing_requirements"):
        idx = col_index[key]
        for r in ws.iter_rows(min_row=2, max_row=ws.max_row, min_col=idx, max_col=idx):
            for cell in r:
                cell.alignment = wrap_top

    # ---------------------------------------------------------------- Sheet 2: Summary -----
    ws2 = wb.create_sheet("Summary")
    ws2["A1"] = "Campaign report summary"
    ws2["A1"].font = title_font
    ws2.append([])
    s = report.summary
    summary_rows: list[tuple[str, Any]] = [
        ("Campaign", s.campaign_name),
        ("Position / role", s.position_title),
        ("Job description role", s.jd_role or NOT_PROVIDED),
        ("Campaign status", s.status_label),
        ("Number of openings", s.number_of_openings),
        ("Total candidates", s.total_candidates),
        ("Scored candidates", s.scored_candidates),
        ("Awaiting screening", s.unscored_candidates),
        ("Contact details", "Unmasked (PII access logged)"
         if s.contact_unmasked else "Masked"),
        ("Generated at", s.generated_at),
        ("About the scores", s.score_note),
    ]
    header_at = ws2.max_row + 1
    ws2.append(["Field", "Value"])
    for label, value in summary_rows:
        ws2.append([_safe_cell(label), _safe_cell(value)])
    for cell in ws2[header_at]:
        cell.font = header_font
        cell.fill = header_fill
    for r in ws2.iter_rows(min_row=header_at + 1, max_row=ws2.max_row, max_col=1):
        for cell in r:
            cell.font = label_font
    for r in ws2.iter_rows(min_row=header_at + 1, max_row=ws2.max_row, min_col=2, max_col=2):
        for cell in r:
            cell.alignment = wrap_top
    ws2.freeze_panes = f"A{header_at + 1}"
    ws2.column_dimensions["A"].width = 24
    ws2.column_dimensions["B"].width = 72

    buffer = io.BytesIO()
    wb.save(buffer)
    return buffer.getvalue()
