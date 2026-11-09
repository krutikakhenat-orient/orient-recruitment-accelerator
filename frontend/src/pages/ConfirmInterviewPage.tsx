import { useMutation, useQuery } from "@tanstack/react-query";
import { useState, type ReactNode } from "react";
import { useParams } from "react-router-dom";

import { getConfirmationPreview, respondToConfirmation } from "../api/automation";
import { ApiError } from "../api/client";
import { Logo } from "../components/Logo";
import { Button, ErrorNote, Loading } from "../components/ui";

/* The page a candidate opens from their personal link (no login). It shows the role and the
   time, and lets them confirm, ask for another time, or say they cannot attend. The link works
   once. Only the first name is shown because the link is a secret anyone holding it could open. */
export function ConfirmInterviewPage(): ReactNode {
  const { token = "" } = useParams();
  const [result, setResult] = useState<string | null>(null);
  const [error, setError] = useState<string | null>(null);

  const preview = useQuery({
    queryKey: ["confirm-preview", token],
    queryFn: () => getConfirmationPreview(token),
    retry: false,
  });
  const reply = useMutation({
    mutationFn: (response: "confirmed" | "declined" | "reschedule_requested") =>
      respondToConfirmation(token, response),
    onSuccess: (r) => {
      setError(null);
      setResult(r.message);
    },
    onError: (e) =>
      setError(e instanceof ApiError ? e.message : "Sorry, we could not save your reply."),
  });

  const p = preview.data;
  return (
    <main className="apply-shell" id="main">
      <div className="apply-brandbar">
        <Logo size={34} title="Orient Recruitment Accelerator" />
        <span className="apply-brandbar__name">Orient</span>
      </div>
      <section className="card apply-card" aria-labelledby="confirm-heading">
        <h1 id="confirm-heading">Your interview</h1>
        {preview.isLoading && <Loading label="Opening your invitation…" />}
        {preview.error && (
          <ErrorNote>This link is not valid or has expired. Please contact the HR team.</ErrorNote>
        )}
        {p && !result && p.state === "open" && (
          <>
            <p>Hello {p.first_name}, you are invited to an interview for <strong>{p.role_title}</strong>.</p>
            <dl className="kv" style={{ marginBottom: 16 }}>
              <dt>When</dt>
              <dd>{p.when}</dd>
              <dt>Where</dt>
              <dd>{p.where}</dd>
              <dt>How</dt>
              <dd>{p.mode}</dd>
            </dl>
            <p className="hint-line">Please tell us if you can come. You can answer once.</p>
            {error && <ErrorNote>{error}</ErrorNote>}
            <div className="btn-row">
              <Button variant="primary" disabled={reply.isPending} onClick={() => reply.mutate("confirmed")}>
                Yes, I can attend
              </Button>
              <Button disabled={reply.isPending} onClick={() => reply.mutate("reschedule_requested")}>
                I need a different time
              </Button>
              <Button variant="ghost" disabled={reply.isPending} onClick={() => reply.mutate("declined")}>
                I can't attend
              </Button>
            </div>
          </>
        )}
        {p && !result && p.state === "answered" && <p>{p.message}</p>}
        {p && !result && p.state === "expired" && (
          <ErrorNote>This link has expired. Please contact the HR team.</ErrorNote>
        )}
        {result && (
          <p role="status" style={{ fontWeight: 600 }}>
            {result}
          </p>
        )}
      </section>
    </main>
  );
}
