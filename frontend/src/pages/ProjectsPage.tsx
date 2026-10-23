import { useMutation, useQuery, useQueryClient } from "@tanstack/react-query";
import { useState, type ReactNode } from "react";

import { ApiError } from "../api/client";
import { createProject, listProjects } from "../api/resources";
import { useAuth } from "../app/auth-context";
import { useToast } from "../components/toast";
import { Badge, Button, Card, Empty, ErrorNote, Field, Loading, Modal, prettify, toneFor } from "../components/ui";

export function ProjectsPage(): ReactNode {
  const { hasPermission } = useAuth();
  const toast = useToast();
  const qc = useQueryClient();
  const [showCreate, setShowCreate] = useState(false);
  const projects = useQuery({ queryKey: ["projects"], queryFn: listProjects });

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
          hasPermission("project.create") && (
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
                  </tr>
                ))}
              </tbody>
            </table>
          </div>
        )}
      </Card>

      {showCreate && (
        <CreateProjectModal
          onClose={() => setShowCreate(false)}
          onCreated={() => {
            setShowCreate(false);
            void qc.invalidateQueries({ queryKey: ["projects"] });
            toast.push("Project created", { tone: "ok" });
          }}
        />
      )}
    </>
  );
}

function CreateProjectModal({ onClose, onCreated }: { onClose: () => void; onCreated: () => void }): ReactNode {
  const [name, setName] = useState("");
  const [department, setDepartment] = useState("");
  const [businessUnit, setBusinessUnit] = useState("");
  const [error, setError] = useState<string | null>(null);

  const mutation = useMutation({
    mutationFn: () =>
      createProject({
        name,
        department: department || null,
        business_unit: businessUnit || null,
      }),
    onSuccess: onCreated,
    onError: (e) => setError(e instanceof ApiError ? e.message : "Could not create project."),
  });

  return (
    <Modal
      title="New project"
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
            {mutation.isPending ? "Creating…" : "Create project"}
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
