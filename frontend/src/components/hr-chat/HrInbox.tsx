import { useMutation, useQuery, useQueryClient } from "@tanstack/react-query";
import { useId, useState, type ReactNode } from "react";

import {
  answerHrQuestion,
  closeHrQuestion,
  faqFromHrQuestion,
  listHrInbox,
  type HrInboxItem,
} from "../../api/automation";
import { ApiError } from "../../api/client";
import { useToast } from "../toast";
import { Button, Card, Empty, ErrorNote, Field, Loading, Modal, StatusBadge, Tabs } from "../ui";

const LABEL = { open: "Open", answered: "Answered", closed: "Closed" } as const;

function AnswerDialog({ item, onClose }: { item: HrInboxItem; onClose: () => void }): ReactNode {
  const qc = useQueryClient();
  const id = useId();
  const [text, setText] = useState(item.answer ?? "");
  const [error, setError] = useState<string | null>(null);
  const save = useMutation({
    mutationFn: () => answerHrQuestion(item.id, text.trim()),
    onSuccess: () => {
      void qc.invalidateQueries({ queryKey: ["hr-inbox"] });
      onClose();
    },
    onError: (e) => setError(e instanceof ApiError ? e.message : "Could not save the answer."),
  });
  return (
    <Modal
      title="Answer question"
      onClose={onClose}
      footer={
        <>
          <Button onClick={onClose}>Cancel</Button>
          <Button variant="primary" disabled={text.trim().length < 2 || save.isPending}
            onClick={() => save.mutate()}>
            {save.isPending ? "Saving…" : "Send answer"}
          </Button>
        </>
      }
    >
      <p style={{ whiteSpace: "pre-wrap" }}>{item.question}</p>
      <p className="doc-row__meta">
        From {item.asked_by_name ?? "an employee"}
        {item.contact_preference === "email" ? " · prefers email (reply is shown in the app)" : ""}
      </p>
      {error && <ErrorNote>{error}</ErrorNote>}
      <Field label="Your answer" htmlFor={id} hint="The employee sees this under My questions to HR.">
        <textarea id={id} rows={5} maxLength={4000} value={text} onChange={(e) => setText(e.target.value)} />
      </Field>
    </Modal>
  );
}

/* HR inbox: questions employees sent to HR (Req 7.3, 7.4). */
export function HrInbox(): ReactNode {
  const qc = useQueryClient();
  const toast = useToast();
  const [status, setStatus] = useState<"open" | "answered" | "closed">("open");
  const [answering, setAnswering] = useState<HrInboxItem | null>(null);
  const [error, setError] = useState<string | null>(null);
  const inbox = useQuery({ queryKey: ["hr-inbox", status], queryFn: () => listHrInbox(status) });
  const act = useMutation({
    mutationFn: (run: () => Promise<unknown>) => run(),
    onSuccess: () => {
      setError(null);
      void qc.invalidateQueries({ queryKey: ["hr-inbox"] });
      void qc.invalidateQueries({ queryKey: ["policies"] });
    },
    onError: (e) => setError(e instanceof ApiError ? e.message : "Could not do that."),
  });
  return (
    <Card title="HR inbox" description="Questions people sent to HR when the chatbot could not answer.">
      <Tabs
        label="Inbox status"
        value={status}
        onChange={(v) => setStatus(v as typeof status)}
        tabs={[
          { id: "open", label: "Open" },
          { id: "answered", label: "Answered" },
          { id: "closed", label: "Closed" },
        ]}
      />
      {error && <ErrorNote>{error}</ErrorNote>}
      {inbox.isLoading && <Loading />}
      {inbox.isError && <ErrorNote>The inbox could not be loaded. Please try again.</ErrorNote>}
      {inbox.data && inbox.data.length === 0 && <Empty>No {LABEL[status].toLowerCase()} questions.</Empty>}
      {inbox.data?.map((q) => (
        <div key={q.id} className="doc-row">
          <div>
            <div className="doc-row__name">
              {q.question} <StatusBadge status={q.status === "open" ? "requested" : "done"} label={LABEL[q.status]} />
            </div>
            <div className="doc-row__meta">
              {q.asked_by_name ?? "Employee"} · {new Date(q.created_at).toLocaleDateString()}
            </div>
            {q.answer && <p style={{ whiteSpace: "pre-wrap", margin: "4px 0 0" }}>{q.answer}</p>}
          </div>
          <div className="btn-row">
            {q.status !== "closed" && (
              <Button small variant="primary" onClick={() => setAnswering(q)}>
                {q.status === "answered" ? "Edit answer" : "Answer"}
              </Button>
            )}
            <Button small title="Start an FAQ draft from this question"
              onClick={() => act.mutate(async () => {
                await faqFromHrQuestion(q.id);
                toast.push("FAQ draft created in the library", { tone: "ok" });
              })}>
              Create FAQ draft
            </Button>
            {q.status !== "closed" && (
              <Button small variant="ghost" onClick={() => act.mutate(() => closeHrQuestion(q.id))}>
                Close
              </Button>
            )}
          </div>
        </div>
      ))}
      {answering && <AnswerDialog item={answering} onClose={() => setAnswering(null)} />}
    </Card>
  );
}
