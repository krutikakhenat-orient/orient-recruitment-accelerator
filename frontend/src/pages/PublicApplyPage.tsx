import { useEffect, useState, type ReactNode } from "react";
import { useParams } from "react-router-dom";

import {
  getPublicRoleForm,
  listOpenRoles,
  previewResume,
  submitPublicApplication,
  type PublicForm,
  type PublicFormField,
  type PublicRole,
} from "../api/resources";
import { Logo } from "../components/Logo";
import { Button, Field } from "../components/ui";

/* Public, unauthenticated candidate application.

   Two entry points, one component:
   - Consolidated careers link  "/apply"            -> candidate picks a role from a live
                                                        dropdown of currently-open roles.
   - Deep link                  "/apply/:campaignId" -> a specific role is pre-selected.

   Either way the chosen role IS the campaign bucket: the application is submitted to that
   campaign's apply endpoint and lands in its bucket, exactly as before. The form itself is
   rendered dynamically from the role's APPROVED form schema, so different roles can collect
   different fields. Protected / medical / highly-personal attributes are never part of a
   baseline form (enforced server-side), so nothing sensitive can appear here. */

const UUID_RE = /^[0-9a-f]{8}-[0-9a-f]{4}-[0-9a-f]{4}-[0-9a-f]{4}-[0-9a-f]{12}$/i;

type Row = Record<string, string>;
type AnswerValue = string | boolean | Row[];

const emptyRow = (cols: { key: string }[]): Row =>
  Object.fromEntries(cols.map((c) => [c.key, ""]));

const nonEmptyRows = (rows: Row[]): Row[] =>
  rows.filter((r) => Object.values(r).some((v) => v.trim() !== ""));

export function PublicApplyPage(): ReactNode {
  const { campaignId: paramCampaignId } = useParams();
  const deepLink = Boolean(paramCampaignId);
  const deepLinkValid = !deepLink || UUID_RE.test(paramCampaignId ?? "");

  // Role selection. In deep-link mode the campaign id comes from the URL; otherwise the
  // candidate chooses from the dropdown (auto-selected when only one role is open).
  const [roles, setRoles] = useState<PublicRole[] | null>(null);
  const [rolesError, setRolesError] = useState<string | null>(null);
  const [selectedId, setSelectedId] = useState<string>(paramCampaignId ?? "");

  const [form, setForm] = useState<PublicForm | null>(null);
  const [formError, setFormError] = useState<string | null>(null);
  const [loadingForm, setLoadingForm] = useState(false);

  // Candidate answers, keyed by field key. Repeating groups hold Row[].
  const [answers, setAnswers] = useState<Record<string, AnswerValue>>({});
  const [resume, setResume] = useState<File | null>(null);
  // Status note shown under the resume upload while/after we read it for pre-fill.
  const [resumeNote, setResumeNote] = useState<string | null>(null);

  const [error, setError] = useState<string | null>(null);
  // `done` holds the single thank-you message shown after a successful submission. There is
  // no second step: we simply confirm the application was received.
  const [done, setDone] = useState<string | null>(null);
  const [busy, setBusy] = useState(false);

  // Always load the open-roles list so the role dropdown is present on the form, whether
  // the candidate arrived via the consolidated link (/apply) or a direct campaign deep
  // link (/apply/<id>). On a deep link we keep the linked role pre-selected but still let
  // the candidate switch to another open role from the dropdown.
  useEffect(() => {
    let active = true;
    listOpenRoles()
      .then((r) => {
        if (!active) return;
        setRoles(r);
        // Auto-select only when nothing is selected yet and exactly one role is open.
        setSelectedId((current) => (current ? current : r.length === 1 ? r[0]!.id : ""));
      })
      .catch((e: unknown) => active && setRolesError(e instanceof Error ? e.message : "Could not load roles."));
    return () => {
      active = false;
    };
  }, []);

  // Load the selected role's form whenever the selection changes.
  useEffect(() => {
    if (!selectedId) {
      setForm(null);
      return;
    }
    let active = true;
    setLoadingForm(true);
    setFormError(null);
    setForm(null);
    getPublicRoleForm(selectedId)
      .then((f) => {
        if (!active) return;
        setForm(f);
        setAnswers(initialAnswers(f.fields));
      })
      .catch((e: unknown) => active && setFormError(e instanceof Error ? e.message : "Could not load the form."))
      .finally(() => active && setLoadingForm(false));
    return () => {
      active = false;
    };
  }, [selectedId]);


  const setValue = (key: string, value: AnswerValue): void =>
    setAnswers((a) => ({ ...a, [key]: value }));

  // When the candidate attaches their resume, read it and pre-fill the fields we can parse
  // (email / mobile / years of experience). We only fill fields the candidate hasn't already
  // typed into, so we never overwrite their input, and every value stays editable.
  const handleResume = (file: File | null): void => {
    setResume(file);
    setResumeNote(null);
    if (!file) return;
    setResumeNote("Reading your resume to pre-fill the form…");
    previewResume(file)
      .then((preview) => {
        if (!preview.extracted) {
          setResumeNote("We couldn't read details from this file — please fill the form in.");
          return;
        }
        const keys = Object.keys(preview.fields);
        if (keys.length === 0) {
          setResumeNote("Resume attached. Please complete the fields below.");
          return;
        }
        setAnswers((a) => {
          const next = { ...a };
          for (const [k, v] of Object.entries(preview.fields)) {
            const current = next[k];
            // Only pre-fill empty text fields; never clobber what the candidate typed.
            if (typeof current !== "string" || current.trim() === "") next[k] = v;
          }
          return next;
        });
        setResumeNote(
          `Resume attached. We pre-filled: ${keys.join(", ")}. Please review and complete the rest.`,
        );
      })
      .catch(() => setResumeNote("Resume attached. Please complete the fields below."));
  };

  const submit = async (e: React.FormEvent): Promise<void> => {
    e.preventDefault();
    setError(null);
    if (!form || !selectedId) {
      setError("Please choose a role first.");
      return;
    }
    const resumeField = form.fields.find((f) => f.field_type === "file");
    if (resumeField && !resume) {
      setError("Please attach your resume.");
      return;
    }
    // Required text/select fields. "position_applied_for" is hidden (the role is chosen
    // above) and filled in by the backend, so it is never validated or sent from here.
    for (const f of form.fields) {
      if (!f.required || f.field_type === "file" || f.field_type === "repeating_group") continue;
      if (f.key === "position_applied_for") continue;
      const v = answers[f.key];
      if (f.field_type === "boolean") {
        if (v !== true) {
          setError(`Please confirm: ${f.label}`);
          return;
        }
      } else if (typeof v !== "string" || !v.trim()) {
        setError(`Please complete: ${f.label}`);
        return;
      }
    }
    if (answers["privacy_consent"] !== true) {
      setError("Privacy consent is required to submit.");
      return;
    }

    setBusy(true);
    try {
      const payload: Record<string, unknown> = {};
      for (const f of form.fields) {
        if (f.field_type === "file" || f.key === "position_applied_for") continue;
        const v = answers[f.key];
        payload[f.key] = f.field_type === "repeating_group" && Array.isArray(v) ? nonEmptyRows(v) : v;
      }
      await submitPublicApplication(selectedId, payload, resume as File);
      // Single confirmation: we only thank the candidate. No score/outcome is shown.
      setDone("Thank you for your application. Your details have been received.");
    } catch (err) {
      setError(err instanceof Error ? err.message : "Submission failed.");
    } finally {
      setBusy(false);
    }
  };

  if (deepLink && !deepLinkValid) {
    return (
      <Shell>
        <h1>This application link isn&rsquo;t valid</h1>
        <p>The role reference in this link is missing or malformed, so the form can&rsquo;t be opened.</p>
        <p className="subtle">
          Try the main careers link <code>/apply</code> and choose your role from the list.
        </p>
      </Shell>
    );
  }

  if (done) {
    return <ThankYou message={done} />;
  }

  return (
    <div style={{ maxWidth: 720, margin: "32px auto", padding: 20 }}>
      <div className="apply-brandbar">
        <Logo size={40} title="Orient" />
        <span className="apply-brandbar__name">Orient Recruitment</span>
      </div>
      <div className="page-head">
        <h1>Apply to Orient</h1>
        <p>Choose the role you&rsquo;d like to apply for, then complete the form. Fields marked * are required.</p>
      </div>

      {/* Role picker — always shown so the candidate can pick/switch the target position,
          whether they arrived via /apply or a direct campaign link. */}
      <div className="card">
        {rolesError && <div className="error-summary" role="alert">{rolesError}</div>}
        {!roles && !rolesError && <p className="subtle">Loading open roles…</p>}
        {roles && roles.length === 0 && (
          <>
            <h2 style={{ marginTop: 0 }}>No open positions right now</h2>
            <p className="subtle">
              There are no roles accepting applications at the moment. Please check back later.
            </p>
          </>
        )}
        {roles && roles.length > 0 && (
          <Field label="Role you are applying for *" htmlFor="role-select">
            <select id="role-select" value={selectedId} onChange={(e) => setSelectedId(e.target.value)} required>
              <option value="">Choose a role…</option>
              {roles.map((r) => (
                <option key={r.id} value={r.id}>
                  {roleLabel(r)}
                </option>
              ))}
            </select>
          </Field>
        )}
      </div>


      {loadingForm && <div className="card"><p className="subtle">Loading the application form…</p></div>}
      {formError && <div className="error-summary" role="alert">{formError}</div>}

      {form && !loadingForm && (
        <form onSubmit={submit} className="card" noValidate>
          {error && <div className="error-summary" role="alert">{error}</div>}

          {(() => {
            // Resume first (upload at the START so we can pre-fill from it); then the rest
            // in form order. "position_applied_for" is hidden — the candidate already picked
            // the role above, and the backend fills the position automatically.
            const ordered = form.fields.slice().sort((a, b) => a.order_index - b.order_index);
            const resumeField = ordered.find((f) => f.field_type === "file");
            const rest = ordered.filter(
              (f) => f.field_type !== "file" && f.key !== "position_applied_for",
            );
            return (
              <>
                {resumeField && (
                  <>
                    <DynamicField
                      key={resumeField.key}
                      field={resumeField}
                      value={answers[resumeField.key]}
                      onChange={(v) => setValue(resumeField.key, v)}
                      onFile={handleResume}
                    />
                    {resumeNote && (
                      <p className="subtle" role="status" aria-live="polite" style={{ marginTop: -4 }}>
                        {resumeNote}
                      </p>
                    )}
                  </>
                )}
                {rest.map((f) => (
                  <DynamicField
                    key={f.key}
                    field={f}
                    value={answers[f.key]}
                    onChange={(v) => setValue(f.key, v)}
                    onFile={handleResume}
                  />
                ))}
              </>
            );
          })()}

          <Button variant="primary" type="submit" disabled={busy}>
            {busy ? "Submitting…" : "Submit application"}
          </Button>
        </form>
      )}
    </div>
  );
}

function roleLabel(r: PublicRole): string {
  const bits = [r.title];
  if (r.location) bits.push(r.location);
  if (r.work_mode) bits.push(r.work_mode);
  return bits.join(" — ");
}

function initialAnswers(fields: PublicFormField[]): Record<string, AnswerValue> {
  const a: Record<string, AnswerValue> = {};
  for (const f of fields) {
    if (f.field_type === "file") continue;
    if (f.field_type === "boolean") a[f.key] = false;
    else if (f.field_type === "repeating_group") a[f.key] = [];
    else a[f.key] = "";
  }
  return a;
}

function DynamicField({
  field,
  value,
  onChange,
  onFile,
}: {
  field: PublicFormField;
  value: AnswerValue | undefined;
  onChange: (v: AnswerValue) => void;
  onFile: (f: File | null) => void;
}): ReactNode {
  const id = `f-${field.key}`;
  const label = `${field.label}${field.required ? " *" : ""}`;

  switch (field.field_type) {
    case "boolean":
      return (
        <div className="checkbox-row">
          <input id={id} type="checkbox" checked={value === true} onChange={(e) => onChange(e.target.checked)} />
          <label htmlFor={id}>{label}</label>
        </div>
      );
    case "file":
      return (
        <Field label={label} htmlFor={id} hint="PDF, DOCX or TXT.">
          <input id={id} type="file" accept=".pdf,.docx,.txt" onChange={(e) => onFile(e.target.files?.[0] ?? null)} />
        </Field>
      );
    case "textarea":
      return (
        <Field label={label} htmlFor={id}>
          <textarea id={id} rows={2} value={typeof value === "string" ? value : ""} onChange={(e) => onChange(e.target.value)} />
        </Field>
      );
    case "select":
      return (
        <Field label={label} htmlFor={id}>
          <select id={id} value={typeof value === "string" ? value : ""} onChange={(e) => onChange(e.target.value)} required={field.required}>
            <option value="">Select…</option>
            {(field.options ?? []).map((o) => (
              <option key={o} value={o}>{o}</option>
            ))}
          </select>
        </Field>
      );
    case "repeating_group":
      return (
        <RepeatingTable
          legend={field.label}
          columns={(field.item_schema ?? []).map((c) => ({
            key: c.key,
            label: c.label,
            type: c.field_type === "textarea" ? "textarea" : c.field_type === "number" ? "number" : "text",
          }))}
          rows={Array.isArray(value) ? value : []}
          onChange={onChange}
        />
      );
    case "number":
      return (
        <Field label={label} htmlFor={id}>
          <input id={id} type="number" value={typeof value === "string" ? value : ""} onChange={(e) => onChange(e.target.value)} required={field.required} />
        </Field>
      );
    case "email":
      return (
        <Field label={label} htmlFor={id}>
          <input id={id} type="email" value={typeof value === "string" ? value : ""} onChange={(e) => onChange(e.target.value)} required={field.required} />
        </Field>
      );
    default:
      return (
        <Field label={label} htmlFor={id}>
          <input id={id} type="text" value={typeof value === "string" ? value : ""} onChange={(e) => onChange(e.target.value)} required={field.required} />
        </Field>
      );
  }
}

type Column = { key: string; label: string; type: "text" | "number" | "textarea" };

function RepeatingTable({
  legend,
  columns,
  rows,
  onChange,
}: {
  legend: string;
  columns: Column[];
  rows: Row[];
  onChange: (rows: Row[]) => void;
}): ReactNode {
  if (columns.length === 0) return null;
  const update = (idx: number, key: string, v: string): void =>
    onChange(rows.map((r, i) => (i === idx ? { ...r, [key]: v } : r)));
  const addRow = (): void => onChange([...rows, emptyRow(columns)]);
  const removeRow = (idx: number): void => onChange(rows.filter((_, i) => i !== idx));

  return (
    <fieldset style={{ border: "1px solid var(--border, #ddd)", borderRadius: 8, padding: 12, marginTop: 12 }}>
      <legend style={{ fontWeight: 600, padding: "0 6px" }}>{legend}</legend>
      {rows.length === 0 && (
        <p className="subtle" style={{ marginTop: 0 }}>No entries yet. Add a row if you&rsquo;d like to list these.</p>
      )}
      {rows.map((row, idx) => (
        <div key={idx} className="grid grid--2" style={{ borderTop: idx ? "1px dashed #eee" : "none", paddingTop: idx ? 10 : 0, marginBottom: 10 }}>
          {columns.map((col) => {
            const cid = `${legend}-${idx}-${col.key}`.replace(/\s+/g, "-").toLowerCase();
            return (
              <Field key={col.key} label={col.label} htmlFor={cid}>
                {col.type === "textarea" ? (
                  <textarea id={cid} rows={2} value={row[col.key] ?? ""} onChange={(e) => update(idx, col.key, e.target.value)} />
                ) : (
                  <input id={cid} type={col.type === "number" ? "number" : "text"} value={row[col.key] ?? ""} onChange={(e) => update(idx, col.key, e.target.value)} />
                )}
              </Field>
            );
          })}
          <div style={{ alignSelf: "end" }}>
            <Button variant="default" type="button" small onClick={() => removeRow(idx)}>
              Remove this entry
            </Button>
          </div>
        </div>
      ))}
      <Button variant="default" type="button" small onClick={addRow}>
        + Add {legend.toLowerCase()} entry
      </Button>
    </fieldset>
  );
}

function Shell({ children }: { children: ReactNode }): ReactNode {
  return (
    <div className="apply-shell">
      <div className="apply-brandbar apply-brandbar--center">
        <Logo size={44} title="Orient" />
        <span className="apply-brandbar__name">Orient Recruitment</span>
      </div>
      <div className="card apply-card">{children}</div>
    </div>
  );
}

/* Branded post-submission confirmation — a single, final thank-you screen. We only confirm
   that the application was received; there is no second step and no outcome/score shown to
   the candidate. Accessible: a single h1, responsive via the apply-* CSS. */
function ThankYou({ message }: { message: string }): ReactNode {
  return (
    <div className="apply-shell apply-thankyou">
      <div className="apply-brandbar apply-brandbar--center">
        <Logo size={56} title="Orient" />
        <span className="apply-brandbar__name">Orient Recruitment</span>
      </div>

      <div className="card apply-card apply-thankyou__card">
        <div className="apply-thankyou__badge" aria-hidden="true">✓</div>
        <h1 style={{ marginTop: 8 }}>Thank you for your application</h1>
        <p className="apply-thankyou__lead">{message}</p>
        <p className="subtle apply-thankyou__note">
          You can safely close this page; your application has been saved. The hiring team
          will be in touch using the contact details you provided.
        </p>
      </div>
    </div>
  );
}
