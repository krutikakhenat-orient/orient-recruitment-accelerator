import type { ReactNode } from "react";
import { Link, Navigate, NavLink, Route, Routes, useLocation } from "react-router-dom";

import { useAuth } from "../../app/auth-context";
import { HrChatLauncher } from "../../components/hr-chat/HrChatLauncher";
import { Logo } from "../../components/Logo";
import { EmployeePage } from "../EmployeePage";
import { EmployeeAskHr } from "./EmployeeAskHr";
import { EmployeeHome } from "./EmployeeHome";
import { EmployeePolicies } from "./EmployeePolicies";

const NAV = [
  { to: "/", label: "Home", end: true },
  { to: "/ask-hr", label: "Ask HR", end: false },
  { to: "/policies", label: "Policies", end: false },
  { to: "/induction", label: "Induction", end: false },
];

/* The employee portal: a calm, focused shell with four destinations. Nothing from the staff
   portal is reachable here (no sidebar, no staff routes, no workflow assistant). */
export function EmployeeShell(): ReactNode {
  const { signOut } = useAuth();
  const { pathname } = useLocation();
  return (
    <div className="emp">
      <a href="#main" className="skip-link">Skip to main content</a>
      <header className="emp-bar">
        <div className="emp-bar__inner">
          <Link to="/" className="emp-brand" aria-label="Orient, home">
            <Logo size={28} title="Orient" />
            <span>Orient</span>
          </Link>
          <nav className="emp-nav" aria-label="Employee">
            {NAV.map((n) => (
              <NavLink key={n.to} to={n.to} end={n.end}
                className={({ isActive }) => `emp-nav__link${isActive ? " is-active" : ""}`}>
                {n.label}
              </NavLink>
            ))}
          </nav>
          <div className="emp-bar__end">
            <Link className="emp-bar__link" to="/guide">Help</Link>
            <button className="btn btn--sm" onClick={signOut}>Sign out</button>
          </div>
        </div>
      </header>
      <main id="main" className="emp-main">
        <Routes>
          <Route path="/" element={<EmployeeHome />} />
          <Route path="/ask-hr" element={<EmployeeAskHr />} />
          <Route path="/policies" element={<EmployeePolicies />} />
          <Route path="/induction" element={<EmployeePage />} />
          <Route path="*" element={<Navigate to="/" replace />} />
        </Routes>
      </main>
      {/* Quick question from any page except the full Ask HR page itself. */}
      {pathname !== "/ask-hr" && <HrChatLauncher />}
    </div>
  );
}
