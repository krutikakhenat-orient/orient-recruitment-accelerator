/* Public job openings board, laid out like a large company careers site:
     left  - "N jobs matched", search, collapsible filters, sort;
     right - one clean card per job: title, company / location / level, minimum
             qualifications from the approved job description, "Learn more" and share.
   Everything is computed in the browser from the public open-jobs list (no tracking, no
   account). Only APPROVED job-description content is ever shown. */

import { BarChart3, Briefcase, Building2, Link2, MapPin, Search } from "lucide-react";
import { useMemo, useState, type ReactNode } from "react";

import type { PublicRole } from "../api/resources";
import { useToast } from "./toast";

export const COMPANY = "Orient";

type Level = "Entry" | "Mid" | "Senior" | "Not specified";

export function levelOf(role: PublicRole): Level {
  const y = role.minimum_experience_years;
  if (y === null || y === undefined) return "Not specified";
  if (y < 2) return "Entry";
  if (y < 5) return "Mid";
  return "Senior";
}

export function pretty(value: string): string {
  const s = value.replace(/_/g, " ");
  return s.charAt(0).toUpperCase() + s.slice(1);
}

export function experienceLine(role: PublicRole): string | null {
  const y = role.minimum_experience_years;
  if (y === null || y === undefined) return null;
  const n = Number.isInteger(y) ? String(y) : y.toFixed(1);
  return y <= 0 ? "Open to freshers" : `${n}+ years of total experience`;
}

type Filters = {
  locations: Set<string>;
  levels: Set<string>;
  skills: Set<string>;
  types: Set<string>;
  modes: Set<string>;
  departments: Set<string>;
};

const emptyFilters = (): Filters => ({
  locations: new Set(),
  levels: new Set(),
  skills: new Set(),
  types: new Set(),
  modes: new Set(),
  departments: new Set(),
});

type Sort = "newest" | "title";

function valuesOf(role: PublicRole, key: keyof Filters): string[] {
  switch (key) {
    case "locations":
      return role.location ? [role.location] : [];
    case "levels":
      return [levelOf(role)];
    case "skills":
      return [...(role.must_have_skills ?? []), ...(role.nice_to_have_skills ?? [])];
    case "types":
      return role.employment_type ? [pretty(role.employment_type)] : [];
    case "modes":
      return role.work_mode ? [pretty(role.work_mode)] : [];
    case "departments":
      return role.department ? [role.department] : [];
  }
}

function matchesText(role: PublicRole, needle: string): boolean {
  if (!needle) return true;
  const haystack = [
    role.title,
    role.department ?? "",
    role.location ?? "",
    ...(role.must_have_skills ?? []),
    ...(role.nice_to_have_skills ?? []),
    ...(role.responsibilities ?? []),
  ]
    .join(" ")
    .toLowerCase();
  return needle
    .split(/\s+/)
    .filter(Boolean)
    .every((word) => haystack.includes(word));
}

const FILTER_SECTIONS: { key: keyof Filters; label: string }[] = [
  { key: "locations", label: "Locations" },
  { key: "levels", label: "Experience" },
  { key: "skills", label: "Skills and qualifications" },
  { key: "types", label: "Job types" },
  { key: "modes", label: "Work mode" },
  { key: "departments", label: "Teams" },
];

export function JobsBoard({
  roles,
  onOpen,
  jobUrl,
}: {
  roles: PublicRole[];
  onOpen: (id: string) => void;
  jobUrl: (id: string) => string;
}): ReactNode {
  const toast = useToast();
  const [query, setQuery] = useState("");
  const [filters, setFilters] = useState<Filters>(emptyFilters);
  const [sort, setSort] = useState<Sort>("newest");

  // Options with counts (from all jobs), so candidates see what exists before choosing.
  const options = useMemo(() => {
    const out = {} as Record<keyof Filters, [string, number][]>;
    for (const { key } of FILTER_SECTIONS) {
      const counts = new Map<string, number>();
      for (const r of roles) for (const v of new Set(valuesOf(r, key))) counts.set(v, (counts.get(v) ?? 0) + 1);
      out[key] = [...counts.entries()].sort((a, b) => b[1] - a[1] || a[0].localeCompare(b[0]));
    }
    return out;
  }, [roles]);

  const needle = query.trim().toLowerCase();
  const shown = roles
    .filter((r) => matchesText(r, needle))
    .filter((r) =>
      FILTER_SECTIONS.every(({ key }) => {
        const chosen = filters[key];
        return chosen.size === 0 || valuesOf(r, key).some((v) => chosen.has(v));
      }),
    )
    .sort((a, b) =>
      sort === "title"
        ? a.title.localeCompare(b.title)
        : Date.parse(b.posted_at ?? "") - Date.parse(a.posted_at ?? "") || a.title.localeCompare(b.title),
    );

  const activeCount = FILTER_SECTIONS.reduce((n, { key }) => n + filters[key].size, 0);
  const toggle = (key: keyof Filters, value: string): void =>
    setFilters((prev) => {
      const next = new Set(prev[key]);
      if (next.has(value)) next.delete(value);
      else next.add(value);
      return { ...prev, [key]: next };
    });
  const clearAll = (): void => {
    setFilters(emptyFilters());
    setQuery("");
  };

  const share = (role: PublicRole): void => {
    const url = jobUrl(role.id);
    void navigator.clipboard
      ?.writeText(url)
      .then(() => toast.push("Job link copied", { tone: "ok" }))
      .catch(() => toast.push(url, { tone: "info" }));
  };

  return (
    <div className="jobs">
      <aside className="jobs__side" aria-label="Search and filters">
        <div className="jobs__count-row">
          <p className="jobs__count" role="status" aria-live="polite">
            <strong>{shown.length}</strong> {shown.length === 1 ? "job" : "jobs"} matched
          </p>
          {(activeCount > 0 || query) && (
            <button type="button" className="jobs__clear" onClick={clearAll}>
              Clear filters
            </button>
          )}
        </div>
        <label htmlFor="jobs-q" className="sr-only">
          Search jobs
        </label>
        <div className="jobs__search">
          <Search size={16} aria-hidden="true" />
          <input
            id="jobs-q"
            type="search"
            value={query}
            onChange={(e) => setQuery(e.target.value)}
            placeholder="What do you want to do?"
          />
        </div>
        {FILTER_SECTIONS.map(({ key, label }) =>
          options[key].length === 0 ? null : (
            <details key={key} className="jobs__filter" open={filters[key].size > 0}>
              <summary>
                {label}
                {filters[key].size > 0 && <span className="jobs__badge">{filters[key].size}</span>}
              </summary>
              <ul>
                {options[key].map(([value, n]) => (
                  <li key={value}>
                    <label className="jobs__opt">
                      <input
                        type="checkbox"
                        checked={filters[key].has(value)}
                        onChange={() => toggle(key, value)}
                      />
                      <span className="jobs__opt-text">{value}</span>
                      <span className="jobs__opt-count" aria-label={`${n} jobs`}>
                        {n}
                      </span>
                    </label>
                  </li>
                ))}
              </ul>
            </details>
          ),
        )}
        <details className="jobs__filter">
          <summary>Sort by</summary>
          <ul>
            {(
              [
                ["newest", "Newest first"],
                ["title", "Job title (A–Z)"],
              ] as const
            ).map(([value, text]) => (
              <li key={value}>
                <label className="jobs__opt">
                  <input
                    type="radio"
                    name="jobs-sort"
                    checked={sort === value}
                    onChange={() => setSort(value)}
                  />
                  <span className="jobs__opt-text">{text}</span>
                </label>
              </li>
            ))}
          </ul>
        </details>
      </aside>

      <section className="jobs__results" aria-label="Job openings">
        {activeCount > 0 && (
          <div className="jobs__chips" aria-label="Active filters">
            {FILTER_SECTIONS.flatMap(({ key }) =>
              [...filters[key]].map((value) => (
                <button
                  key={`${key}-${value}`}
                  type="button"
                  className="jobs__chip"
                  aria-label={`Remove filter ${value}`}
                  onClick={() => toggle(key, value)}
                >
                  {value} <span aria-hidden="true">✕</span>
                </button>
              )),
            )}
          </div>
        )}
        {shown.length === 0 && (
          <div className="job-result">
            <p className="mt-0">No jobs match your search.</p>
            <button type="button" className="btn btn--sm" onClick={clearAll}>
              Clear filters
            </button>
          </div>
        )}
        {shown.map((r) => {
          const quals = [experienceLine(r), ...(r.must_have_skills ?? []).slice(0, 4).map((s) => `Experience with ${s}`)]
            .filter((v): v is string => Boolean(v));
          return (
            <article key={r.id} className="job-result" aria-labelledby={`job-${r.id}`}>
              <div className="job-result__head">
                <h2 id={`job-${r.id}`} className="job-result__title">
                  <a
                    href={jobUrl(r.id)}
                    onClick={(e) => {
                      e.preventDefault();
                      onOpen(r.id);
                    }}
                  >
                    {r.title}
                    {r.department ? `, ${r.department}` : ""}
                  </a>
                </h2>
                <button
                  type="button"
                  className="btn btn--ghost btn--sm"
                  aria-label={`Copy link to ${r.title}`}
                  title="Copy link"
                  onClick={() => share(r)}
                >
                  <Link2 size={16} aria-hidden="true" />
                </button>
              </div>
              <ul className="job-result__meta">
                <li>
                  <Building2 size={15} aria-hidden="true" /> {COMPANY}
                </li>
                {r.location && (
                  <li>
                    <MapPin size={15} aria-hidden="true" /> {r.location}
                  </li>
                )}
                {r.work_mode && (
                  <li>
                    <Briefcase size={15} aria-hidden="true" /> {pretty(r.work_mode)}
                    {r.employment_type ? ` · ${pretty(r.employment_type)}` : ""}
                  </li>
                )}
                {levelOf(r) !== "Not specified" && (
                  <li>
                    <BarChart3 size={15} aria-hidden="true" /> {levelOf(r)}
                  </li>
                )}
              </ul>
              {quals.length > 0 && (
                <div className="job-result__quals">
                  <h3>Minimum qualifications</h3>
                  <ul>
                    {quals.map((q) => (
                      <li key={q}>{q}</li>
                    ))}
                  </ul>
                </div>
              )}
              <button type="button" className="btn btn--sm job-result__more" onClick={() => onOpen(r.id)}>
                Learn more
              </button>
            </article>
          );
        })}
      </section>
    </div>
  );
}
