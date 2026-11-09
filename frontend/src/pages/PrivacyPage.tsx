import { useMutation, useQuery, useQueryClient } from "@tanstack/react-query";
import { useState, type ReactNode } from "react";
import { Link, useSearchParams } from "react-router-dom";
import { z } from "zod";

import { completePrivacyRequest, createPrivacyRequest, listPrivacyRequests } from "../api/automation";
import { apiFetch, ApiError } from "../api/client";
import { useToast } from "../components/toast";
import {
  Button,
  Card,
  Empty,
  ErrorNote,
  Field,
  Loading,
  PageHeader,
  StatusBadge,
  Tabs,
} from "../components/ui";

const retentionPolicy = z.object({ id: z.string(), category: z.string(), retain_days: z.number(), action_on_expiry: z.string() });

const CATEGORIES = [
  "candidate_identity",
  "campaign_application",
  "resume",
  "screening_result",
  "interview_assessment",
  "candidate_communication",
  "talent_pool_record",
  "audit_evidence",
  "security_log",
];
const ACTIONS = ["notify_owner", "restrict_access", "delete", "anonymise", "legal_hold"];

export function PrivacyPage(): ReactNode {
  const [params, setParams] = useSearchParams();
  const rawTab = params.get("tab");
  const tab = rawTab === "rights" || rawTab === "requests" ? rawTab : "retention";
  const toast = useToast();
  const [error, setError] = useState<string | null>(null);

  const [category, setCategory] = useState(CATEGORIES[0]);
  const [retainDays, setRetainDays] = useState(180);
  const [action, setAction] = useState(ACTIONS[0]);
  const [savingPolicy, setSavingPolicy] = useState(false);

  const savePolicy = async (): Promise<void> => {
    setSavingPolicy(true);
    setError(null);
    try {
      await apiFetch("/api/v1/privacy/retention-policies", retentionPolicy, {
        method: "POST",
        body: JSON.stringify({ category, retain_days: retainDays, action_on_expiry: action }),
      });
      toast.push("Retention policy saved", { tone: "ok" });
    } catch (e) {
      setError(e instanceof ApiError ? e.message : "Could not save policy (requires system.configure).");
    } finally {
      setSavingPolicy(false);
    }
  };

  return (
    <>
      <Link to="/settings" className="back-link">
        ← Settings
      </Link>
      <PageHeader
        title="Privacy & retention"
        description="Configure retention per record category and manage candidate privacy requests. Every retention action is logged. These are technical controls that support compliance, not a legal determination."
      />
      <Tabs
        label="Privacy sections"
        value={tab}
        onChange={(t) => setParams({ tab: t }, { replace: true })}
        tabs={[
          { id: "retention", label: "Retention policy" },
          { id: "requests", label: "Privacy requests" },
          { id: "rights", label: "Candidate rights" },
        ]}
      />

      {error && <ErrorNote>{error}</ErrorNote>}

      {tab === "retention" && (
      <Card
        title="Retention policy"
        description="How long each kind of record is kept, and what happens when that time is up."
      >
        <div className="grid grid--3">
          <Field label="Record category" htmlFor="rp-cat">
            <select id="rp-cat" value={category} onChange={(e) => setCategory(e.target.value)}>
              {CATEGORIES.map((c) => (
                <option key={c} value={c}>
                  {c.replace(/_/g, " ")}
                </option>
              ))}
            </select>
          </Field>
          <Field label="Retain for (days)" htmlFor="rp-days">
            <input id="rp-days" type="number" min={0} value={retainDays} onChange={(e) => setRetainDays(Number(e.target.value))} />
          </Field>
          <Field label="Action on expiry" htmlFor="rp-act">
            <select id="rp-act" value={action} onChange={(e) => setAction(e.target.value)}>
              {ACTIONS.map((a) => (
                <option key={a} value={a}>
                  {a.replace(/_/g, " ")}
                </option>
              ))}
            </select>
          </Field>
        </div>
        <Button variant="primary" small disabled={savingPolicy} onClick={() => void savePolicy()}>
          {savingPolicy ? "Saving…" : "Save policy"}
        </Button>
      </Card>
      )}

      {tab === "rights" && (
      <Card
        title="Candidate rights"
        description="What candidates are entitled to, and how a request is handled."
      >
        <p className="subtle" style={{ marginTop: 0 }}>
          Privacy requests (access or export, correction, deletion, processing restriction, consent
          withdrawal) are raised on the "Privacy requests" tab using the email address the person
          applied with. Each one has an auditable lifecycle.
        </p>
        <ul className="subtle" style={{ marginTop: 8, paddingLeft: 18, lineHeight: 1.9 }}>
          <li>Talent-pool consent can be withdrawn at any time.</li>
          <li>Corrections preserve the original extracted value plus a reason.</li>
          <li>Destructive retention actions run only after an owner-notification window.</li>
        </ul>
      </Card>
      )}

      {tab === "requests" && <PrivacyRequests />}
    </>
  );
}

const REQUEST_TYPES: { value: string; label: string }[] = [
  { value: "access_export", label: "Access or export their data" },
  { value: "correction", label: "Correct their data" },
  { value: "deletion", label: "Delete their data" },
  { value: "processing_restriction", label: "Restrict how their data is used" },
  { value: "consent_withdrawal", label: "Withdraw consent" },
];

/* Raise and close privacy requests. The person is found by the email they applied with. The
   list shows the email masked, so managing requests never exposes contact details. */
function PrivacyRequests(): ReactNode {
  const qc = useQueryClient();
  const toast = useToast();
  const [email, setEmail] = useState("");
  const [type, setType] = useState(REQUEST_TYPES[0]?.value ?? "access_export");
  const [detail, setDetail] = useState("");
  const [error, setError] = useState<string | null>(null);
  const requests = useQuery({ queryKey: ["privacy-requests"], queryFn: listPrivacyRequests });

  const create = useMutation({
    mutationFn: () =>
      createPrivacyRequest({
        candidate_email: email.trim(),
        request_type: type,
        ...(detail.trim() ? { detail: detail.trim() } : {}),
      }),
    onSuccess: () => {
      setError(null);
      setEmail("");
      setDetail("");
      toast.push("Request recorded", { tone: "ok" });
      void qc.invalidateQueries({ queryKey: ["privacy-requests"] });
    },
    onError: (e) => setError(e instanceof ApiError ? e.message : "Could not record the request."),
  });
  const complete = useMutation({
    mutationFn: (id: string) => completePrivacyRequest(id),
    onSuccess: () => {
      toast.push("Request closed", { tone: "ok" });
      void qc.invalidateQueries({ queryKey: ["privacy-requests"] });
    },
    onError: (e) => setError(e instanceof ApiError ? e.message : "Could not close the request."),
  });

  return (
    <>
      {error && <ErrorNote>{error}</ErrorNote>}
      <Card
        title="Record a request"
        description="Use this when a candidate asks to see, correct, restrict or delete their data."
      >
        <div className="field-row">
          <Field label="Email the person applied with" htmlFor="pr-email">
            <input id="pr-email" type="email" value={email} onChange={(e) => setEmail(e.target.value)} />
          </Field>
          <Field label="What they asked for" htmlFor="pr-type">
            <select id="pr-type" value={type} onChange={(e) => setType(e.target.value)}>
              {REQUEST_TYPES.map((t) => (
                <option key={t.value} value={t.value}>
                  {t.label}
                </option>
              ))}
            </select>
          </Field>
        </div>
        <Field label="Notes (optional)" htmlFor="pr-detail">
          <input id="pr-detail" value={detail} onChange={(e) => setDetail(e.target.value)} />
        </Field>
        <Button variant="primary" small disabled={!email.trim() || create.isPending} onClick={() => create.mutate()}>
          {create.isPending ? "Saving…" : "Record request"}
        </Button>
      </Card>
      <Card title="Requests" description="Open requests first. Close a request once it has been dealt with.">
        {requests.isLoading && <Loading />}
        {requests.data && requests.data.length === 0 && <Empty>No privacy requests yet.</Empty>}
        {requests.data?.map((r) => (
          <div key={r.id} className="doc-row">
            <div>
              <div className="doc-row__name">
                {REQUEST_TYPES.find((t) => t.value === r.request_type)?.label ?? r.request_type}{" "}
                <StatusBadge status={r.status === "completed" ? "done" : "requested"} label={r.status === "completed" ? "Closed" : "Open"} />
              </div>
              <div className="doc-row__meta">
                {r.candidate_email_masked} · {new Date(r.created_at).toLocaleDateString()}
                {r.detail ? ` · ${r.detail}` : ""}
              </div>
            </div>
            {r.status !== "completed" && (
              <Button small title="Mark this request as dealt with" disabled={complete.isPending}
                onClick={() => complete.mutate(r.id)}>
                Close request
              </Button>
            )}
          </div>
        ))}
      </Card>
    </>
  );
}
