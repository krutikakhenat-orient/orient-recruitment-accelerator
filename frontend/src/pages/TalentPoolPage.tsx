import { useState, type ReactNode } from "react";
import { z } from "zod";

import { apiFetch } from "../api/client";
import { Badge, Button, Card, Empty, ErrorNote, Field, Loading } from "../components/ui";

const match = z.object({
  candidate_id: z.string(),
  full_name: z.string(),
  email: z.string(),
  note: z.string(),
});
type Match = z.infer<typeof match>;

export function TalentPoolPage(): ReactNode {
  const [skill, setSkill] = useState("");
  const [results, setResults] = useState<Match[] | null>(null);
  const [loading, setLoading] = useState(false);
  const [error, setError] = useState<string | null>(null);

  const search = async (): Promise<void> => {
    if (!skill.trim()) return;
    setLoading(true);
    setError(null);
    try {
      const data = await apiFetch(
        `/api/v1/talent-pool/search?skill=${encodeURIComponent(skill)}`,
        z.array(match),
      );
      setResults(data);
    } catch {
      setError("Search failed — you may lack the talent_pool.search permission.");
    } finally {
      setLoading(false);
    }
  };

  return (
    <>
      <div className="page-head">
        <h1>Talent Pool</h1>
        <p>
          Only candidates who gave a separate, explicit opt-in appear here. A match is advisory —
          verify evidence before contacting anyone. Every search is audited.
        </p>
      </div>

      <Card title="Search consented talent">
        {error && <ErrorNote>{error}</ErrorNote>}
        <form
          onSubmit={(e) => {
            e.preventDefault();
            void search();
          }}
        >
          <Field label="Skill or keyword" htmlFor="tp-skill">
            <input id="tp-skill" value={skill} onChange={(e) => setSkill(e.target.value)} placeholder="e.g. python" />
          </Field>
          <Button variant="primary" small type="submit" disabled={loading || !skill.trim()}>
            {loading ? "Searching…" : "Search"}
          </Button>
        </form>
      </Card>

      {loading && <Loading />}
      {results && (
        <Card title={`Matches (${results.length})`}>
          {results.length === 0 && <Empty>No consented candidates matched.</Empty>}
          {results.length > 0 && (
            <div className="table-wrap">
              <table className="data">
                <thead>
                  <tr>
                    <th>Name</th>
                    <th>Email</th>
                    <th>Note</th>
                  </tr>
                </thead>
                <tbody>
                  {results.map((m) => (
                    <tr key={m.candidate_id}>
                      <td>{m.full_name}</td>
                      <td>{m.email}</td>
                      <td>
                        <Badge tone="warn">{m.note}</Badge>
                      </td>
                    </tr>
                  ))}
                </tbody>
              </table>
            </div>
          )}
        </Card>
      )}
    </>
  );
}
