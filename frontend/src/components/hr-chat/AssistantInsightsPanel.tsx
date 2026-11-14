import { useQuery } from "@tanstack/react-query";
import { useId, useState, type ReactNode } from "react";

import { getAssistantInsights } from "../../api/automation";
import { Button, Card, Empty, ErrorNote, Loading, Stat } from "../ui";

/* Aggregated chatbot statistics. There is no per-person view (Req 8.3). */
export function AssistantInsightsPanel(): ReactNode {
  const [days, setDays] = useState(30);
  const selectId = useId();
  const q = useQuery({ queryKey: ["assistant-insights", days], queryFn: () => getAssistantInsights(days) });
  return (
    <Card
      title="Chatbot insights"
      description="What people ask and what is missing. Counts only; nobody is identified."
      actions={
        <label htmlFor={selectId} className="doc-row__meta">
          Period{" "}
          <select id={selectId} value={days} onChange={(e) => setDays(Number(e.target.value))}>
            <option value={7}>Last 7 days</option>
            <option value={30}>Last 30 days</option>
            <option value={90}>Last 90 days</option>
          </select>
        </label>
      }
    >
      {q.isLoading && <Loading />}
      {q.isError && (
        <ErrorNote>
          Insights could not be loaded. <Button small onClick={() => void q.refetch()}>Try again</Button>
        </ErrorNote>
      )}
      {q.data && (
        <>
          <div className="status-strip">
            <Stat label="Questions" value={q.data.total_questions} />
            <Stat label="Answered" value={q.data.answered} />
            <Stat label="Not found" value={q.data.not_found} />
            <Stat label="Personal-data questions" value={q.data.self_service} />
            <Stat label="Not helpful" value={
              q.data.not_helpful_rate == null ? "No ratings" : `${Math.round(q.data.not_helpful_rate * 100)}%`
            } />
            <Stat label="Open HR questions" value={q.data.open_hr_questions} />
          </div>
          <h3>Most asked</h3>
          {q.data.top_questions.length === 0 ? <Empty>No questions yet.</Empty> : (
            <ol>{q.data.top_questions.map((t) => <li key={t.question}>{t.question} ({t.count})</li>)}</ol>
          )}
          <h3>Asked but not answered</h3>
          {q.data.top_unanswered.length === 0 ? <Empty>Nothing missing.</Empty> : (
            <ol>{q.data.top_unanswered.map((t) => <li key={t.question}>{t.question} ({t.count})</li>)}</ol>
          )}
          <h3>Policies past their review date</h3>
          {q.data.review_due.length === 0 ? <Empty>None.</Empty> : (
            <ul>
              {q.data.review_due.map((r) => (
                <li key={r.policy_id}>
                  {r.title} (version {r.version}), review was due {new Date(r.review_due_date).toLocaleDateString()}
                </li>
              ))}
            </ul>
          )}
          {Object.keys(q.data.by_backend).length > 0 && (
            <p className="doc-row__meta">
              Answered by: {Object.entries(q.data.by_backend)
                .map(([k, v]) => `${k === "bedrock_kb" ? "smart search" : "keyword search"} ${v}`)
                .join(", ")}
            </p>
          )}
        </>
      )}
    </Card>
  );
}
