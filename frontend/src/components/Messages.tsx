import { useMutation, useQuery, useQueryClient } from "@tanstack/react-query";
import { useState, type ReactNode } from "react";

import {
  getNotificationStatus,
  listDeliveries,
  listTemplates,
  sendMessage,
  type Delivery,
  type NotificationStatus,
} from "../api/automation";
import { ApiError } from "../api/client";
import { Banner, Button, Empty, ErrorNote, Field, Loading, StatusBadge, prettify } from "./ui";
import { useToast } from "./toast";

/* Everything about messages sent to a person: which channels are connected, a plain log of
   what was sent (or only recorded), and a small form to send a reminder. Nothing is ever
   shown as "sent" unless a real provider accepted it. */

const STATUS_LABEL: Record<string, string> = {
  sent: "Sent",
  simulated: "Demo only: not really delivered",
  unconfigured: "Not sent: no provider connected",
  failed: "Failed",
};

export function deliveryStatusLabel(status: string): string {
  return STATUS_LABEL[status] ?? prettify(status);
}

export function ChannelNote({ status }: { status: NotificationStatus }): ReactNode {
  const worst = [status.email, status.whatsapp].some((c) => c.state === "not_configured");
  return (
    <Banner>
      <strong>Email:</strong> {status.email.message}{" "}
      <strong>WhatsApp:</strong> {status.whatsapp.message}
      {worst && (
        <>
          {" "}
          You can still use the ready-to-send link on each message to send it by hand.
        </>
      )}
    </Banner>
  );
}

export function MessageItem({ item, label }: { item: Delivery; label?: string }): ReactNode {
  return (
    <div className="msg">
      <div className="msg__head">
        <span className="msg__title">{label ?? prettify(item.template_key)}</span>
        <StatusBadge status={item.status} label={deliveryStatusLabel(item.status)} />
      </div>
      <div className="msg__meta">
        {prettify(item.channel)} to {item.recipient} · {new Date(item.created_at).toLocaleString()}
        {item.template_version > 0 ? ` · template v${item.template_version}` : ""}
      </div>
      <details>
        <summary className="msg__meta">Show the message</summary>
        {item.subject && <p className="msg__title">{item.subject}</p>}
        <p className="msg__body">{item.body}</p>
      </details>
      {item.status === "unconfigured" && item.manual_link && (
        <p className="msg__meta" style={{ marginBottom: 0 }}>
          <a href={item.manual_link} target="_blank" rel="noreferrer">
            Open a ready-to-send {item.channel === "whatsapp" ? "WhatsApp message" : "email"}
          </a>{" "}
          to send it by hand.
        </p>
      )}
      {item.failure_reason && <p className="field-error">{item.failure_reason}</p>}
    </div>
  );
}

/* A short form for the messages that need no extra details. Specific messages (confirmation
   link, offer, joining documents) have their own buttons where the details are known. */
const SENDABLE = ["interview_reminder", "offer_followup"];

export function MessagePanel({ applicationId }: { applicationId: string }): ReactNode {
  const qc = useQueryClient();
  const toast = useToast();
  const [templateKey, setTemplateKey] = useState(SENDABLE[0] ?? "interview_reminder");
  const [channel, setChannel] = useState<"email" | "whatsapp">("email");
  const [error, setError] = useState<string | null>(null);

  const status = useQuery({ queryKey: ["notification-status"], queryFn: getNotificationStatus });
  const templates = useQuery({ queryKey: ["message-templates"], queryFn: listTemplates });
  const log = useQuery({
    queryKey: ["deliveries", applicationId],
    queryFn: () => listDeliveries({ applicationId }),
  });
  const send = useMutation({
    mutationFn: () => sendMessage({ application_id: applicationId, template_key: templateKey, channel }),
    onSuccess: (d) => {
      setError(null);
      toast.push("Message recorded", { tone: "ok", message: deliveryStatusLabel(d.status) });
      void qc.invalidateQueries({ queryKey: ["deliveries", applicationId] });
    },
    onError: (e) => setError(e instanceof ApiError ? e.message : "Could not record the message."),
  });

  const labelFor = (key: string): string =>
    templates.data?.find((t) => t.key === key)?.label ?? prettify(key);
  const sendable = (templates.data ?? []).filter((t) => SENDABLE.includes(t.key));

  return (
    <div>
      {status.data && <ChannelNote status={status.data} />}
      {error && <ErrorNote>{error}</ErrorNote>}
      <div className="field-row">
        <Field label="Message" htmlFor="msg-template" hint="Pick the message to send to the candidate.">
          <select id="msg-template" value={templateKey} onChange={(e) => setTemplateKey(e.target.value)}>
            {(sendable.length ? sendable : [{ key: templateKey, label: labelFor(templateKey) }]).map((t) => (
              <option key={t.key} value={t.key}>
                {t.label}
              </option>
            ))}
          </select>
        </Field>
        <Field label="Send by" htmlFor="msg-channel" hint="WhatsApp needs a mobile number on record.">
          <select
            id="msg-channel"
            value={channel}
            onChange={(e) => setChannel(e.target.value as "email" | "whatsapp")}
          >
            <option value="email">Email</option>
            <option value="whatsapp">WhatsApp</option>
          </select>
        </Field>
      </div>
      <Button small variant="primary" disabled={send.isPending} onClick={() => send.mutate()}>
        {send.isPending ? "Sending…" : "Send message"}
      </Button>
      <hr className="divider" />
      <h3>Message history</h3>
      <p className="hint-line">Every message sent to this candidate, newest first.</p>
      {log.isLoading && <Loading />}
      {log.data && log.data.length === 0 && <Empty>No messages yet.</Empty>}
      {log.data?.map((d) => (
        <MessageItem key={d.id} item={d} label={labelFor(d.template_key)} />
      ))}
    </div>
  );
}
