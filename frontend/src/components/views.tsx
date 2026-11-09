import { LayoutGrid, List, Search, Table2 } from "lucide-react";
import { useCallback, useState, type ReactNode } from "react";

/* Shared "multiple views" building blocks: a Grid / List / Table switcher that remembers the
   user's choice per page, a filter bar (search + selects + "Mine"), and the card/row shells the
   grid and list layouts render. The layout choice is a non-sensitive UI preference only. */

export type ViewMode = "grid" | "list" | "table";

const META: Record<ViewMode, { label: string; icon: ReactNode }> = {
  grid: { label: "Grid", icon: <LayoutGrid size={15} aria-hidden="true" /> },
  list: { label: "List", icon: <List size={15} aria-hidden="true" /> },
  table: { label: "Table", icon: <Table2 size={15} aria-hidden="true" /> },
};

function isViewMode(value: string | null): value is ViewMode {
  return value === "grid" || value === "list" || value === "table";
}

/** Current layout for a page, persisted under `orient.view.<key>`. */
export function useViewMode(key: string, initial: ViewMode = "table"): [ViewMode, (m: ViewMode) => void] {
  const storageKey = `orient.view.${key}`;
  const [mode, setMode] = useState<ViewMode>(() => {
    try {
      const saved = localStorage.getItem(storageKey);
      if (isViewMode(saved)) return saved;
    } catch {
      /* storage unavailable: use the default */
    }
    return initial;
  });
  const update = useCallback(
    (next: ViewMode) => {
      setMode(next);
      try {
        localStorage.setItem(storageKey, next);
      } catch {
        /* ignore */
      }
    },
    [storageKey],
  );
  return [mode, update];
}

export function ViewSwitcher({
  value,
  onChange,
  modes = ["grid", "list", "table"],
}: {
  value: ViewMode;
  onChange: (m: ViewMode) => void;
  modes?: ViewMode[];
}): ReactNode {
  return (
    <div className="seg" role="radiogroup" aria-label="Layout">
      {modes.map((m) => (
        <button
          key={m}
          type="button"
          role="radio"
          aria-checked={value === m}
          className="seg__btn"
          onClick={() => onChange(m)}
        >
          {META[m].icon}
          <span>{META[m].label}</span>
        </button>
      ))}
    </div>
  );
}

export function FilterBar({
  search,
  onSearch,
  placeholder = "Search",
  children,
  trailing,
}: {
  search: string;
  onSearch: (v: string) => void;
  placeholder?: string;
  children?: ReactNode;
  trailing?: ReactNode;
}): ReactNode {
  return (
    <div className="filter-bar" role="search">
      <label className="filter-search">
        <Search size={15} aria-hidden="true" />
        <input
          type="search"
          value={search}
          onChange={(e) => onSearch(e.target.value)}
          placeholder={placeholder}
          aria-label={placeholder}
        />
      </label>
      {children}
      <span className="filter-bar__spacer" />
      {trailing}
    </div>
  );
}

export function FilterSelect({
  label,
  value,
  onChange,
  options,
  allLabel,
}: {
  label: string;
  value: string;
  onChange: (v: string) => void;
  options: { value: string; label: string }[];
  allLabel: string;
}): ReactNode {
  return (
    <select className="filter-select" aria-label={label} value={value} onChange={(e) => onChange(e.target.value)}>
      <option value="">{allLabel}</option>
      {options.map((o) => (
        <option key={o.value} value={o.value}>
          {o.label}
        </option>
      ))}
    </select>
  );
}

/** "Mine" quick filter: shows only records the signed-in user is assigned to. */
export function MineToggle({
  checked,
  onChange,
  label = "Mine",
}: {
  checked: boolean;
  onChange: (v: boolean) => void;
  label?: string;
}): ReactNode {
  return (
    <button
      type="button"
      className="chip-toggle"
      aria-pressed={checked}
      onClick={() => onChange(!checked)}
    >
      {label}
    </button>
  );
}

export function ItemGrid({ children }: { children: ReactNode }): ReactNode {
  return <div className="bento">{children}</div>;
}

export function ItemList({ children }: { children: ReactNode }): ReactNode {
  return <div className="item-list">{children}</div>;
}

interface ItemProps {
  title: ReactNode;
  subtitle?: ReactNode;
  badges?: ReactNode;
  meta?: ReactNode;
  actions?: ReactNode;
}

/** Card used by the Grid layout. */
export function ItemCard({ title, subtitle, badges, meta, actions }: ItemProps): ReactNode {
  return (
    <article className="item-card">
      <div className="item-card__title">{title}</div>
      {subtitle && <div className="item-card__sub">{subtitle}</div>}
      {badges && <div className="item-card__badges">{badges}</div>}
      {meta && <div className="item-card__meta">{meta}</div>}
      {actions && <div className="item-card__actions">{actions}</div>}
    </article>
  );
}

/** Row used by the List layout. */
export function ItemRow({ title, subtitle, badges, meta, actions }: ItemProps): ReactNode {
  return (
    <div className="item-row">
      <div className="item-row__main">
        <div className="item-card__title">{title}</div>
        {subtitle && <div className="item-card__sub">{subtitle}</div>}
      </div>
      {meta && <div className="item-row__meta">{meta}</div>}
      {badges && <div className="item-row__badges">{badges}</div>}
      {actions && <div className="item-card__actions">{actions}</div>}
    </div>
  );
}
