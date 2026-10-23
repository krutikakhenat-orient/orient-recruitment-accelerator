import type { ReactNode } from "react";

/* Shared rendering for submitted application-form answers, used by both the Interview
   Panel's "Application Form" tab and the Recruiter Admin application view so they stay
   consistent. Nothing here invents or transforms data: it only formats the stored answers
   for display. Genuinely-missing values render as an explicit "Not provided" — never a
   fabricated value and never silently treated as zero. */

// Internal/technical keys that are not meaningful form answers to display.
export const HIDDEN_ANSWER_KEYS: ReadonlySet<string> = new Set([
  "privacy_consent",
  "talent_pool_consent",
  "position_applied_for",
]);

// Compensation field keys (from forms/policy.py COMPENSATION_FIELDS) that should be
// formatted as currency amounts when present.
const SALARY_KEYS: ReadonlySet<string> = new Set([
  "current_ctc",
  "current_in_hand",
  "expected_ctc",
]);

// Human labels for the known salary keys (mirrors the form field labels).
const KNOWN_LABELS: Record<string, string> = {
  current_ctc: "Current Salary (CTC)",
  current_in_hand: "In-Hand Salary",
  expected_ctc: "Expected Salary (CTC)",
};

export function prettyFieldKey(key: string): string {
  if (KNOWN_LABELS[key]) return KNOWN_LABELS[key];
  return key.replace(/_/g, " ").replace(/\b\w/g, (c) => c.toUpperCase());
}

export function isSalaryKey(key: string): boolean {
  return SALARY_KEYS.has(key);
}

/* Format an Indian-Rupee amount for display. The application collects salary as a plain
   number; we present it with the ₹ symbol and grouped digits (en-IN). Non-numeric or empty
   values are treated as "not provided" by the caller, never coerced to 0. */
export function formatSalary(value: unknown): string | null {
  if (value === null || value === undefined || value === "") return null;
  const n = typeof value === "number" ? value : Number(String(value).replace(/,/g, ""));
  if (!Number.isFinite(n)) {
    // A non-numeric salary answer (shouldn't happen for a number field) is shown verbatim.
    return String(value);
  }
  try {
    return new Intl.NumberFormat("en-IN", {
      style: "currency",
      currency: "INR",
      maximumFractionDigits: 0,
    }).format(n);
  } catch {
    return `₹${n.toLocaleString("en-IN")}`;
  }
}

/* Render a single answer value as display content. Booleans -> Yes/No; arrays (repeating
   groups like education/work history) -> a small list; salary numbers -> formatted
   currency; genuinely-missing -> an explicit "Not provided" marker. */
export function renderAnswerValue(key: string, value: unknown): ReactNode {
  const notProvided = <span className="subtle">Not provided</span>;

  if (value === true) return "Yes";
  if (value === false) return "No";
  if (value === null || value === undefined || value === "") return notProvided;

  if (isSalaryKey(key)) {
    const formatted = formatSalary(value);
    return formatted ?? notProvided;
  }

  if (Array.isArray(value)) {
    if (value.length === 0) return notProvided;
    return (
      <ul style={{ margin: 0, paddingLeft: 18 }}>
        {value.map((row, i) => (
          <li key={i}>
            {typeof row === "object" && row !== null
              ? Object.entries(row as Record<string, unknown>)
                  .filter(([, val]) => val !== "" && val != null)
                  .map(([k, val]) => `${prettyFieldKey(k)}: ${String(val)}`)
                  .join(", ")
              : String(row)}
          </li>
        ))}
      </ul>
    );
  }

  return String(value);
}

/* The salary field keys that should always be shown in the Recruiter Admin salary summary,
   in display order, even if a particular campaign's form did not collect them (in which
   case the value renders as "Not provided" rather than being hidden). */
export const SALARY_DISPLAY_KEYS: readonly string[] = [
  "current_ctc",
  "current_in_hand",
  "expected_ctc",
];
