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
   The recruiter who scheduled the interview does not mark attendance.
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
| Interview Panel | synthetic.interview_panel@example.com | Confirm interview **attendance** and submit structured assessments for the candidates they interview. |
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
  **Team access** card on the campaign Overview tab (**Assign me**, or assign a colleague
  by email).

## The campaign detail tabs

Open a campaign from the **Campaigns** list. The tabs are:

- **Overview** — status, lifecycle buttons, the **Team access** (assignment) card, and the
  **Candidate apply link** card. That card shows the public application URL with a **Copy
  public link** button, an auto-generated **QR code** (candidates scan it from a flyer or a
  shared screen) with its own **Copy link** / **Download QR** buttons, plus **Share via
  email** and **Open apply page**. A 🔒 on a tab means that tab is read-only for your role.
- **Job Description** — upload a JD, review the extracted draft, approve it. Scoring criteria
  and the default 50% threshold are generated and approved automatically when the JD is
  approved, so there is **no separate Rules tab** to configure by hand.
- **Form** — create and approve the application form.
- **Applications & Screening** — see every applicant with their **Resume Score**, open each
  candidate's **Resume Score** (scorecard) to inspect the evidence, or click **View form**
  to see exactly what the candidate submitted on the application form. **Run screening** per
  application; re-running creates a new immutable result and never overwrites the previous
  one. The table columns are: Rank · Applicant · Resume Score · Application form · Review
  status · actions.

Buttons you cannot use are disabled with a short reason (e.g. "needs the Recruiter role" or
"you're not assigned to this campaign"), so you always know why.

## Fast local shortcut: open a campaign in one click

Opening a campaign the proper way takes several approvals across roles. For local
evaluation, each campaign's **Overview** tab has an **"Open this campaign now (dev)"**
button that creates and approves all five artifacts and drives the campaign to
**Applications Open** in one click — and assigns you to it. This button only exists in
local/dev environments.

## The Review Queue

Candidates are **not** added to the review queue by hand. The queue fills **automatically**
when screening routes someone to a human (missing or low-confidence evidence, a conflict,
or a borderline/mandatory-not-confirmed result). To populate it:

1. Open a campaign → **Applications & Screening** → **Run screening** on an applicant.
2. Go to **Review Queue** (sidebar) → select that campaign → flagged items appear.
3. On each item, enter a reason and choose an action: **Recommend interview**, **Waitlist**,
   **Request info**, or **Escalate**. Resolving actions clear the item from the open queue.
   Every action is recorded in the audit trail.

## A ready-made demo campaign

A fully-populated walkthrough campaign is seeded for convenience:

- **Project:** "DEMO - Platform Team 2026"
- **Campaign:** "DEMO - Senior Python Engineer" (already **Applications Open**)
- **3 synthetic applicants** already screened, spanning outcomes (a strong match, a
  borderline case, and one whose mandatory experience is not confirmed)
- **3 open review items** waiting in the Review Queue

To explore it: sign in as `synthetic.recruiter@example.com`, open the DEMO campaign, look at
the **Applications & Screening** tab, then open the **Review Queue** and act on the items.
Sign in as `synthetic.recruiter_admin@example.com` to see the approval and decision side,
and as `synthetic.interview_panel@example.com` to see attendance and assessments.

> This demo data is synthetic. Re-running the local seed or the dev "open now" button may
> create additional demo campaigns; delete or ignore them as needed.
