import { useCallback, useEffect, useRef, useState, type ReactNode } from "react";

import { markReady, probeBackend, sleep, useStartupState } from "../lib/startup";
import { StartupBanner, StartupScreen, type StartupPhase } from "./StartupScreen";

// Show "We are starting up" if the first status check has not answered by then. A warm backend
// answers well within this, so users only ever see the short "Loading…" state.
export const STARTING_MESSAGE_AFTER_MS = 1500;
export const POLL_INTERVAL_MS = 2000;
export const SLOW_AFTER_MS = 45_000;

// Pages that need no database (static content) open immediately.
const NO_BACKEND_PATHS = ["/guide"];

function needsBackend(): boolean {
  const path = window.location.pathname;
  return !NO_BACKEND_PATHS.some((p) => path === p || path.startsWith(`${p}/`));
}

/* Holds the app back until the API and its database answer, showing a branded "We are starting
   up" screen instead of a blank page. The database pauses itself when idle to save cost and takes
   a few seconds to resume; the first status check also wakes it. After the app is open, a slim
   banner covers later resumes while requests retry by themselves (see lib/startup.ts). */
export function StartupGate({ children }: { children: ReactNode }): ReactNode {
  const [ready, setReady] = useState<boolean>(() => !needsBackend());
  const [phase, setPhase] = useState<StartupPhase>("loading");
  const [attempt, setAttempt] = useState(0);
  const startedAt = useRef(Date.now());
  const runtimeState = useStartupState();

  useEffect(() => {
    if (ready) return;
    const controller = new AbortController();
    const showStarting = setTimeout(() => {
      setPhase((p) => (p === "loading" ? "starting" : p));
    }, STARTING_MESSAGE_AFTER_MS);

    void (async () => {
      try {
        for (;;) {
          const result = await probeBackend(controller.signal);
          if (result === "ready") {
            markReady();
            setReady(true);
            return;
          }
          // Starting (database resuming) or briefly unreachable: keep the message up and retry.
          const slow = Date.now() - startedAt.current >= SLOW_AFTER_MS;
          setPhase(slow ? "slow" : "starting");
          await sleep(POLL_INTERVAL_MS);
          if (controller.signal.aborted) return;
        }
      } catch {
        /* aborted on unmount or manual retry */
      }
    })();

    return () => {
      clearTimeout(showStarting);
      controller.abort();
    };
  }, [ready, attempt]);

  const retryNow = useCallback(() => {
    startedAt.current = Date.now();
    setPhase("starting");
    setAttempt((n) => n + 1);
  }, []);

  if (!ready) return <StartupScreen phase={phase} onRetry={retryNow} />;
  return (
    <>
      {runtimeState === "starting" && <StartupBanner />}
      {children}
    </>
  );
}
