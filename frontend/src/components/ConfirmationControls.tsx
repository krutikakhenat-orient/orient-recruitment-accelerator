import { useMutation, useQuery, useQueryClient } from "@tanstack/react-query";
import { useState, type ReactNode } from "react";

import {
  getLinkStatus,
  getSuggestedSlots,
  issueConfirmationLink,
  remindInterview,
} from "../api/automation";
import { ApiError } from "../api/client";
import { deliveryStatusLabel } from "./Messages";
import { useToast } from "./toast";
import { Button, ErrorNote, prettify } from "./ui";

/* Interview confirmation for one invitation: send the candidate a personal link, see their
   reply, send a reminder, and look at open slots. The reply also tells the interviewer. */
export function ConfirmationControls({ invitationId }: { invitationId: string }): ReactNode {
  const qc = useQueryClient();
  const toast = useToast();
  const [error, setError] = useState<string | null>(null);
  const [link, setLink] = useState<string | null>(null);
  const [showSlots, setShowSlots] = useState(false);

  const status = useQuery({
    queryKey: ["confirmation-status", invitationId],
    queryFn: () => getLinkStatus(invitationId),
  });
  const slots = useQuery({
    queryKey: ["suggested-slots", invitationId],
    queryFn: () => getSuggestedSlots(invitationId),
    enabled: showSlots,
  });

  const refresh = (): void => {
    void qc.invalidateQueries({ queryKey: ["confirmation-status", invitationId] });
  };
  const fail = (e: unknown): void =>
    setError(e instanceof ApiError ? e.message : "Something went wrong. Please try again.");

  const issue = useMutation({
    mutationFn: (send: boolean) => issueConfirmationLink(invitationId, send),
    onSuccess: (r, send) => {
      setError(null);
      setLink(r.url);
      if (send && r.delivery) {
        toast.push("Confirmation link recorded", {
          tone: "ok",
          message: deliveryStatusLabel(r.delivery.status),
        });
      }
      refresh();
    },
    onError: fail,
  });
  const remind = useMutation({
    mutationFn: () => remindInterview(invitationId),
    onSuccess: (d) => {
      setError(null);
      toast.push("Reminder recorded", { tone: "ok", message: deliveryStatusLabel(d.status) });
    },
    onError: fail,
  });

  const copy = async (): Promise<void> => {
    if (!link) return;
    try {
      await navigator.clipboard.writeText(link);
      toast.push("Link copied", { tone: "ok" });
    } catch {
      toast.push("Copy the link from the box", { tone: "info" });
    }
  };

  return (
    <div style={{ textAlign: "left", minWidth: 220 }}>
      {error && <ErrorNote>{error}</ErrorNote>}
      {status.data && <p className="doc-row__meta" style={{ margin: "0 0 6px" }}>{status.data.message}</p>}
      <div className="btn-row">
        <Button small title="Create the candidate's personal link and send it to them"
          disabled={issue.isPending} onClick={() => issue.mutate(true)}>
          {status.data?.has_link ? "Send a new link" : "Send confirmation link"}
        </Button>
        <Button small variant="ghost" title="Create a link without sending it, so you can share it yourself"
          disabled={issue.isPending} onClick={() => issue.mutate(false)}>
          Get link only
        </Button>
        <Button small variant="ghost" title="Send the candidate a reminder about this interview"
          disabled={remind.isPending} onClick={() => remind.mutate()}>
          Send reminder
        </Button>
        <Button small variant="ghost" title="Show open interview slots with room left"
          onClick={() => setShowSlots((s) => !s)}>
          {showSlots ? "Hide slots" : "Suggest slots"}
        </Button>
      </div>
      {link && (
        <div style={{ marginTop: 6 }}>
          <input readOnly aria-label="Candidate's personal link" value={link}
            onFocus={(e) => e.currentTarget.select()} />
          <Button small variant="ghost" onClick={() => void copy()}>
            Copy
          </Button>
        </div>
      )}
      {showSlots && (
        <div style={{ marginTop: 6 }}>
          {slots.isLoading && <span className="subtle">Looking…</span>}
          {slots.data && slots.data.length === 0 && (
            <p className="doc-row__meta">No open slots. Create one under "Stages & slots".</p>
          )}
          {slots.data?.map((s) => (
            <p key={s.slot_id} className="doc-row__meta" style={{ margin: "2px 0" }}>
              {s.slot_date} {s.start_time} · {s.stage_name} · {prettify(s.mode)}
              {s.location ? ` · ${s.location}` : ""} · {s.remaining} place(s) left
            </p>
          ))}
          <p className="doc-row__meta">
            Slots come from the ones you created. A calendar connection is not set up yet.
          </p>
        </div>
      )}
    </div>
  );
}
