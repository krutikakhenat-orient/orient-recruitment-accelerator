import { useMutation, useQuery, useQueryClient } from "@tanstack/react-query";
import { useEffect, useState, type ReactNode } from "react";

import {
  approveJoiningContent,
  getHrmsPreview,
  getJoiningCase,
  getNotificationStatus,
  listJoiningCases,
  markJoined,
  receiveDocument,
  remindDocuments,
  resolveFlag,
  sendAnnouncement,
  sendPrejoining,
  sendWelcome,
  setDocumentStatus,
  updateJoiningCase,
  verifyJoiningCase,
  type Delivery,
  type DocumentFlag,
  type JoiningCase,
  type JoiningCaseDetail,
  type JoiningDocument,
} from "../api/automation";
import { ApiError } from "../api/client";
import { useAuth } from "../app/auth-context";
import { ChannelNote, deliveryStatusLabel } from "../components/Messages";
import { useToast } from "../components/toast";
import {
  Action,
  Banner,
  Button,
  Card,
  Drawer,
  Empty,
  ErrorNote,
  Field,
  Loading,
  StatusBadge,
} from "../components/ui";

/* Joining: the checklist of documents a selected candidate must bring, simple checks on what
   HR enters, and the messages before and on day one. Flags are suggestions; HR decides. */

export function JoiningPanel(): ReactNode {
  const cases = useQuery({ queryKey: ["joining-cases"], queryFn: listJoiningCases });
  const [openId, setOpenId] = useState<string | null>(null);

  return (
    <>
      <Banner>
        <strong>How joining works:</strong> 1) the candidate gets a document list, 2) HR marks each
        document as received and runs a check, 3) HR resolves any flags, 4) HR approves the joining
        details and sends the joiner their information, 5) mark them as joined.
      </Banner>
      <Card
        title="Joining cases"
        description="One case per selected candidate who accepted an offer. Open a case to work through it."
      >
        {cases.isLoading && <Loading />}
        {cases.error && <ErrorNote>Could not load joining cases.</ErrorNote>}
        {cases.data && cases.data.length === 0 && (
          <Empty>No joining cases yet. Start one from an accepted offer.</Empty>
        )}
        {cases.data && cases.data.length > 0 && (
          <div className="table-wrap">
            <table className="data">
              <thead>
                <tr>
                  <th>Joiner</th>
                  <th>Role</th>
                  <th>Status</th>
                  <th>Documents ready</th>
                  <th>Joining date</th>
                  <th />
                </tr>
              </thead>
              <tbody>
                {cases.data.map((c) => (
                  <CaseRow key={c.id} item={c} onOpen={() => setOpenId(c.id)} />
                ))}
              </tbody>
            </table>
          </div>
        )}
      </Card>
      {openId && <CaseDrawer caseId={openId} onClose={() => setOpenId(null)} />}
    </>
  );
}

function CaseRow({ item, onOpen }: { item: JoiningCase; onOpen: () => void }): ReactNode {
  const pct = item.documents_total ? Math.round((item.documents_done / item.documents_total) * 100) : 0;
  return (
    <tr>
      <td>{item.candidate_name}</td>
      <td>{item.role_title}</td>
      <td>
        <StatusBadge status={item.status} />
      </td>
      <td style={{ minWidth: 160 }}>
        <div className="progress" role="progressbar" aria-valuenow={pct} aria-valuemin={0}
          aria-valuemax={100} aria-label={`${item.documents_done} of ${item.documents_total} documents ready`}>
          <div className="progress__fill" style={{ width: `${pct}%` }} />
        </div>
        <span className="doc-row__meta">
          {item.documents_done} of {item.documents_total}
          {item.open_flags > 0 ? ` · ${item.open_flags} flag(s) to review` : ""}
        </span>
      </td>
      <td>{item.joining_date ?? <span className="subtle">Not set</span>}</td>
      <td style={{ textAlign: "right" }}>
        <Button small title="Open this joining case" onClick={onOpen}>
          Open
        </Button>
      </td>
    </tr>
  );
}

function CaseDrawer({ caseId, onClose }: { caseId: string; onClose: () => void }): ReactNode {
  const qc = useQueryClient();
  const toast = useToast();
  const { hasPermission } = useAuth();
  const canOperate = hasPermission("candidate.correct");
  const canApprove = hasPermission("hiring_decision.approve");
  const [error, setError] = useState<string | null>(null);

  const detail = useQuery({ queryKey: ["joining-case", caseId], queryFn: () => getJoiningCase(caseId) });
  const channels = useQuery({ queryKey: ["notification-status"], queryFn: getNotificationStatus });

  const refresh = (): void => {
    void qc.invalidateQueries({ queryKey: ["joining-case", caseId] });
    void qc.invalidateQueries({ queryKey: ["joining-cases"] });
  };
  const fail = (e: unknown): void =>
    setError(e instanceof ApiError ? e.message : "Something went wrong. Please try again.");
  const sent = (d: Delivery): void => {
    setError(null);
    toast.push("Message recorded", { tone: "ok", message: deliveryStatusLabel(d.status) });
    refresh();
  };

  const verify = useMutation({
    mutationFn: () => verifyJoiningCase(caseId),
    onSuccess: (flags) => {
      setError(null);
      toast.push("Check finished", { tone: "ok", message: `${flags.filter((f) => f.status === "open").length} item(s) need a look` });
      refresh();
    },
    onError: fail,
  });
  const remind = useMutation({ mutationFn: () => remindDocuments(caseId), onSuccess: sent, onError: fail });
  const prejoin = useMutation({ mutationFn: () => sendPrejoining(caseId), onSuccess: sent, onError: fail });
  const welcome = useMutation({ mutationFn: () => sendWelcome(caseId), onSuccess: sent, onError: fail });
  const approve = useMutation({
    mutationFn: () => approveJoiningContent(caseId),
    onSuccess: () => {
      setError(null);
      toast.push("Joining details approved", { tone: "ok" });
      refresh();
    },
    onError: fail,
  });
  const joined = useMutation({
    mutationFn: () => markJoined(caseId),
    onSuccess: () => {
      toast.push("Marked as joined", { tone: "ok" });
      refresh();
    },
    onError: fail,
  });

  const d = detail.data;
  return (
    <Drawer
      title={d ? d.candidate_name : "Joining case"}
      subtitle={d ? `${d.role_title} · ${d.status.replace(/_/g, " ")}` : undefined}
      onClose={onClose}
    >
      {detail.isLoading && <Loading />}
      {detail.error && <ErrorNote>Could not load this joining case.</ErrorNote>}
      {error && <ErrorNote>{error}</ErrorNote>}
      {d && (
        <>
          {channels.data && <ChannelNote status={channels.data} />}

          <h3>1. Joining details</h3>
          <p className="hint-line">
            What the joiner will be told before day one. Changing anything here means HR must approve
            the wording again.
          </p>
          <DetailsForm detail={d} disabled={!canOperate} onSaved={refresh} onError={fail} />
          <div className="actions-grid">
            <Action
              label={d.content_approved ? "Details approved" : "Approve joining details"}
              hint="HR confirms the details are right. Joining messages cannot be sent until this is done."
              variant="primary"
              disabled={!canApprove || d.content_approved}
              busy={approve.isPending}
              onClick={() => approve.mutate()}
            />
          </div>

          <hr className="divider" />
          <h3>2. Documents</h3>
          <p className="hint-line">
            Mark each document as received and type the name shown on it and its expiry date. Do not
            type ID numbers: they are not needed here.
          </p>
          {d.documents.map((doc) => (
            <DocumentRow key={doc.id} caseId={caseId} doc={doc} disabled={!canOperate} onChanged={refresh} onError={fail} />
          ))}
          <div className="actions-grid">
            <Action
              label="Check documents"
              hint="Compares what you entered with the candidate's record and the joining date, and flags gaps."
              disabled={!canOperate}
              busy={verify.isPending}
              onClick={() => verify.mutate()}
            />
            <Action
              label="Remind about documents"
              hint="Sends the joiner a list of the documents still outstanding."
              disabled={!canOperate}
              busy={remind.isPending}
              onClick={() => remind.mutate()}
            />
          </div>
          <p className="hint-line" style={{ marginTop: 8 }}>{d.ai_verification_note}</p>

          <FlagList caseId={caseId} flags={d.flags} disabled={!canOperate} onChanged={refresh} onError={fail} />

          <hr className="divider" />
          <h3>3. Messages to the joiner</h3>
          <p className="hint-line">Each message uses an approved template and is recorded in the message log.</p>
          <div className="actions-grid">
            <Action
              label="Send joining information"
              hint="Reporting manager, department, location and what to expect. Needs approved details."
              disabled={!canApprove || !d.content_approved}
              busy={prejoin.isPending}
              onClick={() => prejoin.mutate()}
            />
            <Action
              label="Send welcome message"
              hint="A short welcome on the joining date. Needs approved details."
              disabled={!canApprove || !d.content_approved}
              busy={welcome.isPending}
              onClick={() => welcome.mutate()}
            />
          </div>
          <AnnouncementForm caseId={caseId} disabled={!canApprove || !d.content_approved} onSent={sent} onError={fail} />

          <hr className="divider" />
          <h3>4. Finish</h3>
          <HrmsBlock caseId={caseId} />
          <div className="actions-grid">
            <Action
              label="Mark as joined"
              hint="Records that the person has joined. Do this on or after the joining date."
              variant="primary"
              disabled={!canApprove || d.status === "joined"}
              busy={joined.isPending}
              onClick={() => joined.mutate()}
            />
          </div>
        </>
      )}
    </Drawer>
  );
}

function DetailsForm({
  detail,
  disabled,
  onSaved,
  onError,
}: {
  detail: JoiningCaseDetail;
  disabled: boolean;
  onSaved: () => void;
  onError: (e: unknown) => void;
}): ReactNode {
  const [form, setForm] = useState({
    joining_date: detail.joining_date ?? "",
    reporting_manager: detail.reporting_manager ?? "",
    department: detail.department ?? "",
    work_location: detail.work_location ?? "",
    role_expectations: detail.role_expectations ?? "",
  });
  useEffect(() => {
    setForm({
      joining_date: detail.joining_date ?? "",
      reporting_manager: detail.reporting_manager ?? "",
      department: detail.department ?? "",
      work_location: detail.work_location ?? "",
      role_expectations: detail.role_expectations ?? "",
    });
  }, [detail.joining_date, detail.reporting_manager, detail.department, detail.work_location, detail.role_expectations]);
  const save = useMutation({
    mutationFn: () =>
      updateJoiningCase(detail.id, {
        joining_date: form.joining_date || null,
        reporting_manager: form.reporting_manager || null,
        department: form.department || null,
        work_location: form.work_location || null,
        role_expectations: form.role_expectations || null,
      }),
    onSuccess: onSaved,
    onError: onError,
  });
  const set = (k: keyof typeof form) => (e: { target: { value: string } }) =>
    setForm((f) => ({ ...f, [k]: e.target.value }));
  return (
    <>
      <div className="field-row">
        <Field label="Joining date" htmlFor="cd-date">
          <input id="cd-date" type="date" value={form.joining_date} onChange={set("joining_date")} disabled={disabled} />
        </Field>
        <Field label="Reporting manager" htmlFor="cd-mgr">
          <input id="cd-mgr" value={form.reporting_manager} onChange={set("reporting_manager")} disabled={disabled} />
        </Field>
        <Field label="Department" htmlFor="cd-dept">
          <input id="cd-dept" value={form.department} onChange={set("department")} disabled={disabled} />
        </Field>
        <Field label="Work location" htmlFor="cd-loc">
          <input id="cd-loc" value={form.work_location} onChange={set("work_location")} disabled={disabled} />
        </Field>
      </div>
      <Field label="What to expect (goals / KPIs)" htmlFor="cd-exp">
        <textarea id="cd-exp" value={form.role_expectations} onChange={set("role_expectations")} disabled={disabled} />
      </Field>
      <Button small disabled={disabled || save.isPending} onClick={() => save.mutate()}>
        {save.isPending ? "Saving…" : "Save details"}
      </Button>
    </>
  );
}

function DocumentRow({
  caseId,
  doc,
  disabled,
  onChanged,
  onError,
}: {
  caseId: string;
  doc: JoiningDocument;
  disabled: boolean;
  onChanged: () => void;
  onError: (e: unknown) => void;
}): ReactNode {
  const [entering, setEntering] = useState(false);
  const [nameOnDoc, setNameOnDoc] = useState(doc.name_on_document ?? "");
  const [expiry, setExpiry] = useState(doc.expiry_date ?? "");
  const receive = useMutation({
    mutationFn: () =>
      receiveDocument(caseId, doc.id, {
        ...(nameOnDoc.trim() ? { name_on_document: nameOnDoc.trim() } : {}),
        ...(expiry ? { expiry_date: expiry } : {}),
      }),
    onSuccess: () => {
      setEntering(false);
      onChanged();
    },
    onError,
  });
  const status = useMutation({
    mutationFn: (s: "accepted" | "waived" | "correction_requested") => setDocumentStatus(caseId, doc.id, s),
    onSuccess: onChanged,
    onError,
  });
  const received = doc.status !== "requested" && doc.status !== "correction_requested";
  return (
    <div className="doc-row">
      <div>
        <div className="doc-row__name">
          {doc.name} <StatusBadge status={doc.status} />
          {!doc.required && <span className="doc-row__meta"> optional</span>}
        </div>
        <div className="doc-row__meta">
          {doc.name_on_document ? `Name on document: ${doc.name_on_document}. ` : ""}
          {doc.expiry_date ? `Expires ${doc.expiry_date}.` : ""}
        </div>
        {entering && (
          <div className="field-row" style={{ marginTop: 8 }}>
            <Field label="Name shown on the document" htmlFor={`nd-${doc.id}`}>
              <input id={`nd-${doc.id}`} value={nameOnDoc} onChange={(e) => setNameOnDoc(e.target.value)} />
            </Field>
            <Field label="Expiry date (if any)" htmlFor={`ex-${doc.id}`}>
              <input id={`ex-${doc.id}`} type="date" value={expiry} onChange={(e) => setExpiry(e.target.value)} />
            </Field>
          </div>
        )}
      </div>
      <div className="btn-row">
        {entering ? (
          <>
            <Button small variant="primary" disabled={receive.isPending} onClick={() => receive.mutate()}>
              Save as received
            </Button>
            <Button small variant="ghost" onClick={() => setEntering(false)}>
              Cancel
            </Button>
          </>
        ) : (
          <>
            {!disabled && (
              <Button small title="Record that this document arrived" onClick={() => setEntering(true)}>
                {received ? "Edit details" : "Mark received"}
              </Button>
            )}
            {!disabled && received && doc.status !== "accepted" && (
              <Button small title="Accept this document as fine" onClick={() => status.mutate("accepted")}>
                Accept
              </Button>
            )}
            {!disabled && received && (
              <Button small variant="ghost" title="Ask the joiner to send it again"
                onClick={() => status.mutate("correction_requested")}>
                Ask to resend
              </Button>
            )}
            {!disabled && doc.status !== "waived" && !received && (
              <Button small variant="ghost" title="This document is not needed for this person"
                onClick={() => status.mutate("waived")}>
                Not needed
              </Button>
            )}
          </>
        )}
      </div>
    </div>
  );
}

function FlagList({
  caseId,
  flags,
  disabled,
  onChanged,
  onError,
}: {
  caseId: string;
  flags: DocumentFlag[];
  disabled: boolean;
  onChanged: () => void;
  onError: (e: unknown) => void;
}): ReactNode {
  if (flags.length === 0) return null;
  const open = flags.filter((f) => f.status === "open");
  return (
    <div style={{ marginTop: 12 }}>
      <h3>Things to look at ({open.length} open)</h3>
      <p className="hint-line">
        Flags are suggestions, not decisions. Choose what to do with each one and give a short reason.
      </p>
      {flags.map((f) => (
        <FlagItem key={f.id} caseId={caseId} flag={f} disabled={disabled} onChanged={onChanged} onError={onError} />
      ))}
    </div>
  );
}

function FlagItem({
  caseId,
  flag,
  disabled,
  onChanged,
  onError,
}: {
  caseId: string;
  flag: DocumentFlag;
  disabled: boolean;
  onChanged: () => void;
  onError: (e: unknown) => void;
}): ReactNode {
  const [reason, setReason] = useState("");
  const resolve = useMutation({
    mutationFn: (action: "accepted" | "correction_requested" | "waived") =>
      resolveFlag(caseId, flag.id, { action, reason: reason.trim() }),
    onSuccess: onChanged,
    onError,
  });
  const resolved = flag.status !== "open";
  return (
    <div className={`flag ${resolved ? "flag--resolved" : ""}`}>
      <div>
        <StatusBadge status={flag.kind} /> {flag.message}
      </div>
      {resolved ? (
        <div className="doc-row__meta">
          Resolved ({flag.status.replace(/_/g, " ")}): {flag.resolution_reason}
        </div>
      ) : (
        !disabled && (
          <div style={{ marginTop: 8 }}>
            <Field label="Reason" htmlFor={`fr-${flag.id}`} hint="Required. Saved in the audit trail.">
              <input id={`fr-${flag.id}`} value={reason} onChange={(e) => setReason(e.target.value)} />
            </Field>
            <div className="btn-row">
              <Button small disabled={!reason.trim() || resolve.isPending} title="The document is fine"
                onClick={() => resolve.mutate("accepted")}>
                It is fine
              </Button>
              <Button small disabled={!reason.trim() || resolve.isPending} title="Ask the joiner to correct and resend"
                onClick={() => resolve.mutate("correction_requested")}>
                Ask for a correction
              </Button>
              <Button small variant="ghost" disabled={!reason.trim() || resolve.isPending}
                title="Not needed for this person" onClick={() => resolve.mutate("waived")}>
                Not needed
              </Button>
            </div>
          </div>
        )
      )}
    </div>
  );
}

function AnnouncementForm({
  caseId,
  disabled,
  onSent,
  onError,
}: {
  caseId: string;
  disabled: boolean;
  onSent: (d: Delivery) => void;
  onError: (e: unknown) => void;
}): ReactNode {
  const [recipients, setRecipients] = useState("");
  const [agreed, setAgreed] = useState(false);
  const send = useMutation({
    mutationFn: () =>
      sendAnnouncement(
        caseId,
        recipients.split(/[\s,;]+/).filter(Boolean),
        agreed,
      ),
    onSuccess: (r) => {
      const first = r.deliveries[0];
      if (first) onSent(first);
    },
    onError,
  });
  return (
    <div style={{ marginTop: 12 }}>
      <Field
        label="Announce to the team (email addresses)"
        htmlFor="ann-to"
        hint="Separate with commas. The announcement shares the joiner's name, role and team only."
      >
        <textarea id="ann-to" value={recipients} onChange={(e) => setRecipients(e.target.value)} disabled={disabled} />
      </Field>
      <div className="checkbox-row">
        <input id="ann-ok" type="checkbox" checked={agreed} onChange={(e) => setAgreed(e.target.checked)} disabled={disabled} />
        <label htmlFor="ann-ok">The joiner agreed to be announced.</label>
      </div>
      <Action
        label="Send team announcement"
        hint="Introduces the new joiner to the people you listed."
        disabled={disabled || !recipients.trim() || !agreed}
        busy={send.isPending}
        onClick={() => send.mutate()}
      />
    </div>
  );
}

function HrmsBlock({ caseId }: { caseId: string }): ReactNode {
  const [show, setShow] = useState(false);
  const preview = useQuery({
    queryKey: ["hrms-preview", caseId],
    queryFn: () => getHrmsPreview(caseId),
    enabled: show,
  });
  return (
    <div style={{ marginBottom: 12 }}>
      <Action
        label={show ? "Hide HR system preview" : "Preview HR system record (ZingHR)"}
        hint="Shows the record that would be sent to ZingHR. Nothing is sent: the connection is a placeholder."
        onClick={() => setShow((s) => !s)}
      />
      {show && preview.data && (
        <div className="assistant-answer assistant-answer--none">
          <p style={{ marginTop: 0 }}>{preview.data.message}</p>
          <pre style={{ margin: 0, overflowX: "auto" }}>{JSON.stringify(preview.data.record, null, 2)}</pre>
        </div>
      )}
    </div>
  );
}
