import { X } from "lucide-react";
import type { ButtonHTMLAttributes, ReactNode } from "react";
import { Link } from "react-router-dom";

/* Small, dependency-free UI primitives built on the design-system CSS. */

type Variant = "default" | "primary" | "accent" | "danger" | "ghost";

export function Button({
  variant = "default",
  small,
  children,
  className,
  ...rest
}: ButtonHTMLAttributes<HTMLButtonElement> & {
  variant?: Variant;
  small?: boolean;
}): ReactNode {
  const classes = [
    "btn",
    variant !== "default" ? `btn--${variant}` : "",
    small ? "btn--sm" : "",
    className ?? "",
  ]
    .filter(Boolean)
    .join(" ");
  return (
    <button className={classes} {...rest}>
      {children}
    </button>
  );
}

export function Card({
  title,
  description,
  actions,
  children,
}: {
  title?: ReactNode;
  /** One plain-language line under the title: what this section is for. */
  description?: ReactNode;
  actions?: ReactNode;
  children: ReactNode;
}): ReactNode {
  return (
    <section className="card">
      {(title || actions) && (
        <div className="card__head">
          <div>
            {title ? <h2 style={{ margin: 0 }}>{title}</h2> : <span />}
            {description && <p className="card__desc">{description}</p>}
          </div>
          {actions}
        </div>
      )}
      {children}
    </section>
  );
}

/* A small, muted explanation line (what a section or a button is for). */
export function Hint({ children }: { children: ReactNode }): ReactNode {
  return <p className="hint-line">{children}</p>;
}

/* A button with its own one-line explanation underneath, so no action is a mystery. The
   explanation is also exposed as the button's accessible description. */
export function Action({
  label,
  hint,
  onClick,
  variant = "default",
  disabled,
  busy,
  small,
}: {
  label: ReactNode;
  hint: string;
  onClick: () => void;
  variant?: Variant;
  disabled?: boolean;
  busy?: boolean;
  small?: boolean;
}): ReactNode {
  const hintId = `hint-${hint.replace(/[^a-z0-9]+/gi, "-").toLowerCase().slice(0, 40)}`;
  return (
    <div className="action">
      <Button
        variant={variant}
        {...(small !== undefined ? { small } : {})}
        disabled={disabled || busy}
        onClick={onClick}
        aria-describedby={hintId}
      >
        {busy ? "Working…" : label}
      </Button>
      <span id={hintId} className="action__hint">
        {hint}
      </span>
    </div>
  );
}

export function Stat({
  label,
  value,
  hint,
}: {
  label: string;
  value: ReactNode;
  hint?: string;
}): ReactNode {
  return (
    <div className="stat">
      <div className="stat__label">{label}</div>
      <div className="stat__value">{value}</div>
      {hint && <div className="stat__hint">{hint}</div>}
    </div>
  );
}

type Tone = "ok" | "warn" | "danger" | "info" | "neutral";

export function Badge({ tone = "neutral", children }: { tone?: Tone; children: ReactNode }): ReactNode {
  return <span className={`badge badge--${tone}`}>{children}</span>;
}

export function Spinner(): ReactNode {
  return <span className="spinner" aria-hidden="true" />;
}

export function Loading({ label = "Loading…" }: { label?: string }): ReactNode {
  return (
    <div className="loading-row" role="status">
      <Spinner /> {label}
    </div>
  );
}

export function Empty({ children }: { children: ReactNode }): ReactNode {
  return <div className="empty">{children}</div>;
}

export function ErrorNote({ children }: { children: ReactNode }): ReactNode {
  return (
    <div className="error-summary" role="alert">
      {children}
    </div>
  );
}

export function Field({
  label,
  htmlFor,
  error,
  hint,
  children,
}: {
  label: string;
  htmlFor?: string | undefined;
  error?: string | undefined;
  hint?: string | undefined;
  children: ReactNode;
}): ReactNode {
  return (
    <div className="field">
      <label htmlFor={htmlFor}>{label}</label>
      {children}
      {hint && <span className="hint">{hint}</span>}
      {error && (
        <span className="field-error" role="alert">
          {error}
        </span>
      )}
    </div>
  );
}

export function Modal({
  title,
  onClose,
  children,
  footer,
}: {
  title: string;
  onClose: () => void;
  children: ReactNode;
  footer?: ReactNode;
}): ReactNode {
  return (
    <div className="modal-overlay" onClick={onClose} role="presentation">
      <div
        className="modal"
        role="dialog"
        aria-modal="true"
        aria-label={title}
        onClick={(e) => e.stopPropagation()}
      >
        <div className="modal__head">
          <h2 style={{ margin: 0 }}>{title}</h2>
          <Button variant="ghost" small onClick={onClose} aria-label="Close">
            <X size={14} aria-hidden="true" className="inline-icon" />
          </Button>
        </div>
        <div className="modal__body">{children}</div>
        {footer && <div className="modal__foot">{footer}</div>}
      </div>
    </div>
  );
}

/* Accessible right-side slide-over panel. Mirrors Modal's dialog semantics (role=dialog,
   aria-modal) but anchors to the right edge for inspecting a record alongside the page. */
export function Drawer({
  title,
  subtitle,
  onClose,
  children,
  footer,
}: {
  title: ReactNode;
  subtitle?: ReactNode;
  onClose: () => void;
  children: ReactNode;
  footer?: ReactNode;
}): ReactNode {
  return (
    <div className="drawer-overlay" onClick={onClose} role="presentation">
      {/* A div, not <aside>: ARIA does not allow role="dialog" on <aside> (axe aria-allowed-role). */}
      <div
        className="drawer"
        role="dialog"
        aria-modal="true"
        aria-label={typeof title === "string" ? title : "Details"}
        onClick={(e) => e.stopPropagation()}
      >
        <div className="drawer__head">
          <div>
            <h2 style={{ margin: 0 }}>{title}</h2>
            {subtitle && <div className="subtle" style={{ marginTop: 2 }}>{subtitle}</div>}
          </div>
          <Button variant="ghost" small onClick={onClose} aria-label="Close panel">
            <X size={14} aria-hidden="true" className="inline-icon" />
          </Button>
        </div>
        <div className="drawer__body">{children}</div>
        {footer && <div className="drawer__foot">{footer}</div>}
      </div>
    </div>
  );
}

/* A labelled progress/match bar. Pairs a colour tone with a visible numeric label so
   status is never communicated by colour alone (accessibility.md). */
export function MatchBar({
  label,
  value,
  tone = "info",
}: {
  label: string;
  value: number;
  tone?: Tone;
}): ReactNode {
  const pct = Math.max(0, Math.min(100, Math.round(value)));
  return (
    <div className="matchbar">
      <div className="matchbar__top">
        <span>{label}</span>
        <span className="matchbar__pct">{pct}%</span>
      </div>
      <div
        className="matchbar__track"
        role="progressbar"
        aria-valuenow={pct}
        aria-valuemin={0}
        aria-valuemax={100}
        aria-label={`${label}: ${pct} percent`}
      >
        <div className={`matchbar__fill matchbar__fill--${tone}`} style={{ width: `${pct}%` }} />
      </div>
    </div>
  );
}

/* Map a backend status/recommendation string to a badge tone. */
export function toneFor(status: string): Tone {
  const s = status.toLowerCase();
  // Specific workflow statuses first (message, SLA, offer, joining, document, integration).
  if (/^(on_track|accepted|joined|ready_to_join|live|sent|done)$/.test(s)) return "ok";
  if (/^(overdue|declined|failed|withdrawn)$/.test(s)) return "danger";
  if (
    /^(at_risk|unconfigured|not_configured|drafted|documents_pending|correction_requested|missing|mismatch|needs_details|blocked|reschedule_requested)$/.test(
      s,
    )
  )
    return "warn";
  if (/^(simulated|issued|documents_in_review|submitted|current|answered)$/.test(s)) return "info";
  if (/^(paused|planned|skipped|upcoming|requested|waived|none)$/.test(s)) return "neutral";
  if (/(approved|clean|selected|eligible|pass|confirmed|ready|completed|active|recommended_for)/.test(s))
    return "ok";
  if (/(reject|infected|not_confirmed|fail|cancelled|withdrawn|expired|denied)/.test(s))
    return "danger";
  if (/(review|pending|draft|borderline|waitlist|hold|low_|conflict|manual|additional)/.test(s))
    return "warn";
  if (/(published|open|screening|interview|scheduled|submitted|processing)/.test(s)) return "info";
  return "neutral";
}

export function prettify(value: string): string {
  return value
    .replace(/_/g, " ")
    .replace(/\b\w/g, (c) => c.toUpperCase());
}

/* ---------- Page-level building blocks (shared structure for every page) ---------- */

/* Standard page header: title, one-line purpose, optional actions. Same on every page. */
export function PageHeader({
  title,
  description,
  actions,
}: {
  title: ReactNode;
  description?: ReactNode;
  actions?: ReactNode;
}): ReactNode {
  return (
    <div className="page-head">
      <div>
        <h1>{title}</h1>
        {description && <p>{description}</p>}
      </div>
      {actions && <div className="page-head__actions">{actions}</div>}
    </div>
  );
}

export interface TabItem {
  id: string;
  label: ReactNode;
}

/* Accessible tab strip (module sub-navigation). Arrow keys move between tabs. */
export function Tabs({
  tabs,
  value,
  onChange,
  label = "Sections",
}: {
  tabs: TabItem[];
  value: string;
  onChange: (id: string) => void;
  label?: string;
}): ReactNode {
  const move = (index: number, delta: number): void => {
    const next = tabs[(index + delta + tabs.length) % tabs.length];
    if (next) onChange(next.id);
  };
  return (
    <div className="tabs" role="tablist" aria-label={label}>
      {tabs.map((t, i) => (
        <button
          key={t.id}
          role="tab"
          type="button"
          className="tab"
          aria-selected={t.id === value}
          tabIndex={t.id === value ? 0 : -1}
          onClick={() => onChange(t.id)}
          onKeyDown={(e) => {
            if (e.key === "ArrowRight") move(i, 1);
            if (e.key === "ArrowLeft") move(i, -1);
          }}
        >
          {t.label}
        </button>
      ))}
    </div>
  );
}

/* Slim informational bar. */
export function Banner({ icon, children }: { icon?: ReactNode; children: ReactNode }): ReactNode {
  return (
    <div className="banner" role="note">
      {icon}
      <div>{children}</div>
    </div>
  );
}

/* Directory-style link card with icon, title and one-line description. */
export function DirectoryCard({
  to,
  icon,
  title,
  description,
}: {
  to: string;
  icon: ReactNode;
  title: string;
  description: string;
}): ReactNode {
  return (
    <Link className="dir-card" to={to}>
      <span className="todo__icon" aria-hidden="true">
        {icon}
      </span>
      <span>
        <div className="dir-card__title">{title}</div>
        <div className="dir-card__desc">{description}</div>
      </span>
    </Link>
  );
}



/* A status shown as colour AND words (never colour alone). */
export function StatusBadge({ status, label }: { status: string; label?: string }): ReactNode {
  return <Badge tone={toneFor(status)}>{label ?? prettify(status)}</Badge>;
}
