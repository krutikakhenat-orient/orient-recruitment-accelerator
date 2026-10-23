import { useMutation, useQuery, useQueryClient } from "@tanstack/react-query";
import { useState, type ReactNode } from "react";

import { ApiError } from "../api/client";
import {
  createProject,
  deleteProject,
  listProjects,
  updateProject,
  type Project,
} from "../api/resources";
import { useAuth } from "../app/auth-context";
import { useToast } from "../components/toast";
import { Badge, Button, Card, Empty, ErrorNote, Field, Loading, Modal, prettify, toneFor } from "../components/ui";

export function ProjectsPage(): ReactNode {
  const { hasPermission } = useAuth();
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

  return (
    <>
      <div className="page-head">
        <h1>Projects</h1>
        <p>
          A <strong>project</strong> is a hiring need (e.g. &ldquo;Engineering 2026&rdquo;). Each
          project holds one or more <strong>campaigns</strong> — the individual job openings. Start
          here, then add campaigns.
        </p>
      </div>

      <Card
        title="All projects"
        actions={
          canManage && (
            <Button variant="primary" small onClick={() => setShowCreate(true)}>
              + New project
            </Button>
          )
        }
      >
        {projects.isLoading && <Loading />}
        {projects.error && <ErrorNote>Could not load projects.</ErrorNote>}
        {projects.data && projects.data.length === 0 && <Empty>No projects yet.</Empty>}
        {projects.data && projects.data.length > 0 && (
          <div className="table-wrap">
            <table className="data">
              <thead>
                <tr>
                  <th>Name</th>
                  <th>Department</th>
                  <th>Status</th>
                  {canManage && <th aria-label="Actions" />}
                </tr>
              </thead>
              <tbody>
                {projects.data.map((p) => (
                  <tr key={p.id}>
                    <td>{p.name}</td>
                    <td>{p.department ?? "—"}</td>
                    <td>
                      <Badge tone={toneFor(p.status)}>{prettify(p.status)}</Badge>
                    </td>
                    {canManage && (
                      <td style={{ textAlign: "right" }}>
                        <div className="btn-row" style={{ justifyContent: "flex-end" }}>
                          <Button variant="default" small onClick={() => setEditProject(p)}>
                            Edit
                          </Button>
                          <Button variant="danger" small onClick={() => setDeleteTarget(p)}>
                            Delete
                          </Button>
                        </div>
                      </td>
                    )}
                  </tr>
                ))}
              </tbody>
            </table>
          </div>
        )}
      </Card>

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
