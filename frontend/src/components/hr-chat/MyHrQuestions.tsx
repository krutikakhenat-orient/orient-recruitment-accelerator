import { useQuery } from "@tanstack/react-query";
import type { ReactNode } from "react";

import { listMyHrQuestions } from "../../api/automation";
import { Button, Empty, ErrorNote, Loading, StatusBadge } from "../ui";

const LABEL = { open: "Waiting for HR", answered: "Answered", closed: "Closed" } as const;

/* Questions the signed-in person sent to HR, and HR's replies. */
export function MyHrQuestions(): ReactNode {
  const q = useQuery({ queryKey: ["my-hr-questions"], queryFn: listMyHrQuestions });
  if (q.isLoading) return <Loading label="Loading your questions…" />;
  if (q.isError) {
    return (
      <ErrorNote>
        Your questions could not be loaded.{" "}
        <Button small onClick={() => void q.refetch()}>Try again</Button>
      </ErrorNote>
    );
  }
  if (!q.data?.length) return <Empty>You have not sent any questions to HR yet.</Empty>;
  return (
    <ul className="hr-chat__mine">
      {q.data.map((item) => (
        <li key={item.id} className="doc-row">
          <div>
            <div className="doc-row__name">
              {item.question} <StatusBadge status={item.status === "open" ? "requested" : "done"}
                label={LABEL[item.status]} />
            </div>
            <div className="doc-row__meta">Sent {new Date(item.created_at).toLocaleDateString()}</div>
            {item.answer && <p style={{ whiteSpace: "pre-wrap", margin: "6px 0 0" }}>{item.answer}</p>}
          </div>
        </li>
      ))}
    </ul>
  );
}
