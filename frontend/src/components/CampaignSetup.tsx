/* Campaign setup UI: the "Set up this job" checklist, the next-step banner shown above the
   tabs, and the apply-link strip shown once a job is open.

   HR sees four plain jobs to do instead of ~12 lifecycle states. The checklist is computed
   server-side (GET /campaigns/{id}/setup-status); "Open for applications" calls one backend
   action that still runs every internal step through the audited TransitionService. */

import { useMutation, useQuery, useQueryClient } from "@tanstack/react-query";
import { ArrowRight, Check, Copy, ExternalLink, Lock, Mail, QrCode as QrIcon, Rocket } from "lucide-react";
import { useState, type ReactNode } from "react";

import { ApiError } from "../api/client";
import {
  getCampaignSetupStatus,
  openForApplications,
  type Campaign,
  type CampaignSetupStatus,
  type SetupStep,
} from "../api/resources";
import { useAuth } from "../app/auth-context";
import { SETUP_STATUS_LABEL, setupProgress } from "../lib/campaignStatus";
import { QrCode, qrDataUri } from "./QrCode";
import { useToast } from "./toast";
import { Badge, Button, Card, ErrorNote, Loading, Modal } from "./ui";

/** Where a checklist step sends the user (an anchor inside the Setup tab). */
export type SetupSection = "setup-jd" | "setup-form";

export const setupStatusKey = (campaignId: string) => ["campaign", campaignId, "setup"] as const;

/** Loads the checklist when the signed-in user is allowed to see it. */
export function useSetupStatus(campaignId: string) {
  const { hasPermission, canAccessCampaign } = useAuth();
  const allowed =
    canAccessCampaign(campaignId) && (hasPermission("campaign.edit") || hasPermission("campaign.publish"));
  const query = useQuery({
    queryKey: setupStatusKey(campaignId),
    queryFn: () => getCampaignSetupStatus(campaignId),
    enabled: allowed,
  });
  return { ...query, allowed };
}

function useOpenForApplications(campaignId: string, onOpened?: () => void) {
  const qc = useQueryClient();
  const toast = useToast();
  return useMutation({
    mutationFn: () => openForApplications(campaignId),
    onSuccess: () => {
      void qc.invalidateQueries({ queryKey: ["campaign", campaignId] });
      void qc.invalidateQueries({ queryKey: ["campaigns"] });
      toast.push("The job is open. Share the apply link with candidates.", { tone: "ok" });
      onOpened?.();
    },
  });
}

/* Confirmation before going live: candidates can apply as soon as this succeeds. */
function OpenConfirm({
  campaignId,
  title,
  onClose,
}: {
  campaignId: string;
  title: string;
  onClose: () => void;
}): ReactNode {
  const open = useOpenForApplications(campaignId, onClose);
  return (
    <Modal
      title="Open this job for applications?"
      onClose={onClose}
      footer={
        <>
          <Button variant="default" onClick={onClose}>
            Not yet
          </Button>
          <Button variant="accent" disabled={open.isPending} onClick={() => open.mutate()}>
            {open.isPending ? "Opening…" : "Open for applications"}
          </Button>
        </>
      }
    >
      {open.error && (
        <ErrorNote>{open.error instanceof ApiError ? open.error.message : "Could not open the job."}</ErrorNote>
      )}
      <p className="mt-0">
        <strong>{title}</strong> becomes visible to candidates and you get the apply link to share.
      </p>
      <ul className="next-list" style={{ margin: "8px 0 0" }}>
        <li>Candidates apply with the link or QR code. No account needed.</li>
        <li>Each application is screened against the approved criteria.</li>
        <li>You can pause or close applications any time under Settings.</li>
      </ul>
    </Modal>
  );
}

function StepAction({
  step,
  isNext,
  campaignId,
  onGo,
  onOpen,
}: {
  step: SetupStep;
  isNext: boolean;
  campaignId: string;
  onGo: (section: SetupSection) => void;
  onOpen: () => void;
}): ReactNode {
  const { hasPermission, canAccessCampaign } = useAuth();
  const assigned = canAccessCampaign(campaignId);
  const variant = isNext ? "accent" : "default";

  if (step.status === "done") {
    return (
      <Badge tone="ok">
        <Check size={12} aria-hidden="true" className="inline-icon" />
        Done
      </Badge>
    );
  }
  if (step.status === "waiting") return <Badge tone="neutral">{SETUP_STATUS_LABEL.waiting}</Badge>;

  switch (step.key) {
    case "upload_jd":
      return (
        <Button variant={variant} small onClick={() => onGo("setup-jd")}>
          Upload JD <ArrowRight size={14} aria-hidden="true" className="inline-icon" />
        </Button>
      );
    case "approve_jd":
      return hasPermission("jd.approve") && assigned ? (
        <Button variant={variant} small onClick={() => onGo("setup-jd")}>
          Review &amp; approve <ArrowRight size={14} aria-hidden="true" className="inline-icon" />
        </Button>
      ) : (
        <Button variant="default" small onClick={() => onGo("setup-jd")} title="A Recruiter Admin approves the JD">
          Waiting for approver · view
        </Button>
      );
    case "form":
      return (
        <Button variant={variant} small onClick={() => onGo("setup-form")}>
          {step.status === "needs_approver" ? "Approve form" : "Create form"}{" "}
          <ArrowRight size={14} aria-hidden="true" className="inline-icon" />
        </Button>
      );
    case "open":
      return hasPermission("campaign.publish") && assigned ? (
        <Button variant="accent" small onClick={onOpen}>
          <Rocket size={14} aria-hidden="true" className="inline-icon" />
          Open for applications
        </Button>
      ) : (
        <Badge tone="warn">
          <Lock size={12} aria-hidden="true" className="inline-icon" />
          A Recruiter Admin opens it
        </Badge>
      );
    default:
      return <Badge tone="warn">{SETUP_STATUS_LABEL[step.status]}</Badge>;
  }
}

/* The full checklist, shown at the top of the Setup tab. */
export function SetupChecklist({
  campaign,
  onGo,
}: {
  campaign: Campaign;
  onGo: (section: SetupSection) => void;
}): ReactNode {
  const setup = useSetupStatus(campaign.id);
  const [confirmOpen, setConfirmOpen] = useState(false);

  if (!setup.allowed) {
    return (
      <Card title="Set up this job" description="Four steps take a job from draft to accepting applications.">
        <p className="subtle mt-0">
          <Lock size={14} aria-hidden="true" className="inline-icon" />
          You need to be assigned to this job (Settings → <strong>Assign me</strong>) with a Recruiter or
          Recruiter Admin role to work on its setup.
        </p>
      </Card>
    );
  }
  if (setup.isLoading) return <Loading label="Checking setup…" />;
  if (setup.error || !setup.data) return <ErrorNote>Could not load the setup checklist.</ErrorNote>;

  const status: CampaignSetupStatus = setup.data;
  const progress = setupProgress(status.steps);
  const pct = Math.round((progress.done / progress.total) * 100);

  return (
    <Card
      title={status.next_step_key ? "Set up this job" : "Setup complete"}
      description={
        status.next_step_key
          ? "Do these steps to start taking applications. The highlighted step is next."
          : "Everything is approved and the job is live."
      }
    >
      <div className="setup-progress">
        <div
          className="progress"
          role="progressbar"
          aria-label="Setup progress"
          aria-valuemin={0}
          aria-valuemax={progress.total}
          aria-valuenow={progress.done}
        >
          <div className="progress__fill" style={{ width: `${pct}%` }} />
        </div>
        <span className="setup-progress__text">
          {progress.done} of {progress.total} done
        </span>
      </div>
      <ol className="setup-steps">
        {status.steps.map((step, i) => {
          const isNext = step.key === status.next_step_key;
          const cls = [
            "setup-step",
            step.status === "done" ? "setup-step--done" : "",
            isNext ? "setup-step--next" : "",
            step.status === "waiting" ? "setup-step--waiting" : "",
          ]
            .filter(Boolean)
            .join(" ");
          return (
            <li key={step.key} className={cls} aria-current={isNext ? "step" : undefined}>
              <span className="setup-step__dot" aria-hidden="true">
                {step.status === "done" ? <Check size={16} /> : i + 1}
              </span>
              <div>
                <div className="setup-step__title">
                  {step.title}
                  {isNext && <Badge tone="info">Next step</Badge>}
                  {step.status === "needs_approver" && <Badge tone="warn">{SETUP_STATUS_LABEL.needs_approver}</Badge>}
                </div>
                <div className="setup-step__desc">{step.description}</div>
                <div className="setup-step__who">Who: {step.who}</div>
              </div>
              <div className="setup-step__action">
                <StepAction
                  step={step}
                  isNext={isNext}
                  campaignId={campaign.id}
                  onGo={onGo}
                  onOpen={() => setConfirmOpen(true)}
                />
              </div>
            </li>
          );
        })}
      </ol>
      {confirmOpen && (
        <OpenConfirm campaignId={campaign.id} title={campaign.position_title} onClose={() => setConfirmOpen(false)} />
      )}
    </Card>
  );
}

/* A one-line "what to do next" banner shown above the tabs while a job is being set up. */
export function NextStepBanner({
  campaign,
  onGo,
}: {
  campaign: Campaign;
  onGo: () => void;
}): ReactNode {
  const setup = useSetupStatus(campaign.id);
  if (!setup.data || !setup.data.next_step_key) return null;
  const progress = setupProgress(setup.data.steps);
  if (!progress.next) return null;
  return (
    <div className="next-banner" role="status">
      <div className="next-banner__text">
        <div>
          <span className="next-banner__label">
            Next step {progress.nextNumber} of {progress.total}
          </span>
          <strong>{progress.next.title}</strong>
          <span className="subtle"> · {progress.next.who}</span>
        </div>
      </div>
      <Button variant="accent" small onClick={onGo}>
        Go to setup <ArrowRight size={14} aria-hidden="true" className="inline-icon" />
      </Button>
    </div>
  );
}

/* The apply link, shown at the top of the page whenever candidates can apply. */
export function ApplyLinkStrip({ campaign }: { campaign: Campaign }): ReactNode {
  const toast = useToast();
  const [showQr, setShowQr] = useState(false);
  const applyPath = `/apply/${campaign.id}`;
  const applyUrl = `${window.location.origin}${applyPath}`;
  const copy = (): void => {
    void navigator.clipboard
      ?.writeText(applyUrl)
      .then(() => toast.push("Apply link copied", { tone: "ok" }))
      .catch(() => toast.push("Could not copy. Select the link and copy it.", { tone: "danger" }));
  };
  const qrUri = showQr ? qrDataUri(applyUrl) : null;

  return (
    <div className="apply-strip">
      <span className="apply-strip__label">
        <Check size={16} aria-hidden="true" /> Open · Apply link
      </span>
      <label htmlFor={`apply-url-${campaign.id}`} className="sr-only">
        Public apply link
      </label>
      <input id={`apply-url-${campaign.id}`} readOnly value={applyUrl} onFocus={(e) => e.currentTarget.select()} />
      <Button variant="primary" small onClick={copy}>
        <Copy size={14} aria-hidden="true" className="inline-icon" />
        Copy link
      </Button>
      <Button variant="default" small onClick={() => setShowQr(true)}>
        <QrIcon size={14} aria-hidden="true" className="inline-icon" />
        QR code
      </Button>
      <a
        className="btn btn--default btn--sm"
        href={`mailto:?subject=${encodeURIComponent(`Apply: ${campaign.position_title}`)}&body=${encodeURIComponent(
          `Apply for ${campaign.position_title} here: ${applyUrl}`,
        )}`}
      >
        <Mail size={14} aria-hidden="true" className="inline-icon" />
        Email
      </a>
      <a className="btn btn--ghost btn--sm" href={applyPath} target="_blank" rel="noreferrer">
        <ExternalLink size={14} aria-hidden="true" className="inline-icon" />
        Preview
      </a>
      {showQr && (
        <Modal
          title="Scan to apply"
          onClose={() => setShowQr(false)}
          footer={
            <>
              {qrUri && (
                <a
                  className="btn btn--default"
                  href={qrUri}
                  download={`apply-qr-${campaign.position_title.replace(/\s+/g, "-").toLowerCase()}.svg`}
                >
                  Download QR
                </a>
              )}
              <Button variant="primary" onClick={() => setShowQr(false)}>
                Done
              </Button>
            </>
          }
        >
          <div style={{ display: "grid", placeItems: "center", gap: 8 }}>
            <QrCode value={applyUrl} size={200} title={`Apply: ${campaign.position_title}`} />
            <p className="subtle mb-0">Print it on a flyer or show it on screen at a walk-in drive.</p>
          </div>
        </Modal>
      )}
    </div>
  );
}
