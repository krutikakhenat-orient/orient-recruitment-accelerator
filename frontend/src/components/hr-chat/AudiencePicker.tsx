import { useId, type ReactNode } from "react";

/* Who may read a policy and get answers from it. Empty selection = everyone.
   Tags map to the backend's "role:<name>" audience tags. */
export const AUDIENCE_ROLES: { tag: string; label: string }[] = [
  { tag: "role:employee", label: "Employees" },
  { tag: "role:recruiter", label: "Recruiters" },
  { tag: "role:recruiter_admin", label: "Recruitment admins" },
  { tag: "role:interview_panel", label: "Interview panel" },
  { tag: "role:management_viewer", label: "Management" },
];

export function audienceLabel(tags: string[]): string {
  if (!tags.length || tags.includes("everyone")) return "Everyone";
  return tags
    .map((t) => AUDIENCE_ROLES.find((r) => r.tag === t)?.label ?? t.replace(/^\w+:/, ""))
    .join(", ");
}

export function AudiencePicker({
  value,
  onChange,
}: {
  value: string[];
  onChange: (next: string[]) => void;
}): ReactNode {
  const base = useId();
  const everyone = value.length === 0;
  return (
    <fieldset className="field">
      <legend>Who is this for?</legend>
      <label>
        <input type="checkbox" checked={everyone} onChange={() => onChange([])} /> Everyone
      </label>
      {AUDIENCE_ROLES.map((r) => (
        <label key={r.tag} style={{ marginLeft: 12 }} htmlFor={`${base}-${r.tag}`}>
          <input
            id={`${base}-${r.tag}`}
            type="checkbox"
            checked={value.includes(r.tag)}
            onChange={(e) =>
              onChange(e.target.checked ? [...value, r.tag] : value.filter((t) => t !== r.tag))
            }
          />{" "}
          {r.label}
        </label>
      ))}
      <span className="hint">
        Only these people see the policy and get chatbot answers from it.
      </span>
    </fieldset>
  );
}
