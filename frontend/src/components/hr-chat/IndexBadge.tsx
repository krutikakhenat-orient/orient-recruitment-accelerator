import { AlertTriangle, CheckCircle2, Circle, Loader2 } from "lucide-react";
import type { ReactNode } from "react";

import type { IndexStatusValue } from "../../api/automation";
import { Badge } from "../ui";

/* Whether the chatbot can answer from a published policy yet. Always words plus an icon,
   never colour alone (Req 3.1, 10.3). */
export const SYNC_LOOK: Record<
  IndexStatusValue,
  { label: string; tone: "ok" | "warn" | "danger" | "neutral"; icon: ReactNode; help: string }
> = {
  ready: {
    label: "Synced to chatbot",
    tone: "ok",
    icon: <CheckCircle2 size={12} aria-hidden="true" />,
    help: "The chatbot can answer from this version.",
  },
  indexing: {
    label: "Syncing…",
    tone: "warn",
    icon: <Loader2 size={12} aria-hidden="true" className="spin-icon" />,
    help: "Usually under a minute. This page updates by itself.",
  },
  failed: {
    label: "Sync failed",
    tone: "danger",
    icon: <AlertTriangle size={12} aria-hidden="true" />,
    help: "The chatbot is not using this version. Read the reason and retry.",
  },
  not_indexed: {
    label: "Not synced",
    tone: "neutral",
    icon: <Circle size={12} aria-hidden="true" />,
    help: "The chatbot is not using this yet. Click Sync now.",
  },
};

export function IndexBadge({ status }: { status: IndexStatusValue }): ReactNode {
  const look = SYNC_LOOK[status];
  return (
    <span title={look.help}>
      <Badge tone={look.tone}>
        {look.icon} {look.label}
      </Badge>
    </span>
  );
}
