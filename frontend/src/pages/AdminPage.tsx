import { useState, type ReactNode } from "react";
import { z } from "zod";

import { apiFetch, ApiError } from "../api/client";
import { useToast } from "../components/toast";
import { Button, Card, ErrorNote, Field } from "../components/ui";

const userRead = z.object({ id: z.string(), email: z.string(), display_name: z.string() }).passthrough();

const ROLES = [
  // 3-tier operational model: Recruiter authors, Recruiter Admin approves (and carries the
  // hiring-manager duties), Interview Panel assesses.
  "recruiter",
  "recruiter_admin",
  "interview_panel",
  // Governance / non-operational.
  "management_viewer",
  "audit_viewer",
  "system_admin",
];

export function AdminPage(): ReactNode {
  const toast = useToast();
  const [email, setEmail] = useState("");
  const [displayName, setDisplayName] = useState("");
  const [password, setPassword] = useState("");
  const [roles, setRoles] = useState<string[]>(["recruiter_admin"]);
  const [error, setError] = useState<string | null>(null);
  const [busy, setBusy] = useState(false);

  const toggleRole = (role: string): void =>
    setRoles((r) => (r.includes(role) ? r.filter((x) => x !== role) : [...r, role]));

  const create = async (): Promise<void> => {
    setBusy(true);
    setError(null);
    try {
      await apiFetch("/api/v1/users", userRead, {
        method: "POST",
        body: JSON.stringify({
          email,
          display_name: displayName,
          password,
          role_names: roles,
        }),
      });
      toast.push("User created", { tone: "ok", message: email });
      setEmail("");
      setDisplayName("");
      setPassword("");
    } catch (e) {
      setError(e instanceof ApiError ? e.message : "Could not create user (requires user.manage).");
    } finally {
      setBusy(false);
    }
  };

  const valid = email.trim() && displayName.trim() && password.length >= 12;

  return (
    <>
      <div className="page-head">
        <h1>Administration</h1>
        <p>Create staff accounts with least-privilege roles. There is no public signup.</p>
      </div>

      {error && <ErrorNote>{error}</ErrorNote>}

      <Card title="Create a staff user">
        <div className="grid grid--2">
          <Field label="Email" htmlFor="u-email">
            <input id="u-email" type="email" value={email} onChange={(e) => setEmail(e.target.value)} />
          </Field>
          <Field label="Display name" htmlFor="u-name">
            <input id="u-name" value={displayName} onChange={(e) => setDisplayName(e.target.value)} />
          </Field>
        </div>
        <Field label="Temporary password" htmlFor="u-pass" hint="At least 12 characters.">
          <input id="u-pass" type="password" value={password} onChange={(e) => setPassword(e.target.value)} />
        </Field>
        <Field label="Roles">
          <div className="btn-row">
            {ROLES.map((role) => (
              <button
                key={role}
                type="button"
                className={`assist-chip ${roles.includes(role) ? "" : ""}`}
                style={roles.includes(role) ? { background: "var(--brand-100)", borderColor: "var(--brand-500)" } : {}}
                onClick={() => toggleRole(role)}
              >
                {roles.includes(role) ? "✓ " : ""}
                {role.replace(/_/g, " ")}
              </button>
            ))}
          </div>
        </Field>
        <Button variant="primary" small disabled={!valid || busy} onClick={() => void create()}>
          {busy ? "Creating…" : "Create user"}
        </Button>
      </Card>

      <Card title="About accounts">
        <ul className="subtle" style={{ margin: 0, paddingLeft: 18, lineHeight: 1.9 }}>
          <li>Each permission only applies to campaigns the user is assigned to (object-level authz).</li>
          <li>System administrators do not get automatic access to candidate content.</li>
          <li>Rule creators cannot be the sole approver; threshold changes use four-eyes.</li>
        </ul>
      </Card>
    </>
  );
}
