# HR User Guide

Audience: Recruiters and Recruiter Admins.

## The hiring flow, end to end
1. **Create a project** (an approved hiring need), then a **campaign** under it.
2. **Upload the JD.** It is scanned and a draft is extracted for you to review — the
   extraction is a suggestion only; confirm or edit before approving.
3. **Approve the JD version.** Approved versions are immutable; later changes create a new
   version and preserve the original.
4. **Configure screening rules** (typed criteria with weights and mandatory flags) and get
   them **approved by a second person**. Set the **thresholds** (needs a reason; four-eyes
   if configured).
5. **Approve and publish the campaign.** Publication is blocked until the JD, rules, form,
   threshold, and privacy notice are all approved.
6. **Candidates apply** on the public campaign page, give consent, and upload a resume.
7. **Screening** runs deterministically against the approved rule version and produces an
   **explainable score**: every criterion shows the evidence, its source, confidence, and
   the awarded/maximum points, with a reason.
8. **Human review**: anything with missing evidence, low confidence, a conflict, or a
   below-threshold score is routed to you — screening never auto-rejects. Candidates who
   score **50% or above** (and are otherwise clean) are placed on the Interview Panel
   **automatically**; candidates **below 50%** stay under review for a person to decide.
9. **Select for interview.** For a below-50 (under-review) candidate, a Recruitment Admin
   can still **Select for interview** — this is a screening override, so it **requires a
   recorded reason** and is audited. The candidate then lands on the **same Interview
   Panel** tab as the auto-progressed ones. Assign **slots** (capacity-limited) as needed.
   From there the **Interview Panel** takes over: panel members confirm **attendance** and
   capture structured **assessments** from their own "My Assigned Interviews" dashboard.
   The recruiter who scheduled the interview does not mark attendance. Panel members only
   see candidates for the jobs (and stages) they have been **assigned** to — assign them on
   the campaign's **Interviews** tab (Recruiter Admin) or via System Administration.
10. **Make the hiring decision** (select/reject/hold/withdraw). Candidate communications
    never expose internal scores or reviewer notes.
11. **Waitlist** candidates with a reason; **re-evaluate** only under permitted triggers —
    a re-evaluation creates a new result and preserves the original.

## What the platform will not do
- It will not reject a candidate automatically because a score is low.
- It will not **contact or message** a candidate automatically. A ≥50% score places the
  candidate on the internal Interview Panel worklist, but nothing is sent to the candidate —
  the hiring team reaches out using the details on file. Final hiring decisions are always a
  human action.
- It will not use date of birth, gender, religion, disability, caste, race, photo, or
  similar attributes in screening.
- It will not treat a missing field as proof the candidate lacks a qualification — it asks
  a human.

## Dashboards
The HR dashboard shows active campaigns, applications by state, and the review backlog.
Management dashboards are aggregated and suppress small groups to protect individuals; no
per-recruiter or per-interviewer performance rankings are shown.

---

# Operating the platform (local walkthrough)

This section is a hands-on guide for the running app. All accounts and data below are
**synthetic** and for local evaluation only.

## Signing in and switching roles

Open the app at `http://localhost:5173`. Every staff account uses the password
`SyntheticDevPassword123`. To switch roles, click **Sign out** (top-right) and sign in as
the next account.

There are three operational roles plus governance/public roles. See
`docs/permission-matrix.md` for the authoritative permission mapping.

| Role | Email | Does |
|---|---|---|
| Recruiter | synthetic.recruiter@example.com | Author JD/rules, **run screening**, review applications, schedule interviews. Authoring side of four-eyes. |
| Recruiter Admin | synthetic.recruiter_admin@example.com | Everything the Recruiter does **plus** all approvals/sign-off: **approve** JD, rules, thresholds, interviews, and final hiring decisions, and audited PII reveal. (Absorbed the former HR Head and Hiring Manager roles.) Does **not** hold system administration. |
| Interview Panel | synthetic.interview_panel@example.com | Confirm interview **attendance** and submit structured assessments for the candidates they interview — limited to the jobs/stages they are **assigned** to. |
| Management Viewer | synthetic.management_viewer@example.com | Aggregated dashboards only; no candidate PII. |
| Audit Viewer | synthetic.audit_viewer@example.com | Read-only audit log. |
| System Admin | synthetic.system_admin@example.com | Manage staff user accounts. No automatic campaign/candidate access. |

> The former **HR Head** and **Hiring Manager** accounts no longer exist. Their duties now
> live in **Recruiter Admin**.

Two platform rules shape what you can do:

- **Separation of duties** — the person who creates an artifact cannot be the one who
  approves it. Rules and thresholds require the approver to be a *different* user than the
  creator (four-eyes). So opening a campaign normally spans more than one account.
- **Object-level assignment** — holding a permission is not enough; you must also be
  **assigned to the specific campaign**. The creator is auto-assigned. Others use the
  **Team access** card on the campaign's **Settings** tab (**Assign me**, or assign a
  colleague by email).

## From a new campaign to a live apply link

After you create a campaign, open it. While it is being set up it opens on **1 · Setup**,
which starts with a **Set up this job** checklist. The highlighted step is always the next
thing to do, and each step says who does it:

1. **Upload the job description** (Recruiter).
2. **Check and approve the job description** (Recruiter Admin). Approving also creates the
   screening criteria and the default 50% threshold automatically.
3. **Screening criteria ready** (automatic).
4. **Create and approve the application form** (Recruiter).
5. **Open for applications** (Recruiter Admin). One button. It checks that everything above
   is approved, attaches the organisation's privacy notice, and opens the job. Each internal
   status step is still permission-checked and written to the audit trail.

Once the job is open, the **apply link** appears in a green strip at the top of the job
page with **Copy link**, **QR code** (with **Download QR**), **Email** and **Preview**. On
the other tabs, a banner shows the next setup step until the job is open.

The status shown on a job is in plain words: **Setting up**, **Open for applications**,
**Paused**, **Reviewing candidates**, **Interviewing**, **Completed**, **Closed** or
**Cancelled**.

## The campaign detail tabs

- **1 · Setup**: the checklist, the job description (upload, check, approve) and the
  application form (create, approve). There is **no separate Rules tab**.
- **2 · Candidates**: see every applicant with their **Resume Score**, open each
  candidate's **Resume Score** (scorecard) to inspect the evidence, or click **View form**
  to see exactly what the candidate submitted on the application form. **Run screening** per
  application; re-running creates a new immutable result and never overwrites the previous
  one. Each row also has a **⤓ Resume** button to **download that candidate's original
  résumé** (served securely; requires `candidate.view` + campaign assignment; shows
  *Resume unavailable* when there is no file).
  The card header has two report actions:
  - **👁 Preview Excel** opens the campaign report **inside the app** — a searchable,
    scrollable table with a **Candidates** sheet and a **Summary** sheet. You can read and
    filter candidates without opening Microsoft Excel, then click **⤓ Download Excel** to
    save the real `.xlsx`. The preview and the download show the **same** records.
  - **⤓ Export to Excel** downloads the same HR workbook directly.

  The workbook has **two** HR-focused sheets. **Candidates** lists, per candidate: Rank,
  Candidate name, Email address, Contact number, Applied position, Application status,
  **Overall score (%)**, **JD skills match (%)**, Relevant skills & experience, Key
  strengths, Missing / unverified requirements, a **Download Resume** link and a **View
  summary** link. **Summary** holds campaign facts and a score legend. Overall score is the
  saved deterministic fit score; JD skills match is derived from the job description's skill
  criteria (shown only when such criteria exist) — they are different numbers. Nothing is
  rescored or changed. Email/phone are **masked** unless you hold the elevated
  `candidate.view_pii` permission, in which case the real values appear and each access is
  logged. The on-screen table columns are: Rank · Applicant · Resume Score · Application
  form · Review status · actions.
- **Candidate summary** — clicking **View summary** (in the preview, in the Excel workbook,
  or via the report) opens a per-candidate dashboard inside ORA: overall fit score and JD
  skills match, confirmed strengths/skills, missing mandatory requirements and items needing
  human verification, a per-criterion score breakdown, the applied position and status, and
  (with `candidate.view_pii`) an audited contact reveal plus an original-resume download. AI
  /screening output here supports a human decision and never auto-decides hiring.
- **Interviews** — alongside scheduling, Recruiter Admins see an **Interviewer assignments**
  card to assign interview-panel members to this job (optionally scoped to a stage) and
  remove them. An interviewer only ever sees the candidates for jobs/stages they are
  assigned to; this is enforced server-side, not just hidden in the UI.

- **Settings**: **Team access** (assignment), **Job status** (pause, close, reopen, cancel;
  each needs a reason), and **Approvals on record**. While a job is being set up, the
  step-by-step status buttons are tucked under *Advanced*, because the checklist's **Open for
  applications** button replaces them. A 🔒 on a tab means it is read-only for your role.

Buttons you cannot use are disabled with a short reason (e.g. "needs the Recruiter role" or
"you're not assigned to this campaign"), so you always know why.

## Local testing shortcut

For local evaluation only, **Settings** has a **Local testing shortcut** card ("Open this
campaign now (dev)") that creates and approves everything with test data and opens the job
in one click. It skips the normal approvals, so it only exists in local/dev environments and
must never be used for a real job. For real jobs use the Setup checklist.

## The Review inbox

The **Review inbox** (sidebar → My tasks) lists every candidate waiting for a person to
decide, across **all jobs you're assigned to**. There is no campaign to pick first.

- Items are sorted **oldest first**. Anything waiting 3 days or more is marked and can be
  filtered with **Waiting 3+ days**.
- **Filter chips** show a count per reason, in plain words: *Missing info*, *Needs a check*,
  *Hard to read*, *Conflicting details*, *Close to cut-off*, *Possible duplicate* and so on.
  *Missing info* means the resume doesn't show a must-have; that is not proof the candidate
  lacks it.
- Click a row to open it: **View resume & score**, **Journey**, **Open job**, then type a
  reason and choose **Select for interview**, **Waitlist**, **Ask for info** or **Ask hiring
  manager**. The buttons stay disabled until you enter a reason. Select and Waitlist remove
  the item from your inbox; the other two keep it there. Every action is in the audit trail.
- When nothing is waiting you'll see **All caught up**.

Items are not added by hand. They arrive automatically when screening routes someone to a
person (missing or low-confidence evidence, a conflict, or a borderline result).

## A ready-made demo campaign

A fully-populated walkthrough campaign is seeded for convenience:

- **Project:** "DEMO - Platform Team 2026"
- **Campaign:** "DEMO - Senior Python Engineer" (already **Applications Open**)
- **3 synthetic applicants** already screened, spanning outcomes (a strong match, a
  borderline case, and one whose mandatory experience is not confirmed)
- **3 open review items** waiting in the Review inbox

To explore it: sign in as `synthetic.recruiter@example.com`, open the DEMO campaign, look at
the **2 · Candidates** tab, then open the **Review inbox** and act on the items.
Sign in as `synthetic.recruiter_admin@example.com` to see the approval and decision side,
and as `synthetic.interview_panel@example.com` to see attendance and assessments.

> This demo data is synthetic. Re-running the local seed or the dev "open now" button may
> create additional demo campaigns; delete or ignore them as needed.
