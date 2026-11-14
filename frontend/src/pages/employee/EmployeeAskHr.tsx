import type { ReactNode } from "react";
import { useSearchParams } from "react-router-dom";

import { ChatPanel } from "../../components/hr-chat/ChatPanel";
import { MyHrQuestions } from "../../components/hr-chat/MyHrQuestions";

const SUGGESTIONS = [
  "How many days of annual leave do I get?",
  "What are the working hours?",
  "Can I work from home?",
  "What should I do in my first week?",
];

/* Ask HR for employees: a focused, narrow conversation column, then the replies HR sent. */
export function EmployeeAskHr(): ReactNode {
  const [params] = useSearchParams();
  const initial = params.get("q") ?? undefined;
  return (
    <div className="emp-page emp-page--narrow">
      <header className="emp-hero emp-hero--compact">
        <p className="emp-eyebrow">Ask HR</p>
        <h1 className="emp-title">How can we help?</h1>
        <p className="emp-lede">
          Quick answers from approved company policy. If it is not covered, send it to HR with
          one click.
        </p>
      </header>
      <section className="emp-panel" aria-label="Conversation">
        <ChatPanel suggestions={SUGGESTIONS} {...(initial ? { initialQuestion: initial } : {})} />
      </section>
      <section className="emp-section" aria-labelledby="mine-h">
        <h2 id="mine-h" className="emp-h2">My questions to HR</h2>
        <MyHrQuestions />
      </section>
    </div>
  );
}
