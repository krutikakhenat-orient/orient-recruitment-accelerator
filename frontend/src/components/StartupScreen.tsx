import type { ReactNode } from "react";

import { Logo } from "./Logo";

export type StartupPhase = "loading" | "starting" | "slow";

/* Full-page, branded placeholder shown instead of a blank page while the app (or its database,
   which pauses itself when idle) gets ready. Announced politely to screen readers; the spinner
   is decorative and stops for users who prefer reduced motion (global CSS rule). */
export function StartupScreen({
  phase,
  onRetry,
}: {
  phase: StartupPhase;
  onRetry?: () => void;
}): ReactNode {
  const starting = phase !== "loading";
  return (
    <div className="startup-screen" role="status" aria-live="polite" aria-busy="true">
      <div className="startup-screen__card">
        <Logo size={56} title="Orient Recruitment Accelerator" />
        <span className="startup-screen__spinner" aria-hidden="true" />
        {starting ? (
          <>
            <h1 className="startup-screen__title">We are starting up</h1>
            <p className="startup-screen__text">
              {phase === "slow"
                ? "This is taking longer than usual. We will keep trying."
                : "This usually takes a few seconds. The page will open on its own."}
            </p>
            {phase === "slow" && onRetry && (
              <button type="button" className="btn btn--sm" onClick={onRetry}>
                Try again now
              </button>
            )}
          </>
        ) : (
          <p className="startup-screen__text">Loading…</p>
        )}
      </div>
    </div>
  );
}

/* Slim notice shown on top of an open page when a request finds the database resuming after
   an idle period. The request continues by itself; nothing for the user to do. */
export function StartupBanner(): ReactNode {
  return (
    <div className="startup-banner" role="status" aria-live="polite">
      <span className="startup-screen__spinner startup-screen__spinner--small" aria-hidden="true" />
      We are starting up. Your request will continue in a few seconds.
    </div>
  );
}
