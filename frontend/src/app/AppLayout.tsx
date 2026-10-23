import { useState, type ReactNode } from "react";
import { NavLink, useLocation } from "react-router-dom";

import { Logo } from "../components/Logo";
import { useAuth } from "./auth-context";

interface NavEntry {
  to: string;
  label: string;
  icon: string;
  anyPermission?: string[]; // visible if the actor holds any of these (empty = always)
}

interface NavGroup {
  heading: string;
  items: NavEntry[];
}

const NAV: NavGroup[] = [
  {
    heading: "Overview",
    items: [{ to: "/", label: "Dashboard", icon: "▣" }],
  },
  {
    heading: "Hiring",
    items: [
      { to: "/approvals", label: "Approvals", icon: "✅", anyPermission: ["jd.approve", "rule.approve"] },
      { to: "/assessments", label: "My Interviews", icon: "📝", anyPermission: ["assessment.submit"] },
      { to: "/decisions", label: "Hiring Decisions", icon: "⚖", anyPermission: ["hiring_decision.recommend", "hiring_decision.approve"] },
      { to: "/outcomes", label: "Hiring Outcomes", icon: "🏁", anyPermission: ["candidate.view"] },
      { to: "/projects", label: "Projects", icon: "🗂", anyPermission: ["project.create", "campaign.create"] },
      { to: "/campaigns", label: "Campaigns", icon: "📣", anyPermission: ["campaign.create", "campaign.edit", "candidate.view"] },
      { to: "/reviews", label: "Review Queue", icon: "⚑", anyPermission: ["application.review"] },
    ],
  },
  {
    heading: "Talent",
    items: [
      { to: "/talent-pool", label: "Talent Pool", icon: "👥", anyPermission: ["talent_pool.search"] },
    ],
  },
  {
    heading: "Governance",
    items: [
      { to: "/management", label: "Management", icon: "📊", anyPermission: ["campaign.approve", "audit.view"] },
      { to: "/privacy", label: "Privacy & Retention", icon: "🛡", anyPermission: ["privacy_request.manage", "system.configure"] },
      { to: "/admin", label: "Administration", icon: "⚙", anyPermission: ["user.manage", "system.configure"] },
    ],
  },
];

const TITLES: Record<string, string> = {
  "/": "Dashboard",
  "/approvals": "Approvals",
  "/assessments": "My Assigned Interviews",
  "/decisions": "Hiring Decisions",
  "/outcomes": "Hiring Outcomes",
  "/projects": "Projects",
  "/campaigns": "Campaigns",
  "/reviews": "Human Review Queue",
  "/talent-pool": "Talent Pool",
  "/management": "Management Dashboard",
  "/privacy": "Privacy & Retention",
  "/admin": "Administration",
};

export function AppLayout({ children }: { children: ReactNode }): ReactNode {
  const { actor, signOut, hasPermission } = useAuth();
  const [open, setOpen] = useState(false);
  const location = useLocation();

  const can = (entry: NavEntry): boolean =>
    !entry.anyPermission || entry.anyPermission.length === 0 || entry.anyPermission.some(hasPermission);

  const title =
    TITLES[location.pathname] ??
    (location.pathname.startsWith("/campaigns/") ? "Campaign" : "Orient Recruitment Accelerator");

  return (
    <div className="app-shell">
      <a href="#main" className="skip-link">
        Skip to main content
      </a>
      <aside className={`sidebar ${open ? "sidebar--open" : ""}`} aria-label="Primary navigation">
        <div className="sidebar__brand">
          <Logo size={34} title="Orient Recruitment Accelerator" />
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
                {visible.map((entry) => (
                  <NavLink
                    key={entry.to}
                    to={entry.to}
                    end={entry.to === "/"}
                    className={({ isActive }) => `nav-item ${isActive ? "nav-item--active" : ""}`}
                    onClick={() => setOpen(false)}
                  >
                    <span className="nav-item__icon" aria-hidden="true">
                      {entry.icon}
                    </span>
                    {entry.label}
                  </NavLink>
                ))}
              </div>
            );
          })}
        </nav>
        <div className="sidebar__spacer" />
        <div className="sidebar__user">
          <div style={{ fontWeight: 600, color: "#fff" }}>{actor?.email}</div>
          <div>{actor?.role_names.map((r) => r.replace(/_/g, " ")).join(", ") || "no roles"}</div>
        </div>
      </aside>

      <div className="main">
        <header className="topbar">
          <button
            className="btn btn--ghost btn--sm"
            onClick={() => setOpen((o) => !o)}
            aria-label="Toggle navigation"
            style={{ display: "none" }}
          >
            ☰
          </button>
          <div className="topbar__title">{title}</div>
          <div className="topbar__spacer" />
          <button className="btn btn--sm" onClick={signOut}>
            Sign out
          </button>
        </header>
        <main id="main" className="content">
          {children}
        </main>
      </div>
    </div>
  );
}
