/* Review inbox helpers: plain-language reasons, waiting time, filtering and sorting.

   Pure functions so the inbox behaviour is unit-tested without rendering. */

import type { ReviewItem } from "../api/resources";

export type ReasonInfo = {
  /** Short chip label. */
  label: string;
  /** What the reviewer should do, in one line. */
  explain: string;
};

// Every reason the screening service can raise (backend ReviewReason). Wording follows the
// product rule that missing evidence is NOT proof the candidate lacks something.
export const REVIEW_REASONS: Record<string, ReasonInfo> = {
  missing_mandatory_evidence: {
    label: "Missing info",
    explain: "The resume doesn't show a must-have. It may just be unstated, so check or ask the candidate.",
  },
  unverified_value: {
    label: "Needs a check",
    explain: "A detail could not be confirmed automatically. Check it against the resume.",
  },
  low_confidence: {
    label: "Hard to read",
    explain: "Part of the resume couldn't be read reliably. Open it and confirm the details.",
  },
  conflicting_value: {
    label: "Conflicting details",
    explain: "The form and the resume disagree. Decide which is right or ask the candidate.",
  },
  borderline_score: {
    label: "Close to cut-off",
    explain: "The score is near the threshold. A person decides whether to move them forward.",
  },
  duplicate_candidate: {
    label: "Possible duplicate",
    explain: "This may be the same person as another application. Compare before acting.",
  },
  exception_request: {
    label: "Exception asked",
    explain: "Someone asked for an exception to a rule. Review the reason and decide.",
  },
  alternative_role_match: {
    label: "Other role fit",
    explain: "They may suit a different opening better. Consider suggesting it.",
  },
};

export function reasonInfo(reason: string): ReasonInfo {
  return (
    REVIEW_REASONS[reason] ?? {
      label: reason.replace(/_/g, " "),
      explain: "Flagged for a person to look at.",
    }
  );
}

const DAY_MS = 24 * 60 * 60 * 1000;

/** Whole days an item has waited (0 = raised today). Null when the time is unknown. */
export function daysWaiting(createdAt: string | null | undefined, now: Date = new Date()): number | null {
  if (!createdAt) return null;
  const t = Date.parse(createdAt);
  if (Number.isNaN(t)) return null;
  return Math.max(0, Math.floor((now.getTime() - t) / DAY_MS));
}

export function waitingLabel(days: number | null): string {
  if (days === null) return "—";
  if (days === 0) return "Today";
  return days === 1 ? "1 day" : `${days} days`;
}

/** Items waiting this many days or more are highlighted as overdue. */
export const OVERDUE_DAYS = 3;

export type InboxFilter = "all" | "overdue" | string;

export function filterInbox(items: ReviewItem[], filter: InboxFilter, now: Date = new Date()): ReviewItem[] {
  if (filter === "all") return items;
  if (filter === "overdue")
    return items.filter((i) => (daysWaiting(i.created_at, now) ?? 0) >= OVERDUE_DAYS);
  return items.filter((i) => i.reason === filter);
}

export function countByReason(items: ReviewItem[]): Map<string, number> {
  const counts = new Map<string, number>();
  for (const i of items) counts.set(i.reason, (counts.get(i.reason) ?? 0) + 1);
  return counts;
}

/** Oldest first, so the person who has waited longest is handled first. */
export function sortOldestFirst(items: ReviewItem[]): ReviewItem[] {
  return [...items].sort((a, b) => {
    const ta = a.created_at ? Date.parse(a.created_at) : Number.POSITIVE_INFINITY;
    const tb = b.created_at ? Date.parse(b.created_at) : Number.POSITIVE_INFINITY;
    return ta - tb;
  });
}
