import {
  ArrowRight,
  Bot,
  CalendarCheck,
  CheckCircle2,
  ChevronDown,
  ChevronUp,
  ClipboardCheck,
  ClipboardList,
  FileCheck2,
  FileSearch,
  FileText,
  FolderPlus,
  Gavel,
  Info,
  Mail,
  Megaphone,
  MessageSquareText,
  PauseCircle,
  PencilLine,
  PlayCircle,
  Rocket,
  Send,
  Share2,
  ShieldCheck,
  Sparkles,
  UserCheck,
  UserRound,
  UserRoundCog,
  Users,
  type LucideIcon,
} from "lucide-react";
import { useId, useState, type ReactNode } from "react";
import { Link } from "react-router-dom";

import {
  JOURNEY,
  OPENING_FLOW,
  OPENING_STATUSES,
  type FlowStep,
} from "../lib/guideContent";
import { Button, Tabs } from "./ui";

/* Flow diagrams: numbered step cards joined by arrows. Each step has an icon (what happens)
   and a role chip (who does it). Role is shown with colour AND an icon AND words, so it is
   never colour alone. Underneath it is an ordered list, so screen readers read a sequence. */

// ---------------------------------------------------------------- who does it

type Actor = "candidate" | "system" | "recruiter" | "approver" | "interviewer";

const ACTORS: Record<Actor, { label: string; icon: LucideIcon }> = {
  candidate: { label: "Candidate", icon: UserRound },
  system: { label: "System", icon: Bot },
  recruiter: { label: "Recruiter / HR", icon: Users },
  approver: { label: "Approver", icon: ShieldCheck },
  interviewer: { label: "Interviewer", icon: UserRoundCog },
};

function actorFor(who: string): Actor {
  const w = who.toLowerCase();
  if (w.startsWith("candidate")) return "candidate";
  if (w.includes("system")) return "system";
  if (w.includes("admin")) return "approver";
  if (w.includes("interviewer")) return "interviewer";
  return "recruiter";
}

// ------------------------------------------------------------ what happens

const STEP_ICONS: Record<string, LucideIcon> = {
  // Opening a job
  "Create a project": FolderPlus,
  "Create a campaign": Megaphone,
  "Upload the job description": FileText,
  "Set up the application form": PencilLine,
  "Approve the job description": ShieldCheck,
  "Open for applications": Rocket,
  "Share the apply link": Share2,
  // Candidate journey
  Applied: Send,
  "Resume checked": FileSearch,
  Screened: ClipboardCheck,
  "HR review": Users,
  "Short AI interview (optional)": Sparkles,
  "Interview invited": Mail,
  "Interview confirmed": CalendarCheck,
  "Interview held": MessageSquareText,
  Decision: Gavel,
  Offer: FileCheck2,
  "Joining documents": ClipboardList,
  Joining: UserCheck,
};

const STATUS_ICONS: Record<string, LucideIcon> = {
  "Setting up": PencilLine,
  "Open for applications": PlayCircle,
  "Reviewing candidates": Users,
  Interviewing: CalendarCheck,
  Completed: CheckCircle2,
};

function RoleChip({ who }: { who: string }): ReactNode {
  const actor = actorFor(who);
  const Icon = ACTORS[actor].icon;
  return (
    <span className={`role-chip role-chip--${actor}`} title={who}>
      <Icon size={12} aria-hidden="true" />
      {who}
    </span>
  );
}

export function RoleLegend({ steps }: { steps: FlowStep[] }): ReactNode {
  const used = Array.from(new Set(steps.map((s) => actorFor(s.who))));
  return (
    <div className="role-legend" aria-label="Who does each step">
      <span className="role-legend__label">Who does it:</span>
      {used.map((a) => {
        const Icon = ACTORS[a].icon;
        return (
          <span key={a} className={`role-chip role-chip--${a}`}>
            <Icon size={12} aria-hidden="true" />
            {ACTORS[a].label}
          </span>
        );
      })}
    </div>
  );
}

export function FlowDiagram({ steps, label }: { steps: FlowStep[]; label: string }): ReactNode {
  return (
    <ol className="flow" aria-label={label}>
      {steps.map((s, i) => {
        const Icon = STEP_ICONS[s.title] ?? Info;
        const actor = actorFor(s.who);
        return (
          <li key={s.title} className="flow__step">
            <div className={`flow__card flow__card--${actor}`}>
              <div className="flow__head">
                <span className={`flow__icon flow__icon--${actor}`} aria-hidden="true">
                  <Icon size={18} />
                </span>
                <span className="flow__num">Step {i + 1}</span>
              </div>
              <div className="flow__title">
                {s.to ? <Link to={s.to}>{s.title}</Link> : s.title}
              </div>
              <RoleChip who={s.who} />
              <div className="flow__text">{s.text}</div>
            </div>
            {i < steps.length - 1 && (
              <ArrowRight className="flow__arrow" size={18} aria-hidden="true" />
            )}
          </li>
        );
      })}
    </ol>
  );
}

export function StatusStrip(): ReactNode {
  return (
    <div className="status-flow" role="list" aria-label="Statuses of a job opening">
      {OPENING_STATUSES.map((s, i) => {
        const Icon = STATUS_ICONS[s.label] ?? Info;
        return (
          <div key={s.label} role="listitem" className="status-flow__item">
            <span className="status-flow__pill">
              <Icon size={13} aria-hidden="true" />
              {s.label}
            </span>
            <span className="status-flow__text">{s.text}</span>
            {i < OPENING_STATUSES.length - 1 && (
              <ArrowRight className="status-flow__arrow" size={14} aria-hidden="true" />
            )}
          </div>
        );
      })}
      <div role="listitem" className="status-flow__item status-flow__item--aside">
        <span className="status-flow__pill">
          <PauseCircle size={13} aria-hidden="true" />
          Paused
        </span>
        <span className="status-flow__text">Can happen while open; resume any time</span>
      </div>
    </div>
  );
}

/* The candidate journey as flow steps (same data as the user guide). */
export const CANDIDATE_FLOW: FlowStep[] = JOURNEY.map((j) => ({
  title: j.title,
  who: j.who,
  text: j.text,
}));

const COLLAPSE_KEY = "orient.howItWorks.collapsed";

function readCollapsed(): boolean {
  try {
    return localStorage.getItem(COLLAPSE_KEY) === "1";
  } catch {
    return false;
  }
}

/* "How hiring works" on the dashboard. The header (icon, title, one-line summary and the
   Show/Hide button) never disappears, so the steps can always be brought back. The choice is
   remembered on this device. */
export function HowItWorksCard(): ReactNode {
  const [tab, setTab] = useState("opening");
  const [collapsed, setCollapsed] = useState(readCollapsed);
  const bodyId = useId();

  const toggle = (): void => {
    setCollapsed((c) => {
      const next = !c;
      try {
        localStorage.setItem(COLLAPSE_KEY, next ? "1" : "0");
      } catch {
        /* storage unavailable: keep in memory only */
      }
      return next;
    });
  };

  return (
    <section className={`card howto ${collapsed ? "howto--collapsed" : ""}`} aria-labelledby={`${bodyId}-title`}>
      <div className="howto__head">
        <span className="howto__icon" aria-hidden="true">
          <Info size={20} />
        </span>
        <div className="howto__heading">
          <h2 id={`${bodyId}-title`} style={{ margin: 0 }}>
            How hiring works here
          </h2>
          <p className="card__desc">
            {collapsed
              ? "Steps are hidden. Show them any time to see how a job goes live and how a candidate moves through hiring."
              : "Two simple maps: how a job opening goes live, and how a candidate moves through hiring. Click a step title to go to that screen."}
          </p>
        </div>
        <div className="howto__actions">
          <Link className="btn btn--sm btn--ghost" to="/guide">
            Full guide
          </Link>
          <Button
            small
            variant={collapsed ? "primary" : "default"}
            onClick={toggle}
            aria-expanded={!collapsed}
            aria-controls={bodyId}
          >
            {collapsed ? (
              <>
                <ChevronDown size={15} aria-hidden="true" /> Show steps
              </>
            ) : (
              <>
                <ChevronUp size={15} aria-hidden="true" /> Hide steps
              </>
            )}
          </Button>
        </div>
      </div>

      <div id={bodyId} hidden={collapsed} className="howto__body">
        <Tabs
          label="How hiring works"
          value={tab}
          onChange={setTab}
          tabs={[
            { id: "opening", label: "1. Opening a job" },
            { id: "candidate", label: "2. Candidate journey" },
          ]}
        />
        {tab === "opening" ? (
          <>
            <p className="hint-line">
              {OPENING_FLOW.length} steps from a new hiring need to a live apply link.
            </p>
            <RoleLegend steps={OPENING_FLOW} />
            <FlowDiagram steps={OPENING_FLOW} label="How a job opening goes live" />
            <h3 className="flow-subhead">The status you will see on a job opening</h3>
            <StatusStrip />
          </>
        ) : (
          <>
            <p className="hint-line">
              {CANDIDATE_FLOW.length} steps from applying to the first day. Click{" "}
              <strong>Journey</strong> on any candidate to see exactly where they are.
            </p>
            <RoleLegend steps={CANDIDATE_FLOW} />
            <FlowDiagram steps={CANDIDATE_FLOW} label="Candidate journey" />
          </>
        )}
      </div>
    </section>
  );
}
