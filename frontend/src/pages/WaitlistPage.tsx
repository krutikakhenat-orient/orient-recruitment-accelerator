import { useMutation, useQuery, useQueryClient } from "@tanstack/react-query";
import { useState, type ReactNode } from "react";

import { addToWaitlist, listWaitlist, reevaluateApplication, type WaitlistEntry } from "../api/automation";
import { ApiError } from "../api/client";
import { listApplications, listCampaigns } from "../api/resources";
import { JourneyButton } from "../components/JourneyButton";
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
  prettify,
} from "../components/ui";

/* Waitlist: promising candidates kept for later. Re-checking runs the CURRENT approved rules
   again and keeps the original result; it never overwrites it and never contacts the candidate. */
export function WaitlistPage(): ReactNode {
  const qc = useQueryClient();
  const toast = useToast();
  const campaigns = useQuery({ queryKey: ["campaigns"], queryFn: listCampaigns });
  const [campaignId, setCampaignId] = useState("");
  const chosen = campaignId || campaigns.data?.[0]?.id || "";
  const [error, setError] = useState<string | null>(null);
  const [checking, setChecking] = useState<WaitlistEntry | null>(null);
  const [reason, setReason] = useState("");
  const [applicationId, setApplicationId] = useState("");
  const [addReason, setAddReason] = useState("");

  const entries = useQuery({
    queryKey: ["waitlist", chosen],
    queryFn: () => listWaitlist(chosen),
    enabled: chosen !== "",
  });
  const apps = useQuery({
    queryKey: ["applications", chosen],
    queryFn: () => listApplications(chosen),
    enabled: chosen !== "",
  });

  const onWaitlist = new Set((entries.data ?? []).map((e) => e.application_id));
  const candidates = (apps.data ?? []).filter((a) => !onWaitlist.has(a.id));
  const nameOf = (answers: Record<string, unknown>): string =>
    typeof answers["full_name"] === "string" ? (answers["full_name"] as string) : "Candidate";

  const add = useMutation({
    mutationFn: () => addToWaitlist({ application_id: applicationId, reason: addReason.trim() }),
    onSuccess: () => {
      setError(null);
      setApplicationId("");
      setAddReason("");
      toast.push("Added to the waitlist", { tone: "ok" });
      void qc.invalidateQueries({ queryKey: ["waitlist", chosen] });
    },
    onError: (e) => setError(e instanceof ApiError ? e.message : "Could not add to the waitlist."),
  });
  const recheck = useMutation({
    mutationFn: () =>
      reevaluateApplication({
        application_id: checking?.application_id ?? "",
        trigger: "reviewer_requested",
        reason: reason.trim(),
      }),
    onSuccess: (r) => {
      setError(null);
      setChecking(null);
      setReason("");
      toast.push(r.result_changed ? "The result changed" : "The result is the same", {
        tone: "ok",
        message: "The original result is kept. A new result was added next to it.",
      });
    },
    onError: (e) => setError(e instanceof ApiError ? e.message : "Could not re-check."),
  });

  return (
    <>
      <PageHeader
        title="Waitlist"
        description="Keep promising candidates for later. When a place opens, re-check them against the current rules."
      />
      <Banner>
        A re-check adds a new result next to the old one. Nothing is overwritten and the candidate is
        not contacted.
      </Banner>
      {error && <ErrorNote>{error}</ErrorNote>}
      <Field label="Campaign" htmlFor="wl-campaign" hint="Choose the job opening to look at.">
        <select id="wl-campaign" value={chosen} onChange={(e) => setCampaignId(e.target.value)}>
          {campaigns.data?.map((c) => (
            <option key={c.id} value={c.id}>
              {c.name}
            </option>
          ))}
        </select>
      </Field>

      <Card title="On the waitlist" description="Candidates kept for later in this campaign.">
        {entries.isLoading && <Loading />}
        {entries.error && <ErrorNote>Could not load the waitlist. You may not have access.</ErrorNote>}
        {entries.data && entries.data.length === 0 && <Empty>No one is on the waitlist.</Empty>}
        {entries.data?.map((e) => (
          <div key={e.id} className="doc-row">
            <div>
              <div className="doc-row__name">
                {e.candidate_name} <StatusBadge status={e.status} />
              </div>
              <div className="doc-row__meta">
                {e.reason} · added {new Date(e.created_at).toLocaleDateString()} ·{" "}
                {prettify(e.eligibility_state)}
              </div>
            </div>
            <div className="btn-row">
              <JourneyButton applicationId={e.application_id} />
              <Button small title="Run the current approved rules again for this candidate"
                onClick={() => setChecking(e)}>
                Re-check
              </Button>
            </div>
          </div>
        ))}
      </Card>

      <Card
        title="Add a candidate"
        description="Choose someone from this campaign and say why they are being kept."
      >
        <div className="field-row">
          <Field label="Candidate" htmlFor="wl-app">
            <select id="wl-app" value={applicationId} onChange={(e) => setApplicationId(e.target.value)}>
              <option value="">Choose…</option>
              {candidates.map((a) => (
                <option key={a.id} value={a.id}>
                  {nameOf(a.answers)} ({prettify(a.state)})
                </option>
              ))}
            </select>
          </Field>
          <Field label="Reason" htmlFor="wl-reason" hint="Required. Saved in the audit trail.">
            <input id="wl-reason" value={addReason} onChange={(e) => setAddReason(e.target.value)} />
          </Field>
        </div>
        <Button variant="primary" small disabled={!applicationId || !addReason.trim() || add.isPending}
          onClick={() => add.mutate()}>
          {add.isPending ? "Adding…" : "Add to waitlist"}
        </Button>
      </Card>

      {checking && (
        <Modal
          title={`Re-check: ${checking.candidate_name}`}
          onClose={() => setChecking(null)}
          footer={
            <>
              <Button onClick={() => setChecking(null)}>Cancel</Button>
              <Button variant="primary" disabled={!reason.trim() || recheck.isPending} onClick={() => recheck.mutate()}>
                {recheck.isPending ? "Checking…" : "Re-check now"}
              </Button>
            </>
          }
        >
          <p className="hint-line">
            This runs the latest approved rules again. A new result is added; the old one stays.
          </p>
          <Field label="Why are you re-checking?" htmlFor="wl-why" hint="Required. Saved in the audit trail.">
            <input id="wl-why" value={reason} onChange={(e) => setReason(e.target.value)} />
          </Field>
        </Modal>
      )}
    </>
  );
}
