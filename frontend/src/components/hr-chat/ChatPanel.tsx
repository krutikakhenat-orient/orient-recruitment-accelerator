import { useMutation } from "@tanstack/react-query";
import { useEffect, useId, useRef, useState, type ReactNode } from "react";

import { askAssistant, type AskResponse } from "../../api/automation";
import { ApiError } from "../../api/client";
import { useToast } from "../toast";
import { Banner, Button, ErrorNote, Spinner } from "../ui";
import { AnswerCard } from "./AnswerCard";
import { EscalateDialog } from "./EscalateDialog";

interface Turn {
  question: string;
  answer: AskResponse;
}

const MAX_TURNS = 10;

export const CHAT_NOTICE =
  "Answers come only from approved company HR policy. HR decides individual cases.";

/* HR policy chat. Recent turns live in this component's memory only: nothing is written to
   browser storage and the server keeps no conversation (Req 4.8). New answers are announced
   through an aria-live region and focus returns to the question box (Req 10.2). */
export function ChatPanel({
  compact = false,
  suggestions = [],
  initialQuestion,
}: {
  compact?: boolean;
  /* Example questions shown as one-click chips before the first question. */
  suggestions?: string[];
  /* Asked once on mount (e.g. from the employee home question box). */
  initialQuestion?: string;
}): ReactNode {
  const [question, setQuestion] = useState("");
  const [turns, setTurns] = useState<Turn[]>([]);
  const [error, setError] = useState<string | null>(null);
  const [escalate, setEscalate] = useState<string | null>(null);
  const inputRef = useRef<HTMLTextAreaElement>(null);
  const toast = useToast();
  const inputId = useId();
  const ask = useMutation({
    mutationFn: (q: string) => askAssistant(q),
    onSuccess: (answer, q) => {
      setError(null);
      setTurns((t) => [...t, { question: q, answer }].slice(-MAX_TURNS));
      setQuestion("");
      inputRef.current?.focus();
    },
    onError: (e) => {
      setError(
        e instanceof ApiError && e.status === 429
          ? e.message
          : e instanceof ApiError
            ? e.message
            : "The HR assistant could not be reached. Please try again in a moment.",
      );
      inputRef.current?.focus();
    },
  });
  const submit = (): void => {
    const q = question.trim();
    if (q.length >= 2 && !ask.isPending) ask.mutate(q);
  };
  const askedInitial = useRef(false);
  useEffect(() => {
    const q = initialQuestion?.trim();
    if (!q || q.length < 2 || askedInitial.current) return;
    // Defer by a tick and cancel on cleanup: React StrictMode mounts twice in development,
    // and a request started during the first mount reported to a discarded observer, which
    // left the "Looking…" spinner on forever. Only the surviving mount sends the question.
    const timer = window.setTimeout(() => {
      askedInitial.current = true;
      ask.mutate(q.slice(0, 300));
    }, 0);
    return () => window.clearTimeout(timer);
    // ask.mutate is stable for the component's lifetime; run once per initial question.
    // eslint-disable-next-line react-hooks/exhaustive-deps
  }, [initialQuestion]);
  const latest = turns.at(-1);
  return (
    <div className={`hr-chat ${compact ? "hr-chat--compact" : ""}`}>
      <p className="hint-line">{CHAT_NOTICE}</p>
      {latest?.answer.smart_search_unavailable && (
        <Banner>
          Smart search is unavailable right now, so answers use simple keyword matching from
          approved policies.
        </Banner>
      )}
      <div className="hr-chat__log">
        {turns.length === 0 && !ask.isPending && (
          <div className="hr-chat__empty">
            <p className="doc-row__meta" style={{ margin: 0 }}>
              Ask about leave, working hours, travel and other company policies.
            </p>
            {suggestions.length > 0 && (
              <div className="hr-chat__suggestions" role="group" aria-label="Example questions">
                {suggestions.map((s) => (
                  <button key={s} type="button" className="suggestion-chip"
                    onClick={() => ask.mutate(s)} disabled={ask.isPending}>
                    {s}
                  </button>
                ))}
              </div>
            )}
          </div>
        )}
        {turns.map((t, i) => (
          <div key={i} className="hr-chat__turn">
            <p className="hr-chat__question">
              <span className="sr-only">You asked: </span>
              {t.question}
            </p>
            <AnswerCard answer={t.answer} onSendToHr={() => setEscalate(t.question)} />
          </div>
        ))}
        {ask.isPending && (
          <p className="loading-row" role="status">
            <Spinner /> Looking in approved policies…
          </p>
        )}
      </div>
      {/* Screen readers hear the newest answer once, not the whole log. */}
      <div className="sr-only" aria-live="polite" role="status">
        {latest ? `Answer: ${latest.answer.answer}` : ""}
      </div>
      {error && <ErrorNote>{error}</ErrorNote>}
      <form
        className="hr-chat__form"
        onSubmit={(e) => {
          e.preventDefault();
          submit();
        }}
      >
        <label htmlFor={inputId}>Your question</label>
        <textarea
          id={inputId}
          ref={inputRef}
          rows={compact ? 2 : 3}
          maxLength={300}
          value={question}
          onChange={(e) => setQuestion(e.target.value)}
          onKeyDown={(e) => {
            if (e.key === "Enter" && !e.shiftKey) {
              e.preventDefault();
              submit();
            }
          }}
          aria-describedby={`${inputId}-hint`}
        />
        <span id={`${inputId}-hint`} className="hint">
          Press Enter to ask, Shift+Enter for a new line. Do not include personal details.
        </span>
        <div className="btn-row">
          <Button type="submit" variant="primary" small
            disabled={ask.isPending || question.trim().length < 2}>
            {ask.isPending ? "Looking…" : "Ask"}
          </Button>
          {turns.length > 0 && (
            <Button type="button" small variant="ghost" onClick={() => setTurns([])}>
              Clear conversation
            </Button>
          )}
        </div>
      </form>
      {escalate !== null && (
        <EscalateDialog
          question={escalate}
          onClose={() => setEscalate(null)}
          onSent={() => {
            setEscalate(null);
            toast.push("Sent to HR. You will see the reply under My questions to HR.", { tone: "ok" });
            inputRef.current?.focus();
          }}
        />
      )}
    </div>
  );
}
