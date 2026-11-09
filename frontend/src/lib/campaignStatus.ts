/* Plain-language campaign status and setup-checklist helpers.

   The backend has ~20 lifecycle states. HR only needs to know which of a handful of
   phases a job is in, so every screen shows these labels instead of raw state names. The
   raw state stays available under Settings → Advanced for people who need it. */

import type { SetupStep } from "../api/resources";

export type StatusTone = "ok" | "warn" | "danger" | "info" | "neutral";

export type PlainStatus = {
  label: string;
  tone: StatusTone;
  /** One line explaining what this means for HR. */
  hint: string;
};

const SETTING_UP = new Set([
  "draft",
  "jd_uploaded",
  "jd_review",
  "criteria_configuration",
  "criteria_review",
  "approval_pending",
  "approved",
]);
const REVIEWING = new Set(["applications_closed", "screening", "human_review"]);
const INTERVIEWING = new Set(["interview_planning", "interviewing", "selection_review"]);

export function plainCampaignStatus(state: string): PlainStatus {
  if (SETTING_UP.has(state))
    return { label: "Setting up", tone: "warn", hint: "Not visible to candidates yet. Finish the setup steps to open it." };
  if (state === "published" || state === "applications_open")
    return { label: "Open for applications", tone: "ok", hint: "Candidates can apply using the apply link." };
  if (state === "paused")
    return { label: "Paused", tone: "warn", hint: "Applications are paused. Resume it from Settings." };
  if (REVIEWING.has(state))
    return { label: "Reviewing candidates", tone: "info", hint: "Applications are closed. Screening and review are under way." };
  if (INTERVIEWING.has(state))
    return { label: "Interviewing", tone: "info", hint: "Shortlisted candidates are being interviewed." };
  if (state === "completed") return { label: "Completed", tone: "neutral", hint: "Hiring is finished." };
  if (state === "closed") return { label: "Closed", tone: "neutral", hint: "Closed. It can be reopened from Settings." };
  if (state === "archived") return { label: "Archived", tone: "neutral", hint: "Kept for records only." };
  if (state === "cancelled") return { label: "Cancelled", tone: "danger", hint: "This hiring was stopped. Records are kept." };
  return { label: state.replace(/_/g, " "), tone: "neutral", hint: "" };
}

/** True while the job is still being set up (candidates cannot apply yet). */
export function isSettingUp(state: string): boolean {
  return SETTING_UP.has(state);
}

export type SetupProgress = {
  done: number;
  total: number;
  next: SetupStep | null;
  /** 1-based position of the next step, or null when everything is done. */
  nextNumber: number | null;
};

export function setupProgress(steps: SetupStep[]): SetupProgress {
  const done = steps.filter((s) => s.status === "done").length;
  const index = steps.findIndex((s) => s.status !== "done");
  return {
    done,
    total: steps.length,
    next: index >= 0 ? (steps[index] ?? null) : null,
    nextNumber: index >= 0 ? index + 1 : null,
  };
}

export const SETUP_STATUS_LABEL: Record<SetupStep["status"], string> = {
  done: "Done",
  todo: "To do",
  needs_approver: "Waiting for approval",
  waiting: "Do the earlier steps first",
};
