import type { ReactNode } from "react";
import { Link, Navigate, Route, Routes, useLocation } from "react-router-dom";

import { Logo } from "../components/Logo";
import { OrientAssistant } from "../components/OrientAssistant";
import { StartupScreen } from "../components/StartupScreen";
import { AdminPage } from "../pages/AdminPage";
import { AiInterviewPage } from "../pages/AiInterviewPage";
import { ApprovalsPage } from "../pages/ApprovalsPage";
import { AuditPage } from "../pages/AuditPage";
import { ConfirmInterviewPage } from "../pages/ConfirmInterviewPage";
import { GuidePage } from "../pages/GuidePage";
import { IntegrationsPage } from "../pages/IntegrationsPage";
import { OnboardingPage } from "../pages/OnboardingPage";
import { PoliciesPage } from "../pages/PoliciesPage";
import { SlaPage } from "../pages/SlaPage";
import { WaitlistPage } from "../pages/WaitlistPage";
import { AssessmentsPage } from "../pages/AssessmentsPage";
import { CampaignDetailPage } from "../pages/CampaignDetailPage";
import { CampaignsPage } from "../pages/CampaignsPage";
import { CandidateSummaryPage } from "../pages/CandidateSummaryPage";
import { DashboardPage } from "../pages/DashboardPage";
import { DecisionsPage } from "../pages/DecisionsPage";
import { EmployeePage } from "../pages/EmployeePage";
import { LoginPage } from "../pages/LoginPage";
import { ManagementPage } from "../pages/ManagementPage";
import { OutcomesPage } from "../pages/OutcomesPage";
import { PrivacyPage } from "../pages/PrivacyPage";
import { ProjectsPage } from "../pages/ProjectsPage";
import { PublicApplyPage } from "../pages/PublicApplyPage";
import { ReportPreviewPage } from "../pages/ReportPreviewPage";
import { ResumeDownloadPage } from "../pages/ResumeDownloadPage";
import { ReviewQueuePage } from "../pages/ReviewQueuePage";
import { SettingsPage } from "../pages/SettingsPage";
import { TalentPoolPage } from "../pages/TalentPoolPage";
import { AppLayout } from "./AppLayout";
import { useAuth } from "./auth-context";

function RequireAuth({ children }: { children: ReactNode }): ReactNode {
  const { actor, bootstrapping } = useAuth();
  const location = useLocation();
  // Don't decide logged-in vs logged-out until an existing token's session has been
  // restored; otherwise a deep link (e.g. the Excel "Download Resume" URL) opened in a live
  // session would be bounced to login before auth finishes establishing.
  // Never a blank page: show the branded placeholder while the session is restored.
  if (bootstrapping) return <StartupScreen phase="loading" />;
  if (!actor) return <Navigate to="/login" replace state={{ from: location.pathname }} />;
  return children;
}

/* Minimal shell for the employee induction experience: a lightweight header (product name +
   Sign out) and nothing from the staff portal — no AppLayout sidebar, no staff routes, no
   OrientAssistant. An employee only ever sees the EmployeePage. */
function EmployeeShell(): ReactNode {
  const { signOut } = useAuth();
  return (
    <div className="main">
      <a href="#main" className="skip-link">
        Skip to main content
      </a>
      <header className="topbar">
        <div className="btn-row" style={{ alignItems: "center", gap: 10 }}>
          <Logo size={30} title="Orient Recruitment Accelerator" />
          <div className="topbar__title">Orient Recruitment Accelerator</div>
        </div>
        <div className="topbar__spacer" />
        <Link className="btn btn--sm btn--ghost" to="/guide">
          User guide
        </Link>
        <button className="btn btn--sm" onClick={signOut}>
          Sign out
        </button>
      </header>
      <main id="main" className="content">
        <Routes>
          <Route path="/" element={<EmployeePage />} />
          <Route path="*" element={<Navigate to="/" replace />} />
        </Routes>
      </main>
    </div>
  );
}

export function App(): ReactNode {
  const { actor } = useAuth();
  const isEmployee = actor?.role_names.includes("employee") ?? false;

  return (
    <Routes>
      {/* Public, unauthenticated routes */}
      <Route path="/login" element={<LoginPage />} />
      <Route path="/apply" element={<PublicApplyPage />} />
      <Route path="/apply/:campaignId" element={<PublicApplyPage />} />
      {/* Candidate AI voice interview. The single-use link token is the only credential. */}
      <Route path="/ai-interview/:token" element={<AiInterviewPage />} />
      {/* Candidate's personal interview-confirmation link (no login; the token is the secret). */}
      <Route path="/confirm/:token" element={<ConfirmInterviewPage />} />
      {/* The user guide is public so anyone can read how the product works. */}
      <Route path="/guide" element={<GuidePage />} />

      {/* Authenticated application */}
      <Route
        path="/*"
        element={
          <RequireAuth>
            {isEmployee ? (
              // Employees get ONLY the induction dashboard in a minimal shell.
              <EmployeeShell />
            ) : (
              // Staff keep their existing experience unchanged.
              <>
                <AppLayout>
                  <Routes>
                    <Route path="/" element={<DashboardPage />} />
                    <Route path="/approvals" element={<ApprovalsPage />} />
                    <Route path="/assessments" element={<AssessmentsPage />} />
                    <Route path="/decisions" element={<DecisionsPage />} />
                    <Route path="/outcomes" element={<OutcomesPage />} />
                    <Route path="/projects" element={<ProjectsPage />} />
                    <Route path="/campaigns" element={<CampaignsPage />} />
                    <Route path="/campaigns/:id" element={<CampaignDetailPage />} />
                    {/* In-app Excel report preview for a campaign (same data as the download). */}
                    <Route path="/campaigns/:id/report" element={<ReportPreviewPage />} />
                    {/* Candidate summary — target of the Excel "View summary" hyperlink. */}
                    <Route
                      path="/campaigns/:id/candidates/:applicationId"
                      element={<CandidateSummaryPage />}
                    />
                    {/* Landing route for the Excel export's "Download Resume" hyperlink: an
                    authenticated per-candidate resume download (no public file URL). */}
                    <Route path="/resume/:applicationId" element={<ResumeDownloadPage />} />
                    <Route path="/reviews" element={<ReviewQueuePage />} />
                    <Route path="/talent-pool" element={<TalentPoolPage />} />
                    <Route path="/management" element={<ManagementPage />} />
                    <Route path="/sla" element={<SlaPage />} />
                    <Route path="/offers" element={<OnboardingPage />} />
                    <Route path="/waitlist" element={<WaitlistPage />} />
                    <Route path="/policies" element={<PoliciesPage />} />
                    <Route path="/integrations" element={<IntegrationsPage />} />
                    <Route path="/audit" element={<AuditPage />} />
                    <Route path="/settings" element={<SettingsPage />} />
                    <Route path="/privacy" element={<PrivacyPage />} />
                    <Route path="/admin" element={<AdminPage />} />
                    <Route path="*" element={<Navigate to="/" replace />} />
                  </Routes>
                </AppLayout>
                {actor && <OrientAssistant />}
              </>
            )}
          </RequireAuth>
        }
      />
    </Routes>
  );
}
