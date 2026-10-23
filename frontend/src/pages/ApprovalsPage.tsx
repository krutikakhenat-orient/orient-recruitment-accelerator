import { useMutation, useQuery, useQueryClient } from "@tanstack/react-query";
import { useState, type ReactNode } from "react";
import { Link } from "react-router-dom";

import { ApiError } from "../api/client";
import {
  approveJd,
  approveRuleSet,
  listPendingJdVersions,
  listPendingRuleSets,
  rejectJd,
  rejectRuleSet,
  type JDVersion,
  type PendingRuleSet,
} from "../api/resources";
import { useAuth } from "../app/auth-context";
import { useToast } from "../components/toast";
import { Badge, Button, Card, Empty, ErrorNote, Field, Loading, Modal, prettify } from "../components/ui";

/* HR Head / Hiring Manager approvals inbox: pending Job Descriptions and screening
   rule-sets awaiting a decision, each with Approve / Reject. This is the focused view for
   approver roles — they don't see the recruiter authoring tools. */

export function ApprovalsPage(): ReactNode {
  const { hasPermission } = useAuth();
  const canApproveJd = hasPermission("jd.approve");
  const canApproveRules = hasPermission("rule.approve");

  const jds = useQuery({
    queryKey: ["pending-jds"],
    queryFn: listPendingJdVersions,
    enabled: canApproveJd,
  });
  const rules = useQuery({
    queryKey: ["pending-rulesets"],
    queryFn: listPendingRuleSets,
    enabled: canApproveRules,
  });

  const pendingCount = (jds.data?.length ?? 0) + (rules.data?.length ?? 0);

  return (
    <>
      <div className="page-head">
        <h1>Approvals</h1>
        <p>
          Items awaiting your decision. Approving a Job Description or rule-set makes it
          immutable; rejecting returns it to the author with your reason. You are only shown
          items for campaigns you are assigned to.
        </p>
      </div>

      {!canApproveJd && !canApproveRules && (
        <Card title="Nothing to approve">
          <Empty>Your role has no approval responsibilities.</Empty>
        </Card>
      )}

      {(jds.isLoading || rules.isLoading) && <Loading label="Loading approvals…" />}

      {pendingCount === 0 && !jds.isLoading && !rules.isLoading && (canApproveJd || canApproveRules) && (
        <Card title="All clear">
          <Empty>
            No items are awaiting your approval right now. New Job Descriptions and rule-sets
            created by recruiters will appear here.
          </Empty>
        </Card>
      )}

      {canApproveJd && jds.data && jds.data.length > 0 && (
        <Card title={`Job Descriptions awaiting approval (${jds.data.length})`}>
          <div className="table-wrap">
            <table className="data">
              <thead>
                <tr>
                  <th>Position</th>
                  <th>Version</th>
                  <th>Status</th>
                  <th />
                </tr>
              </thead>
              <tbody>
                {jds.data.map((v) => (
                  <JdRow key={v.id} version={v} />
                ))}
              </tbody>
            </table>
          </div>
        </Card>
      )}

      {canApproveRules && rules.data && rules.data.length > 0 && (
        <Card title={`Rule-sets awaiting approval (${rules.data.length})`}>
          <div className="table-wrap">
            <table className="data">
              <thead>
                <tr>
                  <th>Rule set</th>
                  <th>Criteria</th>
                  <th>Version</th>
                  <th />
                </tr>
              </thead>
              <tbody>
                {rules.data.map((v) => (
                  <RuleRow key={v.id} version={v} />
                ))}
              </tbody>
            </table>
          </div>
        </Card>
      )}

      <Card title="Need to see the full campaign?">
        <p className="subtle" style={{ marginTop: 0 }}>
          Open the campaign for full context (readiness, lifecycle, applicants).
        </p>
        <Link to="/campaigns" className="btn btn--sm">
          Go to Campaigns
        </Link>
      </Card>
    </>
  );
}

function JdRow({ version }: { version: JDVersion }): ReactNode {
  const toast = useToast();
  const qc = useQueryClient();
  const [error, setError] = useState<string | null>(null);
  const [rejecting, setRejecting] = useState(false);

  const done = (): void => {
    void qc.invalidateQueries({ queryKey: ["pending-jds"] });
  };

  const approve = useMutation({
    mutationFn: () => approveJd(version.id, "Approved via approvals inbox"),
    onSuccess: () => { done(); toast.push("JD approved", { tone: "ok" }); },
    onError: (e) => setError(e instanceof ApiError ? e.message : "Approval failed."),
  });
  const reject = useMutation({
    mutationFn: (reason: string) => rejectJd(version.id, reason),
    onSuccess: () => { setRejecting(false); done(); toast.push("JD rejected", { tone: "ok" }); },
    onError: (e) => setError(e instanceof ApiError ? e.message : "Rejection failed."),
  });

  return (
    <tr>
      <td>{version.position_title ?? "— (needs a title)"}</td>
      <td>v{version.version_number}</td>
      <td><Badge tone="warn">Pending</Badge></td>
      <td style={{ textAlign: "right" }}>
        {error && <ErrorNote>{error}</ErrorNote>}
        <div className="btn-row" style={{ justifyContent: "flex-end" }}>
          <Button
            variant="accent"
            small
            disabled={approve.isPending || !version.position_title}
            title={version.position_title ? undefined : "The author must set a position title first"}
            onClick={() => { setError(null); approve.mutate(); }}
          >
            Approve
          </Button>
          <Button variant="danger" small disabled={reject.isPending} onClick={() => setRejecting(true)}>
            Reject
          </Button>
        </div>
      </td>
      {rejecting && (
        <RejectModal
          title="Reject Job Description"
          pending={reject.isPending}
          onCancel={() => setRejecting(false)}
          onConfirm={(reason) => reject.mutate(reason)}
        />
      )}
    </tr>
  );
}

function RuleRow({ version }: { version: PendingRuleSet }): ReactNode {
  const toast = useToast();
  const qc = useQueryClient();
  const [error, setError] = useState<string | null>(null);
  const [rejecting, setRejecting] = useState(false);

  const done = (): void => {
    void qc.invalidateQueries({ queryKey: ["pending-rulesets"] });
  };

  const approve = useMutation({
    mutationFn: () => approveRuleSet(version.id),
    onSuccess: () => { done(); toast.push("Rule-set approved", { tone: "ok" }); },
    onError: (e) =>
      setError(
        e instanceof ApiError
          ? e.message + (e.code === "separation_of_duties" ? " — you cannot approve a rule-set you created." : "")
          : "Approval failed.",
      ),
  });
  const reject = useMutation({
    mutationFn: (reason: string) => rejectRuleSet(version.id, reason),
    onSuccess: () => { setRejecting(false); done(); toast.push("Rule-set rejected", { tone: "ok" }); },
    onError: (e) => setError(e instanceof ApiError ? e.message : "Rejection failed."),
  });

  const [showRules, setShowRules] = useState(false);

  return (
    <>
      <tr>
        <td>{version.name}</td>
        <td>
          {version.rules.length} criteria{" "}
          <button className="btn btn--ghost btn--sm" onClick={() => setShowRules((s) => !s)}>
            {showRules ? "Hide" : "View rules"}
          </button>
        </td>
        <td>v{version.version_number}</td>
        <td style={{ textAlign: "right" }}>
          {error && <ErrorNote>{error}</ErrorNote>}
          <div className="btn-row" style={{ justifyContent: "flex-end" }}>
            <Button variant="accent" small disabled={approve.isPending} onClick={() => { setError(null); approve.mutate(); }}>
              Approve
            </Button>
            <Button variant="danger" small disabled={reject.isPending} onClick={() => setRejecting(true)}>
              Reject
            </Button>
          </div>
        </td>
        {rejecting && (
          <RejectModal
            title="Reject rule-set"
            pending={reject.isPending}
            onCancel={() => setRejecting(false)}
            onConfirm={(reason) => reject.mutate(reason)}
          />
        )}
      </tr>
      {showRules && (
        <tr>
          <td colSpan={4} style={{ background: "var(--surface-2, #f3f6fa)" }}>
            <RuleCriteriaList rules={version.rules} />
          </td>
        </tr>
      )}
    </>
  );
}

/* Human-readable list of the criteria in a rule-set, so an approver sees exactly what they
   are approving (not just the name). Groups skill criteria by tier when present. */
function RuleCriteriaList({ rules }: { rules: Record<string, unknown>[] }): ReactNode {
  if (rules.length === 0) return <p className="subtle">This rule-set has no criteria.</p>;

  const describe = (r: Record<string, unknown>): string => {
    const type = String(r.criterion_type ?? "");
    const name = String(r.name ?? r.rule_id ?? type);
    if (type === "exact_skill") {
      return `Skill: ${name}`;
    }
    const op = r.operator ? String(r.operator) : "";
    const expected =
      r.expected_value !== undefined ? String(r.expected_value) : r.max !== undefined ? `${r.min}–${r.max}` : "";
    const field = r.field ? String(r.field) : "";
    return `${name}${field ? ` (${field} ${op} ${expected})` : ""}`;
  };

  return (
    <div style={{ padding: "10px 4px" }}>
      <div className="table-wrap">
        <table className="data">
          <thead>
            <tr>
              <th>Criterion</th>
              <th>Tier</th>
              <th>Weight</th>
              <th>Mandatory</th>
            </tr>
          </thead>
          <tbody>
            {rules.map((r, i) => (
              <tr key={i}>
                <td>{describe(r)}</td>
                <td>{r.tier ? prettify(String(r.tier)) : "—"}</td>
                <td>{r.weight !== undefined ? String(r.weight) : "0"}</td>
                <td>{r.mandatory ? "Yes" : "No"}</td>
              </tr>
            ))}
          </tbody>
        </table>
      </div>
    </div>
  );
}

function RejectModal({
  title,
  pending,
  onCancel,
  onConfirm,
}: {
  title: string;
  pending: boolean;
  onCancel: () => void;
  onConfirm: (reason: string) => void;
}): ReactNode {
  const [reason, setReason] = useState("");
  return (
    <Modal
      title={title}
      onClose={onCancel}
      footer={
        <>
          <Button onClick={onCancel}>Cancel</Button>
          <Button variant="danger" disabled={!reason.trim() || pending} onClick={() => onConfirm(reason.trim())}>
            {pending ? "Rejecting…" : "Confirm reject"}
          </Button>
        </>
      }
    >
      <p className="subtle" style={{ marginTop: 0 }}>
        A reason is required and is recorded in the audit trail. The author will see it.
      </p>
      <Field label="Reason for rejection" htmlFor="reject-reason">
        <input
          id="reject-reason"
          value={reason}
          onChange={(e) => setReason(e.target.value)}
          placeholder="e.g. mandatory experience threshold is too low"
        />
      </Field>
    </Modal>
  );
}
