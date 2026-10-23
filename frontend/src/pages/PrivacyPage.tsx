import { useState, type ReactNode } from "react";
import { z } from "zod";

import { apiFetch, ApiError } from "../api/client";
import { useToast } from "../components/toast";
import { Button, Card, ErrorNote, Field } from "../components/ui";

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
      <div className="page-head">
        <h1>Privacy &amp; Retention</h1>
        <p>
          Configure retention per record category and manage candidate privacy requests. Every
          retention action is logged. These are technical controls that support compliance — not a
          legal determination.
        </p>
      </div>

      {error && <ErrorNote>{error}</ErrorNote>}

      <Card title="Retention policy">
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

      <Card title="Candidate rights">
        <p className="subtle" style={{ marginTop: 0 }}>
          Privacy requests (access/export, correction, deletion, processing restriction, consent
          withdrawal) are created against a candidate id and have an auditable lifecycle. Use the API
          explorer at <code>/api/v1/privacy/requests</code> to raise one for a specific candidate.
        </p>
        <ul className="subtle" style={{ marginTop: 8, paddingLeft: 18, lineHeight: 1.9 }}>
          <li>Talent-pool consent can be withdrawn at any time.</li>
          <li>Corrections preserve the original extracted value plus a reason.</li>
          <li>Destructive retention actions run only after an owner-notification window.</li>
        </ul>
      </Card>
    </>
  );
}
