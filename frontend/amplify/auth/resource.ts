import { defineAuth } from "@aws-amplify/backend";

// Cognito user pool for staff (HR, hiring managers, panel, management, audit, admin).
// Candidates do NOT sign in here: they use single-use links (see docs/architecture-v2.md).
// Groups mirror the application roles; the API still performs the authoritative
// role and object-level authorization checks.
export const auth = defineAuth({
  loginWith: {
    email: true,
  },
  // MFA is off (Gen 2 default is OFF; stated explicitly). Switch to mode "OPTIONAL" or "REQUIRED"
  // with totp: true to turn it on later.
  multifactor: {
    mode: "OFF",
  },
  groups: [
    "HRHead",
    "RecruitmentAdmin",
    "Recruiter",
    "HiringManager",
    "PanelMember",
    "ManagementViewer",
    "AuditViewer",
    "SystemAdmin",
  ],
});
