/* Content of the in-app user guide (/guide). Plain data so it is easy to keep up to date.
   Keep wording short and free of jargon: the reader may be using the product for the first
   time. */

export interface GuideStep {
  title: string;
  who: string;
  where: string;
  text: string;
}

export const OVERVIEW = {
  lede:
    "Orient Recruitment Accelerator helps your team hire people from the first application to the first day at work. " +
    "It keeps every step in one place, shows who needs to act next, and keeps a record of what happened.",
  principles: [
    {
      title: "People decide",
      text: "The system reads resumes and applies rules you approved. It suggests and explains. It never decides who is hired or rejected.",
    },
    {
      title: "Every score is explained",
      text: "Each result shows the rules used and the evidence behind it. The same inputs always give the same result.",
    },
    {
      title: "Missing is not a 'no'",
      text: "If information is missing or unclear, the application goes to a person to look at. It is never turned down automatically.",
    },
    {
      title: "Private by default",
      text: "Candidates' contact details are hidden until someone with permission reveals them, and that is recorded.",
    },
  ],
};

export const JOURNEY: GuideStep[] = [
  {
    title: "Applied",
    who: "Candidate",
    where: "The public apply page for a campaign",
    text: "The candidate fills in the form, uploads a resume and agrees to how their data is used. They see a short 'what happens next' list.",
  },
  {
    title: "Resume checked",
    who: "System",
    where: "Happens automatically",
    text: "The resume is scanned for safety and read. Staff can check and correct what was found.",
  },
  {
    title: "Screened",
    who: "System",
    where: "Job > Candidates",
    text: "The approved rules are applied. You get a score with the evidence for it. This is a recommendation, never a decision.",
  },
  {
    title: "HR review",
    who: "Recruiter",
    where: "Review inbox",
    text: "Anything unclear, borderline or missing information is looked at by a person, who chooses the next step.",
  },
  {
    title: "Short AI interview (optional)",
    who: "Candidate",
    where: "Job > Candidates",
    text: "If switched on, a recruiter approves the questions and the candidate takes a short voice interview from a personal link. The summary is advisory only.",
  },
  {
    title: "Interview invited",
    who: "Recruiter admin",
    where: "Campaign > Interviews",
    text: "An approver invites the candidate. Nobody is invited automatically because of a score.",
  },
  {
    title: "Interview confirmed",
    who: "Candidate",
    where: "The candidate's personal link",
    text: "The candidate confirms, asks for another time, or declines. The interviewer is told straight away.",
  },
  {
    title: "Interview held",
    who: "Interviewer",
    where: "My Interviews",
    text: "The panel checks the candidate in, records an assessment and checks them out.",
  },
  {
    title: "Decision",
    who: "Recruiter admin",
    where: "Hiring Decisions",
    text: "A hiring manager records the outcome: selected, on hold, waitlisted or not selected, with a reason.",
  },
  {
    title: "Offer",
    who: "Recruiter admin",
    where: "Offers & joining > Offers",
    text: "An offer is prepared, approved and sent. HR records the candidate's answer.",
  },
  {
    title: "Joining documents",
    who: "Candidate and HR",
    where: "Offers & joining > Joining cases",
    text: "The candidate gets a document list. HR marks documents received, runs a check and resolves anything flagged.",
  },
  {
    title: "Joining",
    who: "HR",
    where: "Offers & joining > Joining cases",
    text: "HR approves the joining details, sends the joiner their information and welcome, announces them to the team and marks them as joined.",
  },
];

/* How a job opening goes live, as the screens work today. `to` lets the diagram link to the
   screen where each step happens. */
export interface FlowStep {
  title: string;
  who: string;
  text: string;
  to?: string;
}

export const OPENING_FLOW: FlowStep[] = [
  {
    title: "Create a project",
    who: "Recruiter",
    text: "The hiring need, e.g. 'Engineering 2026'. One project can hold many job openings.",
    to: "/projects",
  },
  {
    title: "Create a campaign",
    who: "Recruiter",
    text: "One job opening inside the project: title, number of openings.",
    to: "/campaigns",
  },
  {
    title: "Upload the job description",
    who: "Recruiter",
    text: "Open the job > 1 · Setup. The checklist there always shows the next step.",
    to: "/campaigns",
  },
  {
    title: "Approve the job description",
    who: "Recruiter admin (a different person)",
    text: "Approvals page or the job's Setup tab. Screening criteria are created from it automatically.",
    to: "/approvals",
  },
  {
    title: "Set up the application form",
    who: "Recruiter",
    text: "Setup tab, step 4. Create the form, then approve it.",
    to: "/campaigns",
  },
  {
    title: "Open for applications",
    who: "Recruiter admin",
    text: "One button on the Setup checklist. It checks everything is approved first.",
    to: "/campaigns",
  },
  {
    title: "Share the apply link",
    who: "Recruiter",
    text: "Shown at the top of the job page once it's open. Copy it, email it or show the QR code.",
    to: "/campaigns",
  },
];

/* What HR sees as the status of a job opening (matches lib/campaignStatus.ts). */
export const OPENING_STATUSES: { label: string; text: string }[] = [
  { label: "Setting up", text: "Not visible to candidates yet" },
  { label: "Open for applications", text: "Candidates can apply" },
  { label: "Reviewing candidates", text: "Applications closed, screening and review" },
  { label: "Interviewing", text: "Shortlisted people are interviewed" },
  { label: "Completed", text: "Hiring is finished" },
];

export const NEXT_FOR_CANDIDATE: string[] = [
  "We check your resume and application.",
  "A recruiter looks at your application. This may take a little time.",
  "If you are a good fit for the next step, HR will contact you about an interview.",
  "You will get a personal link to confirm your interview time.",
  "After the interview, the hiring team makes the decision.",
  "If you are selected, you will get your offer and a list of documents to bring.",
];

export interface RoleGuide {
  role: string;
  summary: string;
  tasks: string[];
}

export const ROLES: RoleGuide[] = [
  {
    role: "Recruiter",
    summary: "Sets up hiring and does the day-to-day work. Cannot approve their own work.",
    tasks: [
      "Create projects and campaigns, upload job descriptions, draft rules and forms.",
      "Run screening and work through the Review inbox.",
      "Check the Shortlisting clock and send reminders.",
      "Collect joining documents and run document checks.",
    ],
  },
  {
    role: "Recruiter admin",
    summary: "Does everything a recruiter does, and approves.",
    tasks: [
      "Approve job descriptions, rules, thresholds and forms (a different person from the author).",
      "Invite candidates to interview and record hiring decisions.",
      "Approve and send offers; approve joining details; mark people as joined.",
      "Manage policies and the wording of messages.",
    ],
  },
  {
    role: "Interview panel",
    summary: "Interviews the candidates assigned to them.",
    tasks: ["Open My Interviews, check candidates in, record an assessment, check them out."],
  },
  {
    role: "System admin",
    summary: "Looks after accounts and settings. Does not see candidate content.",
    tasks: [
      "Create staff accounts and choose roles.",
      "Set how long records are kept and handle privacy requests.",
    ],
  },
  {
    role: "Management and audit viewers",
    summary: "Read-only.",
    tasks: [
      "Management viewer: sees combined figures with no personal details.",
      "Audit viewer: reads the audit log.",
    ],
  },
  {
    role: "Employee",
    summary: "A new joiner using the induction area.",
    tasks: [
      "Watch the induction video and download the certificate.",
      "Read company policies and confirm you have read them.",
      "Ask HR a question and get an answer from approved policies.",
    ],
  },
];

export interface TaskGuide {
  title: string;
  steps: string[];
}

export const TASKS: TaskGuide[] = [
  {
    title: "Open a job for applications",
    steps: [
      "Projects: create a project (the hiring need).",
      "Campaigns: create a campaign under it.",
      "Open the job. It opens on 1 · Setup, with a checklist that highlights the next step.",
      "Upload the job description. A Recruiter Admin approves it; screening criteria are then created automatically.",
      "Create the application form and approve it.",
      "A Recruiter Admin clicks Open for applications on the checklist.",
      "The apply link appears at the top of the job page. Copy it, email it or show the QR code.",
    ],
  },
  {
    title: "Handle new applications",
    steps: [
      "Open the job > 2 · Candidates to see candidates ranked by score.",
      "Open a candidate to see the evidence behind each score.",
      "Work through the Review inbox: everything waiting for a person, across all your jobs, oldest first.",
      "Click Journey on any candidate to see exactly where they are and what happens next.",
    ],
  },
  {
    title: "Interview a candidate",
    steps: [
      "An approver invites the candidate (campaign > Interviews).",
      "Choose a slot, then send the candidate their confirmation link. 'Suggest slots' shows free slots.",
      "The candidate answers on their link; the interviewer is told automatically.",
      "On the day the panel opens My Interviews, checks the candidate in and records an assessment.",
    ],
  },
  {
    title: "Record a decision and make an offer",
    steps: [
      "Hiring Decisions: choose selected, on hold, waitlisted or not selected, and give a reason.",
      "Offers & joining > Offers: prepare the offer, approve it, then send it.",
      "When the candidate answers, record Accepted or Declined.",
    ],
  },
  {
    title: "Welcome a new joiner",
    steps: [
      "On an accepted offer click 'Start joining case'. The candidate is sent a document list.",
      "Open the case. Mark each document received, type the name on it and its expiry date (never ID numbers).",
      "Click 'Check documents', then resolve each flag with a short reason.",
      "Fill in the joining details and click 'Approve joining details'.",
      "Send the joining information and welcome message, announce to the team, and mark as joined.",
    ],
  },
  {
    title: "Keep the shortlisting target",
    steps: [
      "Open Shortlisting clock to see who is on track, getting close or overdue.",
      "Click 'Run reminder check' to record reminders. An approver can change the target hours.",
    ],
  },
  {
    title: "Publish a policy",
    steps: [
      "Settings > Policies & guides > New policy or guide. Save the draft.",
      "Click Approve to publish. Employees can read it and the assistant can use it.",
      "To change it later click Revise, edit the new draft and approve it.",
    ],
  },
  {
    title: "Handle a privacy request",
    steps: [
      "Settings > Privacy & retention > Privacy requests.",
      "Type the email the person applied with, choose what they asked for and record it.",
      "Close the request when it has been dealt with. Everything is logged.",
    ],
  },
];

export interface ScreenGuide {
  name: string;
  text: string;
}

export const SCREENS: ScreenGuide[] = [
  { name: "Dashboard", text: "What needs your attention today, the hiring pipeline and a candidate search." },
  { name: "Review inbox", text: "Everything waiting for a person, across your jobs, oldest first: unclear, borderline or missing information." },
  { name: "Approvals", text: "Job descriptions and rules waiting for your sign-off." },
  { name: "My Interviews", text: "Interviews assigned to you: check in, assess, check out." },
  { name: "Projects and Campaigns", text: "A project is a hiring need. A campaign is one job opening inside it." },
  { name: "Waitlist", text: "Candidates kept for later, with a safe way to re-check them." },
  { name: "Talent Pool", text: "People who agreed to be considered for future jobs." },
  { name: "Hiring Decisions and Outcomes", text: "Record decisions and see every final outcome with the reason." },
  { name: "Offers & joining", text: "Everything after someone is selected: offer, documents, joining and welcome." },
  { name: "Shortlisting clock", text: "How long applications have waited for a decision, against the target." },
  { name: "Management", text: "Combined figures. Small groups are hidden to protect individuals." },
  { name: "Settings", text: "People, privacy, policies, connections and message wording." },
  { name: "Audit log", text: "A permanent, read-only record of important actions." },
];

export const MESSAGE_STATES: { state: string; meaning: string }[] = [
  { state: "Sent", meaning: "A real email or message service accepted it." },
  { state: "Demo only: not really delivered", meaning: "Demo mode. It was recorded so you can follow the process, but nothing left the system." },
  { state: "Not sent: no provider connected", meaning: "No email or WhatsApp service is connected. Use the 'ready-to-send' link on the message to send it yourself." },
  { state: "Failed", meaning: "A service was tried and rejected it. The reason is shown." },
];

export interface ConnectionGuide {
  name: string;
  today: string;
  needs: string;
}

export const CONNECTIONS: ConnectionGuide[] = [
  { name: "Email", today: "Works in demo mode or with a mail server (MailHog locally). Otherwise messages are recorded with a ready-to-send link.", needs: "A mail server or Microsoft 365 connection." },
  { name: "WhatsApp", today: "Placeholder. Messages are recorded; nothing is sent.", needs: "A WhatsApp Business provider, approved templates and candidate opt-in." },
  { name: "Calendar", today: "Placeholder. Slot suggestions use the slots you created.", needs: "Calendar access approved by IT." },
  { name: "AI interview", today: "Off by default. The process works without it.", needs: "The interview agent switched on." },
  { name: "ZingHR", today: "Placeholder. HR can preview the record that would be sent; nothing is sent.", needs: "ZingHR API access and a test environment." },
  { name: "Job sites (Naukri and others)", today: "Not connected.", needs: "A feasibility study, terms and consent review." },
  { name: "AI avatar induction", today: "Not built. Induction uses a recorded video.", needs: "Vendor review and consent." },
];

export const GLOSSARY: { term: string; meaning: string }[] = [
  { term: "Project", meaning: "A hiring need, such as 'Engineering 2026'. It can hold several campaigns." },
  { term: "Campaign", meaning: "One job opening, with its own job description, rules and application form." },
  { term: "Job description (JD)", meaning: "The written description of the job. Once approved it cannot be changed; changes make a new version." },
  { term: "Rules", meaning: "What counts as a match for the job, for example required skills. Approved by a person before use." },
  { term: "Threshold", meaning: "The score levels used to suggest a next step. Changing it needs a reason and an approver." },
  { term: "Screening", meaning: "Applying the approved rules to an application to produce an explained score." },
  { term: "Four-eyes", meaning: "Two different people: one prepares, another approves." },
  { term: "Review inbox", meaning: "Applications that need a person to look at them." },
  { term: "Waitlist", meaning: "Candidates kept for later in case a place opens." },
  { term: "Talent pool", meaning: "People who agreed to be considered for future roles." },
  { term: "Offer", meaning: "The formal job offer. Drafted, approved, sent, then accepted or declined." },
  { term: "Joining case", meaning: "The record that follows a selected person from accepting the offer to their first day." },
  { term: "Flag", meaning: "A suggestion that something in a document may need attention. HR decides." },
  { term: "Advisory", meaning: "Shown to help a person decide. Never a decision." },
  { term: "Placeholder", meaning: "A feature that works on this computer, but whose outside connection is not set up yet." },
  { term: "Audit log", meaning: "A permanent record of important actions." },
];

export const FAQ: { q: string; a: string }[] = [
  { q: "Can the system reject a candidate by itself?", a: "No. Scores and flags only suggest. A person decides, and missing or unclear information always goes to a person." },
  { q: "Why did my message say 'Not sent'?", a: "No email or WhatsApp service is connected yet. The message is saved with a ready-to-send link so you can send it yourself. See Settings > Connections & messages." },
  { q: "A candidate says their link does not work.", a: "Personal links work once and expire. Open the interview and send a new confirmation link." },
  { q: "Why is a button greyed out?", a: "You may not have permission, or an earlier step is not done yet (for example, joining details must be approved before joining messages can be sent). The line under the button says why." },
  { q: "Where do I see what happened to a candidate?", a: "Click Journey next to their name. It shows every step, who handles it, and what happens next." },
  { q: "Can I change an approved policy or job description?", a: "Not in place. Use Revise to make a new version. The old version stays on record." },
  { q: "Does the HR assistant use AI?", a: "No. It looks for matching words in approved policies and quotes them with the source. If nothing matches it says so." },
  { q: "Who can see a candidate's phone or email?", a: "Only people with permission, after pressing Reveal. Every reveal is recorded." },
];
