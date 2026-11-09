import { useMutation, useQuery, useQueryClient } from "@tanstack/react-query";
import { useState, type ReactNode } from "react";

import {
  approveOffer,
  createOffer,
  issueOffer,
  listJoiningCases,
  listOffers,
  openJoiningCase,
  remindOffer,
  respondOffer,
  withdrawOffer,
  type Offer,
} from "../api/automation";
import { ApiError } from "../api/client";
import { listOutcomes } from "../api/resources";
import { useAuth } from "../app/auth-context";
import { deliveryStatusLabel } from "../components/Messages";
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
  StatusBadge,
} from "../components/ui";

const ACTIVE = new Set(["drafted", "approved", "issued"]);

const STATUS_HELP: Record<string, string> = {
  drafted: "Prepared. A person with approval rights must approve it before it can be sent.",
  approved: "Approved. Send it to the candidate when you are ready.",
  issued: "Sent. Waiting for the candidate's answer.",
  accepted: "The candidate accepted. You can now start their joining case.",
  declined: "The candidate declined.",
  expired: "The answer date passed.",
  withdrawn: "The offer was withdrawn.",
};

/* Offers: prepare -> approve -> send -> record the candidate's answer. Nothing is sent without
   a person pressing the button, and the offer wording itself is never generated or changed
   automatically. */
export function OffersPanel({ onOpenJoining }: { onOpenJoining: () => void }): ReactNode {
  const qc = useQueryClient();
  const toast = useToast();
  const { hasPermission } = useAuth();
  const canDraft = hasPermission("hiring_decision.recommend");
  const canApprove = hasPermission("hiring_decision.approve");
  const [error, setError] = useState<string | null>(null);
  const [drafting, setDrafting] = useState<{ applicationId: string; name: string } | null>(null);
  const [joiningFor, setJoiningFor] = useState<Offer | null>(null);

  const offers = useQuery({ queryKey: ["offers"], queryFn: listOffers });
  const outcomes = useQuery({ queryKey: ["decision-outcomes"], queryFn: listOutcomes });
  const cases = useQuery({ queryKey: ["joining-cases"], queryFn: listJoiningCases });

  const refresh = (): void => {
    void qc.invalidateQueries({ queryKey: ["offers"] });
    void qc.invalidateQueries({ queryKey: ["joining-cases"] });
  };
  const fail = (e: unknown): void =>
    setError(e instanceof ApiError ? e.message : "Something went wrong. Please try again.");

  const act = useMutation({
    mutationFn: (run: () => Promise<Offer>) => run(),
    onSuccess: (o) => {
      setError(null);
      if (o.delivery) {
        toast.push("Message recorded", { tone: "ok", message: deliveryStatusLabel(o.delivery.status) });
      }
      refresh();
    },
    onError: fail,
  });

  const withOffer = new Set((offers.data ?? []).map((o) => o.application_id));
  const waiting = (outcomes.data ?? []).filter(
    (o) => o.outcome === "selected" && !withOffer.has(o.application_id),
  );
  const caseFor = (applicationId: string): boolean =>
    (cases.data ?? []).some((c) => c.application_id === applicationId);

  return (
    <>
      <Banner>
        <strong>How offers work:</strong> 1) prepare the offer, 2) approve it, 3) send it, 4) record
        what the candidate answers. If they accept, start their joining case.
      </Banner>
      {error && <ErrorNote>{error}</ErrorNote>}

      <Card
        title="Selected, no offer yet"
        description="People who were selected in a hiring decision and do not have an offer yet."
      >
        {outcomes.isLoading && <Loading />}
        {outcomes.data && waiting.length === 0 && (
          <Empty>No one is waiting for an offer. Selected candidates show up here.</Empty>
        )}
        {waiting.length > 0 && (
          <div className="table-wrap">
            <table className="data">
              <thead>
                <tr>
                  <th>Candidate</th>
                  <th>Campaign</th>
                  <th />
                </tr>
              </thead>
              <tbody>
                {waiting.map((o) => (
                  <tr key={o.application_id}>
                    <td>{o.candidate_name}</td>
                    <td>{o.campaign_name}</td>
                    <td style={{ textAlign: "right" }}>
                      {canDraft ? (
                        <Button
                          small
                          variant="primary"
                          title="Create a draft offer. Nothing is sent yet."
                          onClick={() =>
                            setDrafting({ applicationId: o.application_id, name: o.candidate_name })
                          }
                        >
                          Prepare offer
                        </Button>
                      ) : (
                        <span className="subtle">Needs offer drafting rights</span>
                      )}
                    </td>
                  </tr>
                ))}
              </tbody>
            </table>
          </div>
        )}
      </Card>

      <Card
        title="Offers"
        description="Every offer and where it stands. Use the buttons to move it to the next step."
      >
        {offers.isLoading && <Loading />}
        {offers.error && <ErrorNote>Could not load offers.</ErrorNote>}
        {offers.data && offers.data.length === 0 && <Empty>No offers yet.</Empty>}
        {offers.data?.map((o) => (
          <div key={o.id} className="doc-row">
            <div>
              <div className="doc-row__name">
                {o.candidate_name ?? "Candidate"} <StatusBadge status={o.status} />
              </div>
              <div className="doc-row__meta">
                {STATUS_HELP[o.status] ?? ""}
                {o.respond_by ? ` Answer by ${o.respond_by}.` : ""}
              </div>
            </div>
            <div className="btn-row">
              {o.status === "drafted" && canApprove && (
                <Button small variant="primary" title="Approve this offer so it can be sent"
                  onClick={() => act.mutate(() => approveOffer(o.id))}>
                  Approve
                </Button>
              )}
              {o.status === "approved" && canApprove && (
                <Button small variant="primary" title="Send the offer message to the candidate"
                  onClick={() => act.mutate(() => issueOffer(o.id))}>
                  Send offer
                </Button>
              )}
              {o.status === "issued" && (
                <>
                  {canDraft && (
                    <Button small title="Send a gentle reminder about the unanswered offer"
                      onClick={() => act.mutate(() => remindOffer(o.id))}>
                      Send reminder
                    </Button>
                  )}
                  {canApprove && (
                    <>
                      <Button small title="Record that the candidate said yes"
                        onClick={() => act.mutate(() => respondOffer(o.id, "accepted"))}>
                        Candidate accepted
                      </Button>
                      <Button small title="Record that the candidate said no"
                        onClick={() => act.mutate(() => respondOffer(o.id, "declined"))}>
                        Candidate declined
                      </Button>
                    </>
                  )}
                </>
              )}
              {o.status === "accepted" &&
                (caseFor(o.application_id) ? (
                  <Button small title="This person already has a joining case"
                    onClick={onOpenJoining}>
                    Open joining case
                  </Button>
                ) : (
                  canApprove && (
                    <Button small variant="primary"
                      title="Start collecting joining documents and details"
                      onClick={() => setJoiningFor(o)}>
                      Start joining case
                    </Button>
                  )
                ))}
              {ACTIVE.has(o.status) && canApprove && (
                <Button small variant="ghost" title="Cancel this offer"
                  onClick={() => act.mutate(() => withdrawOffer(o.id))}>
                  Withdraw
                </Button>
              )}
            </div>
          </div>
        ))}
      </Card>

      {drafting && (
        <DraftOfferModal
          name={drafting.name}
          applicationId={drafting.applicationId}
          onClose={() => setDrafting(null)}
          onDone={() => {
            setDrafting(null);
            refresh();
            toast.push("Draft offer created", { tone: "ok" });
          }}
        />
      )}
      {joiningFor && (
        <StartJoiningModal
          offer={joiningFor}
          onClose={() => setJoiningFor(null)}
          onDone={() => {
            setJoiningFor(null);
            refresh();
            toast.push("Joining case opened", { tone: "ok" });
            onOpenJoining();
          }}
        />
      )}
    </>
  );
}

function DraftOfferModal({
  name,
  applicationId,
  onClose,
  onDone,
}: {
  name: string;
  applicationId: string;
  onClose: () => void;
  onDone: () => void;
}): ReactNode {
  const [respondBy, setRespondBy] = useState("");
  const [notes, setNotes] = useState("");
  const [error, setError] = useState<string | null>(null);
  const create = useMutation({
    mutationFn: () =>
      createOffer({
        application_id: applicationId,
        ...(respondBy ? { respond_by: respondBy } : {}),
        ...(notes.trim() ? { notes: notes.trim() } : {}),
      }),
    onSuccess: onDone,
    onError: (e) => setError(e instanceof ApiError ? e.message : "Could not create the offer."),
  });
  return (
    <Modal
      title={`Prepare offer: ${name}`}
      onClose={onClose}
      footer={
        <>
          <Button onClick={onClose}>Cancel</Button>
          <Button variant="primary" disabled={create.isPending} onClick={() => create.mutate()}>
            {create.isPending ? "Saving…" : "Create draft"}
          </Button>
        </>
      }
    >
      <p className="hint-line">
        This creates a draft only. It must be approved and then sent. The notes below are for HR
        and are never included in the message to the candidate.
      </p>
      {error && <ErrorNote>{error}</ErrorNote>}
      <Field label="Candidate should answer by (optional)" htmlFor="offer-by">
        <input id="offer-by" type="date" value={respondBy} onChange={(e) => setRespondBy(e.target.value)} />
      </Field>
      <Field label="Internal notes (optional)" htmlFor="offer-notes" hint="Visible to HR only.">
        <textarea id="offer-notes" value={notes} onChange={(e) => setNotes(e.target.value)} />
      </Field>
    </Modal>
  );
}

function StartJoiningModal({
  offer,
  onClose,
  onDone,
}: {
  offer: Offer;
  onClose: () => void;
  onDone: () => void;
}): ReactNode {
  const [joiningDate, setJoiningDate] = useState("");
  const [manager, setManager] = useState("");
  const [department, setDepartment] = useState("");
  const [location, setLocation] = useState("");
  const [expectations, setExpectations] = useState("");
  const [error, setError] = useState<string | null>(null);
  const open = useMutation({
    mutationFn: () =>
      openJoiningCase({
        application_id: offer.application_id,
        ...(joiningDate ? { joining_date: joiningDate } : {}),
        ...(manager.trim() ? { reporting_manager: manager.trim() } : {}),
        ...(department.trim() ? { department: department.trim() } : {}),
        ...(location.trim() ? { work_location: location.trim() } : {}),
        ...(expectations.trim() ? { role_expectations: expectations.trim() } : {}),
      }),
    onSuccess: onDone,
    onError: (e) => setError(e instanceof ApiError ? e.message : "Could not open the joining case."),
  });
  return (
    <Modal
      title={`Start joining case: ${offer.candidate_name ?? "Candidate"}`}
      onClose={onClose}
      footer={
        <>
          <Button onClick={onClose}>Cancel</Button>
          <Button variant="primary" disabled={open.isPending} onClick={() => open.mutate()}>
            {open.isPending ? "Opening…" : "Open case and request documents"}
          </Button>
        </>
      }
    >
      <p className="hint-line">
        This sends the candidate the list of documents needed before joining. You can fill the
        details now or later.
      </p>
      {error && <ErrorNote>{error}</ErrorNote>}
      <div className="field-row">
        <Field label="Joining date" htmlFor="join-date">
          <input id="join-date" type="date" value={joiningDate} onChange={(e) => setJoiningDate(e.target.value)} />
        </Field>
        <Field label="Reporting manager" htmlFor="join-mgr">
          <input id="join-mgr" value={manager} onChange={(e) => setManager(e.target.value)} />
        </Field>
        <Field label="Department" htmlFor="join-dept">
          <input id="join-dept" value={department} onChange={(e) => setDepartment(e.target.value)} />
        </Field>
        <Field label="Work location" htmlFor="join-loc">
          <input id="join-loc" value={location} onChange={(e) => setLocation(e.target.value)} />
        </Field>
      </div>
      <Field label="What to expect (goals / KPIs)" htmlFor="join-exp" hint="Shown to the joiner before day one, after HR approves it.">
        <textarea id="join-exp" value={expectations} onChange={(e) => setExpectations(e.target.value)} />
      </Field>
    </Modal>
  );
}
