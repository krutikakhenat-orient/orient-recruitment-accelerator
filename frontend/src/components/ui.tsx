import type { ButtonHTMLAttributes, ReactNode } from "react";

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
  actions,
  children,
}: {
  title?: ReactNode;
  actions?: ReactNode;
  children: ReactNode;
}): ReactNode {
  return (
    <section className="card">
      {(title || actions) && (
        <div className="card__head">
          {title ? <h2 style={{ margin: 0 }}>{title}</h2> : <span />}
          {actions}
        </div>
      )}
      {children}
    </section>
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
            ✕
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
      <aside
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
            ✕
          </Button>
        </div>
        <div className="drawer__body">{children}</div>
        {footer && <div className="drawer__foot">{footer}</div>}
      </aside>
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
