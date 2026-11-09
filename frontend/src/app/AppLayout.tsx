import {
  BarChart3,
  BookOpen,
  CheckCircle2,
  ClipboardList,
  FolderKanban,
  Flag,
  LayoutDashboard,
  ListChecks,
  Megaphone,
  Menu,
  Moon,
  Scale,
  ScrollText,
  Search,
  Settings,
  Sparkles,
  Sun,
  Timer,
  Trophy,
  UserCheck,
  Users,
} from "lucide-react";
import { useQuery } from "@tanstack/react-query";
import { useEffect, useMemo, useState, type ReactNode } from "react";
import { NavLink, useLocation, useNavigate } from "react-router-dom";

import { getHrDashboard, listPendingJdVersions, listPendingRuleSets } from "../api/resources";
import { CommandPalette, type CommandItem } from "../components/CommandPalette";
import { Logo } from "../components/Logo";
import { OPEN_ASSISTANT_EVENT } from "../lib/events";
import { SETTINGS_DIRECTORY, SETTINGS_PERMISSIONS } from "../lib/settingsDirectory";
import { applyTheme, getInitialTheme, type Theme } from "../lib/theme";
import { useAuth } from "./auth-context";

interface NavEntry {
  to: string;
  label: string;
  icon: ReactNode;
  anyPermission?: string[]; // visible if the actor holds any of these (empty = always)
  hint: string; // one plain-language line: what this page is for (shown as a tooltip)
  badge?: "reviews" | "approvals"; // live count of items waiting on the user
}

interface NavGroup {
  heading: string;
  items: NavEntry[];
}

const ICON = { size: 17, strokeWidth: 1.75, "aria-hidden": true } as const;

// Menu order follows how people work:
//  1. Home first (one fixed starting point).
//  2. "My tasks": things waiting on ME, with live counts, so the most frequent work is nearest.
//  3. "Hiring": the pipeline in the order it happens (set up -> decide -> offer & join).
//  4. "Candidates": people pools you search rather than work through.
//  5. "Reports & admin": rarely used, at the bottom.
// Each group stays short (at most 4 items) so it can be scanned at a glance.
const NAV: NavGroup[] = [
  {
    heading: "Home",
    items: [
      { to: "/", label: "Dashboard", icon: <LayoutDashboard {...ICON} />, hint: "What needs your attention today, and how hiring works" },
    ],
  },
  {
    heading: "My tasks",
    items: [
      { to: "/reviews", label: "Review inbox", icon: <Flag {...ICON} />, anyPermission: ["application.review"], hint: "Candidates waiting for a person to decide", badge: "reviews" },
      { to: "/approvals", label: "Approvals", icon: <CheckCircle2 {...ICON} />, anyPermission: ["jd.approve", "rule.approve"], hint: "Job descriptions and rules waiting for your sign-off", badge: "approvals" },
      { to: "/assessments", label: "My Interviews", icon: <ClipboardList {...ICON} />, anyPermission: ["assessment.submit"], hint: "Interviews assigned to you" },
      { to: "/sla", label: "Shortlisting clock", icon: <Timer {...ICON} />, anyPermission: ["candidate.view"], hint: "How long applications have waited for a decision" },
    ],
  },
  {
    heading: "Hiring",
    items: [
      { to: "/projects", label: "Projects", icon: <FolderKanban {...ICON} />, anyPermission: ["project.create", "campaign.create"], hint: "Step 1: a hiring need that holds one or more job openings" },
      { to: "/campaigns", label: "Campaigns", icon: <Megaphone {...ICON} />, anyPermission: ["campaign.create", "campaign.edit", "candidate.view"], hint: "Step 2: job openings, their candidates and interviews" },
      { to: "/decisions", label: "Hiring Decisions", icon: <Scale {...ICON} />, anyPermission: ["hiring_decision.recommend", "hiring_decision.approve"], hint: "Step 3: record the final decision after interviews" },
      { to: "/offers", label: "Offers & joining", icon: <UserCheck {...ICON} />, anyPermission: ["hiring_decision.recommend", "hiring_decision.approve"], hint: "Step 4: offers, joining documents and welcoming new joiners" },
    ],
  },
  {
    heading: "Candidates",
    items: [
      { to: "/outcomes", label: "Hiring Outcomes", icon: <Trophy {...ICON} />, anyPermission: ["candidate.view"], hint: "Every final decision with its reason" },
      { to: "/waitlist", label: "Waitlist", icon: <ListChecks {...ICON} />, anyPermission: ["waitlist.manage"], hint: "Candidates kept for later" },
      { to: "/talent-pool", label: "Talent Pool", icon: <Users {...ICON} />, anyPermission: ["talent_pool.search"], hint: "People who agreed to be considered for future jobs" },
    ],
  },
  {
    heading: "Reports & admin",
    items: [
      { to: "/management", label: "Management", icon: <BarChart3 {...ICON} />, anyPermission: ["campaign.approve", "audit.view"], hint: "Combined figures with no personal details" },
      { to: "/audit", label: "Audit log", icon: <ScrollText {...ICON} />, anyPermission: ["audit.view"], hint: "A permanent record of important actions" },
      { to: "/settings", label: "Settings", icon: <Settings {...ICON} />, anyPermission: SETTINGS_PERMISSIONS, hint: "People, privacy, policies, connections and message wording" },
    ],
  },
];

const COLLAPSE_KEY = "orient.sidebar.collapsed";
const MOBILE_QUERY = "(max-width: 900px)";

function isMobile(): boolean {
  return typeof window !== "undefined" && !!window.matchMedia?.(MOBILE_QUERY).matches;
}

const TITLES: Record<string, string> = {
  "/": "Dashboard",
  "/approvals": "Approvals",
  "/assessments": "My Assigned Interviews",
  "/decisions": "Hiring Decisions",
  "/outcomes": "Hiring Outcomes",
  "/projects": "Projects",
  "/campaigns": "Campaigns",
  "/reviews": "Review inbox",
  "/talent-pool": "Talent Pool",
  "/management": "Management Dashboard",
  "/privacy": "Privacy & retention",
  "/settings": "Settings",
  "/admin": "Users & roles",
  "/sla": "Shortlisting clock",
  "/waitlist": "Waitlist",
  "/offers": "Offers & joining",
  "/policies": "Policies & guides",
  "/integrations": "Connections & messages",
  "/audit": "Audit log",
};


function initials(email: string | undefined): string {
  const name = (email ?? "?").split("@")[0] ?? "?";
  const parts = name.split(/[._-]+/).filter(Boolean);
  return ((parts[0]?.[0] ?? "?") + (parts[1]?.[0] ?? "")).toUpperCase();
}

export function AppLayout({ children }: { children: ReactNode }): ReactNode {
  const { actor, signOut, hasPermission } = useAuth();
  // `open` = mobile drawer open; `collapsed` = desktop sidebar shrunk to an icon rail.
  const [open, setOpen] = useState(false);
  const [collapsed, setCollapsed] = useState(() => {
    try {
      return localStorage.getItem(COLLAPSE_KEY) === "1";
    } catch {
      return false;
    }
  });
  const [paletteOpen, setPaletteOpen] = useState(false);
  const [theme, setTheme] = useState<Theme>(getInitialTheme);
  const location = useLocation();
  const navigate = useNavigate();

  useEffect(() => applyTheme(theme), [theme]);

  // Close the mobile drawer whenever the route changes.
  useEffect(() => setOpen(false), [location.pathname]);

  // Escape closes the mobile drawer.
  useEffect(() => {
    if (!open) return;
    const onKey = (e: KeyboardEvent): void => {
      if (e.key === "Escape") setOpen(false);
    };
    window.addEventListener("keydown", onKey);
    return () => window.removeEventListener("keydown", onKey);
  }, [open]);

  // The hamburger opens a drawer on small screens and collapses / expands the sidebar on
  // large screens (remembered on this device).
  const toggleNav = (): void => {
    if (isMobile()) {
      setOpen((o) => !o);
      return;
    }
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
  const navExpanded = isMobile() ? open : !collapsed;

  // Live counts on "My tasks" so people see at a glance what is waiting for them. These share
  // cache keys with the dashboard, so no extra requests are made when both are on screen.
  const canSeeReviews = hasPermission("application.review") || hasPermission("campaign.approve");
  const dash = useQuery({ queryKey: ["hr-dashboard"], queryFn: getHrDashboard, enabled: canSeeReviews });
  const pendingJds = useQuery({
    queryKey: ["pending-jds"],
    queryFn: listPendingJdVersions,
    enabled: hasPermission("jd.approve"),
  });
  const pendingRules = useQuery({
    queryKey: ["pending-rulesets"],
    queryFn: listPendingRuleSets,
    enabled: hasPermission("rule.approve"),
  });
  const counts: Record<"reviews" | "approvals", number> = {
    reviews: dash.data?.open_review_items ?? 0,
    approvals: (pendingJds.data?.length ?? 0) + (pendingRules.data?.length ?? 0),
  };

  // Ctrl/Cmd+K opens the command palette from anywhere.
  useEffect(() => {
    const onKey = (e: KeyboardEvent): void => {
      if ((e.ctrlKey || e.metaKey) && e.key.toLowerCase() === "k") {
        e.preventDefault();
        setPaletteOpen((p) => !p);
      }
    };
    window.addEventListener("keydown", onKey);
    return () => window.removeEventListener("keydown", onKey);
  }, []);

  const can = (entry: NavEntry): boolean =>
    !entry.anyPermission || entry.anyPermission.length === 0 || entry.anyPermission.some(hasPermission);

  const openAssistant = (): void => {
    window.dispatchEvent(new Event(OPEN_ASSISTANT_EVENT));
  };

  const commands = useMemo<CommandItem[]>(() => {
    const pages: CommandItem[] = NAV.flatMap((group) =>
      group.items
        .filter(can)
        .map((entry) => ({
          id: entry.to,
          label: entry.label,
          group: "Go to",
          icon: entry.icon,
          run: () => navigate(entry.to),
        })),
    );
    // Settings destinations (users, retention, ...) stay reachable from search.
    const settingsPages: CommandItem[] = SETTINGS_DIRECTORY.filter(
      (e) => !e.anyPermission || e.anyPermission.some(hasPermission),
    )
      .filter((e) => !pages.some((p) => p.id === e.to))
      .map((e) => ({
        id: e.to,
        label: e.title,
        group: "Settings",
        icon: e.icon,
        run: () => navigate(e.to),
      }));
    return [
      ...pages,
      ...settingsPages,
      {
        id: "guide",
        label: "Open the user guide",
        group: "Actions",
        icon: <BookOpen {...ICON} />,
        run: () => navigate("/guide"),
      },
      {
        id: "ask-ai",
        label: "Ask Orient HR Assistance",
        group: "Actions",
        icon: <Sparkles {...ICON} />,
        run: () => window.dispatchEvent(new Event(OPEN_ASSISTANT_EVENT)),
      },
      {
        id: "theme",
        label: theme === "dark" ? "Switch to light theme" : "Switch to dark theme",
        group: "Actions",
        icon: theme === "dark" ? <Sun {...ICON} /> : <Moon {...ICON} />,
        run: () => setTheme((t) => (t === "dark" ? "light" : "dark")),
      },
    ];
    // `can` depends on hasPermission, which is stable per session.
    // eslint-disable-next-line react-hooks/exhaustive-deps
  }, [actor, theme, navigate]);

  const title =
    TITLES[location.pathname] ??
    (location.pathname.startsWith("/campaigns/") ? "Campaign" : "Orient Recruitment Accelerator");

  return (
    <div className={`app-shell ${collapsed ? "app-shell--collapsed" : ""}`}>
      <a href="#main" className="skip-link">
        Skip to main content
      </a>
      <div className={`nav-scrim ${open ? "nav-scrim--open" : ""}`} onClick={() => setOpen(false)} />
      <aside
        id="primary-nav"
        className={`sidebar ${open ? "sidebar--open" : ""}`}
        aria-label="Primary navigation"
      >
        <div className="sidebar__brand">
          <Logo size={32} title="Orient Recruitment Accelerator" />
          <span className="sidebar__brand-text">
            Orient
            <small>Recruitment Accelerator</small>
          </span>
        </div>
        <nav>
          {NAV.map((group) => {
            const visible = group.items.filter(can);
            if (visible.length === 0) return null;
            return (
              <div key={group.heading}>
                <div className="sidebar__section">{group.heading}</div>
                {visible.map((entry) => {
                  const count = entry.badge ? counts[entry.badge] : 0;
                  return (
                    <NavLink
                      key={entry.to}
                      to={entry.to}
                      end={entry.to === "/"}
                      className={({ isActive }) => `nav-item ${isActive ? "nav-item--active" : ""}`}
                      title={collapsed ? `${entry.label}: ${entry.hint}` : entry.hint}
                      aria-label={count > 0 ? `${entry.label}, ${count} waiting` : entry.label}
                    >
                      <span className="nav-item__icon">{entry.icon}</span>
                      <span className="nav-item__label">{entry.label}</span>
                      {count > 0 && (
                        <>
                          <span className="nav-item__count" aria-hidden="true">
                            {count}
                          </span>
                          {collapsed && <span className="nav-item__dot" aria-hidden="true" />}
                        </>
                      )}
                    </NavLink>
                  );
                })}
              </div>
            );
          })}
        </nav>
        <div className="sidebar__spacer" />
        <NavLink
          to="/guide"
          className="nav-item"
          title="How the product works, in plain language"
          aria-label="User guide"
        >
          <span className="nav-item__icon">
            <BookOpen {...ICON} />
          </span>
          <span className="nav-item__label">User guide</span>
        </NavLink>
        <div className="sidebar__user" title={actor?.email}>
          <span className="avatar" aria-hidden="true">
            {initials(actor?.email)}
          </span>
          <div className="sidebar__user-meta">
            <strong>{actor?.email}</strong>
            {actor?.role_names.map((r) => r.replace(/_/g, " ")).join(", ") || "no roles"}
          </div>
        </div>
      </aside>

      <div className="main">
        <header className="topbar">
          <button
            className="btn btn--ghost btn--sm topbar__menu"
            onClick={toggleNav}
            aria-label={navExpanded ? "Hide menu" : "Show menu"}
            aria-controls="primary-nav"
            aria-expanded={navExpanded}
            title={navExpanded ? "Hide menu" : "Show menu"}
          >
            <Menu size={18} aria-hidden="true" />
          </button>
          <div className="topbar__title">{title}</div>
          <div className="topbar__spacer" />
          <button className="cmd-trigger" onClick={() => setPaletteOpen(true)} aria-label="Search pages and actions">
            <Search size={15} aria-hidden="true" />
            <span className="cmd-trigger__label">Search or jump to…</span>
            <span className="kbd" aria-hidden="true">
              Ctrl K
            </span>
          </button>
          <button className="btn btn--sm" onClick={openAssistant}>
            <Sparkles size={14} aria-hidden="true" /> Ask AI
          </button>
          <button
            className="btn btn--ghost btn--sm"
            onClick={() => setTheme((t) => (t === "dark" ? "light" : "dark"))}
            aria-label={theme === "dark" ? "Switch to light theme" : "Switch to dark theme"}
          >
            {theme === "dark" ? <Sun size={16} aria-hidden="true" /> : <Moon size={16} aria-hidden="true" />}
          </button>
          <button className="btn btn--sm" onClick={signOut}>
            Sign out
          </button>
        </header>
        <main id="main" className="content">
          {children}
        </main>
      </div>
      {paletteOpen && <CommandPalette items={commands} onClose={() => setPaletteOpen(false)} />}
    </div>
  );
}



