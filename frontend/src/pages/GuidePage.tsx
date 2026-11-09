import { useMemo, useState, type ReactNode } from "react";
import { Link } from "react-router-dom";

import { useAuth } from "../app/auth-context";
import { CANDIDATE_FLOW, FlowDiagram, RoleLegend, StatusStrip } from "../components/FlowDiagram";
import { Logo } from "../components/Logo";
import {
  CONNECTIONS,
  FAQ,
  GLOSSARY,
  JOURNEY,
  MESSAGE_STATES,
  NEXT_FOR_CANDIDATE,
  OPENING_FLOW,
  OVERVIEW,
  ROLES,
  SCREENS,
  TASKS,
} from "../lib/guideContent";

/* The in-app user guide. Public on purpose (/guide), so a new colleague or a candidate's
   contact person can read it before signing in. Written in plain language. */

const SECTIONS: { id: string; label: string }[] = [
  { id: "overview", label: "What this is" },
  { id: "opening", label: "Opening a job" },
  { id: "journey", label: "The candidate journey" },
  { id: "roles", label: "Who does what" },
  { id: "tasks", label: "How to do common tasks" },
  { id: "screens", label: "What each screen is for" },
  { id: "messages", label: "Messages and connections" },
  { id: "candidate", label: "What candidates see" },
  { id: "glossary", label: "Words used here" },
  { id: "faq", label: "Questions" },
];

function matches(query: string, ...texts: string[]): boolean {
  const q = query.trim().toLowerCase();
  return q === "" || texts.some((t) => t.toLowerCase().includes(q));
}

export function GuidePage(): ReactNode {
  const { actor } = useAuth();
  const [query, setQuery] = useState("");

  const tasks = useMemo(
    () => TASKS.filter((t) => matches(query, t.title, ...t.steps)),
    [query],
  );
  const glossary = useMemo(() => GLOSSARY.filter((g) => matches(query, g.term, g.meaning)), [query]);
  const faq = useMemo(() => FAQ.filter((f) => matches(query, f.q, f.a)), [query]);
  const screens = useMemo(() => SCREENS.filter((s) => matches(query, s.name, s.text)), [query]);
  const searching = query.trim() !== "";

  return (
    <main className="guide-shell" id="main">
      <div className="guide-top">
        <div className="btn-row" style={{ alignItems: "center" }}>
          <Logo size={32} title="Orient Recruitment Accelerator" />
          <h1 style={{ margin: 0, fontSize: "1.4rem" }}>User guide</h1>
        </div>
        <div className="btn-row">
          <label className="filter-search" style={{ minWidth: 240 }}>
            <input
              type="search"
              value={query}
              onChange={(e) => setQuery(e.target.value)}
              placeholder="Search this guide"
              aria-label="Search this guide"
            />
          </label>
          <Link className="btn btn--sm" to={actor ? "/" : "/login"}>
            {actor ? "Back to the app" : "Go to sign in"}
          </Link>
        </div>
      </div>

      <div className="guide-layout">
        <nav className="guide-toc" aria-label="Guide sections">
          {SECTIONS.map((s) => (
            <a key={s.id} href={`#${s.id}`}>
              {s.label}
            </a>
          ))}
        </nav>

        <div>
          {!searching && (
            <section className="guide-section" id="overview" aria-labelledby="h-overview">
              <h2 id="h-overview">What this is</h2>
              <p className="guide-lede">{OVERVIEW.lede}</p>
              <div className="guide-grid">
                {OVERVIEW.principles.map((p) => (
                  <div className="guide-card" key={p.title}>
                    <h3>{p.title}</h3>
                    <p>{p.text}</p>
                  </div>
                ))}
              </div>
            </section>
          )}

          {!searching && (
            <section className="guide-section" id="opening" aria-labelledby="h-opening">
              <h2 id="h-opening">Opening a job</h2>
              <p className="guide-lede">
                How a job opening goes live today, from the first project to the apply link.
              </p>
              <RoleLegend steps={OPENING_FLOW} />
              <FlowDiagram steps={OPENING_FLOW} label="How a job opening goes live" />
              <h3 className="flow-subhead">The status you will see on a job opening</h3>
              <StatusStrip />
            </section>
          )}

          {!searching && (
            <section className="guide-section" id="journey" aria-labelledby="h-journey">
              <h2 id="h-journey">The candidate journey</h2>
              <p className="guide-lede">
                Every candidate follows the same path from applying to their first day. On any
                candidate, click <strong>Journey</strong> to see where they are and what happens
                next.
              </p>
              <RoleLegend steps={CANDIDATE_FLOW} />
              <FlowDiagram steps={CANDIDATE_FLOW} label="Candidate journey" />
              <p className="guide-lede" style={{ marginTop: 16 }}>The same steps, with where each one happens:</p>
              <table className="guide-table">
                <thead>
                  <tr>
                    <th>Step</th>
                    <th>Who</th>
                    <th>Where</th>
                    <th>What happens</th>
                  </tr>
                </thead>
                <tbody>
                  {JOURNEY.map((s, i) => (
                    <tr key={s.title}>
                      <td>
                        {i + 1}. {s.title}
                      </td>
                      <td>{s.who}</td>
                      <td>{s.where}</td>
                      <td>{s.text}</td>
                    </tr>
                  ))}
                </tbody>
              </table>
            </section>
          )}

          {!searching && (
            <section className="guide-section" id="roles" aria-labelledby="h-roles">
              <h2 id="h-roles">Who does what</h2>
              <p className="guide-lede">What you see depends on your role. If a menu item is missing, your role does not include it.</p>
              <div className="guide-grid">
                {ROLES.map((r) => (
                  <div className="guide-card" key={r.role}>
                    <h3>{r.role}</h3>
                    <p>{r.summary}</p>
                    <ul>
                      {r.tasks.map((t) => (
                        <li key={t}>{t}</li>
                      ))}
                    </ul>
                  </div>
                ))}
              </div>
            </section>
          )}

          {tasks.length > 0 && (
            <section className="guide-section" id="tasks" aria-labelledby="h-tasks">
              <h2 id="h-tasks">How to do common tasks</h2>
              {tasks.map((t) => (
                <div className="guide-card" key={t.title} style={{ marginBottom: 12 }}>
                  <h3>{t.title}</h3>
                  <ol className="guide-steps">
                    {t.steps.map((s) => (
                      <li key={s}>{s}</li>
                    ))}
                  </ol>
                </div>
              ))}
            </section>
          )}

          {screens.length > 0 && (
            <section className="guide-section" id="screens" aria-labelledby="h-screens">
              <h2 id="h-screens">What each screen is for</h2>
              <table className="guide-table">
                <tbody>
                  {screens.map((s) => (
                    <tr key={s.name}>
                      <th scope="row">{s.name}</th>
                      <td>{s.text}</td>
                    </tr>
                  ))}
                </tbody>
              </table>
            </section>
          )}

          {!searching && (
            <section className="guide-section" id="messages" aria-labelledby="h-messages">
              <h2 id="h-messages">Messages and connections</h2>
              <p className="guide-lede">
                The product records every message it sends to a candidate or joiner. It never shows
                "sent" unless a real service accepted it.
              </p>
              <table className="guide-table">
                <thead>
                  <tr>
                    <th>You will see</th>
                    <th>It means</th>
                  </tr>
                </thead>
                <tbody>
                  {MESSAGE_STATES.map((m) => (
                    <tr key={m.state}>
                      <td>{m.state}</td>
                      <td>{m.meaning}</td>
                    </tr>
                  ))}
                </tbody>
              </table>
              <p className="guide-lede" style={{ marginTop: 16 }}>
                Everything works on this computer. Some outside connections are placeholders until
                they are set up:
              </p>
              <table className="guide-table">
                <thead>
                  <tr>
                    <th>Connection</th>
                    <th>Today</th>
                    <th>To connect it</th>
                  </tr>
                </thead>
                <tbody>
                  {CONNECTIONS.map((c) => (
                    <tr key={c.name}>
                      <td>{c.name}</td>
                      <td>{c.today}</td>
                      <td>{c.needs}</td>
                    </tr>
                  ))}
                </tbody>
              </table>
            </section>
          )}

          {!searching && (
            <section className="guide-section" id="candidate" aria-labelledby="h-candidate">
              <h2 id="h-candidate">What candidates see</h2>
              <p className="guide-lede">After applying, candidates are told what to expect:</p>
              <ol className="guide-steps">
                {NEXT_FOR_CANDIDATE.map((s) => (
                  <li key={s}>{s}</li>
                ))}
              </ol>
            </section>
          )}

          {glossary.length > 0 && (
            <section className="guide-section" id="glossary" aria-labelledby="h-glossary">
              <h2 id="h-glossary">Words used here</h2>
              <table className="guide-table">
                <tbody>
                  {glossary.map((g) => (
                    <tr key={g.term}>
                      <th scope="row">{g.term}</th>
                      <td>{g.meaning}</td>
                    </tr>
                  ))}
                </tbody>
              </table>
            </section>
          )}

          {faq.length > 0 && (
            <section className="guide-section guide-faq" id="faq" aria-labelledby="h-faq">
              <h2 id="h-faq">Questions</h2>
              {faq.map((f) => (
                <details key={f.q} open={searching}>
                  <summary>{f.q}</summary>
                  <p>{f.a}</p>
                </details>
              ))}
            </section>
          )}

          {searching && tasks.length + glossary.length + faq.length + screens.length === 0 && (
            <p className="guide-lede">Nothing in the guide matches "{query}". Try a simpler word.</p>
          )}
        </div>
      </div>
    </main>
  );
}
