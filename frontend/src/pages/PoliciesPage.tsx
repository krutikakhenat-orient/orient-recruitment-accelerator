import { useMutation, useQuery, useQueryClient } from "@tanstack/react-query";
import { useEffect, useId, useState, type ReactNode } from "react";
import { Link } from "react-router-dom";

import {
  acknowledgePolicy,
  approvePolicy,
  createPolicy,
  downloadPolicyOriginal,
  faqFromUnanswered,
  getIndexStatus,
  getOriginalLink,
  listPolicies,
  listUnanswered,
  reindexPolicy,
  retirePolicy,
  revisePolicy,
  updatePolicy,
  type Policy,
  type PolicyKind,
} from "../api/automation";
import { ApiError } from "../api/client";
import { useAuth } from "../app/auth-context";
import { AssistantInsightsPanel } from "../components/hr-chat/AssistantInsightsPanel";
import { AudiencePicker, audienceLabel } from "../components/hr-chat/AudiencePicker";
import { ChatPanel } from "../components/hr-chat/ChatPanel";
import { HrInbox } from "../components/hr-chat/HrInbox";
import { IndexBadge } from "../components/hr-chat/IndexBadge";
import { MyHrQuestions } from "../components/hr-chat/MyHrQuestions";
import { UploadPolicyDialog } from "../components/hr-chat/UploadPolicyDialog";
import { useToast } from "../components/toast";
import {
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

const KIND_LABEL: Record<string, string> = { policy: "Policy", sop: "Guide / SOP", faq: "FAQ" };

/* The HR assistant for employees: cited answers from approved policies, plus the replies to
   questions they sent to HR. Used on the employee dashboard and the policies page. */
export function AssistantBox(): ReactNode {
  return (
    <>
      <Card title="Ask HR" description="Ask about leave, working hours and other policies.">
        <ChatPanel />
      </Card>
      <Card title="My questions to HR" description="Questions you sent to HR and their replies.">
        <MyHrQuestions />
      </Card>
    </>
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
        {KIND_LABEL[policy.kind] ?? prettify(policy.kind)} · version {policy.version}
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
      {policies.isError && <ErrorNote>The policies could not be loaded. Please try again.</ErrorNote>}
      {policies.data && approved.length === 0 && <Empty>No policies have been published yet.</Empty>}
      {approved.map((p) => (
        <div key={p.id} className="doc-row">
          <div>
            <div className="doc-row__name">
              {p.title}{" "}
              <StatusBadge status={p.acknowledged ? "done" : "requested"} label={p.acknowledged ? "Read" : "To read"} />
            </div>
            <div className="doc-row__meta">
              {KIND_LABEL[p.kind] ?? prettify(p.kind)} · version {p.version}
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
  onDone: (saved: Policy) => void;
}): ReactNode {
  const base = useId();
  const uploaded = !!existing?.source_filename;
  const [asDraft, setAsDraft] = useState(false);
  const [title, setTitle] = useState(existing?.title ?? "");
  const [kind, setKind] = useState<PolicyKind>((existing?.kind as PolicyKind) ?? "policy");
  const [department, setDepartment] = useState(existing?.department ?? "");
  const [body, setBody] = useState(existing?.body ?? "");
  const [audience, setAudience] = useState<string[]>(
    (existing?.audience ?? []).filter((t) => t !== "everyone"),
  );
  const [reviewDue, setReviewDue] = useState(existing?.review_due_date ?? "");
  const [error, setError] = useState<string | null>(null);
  const save = useMutation({
    mutationFn: () =>
      existing
        ? updatePolicy(existing.id, {
            title, department, audience, review_due_date: reviewDue || null,
            ...(uploaded ? {} : { body }),
          })
        : createPolicy({
            title, kind, body, audience, publish: !asDraft,
            ...(department.trim() ? { department: department.trim() } : {}),
            ...(reviewDue ? { review_due_date: reviewDue } : {}),
          }),
    onSuccess: onDone,
    onError: (e) => setError(e instanceof ApiError ? e.message : "Could not save."),
  });
  const label = existing ? "Save changes" : asDraft ? "Save draft" : "Publish";
  return (
    <Modal
      title={existing ? "Edit draft" : "Write a policy, guide or FAQ"}
      onClose={onClose}
      footer={
        <>
          <Button onClick={onClose}>Cancel</Button>
          <Button variant="primary" disabled={!title.trim() || !body.trim() || save.isPending} onClick={() => save.mutate()}>
            {save.isPending ? "Saving…" : label}
          </Button>
        </>
      }
    >
      <p className="hint-line">
        {existing
          ? "This is a draft. Save your changes, then click Publish in the library."
          : "Publishing makes it visible to the people it is for and syncs it to the chatbot straight away."}
      </p>
      {error && <ErrorNote>{error}</ErrorNote>}
      <Field label="Title" htmlFor={`${base}-title`}>
        <input id={`${base}-title`} value={title} onChange={(e) => setTitle(e.target.value)} />
      </Field>
      {!existing && (
        <Field label="Type" htmlFor={`${base}-kind`} hint="A policy is a company rule. A guide (SOP) is a how-to for one team. An FAQ is a short question and answer.">
          <select id={`${base}-kind`} value={kind} onChange={(e) => setKind(e.target.value as PolicyKind)}>
            <option value="policy">Policy</option>
            <option value="sop">Guide / SOP</option>
            <option value="faq">FAQ</option>
          </select>
        </Field>
      )}
      <Field label="Department (optional)" htmlFor={`${base}-dept`} hint="Shown as a label only.">
        <input id={`${base}-dept`} value={department} onChange={(e) => setDepartment(e.target.value)} />
      </Field>
      <AudiencePicker value={audience} onChange={setAudience} />
      <Field label="Review by (optional)" htmlFor={`${base}-review`}>
        <input id={`${base}-review`} type="date" value={reviewDue} onChange={(e) => setReviewDue(e.target.value)} />
      </Field>
      <Field
        label="Text"
        htmlFor={`${base}-body`}
        hint={uploaded ? "This text was read from the uploaded file. Use Replace file to change it." : undefined}
      >
        <textarea id={`${base}-body`} rows={8} value={body} readOnly={uploaded}
          onChange={(e) => setBody(e.target.value)} />
      </Field>
      {!existing && (
        <label className="check-row" htmlFor={`${base}-draft`}>
          <input id={`${base}-draft`} type="checkbox" checked={asDraft}
            onChange={(e) => setAsDraft(e.target.checked)} />
          <span>
            <strong>Save as draft</strong>
            <span className="hint"> Not ready yet: nobody sees it and the chatbot does not use it
              until you publish it.</span>
          </span>
        </label>
      )}
    </Modal>
  );
}

/* While a version is syncing, check every 10 seconds. When it settles, tell HR clearly
   (toast) whether the chatbot can now answer from it, and refresh the list. */
function IndexWatcher({ policyId, title }: { policyId: string; title: string }): null {
  const qc = useQueryClient();
  const toast = useToast();
  const status = useQuery({
    queryKey: ["index-status", policyId],
    queryFn: () => getIndexStatus(policyId),
    refetchInterval: (q) => (q.state.data && q.state.data.index_status !== "indexing" ? false : 10_000),
  });
  const settled = status.data?.index_status;
  useEffect(() => {
    if (!settled || settled === "indexing") return;
    if (settled === "ready") {
      toast.push(`"${title}" is synced`, { tone: "ok", message: "The chatbot can answer from it now." });
    } else if (settled === "failed") {
      toast.push(`"${title}" did not sync`, { tone: "danger", message: "Open the library to see why and retry." });
    }
    void qc.invalidateQueries({ queryKey: ["policies"] });
  }, [settled, title, qc, toast]);
  return null;
}

/* What HR sees right after publishing. */
export function publishedMessage(p: Policy): { title: string; message: string; tone: "ok" | "danger" | "info" } {
  if (p.status === "draft") return { title: "Draft saved", message: "Publish it when it is ready.", tone: "info" };
  if (p.index_status === "ready") {
    return { title: "Published and synced", message: "The chatbot can answer from it now.", tone: "ok" };
  }
  if (p.index_status === "failed") {
    return { title: "Published, but the sync failed", message: p.index_error ?? "Retry the sync from the library.", tone: "danger" };
  }
  return { title: "Published. Syncing to the chatbot…", message: "You will see a confirmation when it is ready.", tone: "info" };
}

const STATUS_LABEL: Record<string, string> = { draft: "Draft", approved: "Published", retired: "Retired" };

async function openOriginal(policyId: string): Promise<void> {
  const link = await getOriginalLink(policyId);
  if (link.url) {
    window.open(link.url, "_blank", "noopener,noreferrer");
    return;
  }
  const { blob, filename } = await downloadPolicyOriginal(policyId);
  const url = URL.createObjectURL(blob);
  const a = document.createElement("a");
  a.href = url;
  a.download = filename;
  a.click();
  URL.revokeObjectURL(url);
}

function ManageLibrary(): ReactNode {
  const qc = useQueryClient();
  const toast = useToast();
  const [form, setForm] = useState<{ existing?: Policy } | null>(null);
  const [upload, setUpload] = useState<{ replacing?: Policy } | null>(null);
  const [error, setError] = useState<string | null>(null);
  const policies = useQuery({ queryKey: ["policies"], queryFn: listPolicies });
  const unanswered = useQuery({ queryKey: ["unanswered"], queryFn: listUnanswered });
  const refresh = (): void => {
    void qc.invalidateQueries({ queryKey: ["policies"] });
  };
  const act = useMutation({
    mutationFn: (run: () => Promise<unknown>) => run(),
    onSuccess: (result) => {
      setError(null);
      refresh();
      if (result && typeof result === "object" && "index_status" in result) {
        const m = publishedMessage(result as Policy);
        toast.push(m.title, { tone: m.tone, message: m.message });
      }
    },
    onError: (e) => setError(e instanceof Error ? e.message : "Could not do that."),
  });
  const published = (policies.data ?? []).filter((p) => p.status === "approved");
  const synced = published.filter((p) => p.index_status === "ready").length;
  const needsAction = published.filter((p) => p.index_status === "failed" || p.index_status === "not_indexed");
  return (
    <>
      {error && <ErrorNote>{error}</ErrorNote>}
      <Card
        title="Library"
        description="Upload or write a policy and it is published and synced to the chatbot in one step. Revise keeps the old version answering until the new one is synced."
        actions={
          <div className="btn-row">
            <Button variant="primary" small onClick={() => setUpload({})}>Upload file</Button>
            <Button small onClick={() => setForm({})}>Write one</Button>
          </div>
        }
      >
        {policies.data && published.length > 0 && (
          <p className={`sync-summary ${needsAction.length ? "sync-summary--warn" : "sync-summary--ok"}`} role="status">
            <strong>{synced} of {published.length}</strong> published{" "}
            {published.length === 1 ? "policy is" : "policies are"} synced to the chatbot
            {needsAction.length > 0 && (
              <>
                {". "}
                {needsAction.length} need{needsAction.length === 1 ? "s" : ""} a sync.{" "}
                <Button small variant="primary" disabled={act.isPending}
                  onClick={() => act.mutate(async () => {
                    for (const p of needsAction) await reindexPolicy(p.id);
                  })}>
                  Sync all now
                </Button>
              </>
            )}
          </p>
        )}
        {policies.isLoading && <Loading />}
        {policies.isError && <ErrorNote>The library could not be loaded. Please try again.</ErrorNote>}
        {policies.data && policies.data.length === 0 && <Empty>Nothing here yet. Add the first policy.</Empty>}
        {policies.data?.map((p) => (
          <div key={p.id} className="doc-row">
            <div>
              <div className="doc-row__name">
                {p.title} <StatusBadge status={p.status === "approved" ? "done" : p.status}
                  label={STATUS_LABEL[p.status] ?? prettify(p.status)} />{" "}
                {p.status === "approved" && <IndexBadge status={p.index_status} />}
              </div>
              <div className="doc-row__meta">
                {KIND_LABEL[p.kind] ?? prettify(p.kind)} · version {p.version} · for {audienceLabel(p.audience)}
                {p.source_filename ? ` · file: ${p.source_filename}` : ""}
                {p.status === "approved" ? ` · read by ${p.acknowledgement_count}` : ""}
                {p.review_due_date ? ` · review by ${new Date(p.review_due_date).toLocaleDateString()}` : ""}
              </div>
              {p.status === "approved" && p.index_status === "failed" && p.index_error && (
                <p className="field-error" style={{ margin: "4px 0 0" }}>Why the sync failed: {p.index_error}</p>
              )}
              {p.index_status === "indexing" && <IndexWatcher policyId={p.id} title={p.title} />}
            </div>
            <div className="btn-row">
              {p.has_file && (
                <Button small variant="ghost" title="Download the stored file"
                  onClick={() => act.mutate(() => openOriginal(p.id))}>
                  Open original
                </Button>
              )}
              {p.status === "draft" && (
                <>
                  <Button small title="Change the details of this draft" onClick={() => setForm({ existing: p })}>
                    Edit
                  </Button>
                  {p.source_filename && (
                    <Button small title="Upload a new file for this draft" onClick={() => setUpload({ replacing: p })}>
                      Replace file
                    </Button>
                  )}
                  <Button small variant="primary" title="Make it visible and sync it to the chatbot"
                    onClick={() => act.mutate(() => approvePolicy(p.id))}>
                    Publish
                  </Button>
                </>
              )}
              {p.status === "approved" && (
                <>
                  {(p.index_status === "failed" || p.index_status === "not_indexed") && (
                    <Button small variant="primary" title="Send this version to the chatbot again"
                      onClick={() => act.mutate(() => reindexPolicy(p.id))}>
                      {p.index_status === "failed" ? "Retry sync" : "Sync now"}
                    </Button>
                  )}
                  <Button small title="Start a new version as a draft"
                    onClick={() => act.mutate(() => revisePolicy(p.id))}>
                    Revise
                  </Button>
                  <Button small variant="ghost" title="Stop using this policy and remove it from the chatbot"
                    onClick={() => {
                      if (window.confirm(`Retire "${p.title}"? Employees will no longer see it and the chatbot will stop using it.`)) {
                        act.mutate(() => retirePolicy(p.id));
                      }
                    }}>
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
        description="What people asked that no approved policy covered. Turn one into an FAQ draft."
      >
        {unanswered.isLoading && <Loading />}
        {unanswered.data && unanswered.data.length === 0 && <Empty>No open questions.</Empty>}
        {unanswered.data?.map((q, i) => (
          <div key={q.id ?? i} className="doc-row">
            <div>
              {q.question} <span className="doc-row__meta">{new Date(q.asked_at).toLocaleDateString()}</span>
            </div>
            {q.id && (
              <Button small onClick={() => act.mutate(async () => {
                await faqFromUnanswered(q.id as string);
                toast.push("FAQ draft created", { tone: "ok" });
              })}>
                Create FAQ draft
              </Button>
            )}
          </div>
        ))}
      </Card>
      {form && (
        <PolicyForm
          {...(form.existing ? { existing: form.existing } : {})}
          onClose={() => setForm(null)}
          onDone={(saved) => {
            setForm(null);
            refresh();
            const m = publishedMessage(saved);
            toast.push(m.title, { tone: m.tone, message: m.message });
          }}
        />
      )}
      {upload && (
        <UploadPolicyDialog
          {...(upload.replacing ? { replacing: upload.replacing } : {})}
          onClose={() => setUpload(null)}
          onDone={(saved) => {
            setUpload(null);
            refresh();
            const m = publishedMessage(saved);
            toast.push(m.title, { tone: m.tone, message: m.message });
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
        description="The company's HR policies and team guides. Employees read them here and the HR chatbot answers from them."
      />
      {manage ? (
        <>
          <Tabs
            label="Policies"
            value={tab}
            onChange={setTab}
            tabs={[
              { id: "manage", label: "Manage library" },
              { id: "inbox", label: "HR inbox" },
              { id: "insights", label: "Insights" },
              { id: "read", label: "How employees see it" },
              { id: "ask", label: "Try the chatbot" },
            ]}
          />
          {tab === "manage" && <ManageLibrary />}
          {tab === "inbox" && <HrInbox />}
          {tab === "insights" && <AssistantInsightsPanel />}
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
