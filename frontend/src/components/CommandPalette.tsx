import { useEffect, useMemo, useRef, useState, type ReactNode } from "react";

/* Global command palette (Ctrl/Cmd+K): jump to a page or run a quick action.
   Items are supplied by the app shell already filtered by the actor's permissions, so the
   palette can never reveal a destination the user cannot open. */

export interface CommandItem {
  id: string;
  label: string;
  group: string;
  icon?: ReactNode;
  run: () => void;
}

export function CommandPalette({
  items,
  onClose,
}: {
  items: CommandItem[];
  onClose: () => void;
}): ReactNode {
  const [query, setQuery] = useState("");
  const [active, setActive] = useState(0);
  const inputRef = useRef<HTMLInputElement>(null);

  useEffect(() => {
    inputRef.current?.focus();
  }, []);

  const results = useMemo(() => {
    const q = query.trim().toLowerCase();
    return q ? items.filter((i) => i.label.toLowerCase().includes(q)) : items;
  }, [items, query]);

  const choose = (item: CommandItem | undefined): void => {
    if (!item) return;
    onClose();
    item.run();
  };

  const onKeyDown = (e: React.KeyboardEvent): void => {
    if (e.key === "Escape") onClose();
    else if (e.key === "ArrowDown") {
      e.preventDefault();
      setActive((a) => Math.min(a + 1, results.length - 1));
    } else if (e.key === "ArrowUp") {
      e.preventDefault();
      setActive((a) => Math.max(a - 1, 0));
    } else if (e.key === "Enter") {
      e.preventDefault();
      choose(results[active]);
    }
  };

  let lastGroup = "";
  return (
    <div className="cmd-overlay" role="presentation" onClick={onClose}>
      <div
        className="cmd"
        role="dialog"
        aria-modal="true"
        aria-label="Command palette"
        onClick={(e) => e.stopPropagation()}
        onKeyDown={onKeyDown}
      >
        <input
          ref={inputRef}
          className="cmd__input"
          placeholder="Search pages or ask…"
          aria-label="Search pages and actions"
          value={query}
          onChange={(e) => {
            setQuery(e.target.value);
            setActive(0);
          }}
        />
        {results.length === 0 ? (
          <div className="cmd__empty">No matches.</div>
        ) : (
          <ul className="cmd__list" role="listbox" aria-label="Results">
            {results.map((item, i) => {
              const header = item.group !== lastGroup ? item.group : null;
              lastGroup = item.group;
              return (
                <li key={item.id} role="presentation">
                  {header && <div className="cmd__group">{header}</div>}
                  <button
                    type="button"
                    role="option"
                    aria-selected={i === active}
                    className="cmd__item"
                    onMouseEnter={() => setActive(i)}
                    onClick={() => choose(item)}
                  >
                    {item.icon}
                    {item.label}
                  </button>
                </li>
              );
            })}
          </ul>
        )}
      </div>
    </div>
  );
}
