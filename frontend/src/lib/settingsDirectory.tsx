import {
  BarChart3,
  BookText,
  CheckCircle2,
  Clock3,
  FolderKanban,
  Inbox,
  Megaphone,
  Plug,
  Scale,
  ShieldCheck,
  Timer,
  UserPlus,
  UserRoundCog,
  Users,
} from "lucide-react";
import type { ReactNode } from "react";

/* Single source of truth for the Settings directory. The Settings page renders it as
   searchable cards and the command palette reuses it, so a destination is only ever listed
   to someone who holds one of its permissions. Server-side checks remain authoritative. */

export interface SettingsEntry {
  to: string;
  title: string;
  description: string;
  group: string;
  icon: ReactNode;
  anyPermission?: string[];
}

const ICON = { size: 18, strokeWidth: 1.75, "aria-hidden": true } as const;

export const SETTINGS_PERMISSIONS = [
  "user.manage",
  "system.configure",
  "privacy_request.manage",
  "campaign.approve",
];

export const SETTINGS_DIRECTORY: SettingsEntry[] = [
  {
    group: "People & access",
    to: "/admin?tab=users",
    title: "Users & roles",
    description: "See staff accounts, their roles and status",
    icon: <UserRoundCog {...ICON} />,
    anyPermission: ["user.manage", "system.configure"],
  },
  {
    group: "People & access",
    to: "/admin?tab=create",
    title: "Create a staff user",
    description: "Add an account with least-privilege roles",
    icon: <UserPlus {...ICON} />,
    anyPermission: ["user.manage", "system.configure"],
  },
  {
    group: "Privacy & data",
    to: "/privacy?tab=retention",
    title: "Retention policy",
    description: "Set how long each record category is kept",
    icon: <Clock3 {...ICON} />,
    anyPermission: ["privacy_request.manage", "system.configure"],
  },
  {
    group: "Privacy & data",
    to: "/privacy?tab=rights",
    title: "Candidate rights",
    description: "Access, correction, deletion and consent withdrawal",
    icon: <ShieldCheck {...ICON} />,
    anyPermission: ["privacy_request.manage", "system.configure"],
  },
  {
    group: "Privacy & data",
    to: "/privacy?tab=requests",
    title: "Privacy requests",
    description: "Record and close requests to see, correct or delete a person's data",
    icon: <Inbox {...ICON} />,
    anyPermission: ["privacy_request.manage"],
  },
  {
    group: "Policies & messages",
    to: "/policies",
    title: "Policies & guides",
    description: "Company policies and team guides that employees read and the HR assistant uses",
    icon: <BookText {...ICON} />,
    anyPermission: ["campaign.approve"],
  },
  {
    group: "Policies & messages",
    to: "/integrations",
    title: "Connections & message wording",
    description: "See what is connected (email, WhatsApp, ZingHR) and edit the messages people receive",
    icon: <Plug {...ICON} />,
    anyPermission: ["campaign.approve", "system.configure"],
  },
  {
    group: "Policies & messages",
    to: "/sla",
    title: "Shortlisting target",
    description: "The number of hours allowed to reach a shortlisting decision",
    icon: <Timer {...ICON} />,
    anyPermission: ["campaign.approve"],
  },
  {
    group: "Hiring setup",
    to: "/projects",
    title: "Projects",
    description: "Hiring needs that hold one or more campaigns",
    icon: <FolderKanban {...ICON} />,
    anyPermission: ["project.create", "campaign.create"],
  },
  {
    group: "Hiring setup",
    to: "/campaigns",
    title: "Campaigns",
    description: "Job openings with their JD, rules and application form",
    icon: <Megaphone {...ICON} />,
    anyPermission: ["campaign.create", "campaign.edit", "candidate.view"],
  },
  {
    group: "Hiring setup",
    to: "/approvals",
    title: "Approvals",
    description: "Job descriptions and rule-sets awaiting a decision",
    icon: <CheckCircle2 {...ICON} />,
    anyPermission: ["jd.approve", "rule.approve"],
  },
  {
    group: "Reporting",
    to: "/management",
    title: "Management dashboard",
    description: "Aggregated hiring indicators with small groups suppressed",
    icon: <BarChart3 {...ICON} />,
    anyPermission: ["campaign.approve", "audit.view"],
  },
  {
    group: "Reporting",
    to: "/decisions",
    title: "Hiring decisions",
    description: "Final decisions after interview assessment",
    icon: <Scale {...ICON} />,
    anyPermission: ["hiring_decision.recommend", "hiring_decision.approve"],
  },
  {
    group: "Reporting",
    to: "/talent-pool",
    title: "Talent pool",
    description: "Consented candidates you can search",
    icon: <Users {...ICON} />,
    anyPermission: ["talent_pool.search"],
  },
];
