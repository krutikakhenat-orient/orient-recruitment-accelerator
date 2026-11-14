import { useMutation } from "@tanstack/react-query";
import { useId, useState, type ReactNode } from "react";

import {
  duplicatesDetail,
  replacePolicyFile,
  uploadPolicy,
  type Policy,
  type PolicyKind,
} from "../../api/automation";
import { ApiError } from "../../api/client";
import { Button, ErrorNote, Field, Modal } from "../ui";
import { AudiencePicker } from "./AudiencePicker";

const ACCEPT = ".pdf,.docx,.txt,.md";
const MAX_MB = 10;

/* Upload a policy file as a draft, or replace the file of an existing draft (Req 1).
   The server validates type, signature, size and malware; this form only pre-checks
   extension and size so people get a fast, plain answer. */
export function UploadPolicyDialog({
  replacing,
  onClose,
  onDone,
}: {
  replacing?: Policy;
  onClose: () => void;
  onDone: (p: Policy) => void;
}): ReactNode {
  const base = useId();
  const [file, setFile] = useState<File | null>(null);
  const [title, setTitle] = useState("");
  const [kind, setKind] = useState<PolicyKind>("policy");
  const [audience, setAudience] = useState<string[]>([]);
  const [reviewDue, setReviewDue] = useState("");
  const [asDraft, setAsDraft] = useState(false);
  const [error, setError] = useState<string | null>(null);
  const [duplicates, setDuplicates] = useState<string[] | null>(null);

  const send = useMutation({
    mutationFn: (confirmDuplicate: boolean) => {
      if (!file) throw new Error("Choose a file first.");
      if (replacing) return replacePolicyFile(replacing.id, file, confirmDuplicate);
      return uploadPolicy({
        file, title: title.trim(), kind, audience,
        ...(reviewDue ? { reviewDueDate: reviewDue } : {}), confirmDuplicate,
        publish: !asDraft,
      });
    },
    onSuccess: onDone,
    onError: (e) => {
      if (e instanceof ApiError && e.status === 409) {
        const parsed = duplicatesDetail.safeParse(e.details);
        if (parsed.success) {
          setError(null);
          setDuplicates(parsed.data.duplicates.map((d) => `${d.title} (version ${d.version}, ${d.status})`));
          return;
        }
      }
      setDuplicates(null);
      setError(e instanceof Error ? e.message : "Could not upload the file.");
    },
  });

  const pick = (f: File | null): void => {
    setError(null);
    setDuplicates(null);
    if (f && !/\.(pdf|docx|txt|md)$/i.test(f.name)) {
      setError("Only PDF, DOCX, TXT and MD files can be uploaded.");
      setFile(null);
      return;
    }
    if (f && f.size > MAX_MB * 1024 * 1024) {
      setError(`The file is larger than the ${MAX_MB} MB limit.`);
      setFile(null);
      return;
    }
    setFile(f);
    if (f && !title && !replacing) setTitle(f.name.replace(/\.[^.]+$/, "").slice(0, 255));
  };

  const ready = !!file && (replacing || title.trim().length > 0) && !send.isPending;
  return (
    <Modal
      title={replacing ? `Replace file: ${replacing.title}` : "Upload a policy file"}
      onClose={onClose}
      footer={
        <>
          <Button onClick={onClose}>Cancel</Button>
          {duplicates ? (
            <Button variant="primary" disabled={send.isPending} onClick={() => send.mutate(true)}>
              Upload anyway
            </Button>
          ) : (
            <Button variant="primary" disabled={!ready} onClick={() => send.mutate(false)}>
              {send.isPending
                ? "Checking the file…"
                : replacing ? "Replace file" : asDraft ? "Save draft" : "Publish"}
            </Button>
          )}
        </>
      }
    >
      <p className="hint-line">
        {replacing
          ? "The new file is checked for safety, then replaces the draft's file."
          : "The file is checked for safety, then published and synced to the chatbot straight away."}
      </p>
      {error && <ErrorNote>{error}</ErrorNote>}
      {duplicates && (
        <div className="banner" role="alert">
          This file has already been uploaded as: {duplicates.join("; ")}. Upload it again only if
          you really want a second copy.
        </div>
      )}
      <Field label="File" htmlFor={`${base}-file`} hint={`PDF, DOCX, TXT or MD, up to ${MAX_MB} MB. Scanned images cannot be read.`}>
        <input id={`${base}-file`} type="file" accept={ACCEPT}
          onChange={(e) => pick(e.target.files?.[0] ?? null)} />
      </Field>
      {!replacing && (
        <>
          <Field label="Title" htmlFor={`${base}-title`}>
            <input id={`${base}-title`} value={title} maxLength={255}
              onChange={(e) => setTitle(e.target.value)} />
          </Field>
          <Field label="Type" htmlFor={`${base}-kind`}>
            <select id={`${base}-kind`} value={kind} onChange={(e) => setKind(e.target.value as PolicyKind)}>
              <option value="policy">Policy</option>
              <option value="sop">Guide / SOP</option>
              <option value="faq">FAQ</option>
            </select>
          </Field>
          <AudiencePicker value={audience} onChange={setAudience} />
          <Field label="Review by (optional)" htmlFor={`${base}-review`}
            hint="HR insights list policies that are past this date.">
            <input id={`${base}-review`} type="date" value={reviewDue}
              onChange={(e) => setReviewDue(e.target.value)} />
          </Field>
          <label className="check-row" htmlFor={`${base}-draft`}>
            <input id={`${base}-draft`} type="checkbox" checked={asDraft}
              onChange={(e) => setAsDraft(e.target.checked)} />
            <span>
              <strong>Save as draft</strong>
              <span className="hint"> Not ready yet: nobody sees it and the chatbot does not use it
                until you publish it.</span>
            </span>
          </label>
        </>
      )}
    </Modal>
  );
}
