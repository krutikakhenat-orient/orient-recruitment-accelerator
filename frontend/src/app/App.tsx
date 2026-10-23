import type { ReactNode } from "react";
import { Navigate, Route, Routes, useLocation } from "react-router-dom";

import { OrientAssistant } from "../components/OrientAssistant";
import { AdminPage } from "../pages/AdminPage";
import { ApprovalsPage } from "../pages/ApprovalsPage";
import { AssessmentsPage } from "../pages/AssessmentsPage";
import { CampaignDetailPage } from "../pages/CampaignDetailPage";
import { CampaignsPage } from "../pages/CampaignsPage";
import { DashboardPage } from "../pages/DashboardPage";
import { DecisionsPage } from "../pages/DecisionsPage";
import { LoginPage } from "../pages/LoginPage";
import { ManagementPage } from "../pages/ManagementPage";
import { OutcomesPage } from "../pages/OutcomesPage";
import { PrivacyPage } from "../pages/PrivacyPage";
import { ProjectsPage } from "../pages/ProjectsPage";
import { PublicApplyPage } from "../pages/PublicApplyPage";
import { ReviewQueuePage } from "../pages/ReviewQueuePage";
import { TalentPoolPage } from "../pages/TalentPoolPage";
import { AppLayout } from "./AppLayout";
import { useAuth } from "./auth-context";

function RequireAuth({ children }: { children: ReactNode }): ReactNode {
  const { actor } = useAuth();
  const location = useLocation();
  if (!actor) return <Navigate to="/login" replace state={{ from: location.pathname }} />;
  return children;
}

export function App(): ReactNode {
  const { actor } = useAuth();

  return (
    <Routes>
      {/* Public, unauthenticated routes */}
      <Route path="/login" element={<LoginPage />} />
      <Route path="/apply" element={<PublicApplyPage />} />
      <Route path="/apply/:campaignId" element={<PublicApplyPage />} />

      {/* Authenticated application */}
      <Route
        path="/*"
        element={
          <RequireAuth>
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
                <Route path="/reviews" element={<ReviewQueuePage />} />
                <Route path="/talent-pool" element={<TalentPoolPage />} />
                <Route path="/management" element={<ManagementPage />} />
                <Route path="/privacy" element={<PrivacyPage />} />
                <Route path="/admin" element={<AdminPage />} />
                <Route path="*" element={<Navigate to="/" replace />} />
              </Routes>
            </AppLayout>
            {actor && <OrientAssistant />}
          </RequireAuth>
        }
      />
    </Routes>
  );
}
