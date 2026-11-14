import { useMutation } from "@tanstack/react-query";
import { FileText, ThumbsDown, ThumbsUp } from "lucide-react";
import { useId, useState, type ReactNode } from "react";

import { sendAnswerFeedback, type AskResponse } from "../../api/automation";
import { ApiError } from "../../api/client";
import { Button } from "../ui";

/* Helpful / not helpful, with an optional comment of at most 300 characters (Req 7.1). */
function FeedbackButtons({ queryId }: { queryId: string }): ReactNode {
  const [choice, setChoice] = useState<boolean | null>(null);
  const [comment, setComment] = useState("");
  const [done, setDone] = useState(false);
  const [error, setError] = useState<string | null>(null);
  const commentId = useId();
  const send = useMutation({
    mutationFn: (helpful: boolean) =>
      sendAnswerFeedback({
        query_id: queryId,
        helpful,
        ...(comment.trim() ? { comment: comment.trim() } : {}),
      }),
    onSuccess: () => setDone(true),
    onError: (e) => setError(e instanceof ApiError ? e.message : "Could not save your feedback."),
  });
  if (done) return <p className="doc-row__meta" role="status">Thanks for the feedback.</p>;
  return (
    <div className="hr-chat__feedback">
      <span className="doc-row__meta">Was this helpful?</span>{" "}
      <Button small variant="ghost" aria-pressed={choice === true} disabled={send.isPending}
        onClick={() => { setChoice(true); send.mutate(true); }}>
        <ThumbsUp size={14} aria-hidden="true" /> Yes
      </Button>{" "}
      <Button small variant="ghost" aria-pressed={choice === false} disabled={send.isPending}
        onClick={() => setChoice(false)}>
        <ThumbsDown size={14} aria-hidden="true" /> No
      </Button>
      {choice === false && (
        <div className="field" style={{ marginTop: 8 }}>
          <label htmlFor={commentId}>What was missing? (optional)</label>
          <textarea id={commentId} rows={2} maxLength={300} value={comment}
            onChange={(e) => setComment(e.target.value)} />
          <span className="hint">{comment.length}/300 characters</span>
          <div>
            <Button small onClick={() => send.mutate(false)} disabled={send.isPending}>
              Send feedback
            </Button>
          </div>
        </div>
      )}
      {error && <p className="field-error" role="alert">{error}</p>}
    </div>
  );
}

/* One reply. Answer and quoted text are rendered as PLAIN TEXT (React escapes it); nothing
   from a policy document is ever rendered as HTML (Req 5.5). */
export function AnswerCard({
  answer,
  onSendToHr,
}: {
  answer: AskResponse;
  onSendToHr: () => void;
}): ReactNode {
  // A greeting/thanks reply is neither an answer nor a miss: plain, with no HR hand-off.
  if (answer.outcome === "greeting") {
    return (
      <div className="assistant-answer">
        <p style={{ margin: 0, whiteSpace: "pre-wrap" }}>{answer.answer}</p>
      </div>
    );
  }
  return (
    <div className={`assistant-answer ${answer.answered ? "" : "assistant-answer--none"}`}>
      <p style={{ margin: 0, whiteSpace: "pre-wrap" }}>{answer.answer}</p>
      {answer.sources.length > 0 && (
        <ul className="hr-chat__sources" aria-label="Sources">
          {answer.sources.map((s) => (
            <li key={`${s.policy_id}-${s.ref}`} className="doc-row__meta">
              <FileText size={12} aria-hidden="true" /> [{s.ref}] {s.title}, version {s.version}
              {s.page != null ? `, page ${s.page}` : ""}
            </li>
          ))}
        </ul>
      )}
      <div className="btn-row" style={{ marginTop: 8 }}>
        {answer.route_to_hr ? (
          <Button small variant="primary" onClick={onSendToHr}>Send to HR</Button>
        ) : (
          <Button small variant="ghost" onClick={onSendToHr}>Still need help? Send to HR</Button>
        )}
      </div>
      {answer.answered && answer.query_id && <FeedbackButtons queryId={answer.query_id} />}
    </div>
  );
}
