import { useQuery, useQueryClient } from "@tanstack/react-query";
import { useState, type ReactNode } from "react";
import { z } from "zod";

import { apiFetch, ApiError } from "../api/client";
import { deleteUser, listUsers } from "../api/resources";
import { useAuth } from "../app/auth-context";
import { useToast } from "../components/toast";
import { Badge, Button, Card, Empty, ErrorNote, Field, Loading } from "../components/ui";

// Human-readable label for a role id.
const prettyRole = (r: string): string => r.replace(/_/g, " ");

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
  const qc = useQueryClient();
  const [email, setEmail] = useState("");
  const [displayName, setDisplayName] = useState("");
  const [password, setPassword] = useState("");
  const [confirmPassword, setConfirmPassword] = useState("");
  const [showPassword, setShowPassword] = useState(false);
  const [showConfirm, setShowConfirm] = useState(false);
  const [roles, setRoles] = useState<string[]>(["recruiter_admin"]);
  const [error, setError] = useState<string | null>(null);
  const [showErrors, setShowErrors] = useState(false);
  const [busy, setBusy] = useState(false);

  const toggleRole = (role: string): void =>
    setRoles((r) => (r.includes(role) ? r.filter((x) => x !== role) : [...r, role]));

  // Passwords must match before we attempt creation (the confirm field never leaves the
  // browser — only the single `password` is sent, exactly as before).
  const passwordsMatch = password === confirmPassword;
  const passwordLongEnough = password.length >= 12;

  const create = async (): Promise<void> => {
    setShowErrors(true);
    if (!email.trim() || !displayName.trim() || !passwordLongEnough || !passwordsMatch) {
      return;
    }
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
      setConfirmPassword("");
      setShowErrors(false);
      // Show the new user in the table immediately (no manual refresh needed).
      void qc.invalidateQueries({ queryKey: ["admin-users"] });
    } catch (e) {
      setError(e instanceof ApiError ? e.message : "Could not create user (requires user.manage).");
    } finally {
      setBusy(false);
    }
  };

  const valid =
    email.trim() !== "" && displayName.trim() !== "" && passwordLongEnough && passwordsMatch;

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

        <Field
          label="Temporary password"
          htmlFor="u-pass"
          hint="At least 12 characters."
          error={showErrors && !passwordLongEnough ? "Password must be at least 12 characters." : undefined}
        >
          <PasswordInput
            id="u-pass"
            value={password}
            onChange={setPassword}
            visible={showPassword}
            onToggle={() => setShowPassword((v) => !v)}
            autoComplete="new-password"
          />
        </Field>

        <Field
          label="Confirm password"
          htmlFor="u-pass-confirm"
          error={
            showErrors && password !== "" && !passwordsMatch
              ? "Passwords do not match."
              : undefined
          }
        >
          <PasswordInput
            id="u-pass-confirm"
            value={confirmPassword}
            onChange={setConfirmPassword}
            visible={showConfirm}
            onToggle={() => setShowConfirm((v) => !v)}
            autoComplete="new-password"
          />
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

      <UsersTable />

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

/* A masked text input with an accessible show/hide eye toggle. Used only for passwords being
   ENTERED (creation / reset). It never reveals a stored password — there is no such data on
   the client; this only toggles the visibility of what the admin is typing right now. */
function PasswordInput({
  id,
  value,
  onChange,
  visible,
  onToggle,
  autoComplete,
}: {
  id: string;
  value: string;
  onChange: (v: string) => void;
  visible: boolean;
  onToggle: () => void;
  autoComplete?: string;
}): ReactNode {
  return (
    <div style={{ position: "relative", display: "flex", alignItems: "center" }}>
      <input
        id={id}
        type={visible ? "text" : "password"}
        value={value}
        autoComplete={autoComplete}
        onChange={(e) => onChange(e.target.value)}
        style={{ width: "100%", paddingRight: 40 }}
      />
      <button
        type="button"
        onClick={onToggle}
        aria-label={visible ? "Hide password" : "Show password"}
        aria-pressed={visible}
        title={visible ? "Hide password" : "Show password"}
        style={{
          position: "absolute",
          right: 6,
          background: "transparent",
          border: "none",
          cursor: "pointer",
          fontSize: "1rem",
          lineHeight: 1,
          padding: 4,
        }}
      >
        {visible ? "🙈" : "👁"}
      </button>
    </div>
  );
}

/* The staff user list for System Admin: Name, Email, Role, Status, and a Delete action.
   Newly created users appear here immediately (Active). Delete is a safe soft-delete
   (deactivation) confirmed with the admin; the account is kept (history/assignments intact)
   but can no longer sign in or be selected as an interviewer. User metadata only — no
   candidate profiles, resumes, scores, or assessments are shown here. */
function UsersTable(): ReactNode {
  const { token, hasPermission } = useAuth();
  const qc = useQueryClient();
  const toast = useToast();
  const [error, setError] = useState<string | null>(null);
  const [deleting, setDeleting] = useState<string | null>(null);

  // Managing users needs user.manage. (System Admin holds it; it grants no candidate access.)
  const canManage = hasPermission("user.manage");

  const users = useQuery({
    queryKey: ["admin-users"],
    queryFn: () => listUsers(true), // include inactive so status is visible
    enabled: canManage,
  });

  async function handleDelete(id: string, name: string): Promise<void> {
    const authToken = token();
    if (!authToken) return;
    if (!window.confirm(`Delete user "${name}"?\n\nThey will be deactivated: they can no longer sign in or be selected as an interviewer. Existing records are kept.`)) {
      return;
    }
    setDeleting(id);
    setError(null);
    try {
      await deleteUser(id, authToken);
      await qc.invalidateQueries({ queryKey: ["admin-users"] });
      toast.push("User deleted.", { tone: "ok" });
    } catch (e) {
      setError(e instanceof Error ? e.message : "Could not delete the user.");
    } finally {
      setDeleting(null);
    }
  }

  if (!canManage) return null;

  const rows = users.data ?? [];

  return (
    <Card title="Users">
      <p className="subtle" style={{ marginTop: 0 }}>
        Staff accounts in your organisation. Deleting a user deactivates the account safely —
        existing records and assignments are preserved.
      </p>
      {error && <ErrorNote>{error}</ErrorNote>}
      {users.isLoading && <Loading label="Loading users…" />}
      {users.error && <ErrorNote>Could not load users (requires user.manage).</ErrorNote>}
      {users.data && rows.length === 0 && <Empty>No staff users yet.</Empty>}
      {rows.length > 0 && (
        <div className="table-wrap">
          <table className="data">
            <thead>
              <tr>
                <th>Name</th>
                <th>Email</th>
                <th>Role</th>
                <th>Status</th>
                <th />
              </tr>
            </thead>
            <tbody>
              {rows.map((u) => (
                <tr key={u.id}>
                  <td>{u.display_name}</td>
                  <td className="subtle">{u.email}</td>
                  <td>{(u.role_names ?? []).map(prettyRole).join(", ") || "—"}</td>
                  <td>
                    <Badge tone={u.is_active === false ? "neutral" : "ok"}>
                      {u.is_active === false ? "Inactive" : "Active"}
                    </Badge>
                  </td>
                  <td style={{ textAlign: "right" }}>
                    {u.is_active === false ? (
                      <span className="subtle">Deleted</span>
                    ) : (
                      <Button
                        variant="default"
                        small
                        disabled={deleting === u.id}
                        onClick={() => void handleDelete(u.id, u.display_name)}
                      >
                        {deleting === u.id ? "Deleting…" : "Delete"}
                      </Button>
                    )}
                  </td>
                </tr>
              ))}
            </tbody>
          </table>
        </div>
      )}
    </Card>
  );
}
