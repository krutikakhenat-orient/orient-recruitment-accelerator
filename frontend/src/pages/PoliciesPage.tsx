import { useMutation, useQuery, useQueryClient } from "@tanstack/react-query";
import { useState, type ReactNode } from "react";
import { Link } from "react-router-dom";

import {
  acknowledgePolicy,
  approvePolicy,
  askAssistant,
  createPolicy,
  listPolicies,
  listUnanswered,
  retirePolicy,
  revisePolicy,
  updatePolicy,
  type AskResponse,
  type Policy,
} from "../api/automation";
import { ApiError } from "../api/client";
import { useAuth } from "../app/auth-context";
import { useToast } from "../components/toast";
import {
  Banner,
  Button,
  Card,
  Empty,
  ErrorNote,
  Field,
  Loading,
  Modal,
  PageHeader,
  StatusBadge,
  Tabs,
  prettify,
} from "../components/ui";

/* The HR assistant: asks a question, answers only from approved policies, names its source
   and says so plainly when nothing covers the question. No AI model is involved. */
export function AssistantBox(): ReactNode {
  const [question, setQuestion] = useState("");
  const [answer, setAnswer] = useState<AskResponse | null>(null);
  const [error, setError] = useState<string | null>(null);
  const ask = useMutation({
    mutationFn: () => askAssistant(question.trim()),
    onSuccess: (r) => {
      setError(null);
      setAnswer(r);
    },
    onError: (e) => setError(e instanceof ApiError ? e.message : "Could not ask the question."),
  });
  return (
    <Card
      title="Ask HR"
      description="Ask about leave, working hours and other policies. Answers come only from approved HR policies."
    >
      {error && <ErrorNote>{error}</ErrorNote>}
      <form
        onSubmit={(e) => {
          e.preventDefault();
          if (question.trim().length >= 2) ask.mutate();
        }}
      >
        <Field label="Your question" htmlFor="ask-q" hint="For example: how many days of annual leave do I get?">
          <input id="ask-q" value={question} onChange={(e) => setQuestion(e.target.value)} />
        </Field>
        <Button type="submit" variant="primary" small disabled={ask.isPending || question.trim().length < 2}>
          {ask.isPending ? "Looking…" : "Ask"}
        </Button>
      </form>
      {answer && (
        <div className={`assistant-answer ${answer.answered ? "" : "assistant-answer--none"}`} role="status">
          <p style={{ margin: 0 }}>{answer.answer}</p>
          {answer.sources.map((s) => (
            <p key={s.policy_id} className="doc-row__meta" style={{ margin: "6px 0 0" }}>
              Source: {s.title} (version {s.version})
            </p>
          ))}
          {answer.route_to_hr && (
            <p className="doc-row__meta" style={{ margin: "6px 0 0" }}>
              Please check with HR directly.
            </p>
          )}
          <p className="doc-row__meta" style={{ margin: "6px 0 0" }}>{answer.note}</p>
        </div>
      )}
    </Card>
  );
}

function PolicyReader({ policy, onClose }: { policy: Policy; onClose: () => void }): ReactNode {
  const qc = useQueryClient();
  const toast = useToast();
  const ack = useMutation({
    mutationFn: () => acknowledgePolicy(policy.id),
    onSuccess: () => {
      toast.push("Thanks, noted", { tone: "ok" });
      void qc.invalidateQueries({ queryKey: ["policies"] });
      onClose();
    },
  });
  return (
    <Modal
      title={policy.title}
      onClose={onClose}
      footer={
        <>
          <Button onClick={onClose}>Close</Button>
          {policy.status === "approved" && !policy.acknowledged && (
            <Button variant="primary" disabled={ack.isPending} onClick={() => ack.mutate()}>
              I have read this
            </Button>
          )}
        </>
      }
    >
      <p className="doc-row__meta">
        {prettify(policy.kind)} · version {policy.version}
        {policy.department ? ` · ${policy.department}` : ""}
      </p>
      <p style={{ whiteSpace: "pre-wrap" }}>{policy.body}</p>
    </Modal>
  );
}

/* The library as an employee sees it: approved documents to read and acknowledge. */
export function PolicyLibrary(): ReactNode {
  const policies = useQuery({ queryKey: ["policies"], queryFn: listPolicies });
  const [reading, setReading] = useState<Policy | null>(null);
  const approved = (policies.data ?? []).filter((p) => p.status === "approved");
  return (
    <Card
      title="Policies and guides"
      description="Read each one and confirm that you have read it. Anything revised later will ask you again."
    >
      {policies.isLoading && <Loading />}
      {policies.data && approved.length === 0 && <Empty>No policies have been published yet.</Empty>}
      {approved.map((p) => (
        <div key={p.id} className="doc-row">
          <div>
            <div className="doc-row__name">
              {p.title}{" "}
              <StatusBadge status={p.acknowledged ? "done" : "requested"} label={p.acknowledged ? "Read" : "To read"} />
            </div>
            <div className="doc-row__meta">
              {prettify(p.kind)} · version {p.version}
              {p.department ? ` · ${p.department}` : ""}
            </div>
          </div>
          <Button small title="Open and read this document" onClick={() => setReading(p)}>
            Read
          </Button>
        </div>
      ))}
      {reading && <PolicyReader policy={reading} onClose={() => setReading(null)} />}
    </Card>
  );
}

function PolicyForm({
  existing,
  onClose,
  onDone,
}: {
  existing?: Policy;
  onClose: () => void;
  onDone: () => void;
}): ReactNode {
  const [title, setTitle] = useState(existing?.title ?? "");
  const [kind, setKind] = useState<"policy" | "sop">((existing?.kind as "policy" | "sop") ?? "policy");
  const [department, setDepartment] = useState(existing?.department ?? "");
  const [body, setBody] = useState(existing?.body ?? "");
  const [error, setError] = useState<string | null>(null);
  const save = useMutation({
    mutationFn: () =>
      existing
        ? updatePolicy(existing.id, { title, body, department })
        : createPolicy({ title, kind, body, ...(department.trim() ? { department: department.trim() } : {}) }),
    onSuccess: onDone,
    onError: (e) => setError(e instanceof ApiError ? e.message : "Could not save."),
  });
  return (
    <Modal
      title={existing ? "Edit draft" : "New policy or guide"}
      onClose={onClose}
      footer={
        <>
          <Button onClick={onClose}>Cancel</Button>
          <Button variant="primary" disabled={!title.trim() || !body.trim() || save.isPending} onClick={() => save.mutate()}>
            {save.isPending ? "Saving…" : "Save draft"}
          </Button>
        </>
      }
    >
      <p className="hint-line">A draft is not visible to employees and is not used by the assistant until you approve it.</p>
      {error && <ErrorNote>{error}</ErrorNote>}
      <Field label="Title" htmlFor="pol-title">
        <input id="pol-title" value={title} onChange={(e) => setTitle(e.target.value)} />
      </Field>
      {!existing && (
        <Field label="Type" htmlFor="pol-kind" hint="A policy is a company rule. A guide (SOP) is a how-to for one team.">
          <select id="pol-kind" value={kind} onChange={(e) => setKind(e.target.value as "policy" | "sop")}>
            <option value="policy">Policy</option>
            <option value="sop">Guide / SOP</option>
          </select>
        </Field>
      )}
      <Field label="Department (optional)" htmlFor="pol-dept" hint="Leave empty if it applies to everyone.">
        <input id="pol-dept" value={department} onChange={(e) => setDepartment(e.target.value)} />
      </Field>
      <Field label="Text" htmlFor="pol-body">
        <textarea id="pol-body" rows={8} value={body} onChange={(e) => setBody(e.target.value)} />
      </Field>
    </Modal>
  );
}

function ManageLibrary(): ReactNode {
  const qc = useQueryClient();
  const toast = useToast();
  const [form, setForm] = useState<{ existing?: Policy } | null>(null);
  const [error, setError] = useState<string | null>(null);
  const policies = useQuery({ queryKey: ["policies"], queryFn: listPolicies });
  const unanswered = useQuery({ queryKey: ["unanswered"], queryFn: listUnanswered });
  const refresh = (): void => {
    void qc.invalidateQueries({ queryKey: ["policies"] });
  };
  const act = useMutation({
    mutationFn: (run: () => Promise<Policy>) => run(),
    onSuccess: () => {
      setError(null);
      refresh();
    },
    onError: (e) => setError(e instanceof ApiError ? e.message : "Could not do that."),
  });
  return (
    <>
      <Banner>
        <strong>How the library works:</strong> write a draft, approve it to publish it, and use
        "Revise" to make a new version. Approved text is never edited in place, so what people
        acknowledged stays on record.
      </Banner>
      {error && <ErrorNote>{error}</ErrorNote>}
      <Card
        title="Library"
        description="Every policy and guide, including drafts and older versions."
        actions={
          <Button variant="primary" small onClick={() => setForm({})}>
            New policy or guide
          </Button>
        }
      >
        {policies.isLoading && <Loading />}
        {policies.data && policies.data.length === 0 && <Empty>Nothing here yet. Add the first policy.</Empty>}
        {policies.data?.map((p) => (
          <div key={p.id} className="doc-row">
            <div>
              <div className="doc-row__name">
                {p.title} <StatusBadge status={p.status} />
              </div>
              <div className="doc-row__meta">
                {prettify(p.kind)} · version {p.version}
                {p.department ? ` · ${p.department}` : ""}
                {p.status === "approved" ? ` · read by ${p.acknowledgement_count}` : ""}
              </div>
            </div>
            <div className="btn-row">
              {p.status === "draft" && (
                <>
                  <Button small title="Change the wording of this draft" onClick={() => setForm({ existing: p })}>
                    Edit
                  </Button>
                  <Button small variant="primary" title="Publish it. Employees and the assistant can then use it"
                    onClick={() => act.mutate(() => approvePolicy(p.id))}>
                    Approve
                  </Button>
                </>
              )}
              {p.status === "approved" && (
                <>
                  <Button small title="Start a new version as a draft"
                    onClick={() => act.mutate(() => revisePolicy(p.id))}>
                    Revise
                  </Button>
                  <Button small variant="ghost" title="Stop using this policy"
                    onClick={() => act.mutate(() => retirePolicy(p.id))}>
                    Retire
                  </Button>
                </>
              )}
            </div>
          </div>
        ))}
      </Card>
      <Card
        title="Questions nobody could answer"
        description="What people asked the HR assistant that no approved policy covered. Use this to decide what to write next."
      >
        {unanswered.data && unanswered.data.length === 0 && <Empty>No open questions.</Empty>}
        {unanswered.data?.map((q, i) => (
          <p key={i} style={{ margin: "4px 0" }}>
            {q.question} <span className="doc-row__meta">{new Date(q.asked_at).toLocaleDateString()}</span>
          </p>
        ))}
      </Card>
      {form && (
        <PolicyForm
          {...(form.existing ? { existing: form.existing } : {})}
          onClose={() => setForm(null)}
          onDone={() => {
            setForm(null);
            refresh();
            toast.push("Draft saved", { tone: "ok" });
          }}
        />
      )}
    </>
  );
}

export function PoliciesPage(): ReactNode {
  const { hasPermission } = useAuth();
  const manage = hasPermission("campaign.approve");
  const [tab, setTab] = useState(manage ? "manage" : "read");
  return (
    <>
      <Link to="/settings" className="back-link">← Settings</Link>
      <PageHeader
        title="Policies & guides"
        description="The company's HR policies and team guides. Employees read them here and the HR assistant answers from them."
      />
      {manage ? (
        <>
          <Tabs
            label="Policies"
            value={tab}
            onChange={setTab}
            tabs={[
              { id: "manage", label: "Manage library" },
              { id: "read", label: "How employees see it" },
              { id: "ask", label: "Try the assistant" },
            ]}
          />
          {tab === "manage" && <ManageLibrary />}
          {tab === "read" && <PolicyLibrary />}
          {tab === "ask" && <AssistantBox />}
        </>
      ) : (
        <>
          <AssistantBox />
          <PolicyLibrary />
        </>
      )}
    </>
  );
}
