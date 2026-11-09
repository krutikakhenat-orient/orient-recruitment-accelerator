import { useMutation, useQuery, useQueryClient } from "@tanstack/react-query";
import { useMemo, useState, type ReactNode } from "react";
import { Link } from "react-router-dom";

import { ApiError } from "../api/client";
import {
  createCampaign,
  deleteCampaign,
  listCampaigns,
  listProjects,
  type Campaign,
} from "../api/resources";
import { useAuth } from "../app/auth-context";
import { useToast } from "../components/toast";
import { Badge, Button, Empty, ErrorNote, Field, Loading, Modal, PageHeader, prettify, toneFor } from "../components/ui";
import {
  FilterBar,
  FilterSelect,
  ItemCard,
  ItemGrid,
  ItemList,
  ItemRow,
  MineToggle,
  ViewSwitcher,
  useViewMode,
} from "../components/views";

export function CampaignsPage(): ReactNode {
  const { hasPermission, canAccessCampaign } = useAuth();
  const toast = useToast();
  const qc = useQueryClient();
  const [showCreate, setShowCreate] = useState(false);
  const [toDelete, setToDelete] = useState<Campaign | null>(null);
  const campaigns = useQuery({ queryKey: ["campaigns"], queryFn: listCampaigns });
  const canDelete = hasPermission("campaign.edit");

  const [view, setView] = useViewMode("campaigns", "table");
  const [search, setSearch] = useState("");
  const [stateFilter, setStateFilter] = useState("");
  const [mine, setMine] = useState(false);

  const all = useMemo(() => campaigns.data ?? [], [campaigns.data]);
  const stateOptions = useMemo(
    () => [...new Set(all.map((c) => c.state))].sort().map((s) => ({ value: s, label: prettify(s) })),
    [all],
  );
  const visible = useMemo(() => {
    const q = search.trim().toLowerCase();
    return all.filter(
      (c) =>
        (!q || c.name.toLowerCase().includes(q) || c.position_title.toLowerCase().includes(q)) &&
        (!stateFilter || c.state === stateFilter) &&
        (!mine || canAccessCampaign(c.id)),
    );
  }, [all, search, stateFilter, mine, canAccessCampaign]);

  const readiness = (c: Campaign): number =>
    [
      c.approved_jd_version_id,
      c.approved_rule_set_version_id,
      c.approved_form_version_id,
      c.active_threshold_version_id,
      c.privacy_notice_version,
    ].filter(Boolean).length;

  const applyLink = (c: Campaign): ReactNode => (
    <a
      className="btn btn--ghost btn--sm"
      href={`/apply/${c.id}`}
      target="_blank"
      rel="noreferrer"
      title="Open the public candidate application page"
    >
      Apply page ↗
    </a>
  );
  const deleteButton = (c: Campaign): ReactNode =>
    canDelete ? (
      <Button
        variant="danger"
        small
        onClick={() => setToDelete(c)}
        title="Permanently delete this campaign and all its data"
      >
        Delete
      </Button>
    ) : null;
  const badges = (c: Campaign): ReactNode => (
    <>
      <Badge tone={readiness(c) === 5 ? "ok" : "warn"}>{readiness(c)}/5 artifacts</Badge>
      <Badge tone={toneFor(c.state)}>{prettify(c.state)}</Badge>
    </>
  );

  return (
    <>
      <PageHeader
        title="Campaigns"
        description={
          <>
            A <strong>campaign</strong> is one job opening. Open a campaign to set up its job
            description, screening rules and application form, then open it so candidates can apply.
          </>
        }
        actions={
          hasPermission("campaign.create") && (
            <Button variant="primary" onClick={() => setShowCreate(true)}>
              + New campaign
            </Button>
          )
        }
      />

      {campaigns.isLoading && <Loading />}
      {campaigns.error && <ErrorNote>Could not load campaigns.</ErrorNote>}
      {campaigns.data && campaigns.data.length === 0 && <Empty>No campaigns yet.</Empty>}

      {all.length > 0 && (
        <>
          <FilterBar
            search={search}
            onSearch={setSearch}
            placeholder="Search campaigns or positions"
            trailing={
              <>
                <span className="result-count" aria-live="polite">
                  {visible.length} of {all.length}
                </span>
                <ViewSwitcher value={view} onChange={setView} />
              </>
            }
          >
            <FilterSelect
              label="Filter by state"
              allLabel="All states"
              value={stateFilter}
              onChange={setStateFilter}
              options={stateOptions}
            />
            <MineToggle checked={mine} onChange={setMine} label="Mine" />
          </FilterBar>

          {visible.length === 0 && (
            <Empty>{mine ? "You are not assigned to any matching campaign." : "No campaigns match your filters."}</Empty>
          )}

          {visible.length > 0 && view === "grid" && (
            <ItemGrid>
              {visible.map((c) => (
                <ItemCard
                  key={c.id}
                  title={<Link to={`/campaigns/${c.id}`}>{c.name}</Link>}
                  subtitle={c.position_title}
                  badges={badges(c)}
                  meta={`${c.number_of_openings} opening${c.number_of_openings === 1 ? "" : "s"}`}
                  actions={
                    <>
                      {applyLink(c)}
                      {deleteButton(c)}
                    </>
                  }
                />
              ))}
            </ItemGrid>
          )}

          {visible.length > 0 && view === "list" && (
            <ItemList>
              {visible.map((c) => (
                <ItemRow
                  key={c.id}
                  title={<Link to={`/campaigns/${c.id}`}>{c.name}</Link>}
                  subtitle={c.position_title}
                  meta={`${c.number_of_openings} opening${c.number_of_openings === 1 ? "" : "s"}`}
                  badges={badges(c)}
                  actions={
                    <>
                      {applyLink(c)}
                      {deleteButton(c)}
                    </>
                  }
                />
              ))}
            </ItemList>
          )}

          {visible.length > 0 && view === "table" && (
            <div className="table-wrap">
              <table className="data">
                <thead>
                  <tr>
                    <th>Campaign</th>
                    <th>Position</th>
                    <th>Openings</th>
                    <th>Readiness</th>
                    <th>State</th>
                    <th>Apply link</th>
                    {canDelete && <th>Actions</th>}
                  </tr>
                </thead>
                <tbody>
                  {visible.map((c) => (
                    <tr key={c.id}>
                      <td>
                        <Link to={`/campaigns/${c.id}`}>{c.name}</Link>
                      </td>
                      <td>{c.position_title}</td>
                      <td>{c.number_of_openings}</td>
                      <td>
                        <Badge tone={readiness(c) === 5 ? "ok" : "warn"}>{readiness(c)}/5 artifacts</Badge>
                      </td>
                      <td>
                        <Badge tone={toneFor(c.state)}>{prettify(c.state)}</Badge>
                      </td>
                      <td>{applyLink(c)}</td>
                      {canDelete && <td>{deleteButton(c)}</td>}
                    </tr>
                  ))}
                </tbody>
              </table>
            </div>
          )}
        </>
      )}

      {showCreate && (
        <CreateCampaignModal
          onClose={() => setShowCreate(false)}
          onCreated={() => {
            setShowCreate(false);
            void qc.invalidateQueries({ queryKey: ["campaigns"] });
            toast.push("Campaign created", { tone: "ok" });
          }}
        />
      )}

      {toDelete && (
        <DeleteCampaignModal
          campaign={toDelete}
          onClose={() => setToDelete(null)}
          onDeleted={(removed) => {
            setToDelete(null);
            void qc.invalidateQueries({ queryKey: ["campaigns"] });
            toast.push(
              removed > 0
                ? `Campaign deleted (${removed} application${removed === 1 ? "" : "s"} removed)`
                : "Campaign deleted",
              { tone: "ok" },
            );
          }}
        />
      )}
    </>
  );
}
function DeleteCampaignModal({
  campaign,
  onClose,
  onDeleted,
}: {
  campaign: Campaign;
  onClose: () => void;
  onDeleted: (applicationsRemoved: number) => void;
}): ReactNode {
  // Typed confirmation: the user must type the campaign name to arm the destructive action.
  const [confirmText, setConfirmText] = useState("");
  const [error, setError] = useState<string | null>(null);
  const armed = confirmText.trim() === campaign.name.trim();

  const mutation = useMutation({
    mutationFn: () => deleteCampaign(campaign.id),
    onSuccess: (res) => onDeleted(res.applications_removed),
    onError: (e) => setError(e instanceof ApiError ? e.message : "Could not delete the campaign."),
  });

  return (
    <Modal
      title="Delete campaign"
      onClose={onClose}
      footer={
        <>
          <Button onClick={onClose}>Cancel</Button>
          <Button
            variant="danger"
            disabled={!armed || mutation.isPending}
            onClick={() => {
              setError(null);
              mutation.mutate();
            }}
          >
            {mutation.isPending ? "Deleting…" : "Delete permanently"}
          </Button>
        </>
      }
    >
      {error && <ErrorNote>{error}</ErrorNote>}
      <p>
        This permanently deletes <strong>{campaign.name}</strong> ({campaign.position_title}) and
        <strong> all of its data</strong> — applications, screening and review history, the JD,
        screening rules, thresholds and application form. This cannot be undone.
      </p>
      <Field label={`Type the campaign name to confirm: ${campaign.name}`} htmlFor="del-confirm">
        <input
          id="del-confirm"
          value={confirmText}
          onChange={(e) => setConfirmText(e.target.value)}
          placeholder={campaign.name}
          autoFocus
        />
      </Field>
    </Modal>
  );
}

function CreateCampaignModal({ onClose, onCreated }: { onClose: () => void; onCreated: () => void }): ReactNode {
  const projects = useQuery({ queryKey: ["projects"], queryFn: listProjects });
  const [projectId, setProjectId] = useState("");
  const [name, setName] = useState("");
  const [position, setPosition] = useState("");
  const [openings, setOpenings] = useState(1);
  const [error, setError] = useState<string | null>(null);

  const mutation = useMutation({
    mutationFn: () =>
      createCampaign({
        project_id: projectId,
        name,
        position_title: position,
        number_of_openings: openings,
      }),
    onSuccess: onCreated,
    onError: (e) => setError(e instanceof ApiError ? e.message : "Could not create campaign."),
  });

  const valid = projectId && name.trim() && position.trim();

  return (
    <Modal
      title="New campaign"
      onClose={onClose}
      footer={
        <>
          <Button onClick={onClose}>Cancel</Button>
          <Button
            variant="primary"
            disabled={!valid || mutation.isPending}
            onClick={() => {
              setError(null);
              mutation.mutate();
            }}
          >
            {mutation.isPending ? "Creating…" : "Create campaign"}
          </Button>
        </>
      }
    >
      {error && <ErrorNote>{error}</ErrorNote>}
      {projects.data && projects.data.length === 0 && (
        <ErrorNote>Create a project first — campaigns must belong to one.</ErrorNote>
      )}
      <Field label="Project" htmlFor="c-project">
        <select id="c-project" value={projectId} onChange={(e) => setProjectId(e.target.value)}>
          <option value="">Select a project…</option>
          {projects.data?.map((p) => (
            <option key={p.id} value={p.id}>
              {p.name}
            </option>
          ))}
        </select>
      </Field>
      <Field label="Campaign name" htmlFor="c-name">
        <input id="c-name" value={name} onChange={(e) => setName(e.target.value)} />
      </Field>
      <Field label="Position title" htmlFor="c-pos">
        <input id="c-pos" value={position} onChange={(e) => setPosition(e.target.value)} />
      </Field>
      <Field label="Number of openings" htmlFor="c-open">
        <input
          id="c-open"
          type="number"
          min={1}
          value={openings}
          onChange={(e) => setOpenings(Number(e.target.value))}
        />
      </Field>
    </Modal>
  );
}
