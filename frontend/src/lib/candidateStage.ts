/* Where a candidate is, in plain words, and what has to happen next.

   The backend has ~18 application states. HR only needs seven stages, shown in the same
   order everywhere (campaign stage strip, candidate table, candidate page). The "next step"
   names the action, who usually does it, and where in the app it happens, so every row can
   link straight to it. Wording is outcome-oriented: it never labels a person. */

import type { StatusTone } from "./campaignStatus";

export type StageKey =
  | "applied"
  | "screened"
  | "review"
  | "shortlisted"
  | "interviewing"
  | "decision"
  | "outcome";

export interface Stage {
  key: StageKey;
  number: number;
  label: string;
  tone: StatusTone;
  /** One line explaining the stage to HR. */
  hint: string;
}

export const STAGES: Stage[] = [
  { key: "applied", number: 1, label: "Applied", tone: "neutral", hint: "Application received; screening has not run yet." },
  { key: "screened", number: 2, label: "Screened", tone: "info", hint: "Scored against the job's criteria." },
  { key: "review", number: 3, label: "Needs review", tone: "warn", hint: "A person must check something before the candidate can move on." },
  { key: "shortlisted", number: 4, label: "Shortlisted", tone: "info", hint: "Recommended for an interview. Invite them." },
  { key: "interviewing", number: 5, label: "Interviewing", tone: "info", hint: "Interview booked or under way." },
  { key: "decision", number: 6, label: "Decision", tone: "warn", hint: "Interview done. Waiting for the hiring decision." },
  { key: "outcome", number: 7, label: "Outcome", tone: "neutral", hint: "A decision has been recorded." },
];

const STATE_TO_STAGE: Record<string, StageKey> = {
  submitted: "applied",
  documents_processing: "applied",
  extraction_review: "applied",
  screened: "screened",
  manual_review: "review",
  additional_info_requested: "review",
  interview_recommended: "shortlisted",
  interview_scheduled: "interviewing",
  checked_in: "interviewing",
  // Assessed = the panel submitted feedback but has not checked the candidate out yet.
  assessed: "interviewing",
  attended: "decision",
  checked_out: "decision",
  selected: "outcome",
  rejected: "outcome",
  hold: "outcome",
  waitlisted: "outcome",
  withdrawn: "outcome",
  no_show: "outcome",
};

export function stageFor(state: string): Stage {
  const key = STATE_TO_STAGE[state] ?? "applied";
  return STAGES.find((s) => s.key === key) ?? STAGES[0]!;
}

/** Plain label for the exact state inside a stage (e.g. "Checked in" inside Interviewing). */
export function stateLabel(state: string): string {
  const labels: Record<string, string> = {
    submitted: "Received",
    documents_processing: "Reading resume",
    extraction_review: "Checking resume details",
    screened: "Screened",
    manual_review: "Needs review",
    additional_info_requested: "Waiting for candidate",
    interview_recommended: "Shortlisted",
    interview_scheduled: "Interview booked",
    checked_in: "In interview",
    attended: "Interviewed",
    assessed: "Assessed",
    checked_out: "Interview finished",
    selected: "Selected",
    rejected: "Not selected",
    hold: "On hold",
    waitlisted: "Waitlisted",
    withdrawn: "Withdrew",
    no_show: "Did not attend",
  };
  return labels[state] ?? state.replace(/_/g, " ");
}

/** Where the next step happens. "candidate" = a section of the candidate page. */
export type NextTarget =
  | { kind: "screen" }
  | { kind: "candidate"; section: CandidateSection }
  | { kind: "page"; to: string }
  | { kind: "none" };

export type CandidateSection = "next" | "score" | "interviews" | "decision" | "application";

export interface NextStep {
  text: string;
  who: string;
  /** Short button label. */
  cta: string;
  target: NextTarget;
}

export function nextStepFor(state: string, opts: { hasRun?: boolean } = {}): NextStep {
  switch (state) {
    case "submitted":
    case "documents_processing":
    case "extraction_review":
      return opts.hasRun
        ? { text: "Screening could not score this application. Check the resume details.", who: "Recruiter", cta: "Check details", target: { kind: "candidate", section: "score" } }
        : { text: "Run screening against the job's criteria.", who: "Recruiter", cta: "Run screening", target: { kind: "screen" } };
    case "screened":
      return { text: "Screened. Look at the score and decide whether to invite them to an interview.", who: "Recruiter Admin", cta: "Open candidate", target: { kind: "candidate", section: "interviews" } };
    case "manual_review":
      return { text: "Check the flagged details (missing evidence or low confidence) in the Review inbox.", who: "Recruiter", cta: "Open review", target: { kind: "page", to: "/reviews" } };
    case "additional_info_requested":
      return { text: "Waiting for the candidate to send more information.", who: "Candidate", cta: "Open candidate", target: { kind: "candidate", section: "next" } };
    case "interview_recommended":
      return { text: "Invite them to an interview: an AI voice interview, a panel interview, or both.", who: "Recruiter Admin", cta: "Invite", target: { kind: "candidate", section: "interviews" } };
    case "interview_scheduled":
      return { text: "Interview booked. The interview panel checks them in on the day.", who: "Interview panel", cta: "See interview", target: { kind: "candidate", section: "interviews" } };
    case "checked_in":
      return { text: "Interview in progress. The panel submits their assessment.", who: "Interview panel", cta: "See interview", target: { kind: "candidate", section: "interviews" } };
    case "assessed":
      return { text: "Assessment submitted. The panel checks the candidate out to finish the interview.", who: "Interview panel", cta: "See interview", target: { kind: "candidate", section: "interviews" } };
    case "attended":
    case "checked_out":
      return { text: "Read the panel's assessment and record the hiring decision.", who: "Recruiter Admin", cta: "Decide", target: { kind: "candidate", section: "decision" } };
    case "selected":
      return { text: "Selected. Prepare and send the offer.", who: "Recruiter Admin", cta: "Offers & joining", target: { kind: "page", to: "/offers" } };
    case "waitlisted":
      return { text: "On the waitlist. They can be re-checked if a place opens.", who: "Recruiter", cta: "Waitlist", target: { kind: "page", to: "/waitlist" } };
    case "hold":
      return { text: "On hold. Record a final decision when ready.", who: "Recruiter Admin", cta: "Decide", target: { kind: "candidate", section: "decision" } };
    case "no_show":
      return { text: "Did not attend the interview. Offer a new interview or record a decision.", who: "Recruiter Admin", cta: "Open candidate", target: { kind: "candidate", section: "interviews" } };
    case "rejected":
      return { text: "Closed: not selected. No further steps.", who: "—", cta: "Open candidate", target: { kind: "none" } };
    case "withdrawn":
      return { text: "Closed: the candidate withdrew.", who: "—", cta: "Open candidate", target: { kind: "none" } };
    default:
      return { text: "Open the candidate to see details.", who: "—", cta: "Open candidate", target: { kind: "none" } };
  }
}

export function candidatePath(campaignId: string, applicationId: string, section?: CandidateSection): string {
  const base = `/campaigns/${campaignId}/candidates/${applicationId}`;
  return section && section !== "next" ? `${base}#${section}` : base;
}
