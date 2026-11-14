import { useQuery } from "@tanstack/react-query";
import { ArrowRight, Award, BookOpen, CheckCircle2, Circle, Lock, PlayCircle } from "lucide-react";
import { useId, useState, type ReactNode } from "react";
import { Link, useNavigate } from "react-router-dom";

import { listPolicies } from "../../api/automation";
import { getInductionStatus } from "../../api/resources";
import { Loading } from "../../components/ui";

type StepState = "done" | "todo" | "locked";

interface Step {
  icon: ReactNode;
  title: string;
  detail: string;
  state: StepState;
  to: string;
  action: string;
}

const STATE_TEXT: Record<StepState, string> = { done: "Done", todo: "To do", locked: "Locked" };

function StepRow({ step, index }: { step: Step; index: number }): ReactNode {
  const mark = step.state === "done"
    ? <CheckCircle2 size={20} aria-hidden="true" />
    : step.state === "locked" ? <Lock size={18} aria-hidden="true" /> : <Circle size={20} aria-hidden="true" />;
  return (
    <li className={`emp-step emp-step--${step.state}`}>
      <span className="emp-step__mark">{mark}</span>
      <div className="emp-step__body">
        <p className="emp-step__title">
          <span className="sr-only">Step {index + 1}: </span>
          {step.icon}
          {step.title}
        </p>
        <p className="emp-step__detail">{step.detail}</p>
      </div>
      <span className="emp-step__state">{STATE_TEXT[step.state]}</span>
      {step.state !== "locked" && (
        <Link to={step.to} className={`btn btn--sm ${step.state === "todo" ? "btn--primary" : ""}`}>
          {step.action}
        </Link>
      )}
    </li>
  );
}

const SUGGESTIONS = [
  "How many days of annual leave do I get?",
  "What are the working hours?",
  "What should I do in my first week?",
];

/* Employee home: one message ("here is what to do"), a short checklist with live status,
   and a question box that opens Ask HR with the answer. */
export function EmployeeHome(): ReactNode {
  const navigate = useNavigate();
  const inputId = useId();
  const [q, setQ] = useState("");
  const induction = useQuery({ queryKey: ["induction-status"], queryFn: getInductionStatus });
  const policies = useQuery({ queryKey: ["policies"], queryFn: listPolicies });

  const published = (policies.data ?? []).filter((p) => p.status === "approved");
  const read = published.filter((p) => p.acknowledged).length;
  const watched = induction.data?.completed ?? false;

  const steps: Step[] = [
    {
      icon: <PlayCircle size={16} aria-hidden="true" />,
      title: "Watch the induction video",
      detail: induction.data?.has_video === false
        ? "The video is not available yet. Please check back later."
        : watched ? "Completed. You can watch it again any time." : "About the company and how things work.",
      state: watched ? "done" : "todo",
      to: "/induction",
      action: watched ? "Watch again" : "Watch now",
    },
    {
      icon: <Award size={16} aria-hidden="true" />,
      title: "Get your certificate",
      detail: watched ? "Download or print it." : "Unlocks after you watch the whole video.",
      state: watched ? "done" : "locked",
      to: "/induction",
      action: "Open certificate",
    },
    {
      icon: <BookOpen size={16} aria-hidden="true" />,
      title: "Read the company policies",
      detail: published.length === 0
        ? "No policies have been published yet."
        : `${read} of ${published.length} read.`,
      state: published.length > 0 && read === published.length ? "done" : "todo",
      to: "/policies",
      action: read === published.length && published.length > 0 ? "Review" : "Read now",
    },
  ];
  const doneCount = steps.filter((s) => s.state === "done").length;

  const go = (text: string): void => {
    const t = text.trim();
    if (t.length >= 2) navigate(`/ask-hr?q=${encodeURIComponent(t.slice(0, 300))}`);
  };

  return (
    <div className="emp-page">
      <header className="emp-hero">
        <p className="emp-eyebrow">Your first days</p>
        <h1 className="emp-title">Welcome to Orient</h1>
        <p className="emp-lede">Three things to do, in your own time. Ask HR anything along the way.</p>
      </header>

      <section aria-labelledby="steps-h" className="emp-section">
        <div className="emp-section__head">
          <h2 id="steps-h" className="emp-h2">Getting started</h2>
          <span className="emp-progress" aria-label={`${doneCount} of ${steps.length} steps done`}>
            {doneCount} of {steps.length} done
          </span>
        </div>
        {induction.isLoading || policies.isLoading ? (
          <Loading label="Loading your progress…" />
        ) : (
          <ol className="emp-steps">
            {steps.map((s, i) => <StepRow key={s.title} step={s} index={i} />)}
          </ol>
        )}
      </section>

      <section aria-labelledby="ask-h" className="emp-section emp-ask">
        <h2 id="ask-h" className="emp-h2">Have a question?</h2>
        <p className="emp-muted">Answers come from approved company policy, with the policy they came from.</p>
        <form className="emp-ask__form" onSubmit={(e) => { e.preventDefault(); go(q); }}>
          <label htmlFor={inputId} className="sr-only">Your question for HR</label>
          <input id={inputId} value={q} maxLength={300} onChange={(e) => setQ(e.target.value)}
            placeholder="For example: how many days of annual leave do I get?" />
          <button type="submit" className="btn btn--primary" disabled={q.trim().length < 2}>
            Ask <ArrowRight size={16} aria-hidden="true" />
          </button>
        </form>
        <div className="hr-chat__suggestions" role="group" aria-label="Example questions">
          {SUGGESTIONS.map((s) => (
            <button key={s} type="button" className="suggestion-chip" onClick={() => go(s)}>{s}</button>
          ))}
        </div>
      </section>
    </div>
  );
}
