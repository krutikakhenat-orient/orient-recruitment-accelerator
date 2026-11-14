import { useMutation } from "@tanstack/react-query";
import { useId, useRef, useState, type ReactNode } from "react";

import { escalateToHr } from "../../api/automation";
import { ApiError } from "../../api/client";
import { Button, ErrorNote, Field, Modal } from "../ui";

function newKey(): string {
  const c = globalThis.crypto as Crypto | undefined;
  if (c && "randomUUID" in c) return c.randomUUID();
  return `k-${Date.now()}-${Math.random().toString(36).slice(2)}`;
}

/* "Send to HR": creates ONE HR question per dialog, even if the button is pressed twice or
   the request is retried (idempotency key). Req 7.2, 7.5. */
export function EscalateDialog({
  question,
  onClose,
  onSent,
}: {
  question: string;
  onClose: () => void;
  onSent: () => void;
}): ReactNode {
  const [text, setText] = useState(question.slice(0, 300));
  const [contact, setContact] = useState<"in_app" | "email">("in_app");
  const [error, setError] = useState<string | null>(null);
  const key = useRef(newKey());
  const idBase = useId();
  const send = useMutation({
    mutationFn: () => escalateToHr({ question: text.trim(), contact_preference: contact }, key.current),
    onSuccess: onSent,
    onError: (e) => setError(e instanceof ApiError ? e.message : "Could not send your question."),
  });
  const valid = text.trim().length >= 2;
  return (
    <Modal
      title="Send your question to HR"
      onClose={onClose}
      footer={
        <>
          <Button onClick={onClose}>Cancel</Button>
          <Button variant="primary" disabled={!valid || send.isPending} onClick={() => send.mutate()}>
            {send.isPending ? "Sending…" : "Send to HR"}
          </Button>
        </>
      }
    >
      <p className="hint-line">
        HR will see your name with this question so they can reply. The reply appears under
        "My questions to HR".
      </p>
      {error && <ErrorNote>{error}</ErrorNote>}
      <Field label="Question" htmlFor={`${idBase}-q`} hint={`${text.length}/300 characters`}>
        <textarea
          id={`${idBase}-q`}
          rows={4}
          maxLength={300}
          value={text}
          onChange={(e) => setText(e.target.value)}
        />
      </Field>
      <fieldset className="field">
        <legend>How should HR reply?</legend>
        <label>
          <input
            type="radio"
            name={`${idBase}-contact`}
            checked={contact === "in_app"}
            onChange={() => setContact("in_app")}
          />{" "}
          In this app
        </label>{" "}
        <label>
          <input
            type="radio"
            name={`${idBase}-contact`}
            checked={contact === "email"}
            onChange={() => setContact("email")}
          />{" "}
          By email (if HR sends email)
        </label>
      </fieldset>
    </Modal>
  );
}
