import { useMutation, useQuery, useQueryClient } from "@tanstack/react-query";
import { useState, type ReactNode } from "react";
import { Link } from "react-router-dom";

import {
  listIntegrations,
  listTemplates,
  saveTemplate,
  type Integration,
  type MessageTemplate,
} from "../api/automation";
import { ApiError } from "../api/client";
import { useAuth } from "../app/auth-context";
import { useToast } from "../components/toast";
import {
  Badge,
  Banner,
  Button,
  Card,
  ErrorNote,
  Field,
  Loading,
  PageHeader,
  Tabs,
  prettify,
} from "../components/ui";

const STATE_WORDS: Record<string, string> = {
  live: "Connected",
  simulated: "Demo mode",
  not_configured: "Not connected (placeholder)",
  planned: "Planned",
};

function stateTone(state: string): "ok" | "info" | "warn" | "neutral" {
  if (state === "live") return "ok";
  if (state === "simulated") return "info";
  if (state === "not_configured") return "warn";
  return "neutral";
}

function IntegrationCard({ item }: { item: Integration }): ReactNode {
  return (
    <article className="integration">
      <div className="integration__head">
        <div>
          <h3 style={{ margin: 0 }}>{item.name}</h3>
          <p className="hint-line" style={{ margin: "2px 0 0" }}>{item.purpose}</p>
        </div>
        <Badge tone={stateTone(item.state)}>{STATE_WORDS[item.state] ?? prettify(item.state)}</Badge>
      </div>
      <p style={{ margin: "8px 0 0", fontSize: "0.88rem" }}>{item.message}</p>
      {item.needs.length > 0 && (
        <>
          <p className="hint-line" style={{ margin: "10px 0 0" }}><strong>What it needs</strong></p>
          <ul>
            {item.needs.map((n) => (
              <li key={n}>{n}</li>
            ))}
          </ul>
        </>
      )}
      <p className="doc-row__meta" style={{ marginTop: 8 }}>Used by: {item.used_by.join(", ")}</p>
    </article>
  );
}

function TemplateEditor({ item, canEdit }: { item: MessageTemplate; canEdit: boolean }): ReactNode {
  const qc = useQueryClient();
  const toast = useToast();
  const [subject, setSubject] = useState(item.subject);
  const [body, setBody] = useState(item.body);
  const [error, setError] = useState<string | null>(null);
  const save = useMutation({
    mutationFn: () => saveTemplate(item.key, { subject, body }),
    onSuccess: (t) => {
      setError(null);
      toast.push("Template saved", { tone: "ok", message: `Now version ${t.version}` });
      void qc.invalidateQueries({ queryKey: ["message-templates"] });
    },
    onError: (e) => setError(e instanceof ApiError ? e.message : "Could not save the template."),
  });
  const changed = subject !== item.subject || body !== item.body;
  return (
    <details className="guide-card" style={{ marginBottom: 8 }}>
      <summary style={{ cursor: "pointer", fontWeight: 600 }}>
        {item.label}{" "}
        <span className="doc-row__meta">
          {item.is_built_in ? "built-in wording" : `edited, version ${item.version}`} · for {item.audience}
        </span>
      </summary>
      <p className="hint-line" style={{ marginTop: 8 }}>{item.description}</p>
      {error && <ErrorNote>{error}</ErrorNote>}
      <Field label="Subject" htmlFor={`ts-${item.key}`}>
        <input id={`ts-${item.key}`} value={subject} disabled={!canEdit} onChange={(e) => setSubject(e.target.value)} />
      </Field>
      <Field
        label="Message"
        htmlFor={`tb-${item.key}`}
        hint={`You can use: ${item.placeholders.map((p) => `{{${p}}}`).join(", ")}`}
      >
        <textarea id={`tb-${item.key}`} rows={7} value={body} disabled={!canEdit} onChange={(e) => setBody(e.target.value)} />
      </Field>
      {canEdit ? (
        <Button small variant="primary" disabled={!changed || save.isPending} onClick={() => save.mutate()}>
          {save.isPending ? "Saving…" : "Save as new version"}
        </Button>
      ) : (
        <p className="hint-line">Only an approver can change message wording.</p>
      )}
    </details>
  );
}

/* Integrations and message wording. Every connection shows plainly whether it is live, a demo
   or still a placeholder, and what is needed to connect it. */
export function IntegrationsPage(): ReactNode {
  const { hasPermission } = useAuth();
  const [tab, setTab] = useState("connections");
  const integrations = useQuery({ queryKey: ["integrations"], queryFn: listIntegrations });
  const templates = useQuery({
    queryKey: ["message-templates"],
    queryFn: listTemplates,
    enabled: tab === "templates",
  });

  return (
    <>
      <Link to="/settings" className="back-link">← Settings</Link>
      <PageHeader
        title="Connections & messages"
        description="See which outside systems are connected, and edit the wording of the messages candidates and joiners receive."
      />
      <Tabs
        label="Connections and messages"
        value={tab}
        onChange={setTab}
        tabs={[
          { id: "connections", label: "Connections" },
          { id: "templates", label: "Message wording" },
        ]}
      />
      {tab === "connections" && (
        <>
          <Banner>
            Everything works on this computer without these connections. A placeholder means the
            feature runs locally, but nothing leaves the system until the connection is set up.
          </Banner>
          {integrations.isLoading && <Loading />}
          {integrations.error && <ErrorNote>Could not load connections.</ErrorNote>}
          <div className="integration-grid">
            {integrations.data?.map((i) => <IntegrationCard key={i.key} item={i} />)}
          </div>
        </>
      )}
      {tab === "templates" && (
        <Card
          title="Message wording"
          description="Each message has built-in wording. Saving a change creates a new version. Messages never include scores or internal notes."
        >
          {templates.isLoading && <Loading />}
          {templates.data?.map((t) => (
            <TemplateEditor key={`${t.key}-${t.version}`} item={t} canEdit={hasPermission("campaign.approve")} />
          ))}
        </Card>
      )}
    </>
  );
}
