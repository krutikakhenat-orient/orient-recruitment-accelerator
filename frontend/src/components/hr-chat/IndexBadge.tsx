import { AlertTriangle, CheckCircle2, Circle, Loader2 } from "lucide-react";
import type { ReactNode } from "react";

import type { IndexStatusValue } from "../../api/automation";
import { Badge } from "../ui";

/* Whether the HR chatbot can use a policy version. Always text plus icon, never colour alone
   (Req 3.1, 10.3). */
const LOOK: Record<IndexStatusValue, { label: string; tone: "ok" | "warn" | "danger" | "neutral"; icon: ReactNode }> = {
  ready: { label: "Ready for chatbot", tone: "ok", icon: <CheckCircle2 size={12} aria-hidden="true" /> },
  indexing: { label: "Indexing", tone: "warn", icon: <Loader2 size={12} aria-hidden="true" /> },
  failed: { label: "Index failed", tone: "danger", icon: <AlertTriangle size={12} aria-hidden="true" /> },
  not_indexed: { label: "Not indexed", tone: "neutral", icon: <Circle size={12} aria-hidden="true" /> },
};

export function IndexBadge({ status }: { status: IndexStatusValue }): ReactNode {
  const look = LOOK[status];
  return (
    <Badge tone={look.tone}>
      {look.icon} {look.label}
    </Badge>
  );
}
