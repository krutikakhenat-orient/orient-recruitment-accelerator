import { Search } from "lucide-react";
import { useMemo, useState, type ReactNode } from "react";

import { useAuth } from "../app/auth-context";
import { DirectoryCard, Empty, PageHeader } from "../components/ui";
import { SETTINGS_DIRECTORY } from "../lib/settingsDirectory";

/* Settings directory: a searchable set of cards (icon, title, one-line description) grouped by
   purpose, like a control panel. Only destinations the signed-in user is permitted to open are
   listed. This is navigation only; each target page still enforces its own permissions. */
export function SettingsPage(): ReactNode {
  const { hasPermission } = useAuth();
  const [query, setQuery] = useState("");

  const groups = useMemo(() => {
    const q = query.trim().toLowerCase();
    const allowed = SETTINGS_DIRECTORY.filter(
      (e) => !e.anyPermission || e.anyPermission.some(hasPermission),
    ).filter(
      (e) => !q || e.title.toLowerCase().includes(q) || e.description.toLowerCase().includes(q),
    );
    const byGroup = new Map<string, typeof allowed>();
    for (const entry of allowed) {
      byGroup.set(entry.group, [...(byGroup.get(entry.group) ?? []), entry]);
    }
    return [...byGroup.entries()];
  }, [query, hasPermission]);

  return (
    <>
      <PageHeader
        title="Settings"
        description="Manage people, privacy and how hiring is set up. Pick a section, or search for what you need."
      />

      <label className="filter-search settings-search">
        <Search size={15} aria-hidden="true" />
        <input
          type="search"
          value={query}
          onChange={(e) => setQuery(e.target.value)}
          placeholder="Search settings, like retention or users"
          aria-label="Search settings"
        />
      </label>

      {groups.length === 0 && <Empty>No settings match your search.</Empty>}

      {groups.map(([group, entries]) => (
        <section key={group} aria-label={group}>
          <h2 className="dir-group">{group}</h2>
          <div className="dir-grid">
            {entries.map((e) => (
              <DirectoryCard key={e.to} to={e.to} icon={e.icon} title={e.title} description={e.description} />
            ))}
          </div>
        </section>
      ))}
    </>
  );
}
