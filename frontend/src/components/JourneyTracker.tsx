import { AlertTriangle, ArrowRight, Check, Minus } from "lucide-react";
import type { ReactNode } from "react";

import type { Journey, JourneyStage } from "../api/automation";
import { Badge } from "./ui";

/* The candidate journey: every step from applying to joining, where this person is now, and
   what happens next. Read-only: it reports progress, it never decides anything. */

const STATUS_WORDS: Record<string, string> = {
  done: "Done",
  current: "Now",
  blocked: "Needs attention",
  upcoming: "Later",
  skipped: "Not used",
};

function tone(status: string): "ok" | "info" | "warn" | "neutral" {
  if (status === "done") return "ok";
  if (status === "current") return "info";
  if (status === "blocked") return "warn";
  return "neutral";
}

function Dot({ stage, index }: { stage: JourneyStage; index: number }): ReactNode {
  if (stage.status === "done") return <Check size={15} aria-hidden="true" />;
  if (stage.status === "blocked") return <AlertTriangle size={14} aria-hidden="true" />;
  if (stage.status === "skipped") return <Minus size={14} aria-hidden="true" />;
  return <span aria-hidden="true">{index + 1}</span>;
}

export function JourneyTracker({
  journey,
  actionFor,
  hideNextStep = false,
}: {
  journey: Journey;
  /** Optional button for a step (e.g. "Record decision"). Return null for no button. */
  actionFor?: (stage: JourneyStage) => ReactNode;
  /** Hide the "What happens next" line when the page already shows it. */
  hideNextStep?: boolean;
}): ReactNode {
  return (
    <div>
      {!hideNextStep && (
      <div className={`next-step ${journey.closed ? "next-step--closed" : ""}`} role="status">
        <ArrowRight size={18} aria-hidden="true" style={{ flex: "0 0 auto", marginTop: 2 }} />
        <div>
          <span className="next-step__label">{journey.closed ? "Status" : "What happens next"}</span>
          {journey.next_step}
        </div>
      </div>
      )}
      <ol className="journey" aria-label={`Journey of ${journey.candidate_name}`}>
        {journey.stages.map((stage, index) => (
          <li key={stage.key} className={`journey__item journey__item--${stage.status}`}>
            <span className="journey__dot">
              <Dot stage={stage} index={index} />
            </span>
            <div>
              <div className="journey__title">
                {stage.label}
                <Badge tone={tone(stage.status)}>{STATUS_WORDS[stage.status] ?? stage.status}</Badge>
                {stage.optional && <span className="journey__meta">Optional</span>}
              </div>
              <div className="journey__desc">{stage.description}</div>
              {stage.detail && <div className="journey__detail">{stage.detail}</div>}
              <div className="journey__meta">
                Handled by: {stage.owner}
                {stage.at ? ` · ${new Date(stage.at).toLocaleString()}` : ""}
              </div>
              {actionFor && <div className="journey__action">{actionFor(stage)}</div>}
            </div>
          </li>
        ))}
      </ol>
    </div>
  );
}
