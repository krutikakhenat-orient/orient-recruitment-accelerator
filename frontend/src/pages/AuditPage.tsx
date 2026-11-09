import { useQuery } from "@tanstack/react-query";
import { useState, type ReactNode } from "react";

import { listAuditEvents } from "../api/automation";
import { Banner, Button, Card, Empty, ErrorNote, Loading, PageHeader, prettify } from "../components/ui";

const PAGE = 50;

/* The audit log: a read-only record of who did what. It cannot be edited. Each row is linked
   to the one before it by a code, so tampering would show. */
export function AuditPage(): ReactNode {
  const [offset, setOffset] = useState(0);
  const events = useQuery({
    queryKey: ["audit", offset],
    queryFn: () => listAuditEvents(PAGE, offset),
  });
  return (
    <>
      <PageHeader
        title="Audit log"
        description="A permanent, read-only record of important actions: who did what, and when."
      />
      <Banner>
        Entries cannot be changed or deleted. Names, messages and documents are never stored here,
        only what happened and which record it was about.
      </Banner>
      <Card title="Recent activity" description="Newest first.">
        {events.isLoading && <Loading />}
        {events.error && <ErrorNote>Could not load the audit log. You may not have access.</ErrorNote>}
        {events.data && events.data.length === 0 && <Empty>No entries.</Empty>}
        {events.data && events.data.length > 0 && (
          <div className="table-wrap">
            <table className="data">
              <thead>
                <tr>
                  <th>#</th>
                  <th>When</th>
                  <th>Action</th>
                  <th>Record</th>
                  <th>Role</th>
                  <th>Reason</th>
                </tr>
              </thead>
              <tbody>
                {events.data.map((e) => (
                  <tr key={e.id}>
                    <td>{e.sequence}</td>
                    <td>{new Date(e.occurred_at).toLocaleString()}</td>
                    <td>{e.action}</td>
                    <td>{prettify(e.entity_type)}</td>
                    <td>{e.actor_role ? prettify(e.actor_role) : "System"}</td>
                    <td className="subtle">{e.reason ?? ""}</td>
                  </tr>
                ))}
              </tbody>
            </table>
          </div>
        )}
        <div className="btn-row" style={{ marginTop: 12 }}>
          <Button small disabled={offset === 0} onClick={() => setOffset(Math.max(0, offset - PAGE))}>
            Newer
          </Button>
          <Button small disabled={(events.data?.length ?? 0) < PAGE} onClick={() => setOffset(offset + PAGE)}>
            Older
          </Button>
        </div>
      </Card>
    </>
  );
}
