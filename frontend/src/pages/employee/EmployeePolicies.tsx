import { useMutation, useQuery, useQueryClient } from "@tanstack/react-query";
import { CheckCircle2, Circle, Search } from "lucide-react";
import { useId, useMemo, useState, type ReactNode } from "react";

import { acknowledgePolicy, listPolicies, type Policy } from "../../api/automation";
import { useToast } from "../../components/toast";
import { Button, Empty, ErrorNote, Loading, Modal } from "../../components/ui";

const KIND: Record<string, string> = { policy: "Policy", sop: "Guide", faq: "FAQ" };

function Reader({ policy, onClose }: { policy: Policy; onClose: () => void }): ReactNode {
  const qc = useQueryClient();
  const toast = useToast();
  const ack = useMutation({
    mutationFn: () => acknowledgePolicy(policy.id),
    onSuccess: () => {
      toast.push("Marked as read", { tone: "ok" });
      void qc.invalidateQueries({ queryKey: ["policies"] });
      onClose();
    },
  });
  return (
    <Modal
      title={policy.title}
      onClose={onClose}
      footer={
        <>
          <Button onClick={onClose}>Close</Button>
          {!policy.acknowledged && (
            <Button variant="primary" disabled={ack.isPending} onClick={() => ack.mutate()}>
              {ack.isPending ? "Saving…" : "I have read this"}
            </Button>
          )}
        </>
      }
    >
      <p className="emp-muted" style={{ marginTop: 0 }}>
        {KIND[policy.kind] ?? policy.kind} · version {policy.version}
      </p>
      {ack.isError && <ErrorNote>Could not save. Please try again.</ErrorNote>}
      <div className="emp-reader">{policy.body}</div>
    </Modal>
  );
}

/* Company policies for employees: search, read status and a reader. Only published policies
   the person may see are returned by the server. */
export function EmployeePolicies(): ReactNode {
  const searchId = useId();
  const [query, setQuery] = useState("");
  const [reading, setReading] = useState<Policy | null>(null);
  const policies = useQuery({ queryKey: ["policies"], queryFn: listPolicies });
  const published = useMemo(
    () => (policies.data ?? []).filter((p) => p.status === "approved"),
    [policies.data],
  );
  const shown = useMemo(() => {
    const q = query.trim().toLowerCase();
    if (!q) return published;
    return published.filter((p) => `${p.title} ${p.body}`.toLowerCase().includes(q));
  }, [published, query]);
  const unread = published.filter((p) => !p.acknowledged).length;

  return (
    <div className="emp-page emp-page--narrow">
      <header className="emp-hero emp-hero--compact">
        <p className="emp-eyebrow">Policies</p>
        <h1 className="emp-title">Company policies and guides</h1>
        <p className="emp-lede">
          {published.length === 0
            ? "Policies will appear here once HR publishes them."
            : unread === 0
              ? "You have read everything. Revised policies will ask you again."
              : `${unread} to read. Open each one and confirm you have read it.`}
        </p>
      </header>

      <div className="emp-search">
        <Search size={18} aria-hidden="true" />
        <label htmlFor={searchId} className="sr-only">Search policies</label>
        <input id={searchId} type="search" placeholder="Search policies" value={query}
          onChange={(e) => setQuery(e.target.value)} />
      </div>

      {policies.isLoading && <Loading label="Loading policies…" />}
      {policies.isError && (
        <ErrorNote>
          The policies could not be loaded.{" "}
          <Button small onClick={() => void policies.refetch()}>Try again</Button>
        </ErrorNote>
      )}
      {policies.data && published.length > 0 && shown.length === 0 && (
        <Empty>No policy matches "{query}".</Empty>
      )}

      <ul className="emp-list" aria-label="Policies">
        {shown.map((p) => (
          <li key={p.id}>
            <button type="button" className="emp-list__item" onClick={() => setReading(p)}>
              <span className={`emp-list__mark ${p.acknowledged ? "is-read" : ""}`}>
                {p.acknowledged
                  ? <CheckCircle2 size={18} aria-hidden="true" />
                  : <Circle size={18} aria-hidden="true" />}
              </span>
              <span className="emp-list__text">
                <span className="emp-list__title">{p.title}</span>
                <span className="emp-list__meta">{KIND[p.kind] ?? p.kind} · version {p.version}</span>
              </span>
              <span className={`emp-list__state ${p.acknowledged ? "is-read" : ""}`}>
                {p.acknowledged ? "Read" : "To read"}
              </span>
            </button>
          </li>
        ))}
      </ul>
      {reading && <Reader policy={reading} onClose={() => setReading(null)} />}
    </div>
  );
}
