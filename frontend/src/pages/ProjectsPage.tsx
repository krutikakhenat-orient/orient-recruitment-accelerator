import { useMutation, useQuery, useQueryClient } from "@tanstack/react-query";
import { useMemo, useState, type ReactNode } from "react";

import { ApiError } from "../api/client";
import {
  createProject,
  deleteProject,
  listCampaigns,
  listProjects,
  updateProject,
  type Project,
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

export function ProjectsPage(): ReactNode {
  const { hasPermission, canAccessCampaign } = useAuth();
  const toast = useToast();
  const qc = useQueryClient();
  const [showCreate, setShowCreate] = useState(false);
  const [editProject, setEditProject] = useState<Project | null>(null);
  const [deleteTarget, setDeleteTarget] = useState<Project | null>(null);
  const projects = useQuery({ queryKey: ["projects"], queryFn: listProjects });

  // project.create is the permission the backend requires for create/edit/delete.
  const canManage = hasPermission("project.create");

  const refresh = (): void => {
    void qc.invalidateQueries({ queryKey: ["projects"] });
    // Deleting a project removes its campaigns too; refresh those lists as well.
    void qc.invalidateQueries({ queryKey: ["campaigns"] });
  };

  const campaigns = useQuery({ queryKey: ["campaigns"], queryFn: listCampaigns });
  const [view, setView] = useViewMode("projects", "table");
  const [search, setSearch] = useState("");
  const [statusFilter, setStatusFilter] = useState("");
  const [mine, setMine] = useState(false);

  const all = useMemo(() => projects.data ?? [], [projects.data]);
  const statusOptions = useMemo(
    () => [...new Set(all.map((p) => p.status))].sort().map((s) => ({ value: s, label: prettify(s) })),
    [all],
  );
  // A project is "mine" when it holds at least one campaign the user is assigned to.
  const myProjectIds = useMemo(
    () => new Set((campaigns.data ?? []).filter((c) => canAccessCampaign(c.id)).map((c) => c.project_id)),
    [campaigns.data, canAccessCampaign],
  );
  const countByProject = useMemo(() => {
    const m = new Map<string, number>();
    for (const c of campaigns.data ?? []) m.set(c.project_id, (m.get(c.project_id) ?? 0) + 1);
    return m;
  }, [campaigns.data]);
  const campaignCount = (projectId: string): string => {
    const n = countByProject.get(projectId) ?? 0;
    return `${n} campaign${n === 1 ? "" : "s"}`;
  };
  const visible = useMemo(() => {
    const q = search.trim().toLowerCase();
    return all.filter(
      (p) =>
        (!q || p.name.toLowerCase().includes(q) || (p.department ?? "").toLowerCase().includes(q)) &&
        (!statusFilter || p.status === statusFilter) &&
        (!mine || myProjectIds.has(p.id)),
    );
  }, [all, search, statusFilter, mine, myProjectIds]);

  const rowActions = (p: Project): ReactNode =>
    canManage ? (
      <>
        <Button variant="default" small onClick={() => setEditProject(p)}>
          Edit
        </Button>
        <Button variant="danger" small onClick={() => setDeleteTarget(p)}>
          Delete
        </Button>
      </>
    ) : null;
  return (
    <>
      <PageHeader
        title="Projects"
        description={
          <>
            A <strong>project</strong> is a hiring need (e.g. &ldquo;Engineering 2026&rdquo;). Each
            project holds one or more <strong>campaigns</strong> &mdash; the individual job openings.
            Start here, then add campaigns.
          </>
        }
        actions={
          canManage && (
            <Button variant="primary" onClick={() => setShowCreate(true)}>
              + New project
            </Button>
          )
        }
      />

      {projects.isLoading && <Loading />}
      {projects.error && <ErrorNote>Could not load projects.</ErrorNote>}
      {projects.data && projects.data.length === 0 && <Empty>No projects yet.</Empty>}

      {all.length > 0 && (
        <>
          <FilterBar
            search={search}
            onSearch={setSearch}
            placeholder="Search projects or departments"
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
              label="Filter by status"
              allLabel="All statuses"
              value={statusFilter}
              onChange={setStatusFilter}
              options={statusOptions}
            />
            <MineToggle checked={mine} onChange={setMine} label="Mine" />
          </FilterBar>

          {visible.length === 0 && (
            <Empty>{mine ? "You are not assigned to any campaign in a matching project." : "No projects match your filters."}</Empty>
          )}

          {visible.length > 0 && view === "grid" && (
            <ItemGrid>
              {visible.map((p) => (
                <ItemCard
                  key={p.id}
                  title={p.name}
                  subtitle={p.department ?? "No department"}
                  badges={<Badge tone={toneFor(p.status)}>{prettify(p.status)}</Badge>}
                  meta={campaignCount(p.id)}
                  actions={rowActions(p)}
                />
              ))}
            </ItemGrid>
          )}

          {visible.length > 0 && view === "list" && (
            <ItemList>
              {visible.map((p) => (
                <ItemRow
                  key={p.id}
                  title={p.name}
                  subtitle={p.department ?? "No department"}
                  meta={campaignCount(p.id)}
                  badges={<Badge tone={toneFor(p.status)}>{prettify(p.status)}</Badge>}
                  actions={rowActions(p)}
                />
              ))}
            </ItemList>
          )}

          {visible.length > 0 && view === "table" && (
            <div className="table-wrap">
              <table className="data">
                <thead>
                  <tr>
                    <th>Name</th>
                    <th>Department</th>
                    <th>Campaigns</th>
                    <th>Status</th>
                    {canManage && <th aria-label="Actions" />}
                  </tr>
                </thead>
                <tbody>
                  {visible.map((p) => (
                    <tr key={p.id}>
                      <td>{p.name}</td>
                      <td>{p.department ?? "—"}</td>
                      <td>{campaignCount(p.id)}</td>
                      <td>
                        <Badge tone={toneFor(p.status)}>{prettify(p.status)}</Badge>
                      </td>
                      {canManage && (
                        <td style={{ textAlign: "right" }}>
                          <div className="btn-row" style={{ justifyContent: "flex-end" }}>
                            {rowActions(p)}
                          </div>
                        </td>
                      )}
                    </tr>
                  ))}
                </tbody>
              </table>
            </div>
          )}
        </>
      )}
      {showCreate && (
        <ProjectFormModal
          mode="create"
          onClose={() => setShowCreate(false)}
          onDone={() => {
            setShowCreate(false);
            refresh();
            toast.push("Project created", { tone: "ok" });
          }}
        />
      )}

      {editProject && (
        <ProjectFormModal
          mode="edit"
          project={editProject}
          onClose={() => setEditProject(null)}
          onDone={() => {
            setEditProject(null);
            refresh();
            toast.push("Project updated", { tone: "ok" });
          }}
        />
      )}

      {deleteTarget && (
        <DeleteProjectModal
          project={deleteTarget}
          onClose={() => setDeleteTarget(null)}
          onDeleted={(summary) => {
            setDeleteTarget(null);
            refresh();
            toast.push(
              `Project deleted — removed ${summary.campaigns} campaign(s) and ${summary.applications} application(s)`,
              { tone: "ok" },
            );
          }}
        />
      )}
    </>
  );
}

/* Create or edit a project. In edit mode the fields are pre-filled from the project and
   only changed fields are sent. */
function ProjectFormModal({
  mode,
  project,
  onClose,
  onDone,
}: {
  mode: "create" | "edit";
  project?: Project;
  onClose: () => void;
  onDone: () => void;
}): ReactNode {
  const [name, setName] = useState(project?.name ?? "");
  const [department, setDepartment] = useState(project?.department ?? "");
  const [businessUnit, setBusinessUnit] = useState(
    (project as { business_unit?: string | null } | undefined)?.business_unit ?? "",
  );
  const [error, setError] = useState<string | null>(null);

  const mutation = useMutation({
    mutationFn: () => {
      const body = {
        name: name.trim(),
        department: department.trim() || null,
        business_unit: businessUnit.trim() || null,
      };
      return mode === "create"
        ? createProject(body)
        : updateProject(project!.id, body);
    },
    onSuccess: onDone,
    onError: (e) =>
      setError(e instanceof ApiError ? e.message : `Could not ${mode} project.`),
  });

  return (
    <Modal
      title={mode === "create" ? "New project" : "Edit project"}
      onClose={onClose}
      footer={
        <>
          <Button onClick={onClose}>Cancel</Button>
          <Button
            variant="primary"
            disabled={!name.trim() || mutation.isPending}
            onClick={() => {
              setError(null);
              mutation.mutate();
            }}
          >
            {mutation.isPending
              ? "Saving…"
              : mode === "create"
                ? "Create project"
                : "Save changes"}
          </Button>
        </>
      }
    >
      {error && <ErrorNote>{error}</ErrorNote>}
      <Field label="Project name" htmlFor="p-name">
        <input id="p-name" value={name} onChange={(e) => setName(e.target.value)} />
      </Field>
      <Field label="Department" htmlFor="p-dept">
        <input id="p-dept" value={department} onChange={(e) => setDepartment(e.target.value)} />
      </Field>
      <Field label="Business unit" htmlFor="p-bu">
        <input id="p-bu" value={businessUnit} onChange={(e) => setBusinessUnit(e.target.value)} />
      </Field>
    </Modal>
  );
}

/* Destructive delete confirmation. Deleting a project removes ALL its campaigns and their
   data (applications, screening, interviews, assessments, decisions, waitlist, config), so
   we require the user to type the project name to confirm (accessibility.md: confirmation
   for consequential actions). */
function DeleteProjectModal({
  project,
  onClose,
  onDeleted,
}: {
  project: Project;
  onClose: () => void;
  onDeleted: (summary: { campaigns: number; applications: number }) => void;
}): ReactNode {
  const [confirmText, setConfirmText] = useState("");
  const [error, setError] = useState<string | null>(null);

  const mutation = useMutation({
    mutationFn: () => deleteProject(project.id),
    onSuccess: (res) =>
      onDeleted({
        campaigns: res.campaigns_removed,
        applications: res.applications_removed,
      }),
    onError: (e) => setError(e instanceof ApiError ? e.message : "Could not delete project."),
  });

  const confirmed = confirmText.trim() === project.name;

  return (
    <Modal
      title="Delete project"
      onClose={onClose}
      footer={
        <>
          <Button onClick={onClose}>Cancel</Button>
          <Button
            variant="danger"
            disabled={!confirmed || mutation.isPending}
            title={confirmed ? undefined : "Type the project name to confirm"}
            onClick={() => {
              setError(null);
              mutation.mutate();
            }}
          >
            {mutation.isPending ? "Deleting…" : "Delete project and all its data"}
          </Button>
        </>
      }
    >
      {error && <ErrorNote>{error}</ErrorNote>}
      <div className="error-summary" role="alert" style={{ marginBottom: 12 }}>
        ⚠️ This permanently deletes <strong>{project.name}</strong> and <strong>every campaign
        inside it</strong>, including all applications, resumes/extracted data, screening and
        review history, interviews, assessments, hiring decisions and waitlist entries. This
        cannot be undone.
      </div>
      <Field
        label={`Type the project name to confirm: ${project.name}`}
        htmlFor="p-confirm"
      >
        <input
          id="p-confirm"
          value={confirmText}
          onChange={(e) => setConfirmText(e.target.value)}
          placeholder={project.name}
          autoComplete="off"
        />
      </Field>
    </Modal>
  );
}
