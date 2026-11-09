# User guide — Orient Recruitment Accelerator

The same guide is built into the app at **`/guide`** (public, searchable, linked from the
sidebar and the employee area). This file is the version for the repository.

## What this is

The product helps your team hire people from the first application to the first day at work.
Every step is in one place, it shows who needs to act next, and it keeps a record.

- **People decide.** The system reads resumes and applies rules you approved. It suggests and
  explains; it never decides who is hired or rejected.
- **Every score is explained.** Each result shows the rules and evidence. The same inputs always
  give the same result.
- **Missing is not a "no".** Missing or unclear information goes to a person, never to an
  automatic rejection.
- **Private by default.** Contact details are hidden until someone with permission reveals them,
  and that is recorded.

## The candidate journey

On any candidate, click **Journey** to see every step, who handles it, and what happens next.

| # | Step | Who | Where |
|---|---|---|---|
| 1 | Applied | Candidate | Public apply page |
| 2 | Resume checked | System | Automatic |
| 3 | Screened | System | Job > 2 · Candidates |
| 4 | HR review | Recruiter | Review inbox |
| 5 | Short AI interview (optional) | Candidate | Personal link |
| 6 | Interview invited | Recruiter admin | Campaign > Interviews |
| 7 | Interview confirmed | Candidate | Personal confirmation link (`/confirm/...`) |
| 8 | Interview held | Interviewer | My Interviews |
| 9 | Decision | Recruiter admin | Hiring Decisions |
| 10 | Offer | Recruiter admin | Offers & joining > Offers |
| 11 | Joining documents | Candidate and HR | Offers & joining > Joining cases |
| 12 | Joining | HR | Offers & joining > Joining cases |

## Common tasks

**Interview a candidate.** An approver invites the candidate. In *Campaign > Interviews*, use
**Send confirmation link** (or **Get link only** to share it yourself). The candidate confirms,
asks for another time, or declines; the assigned interviewers are told automatically.
**Suggest slots** lists open slots with room left.

**Make an offer.** *Offers & joining > Offers*: **Prepare offer** → **Approve** → **Send offer**
→ record **Candidate accepted / declined**. Nothing is sent without someone pressing the button.

**Welcome a new joiner.** On an accepted offer, **Start joining case** (the candidate is sent a
document list). In the case: mark documents received (type the name on the document and its
expiry date, never ID numbers) → **Check documents** → resolve each flag with a reason → fill
the joining details → **Approve joining details** → send joining information and welcome →
announce to the team (only with the joiner's agreement) → **Mark as joined**.

**Keep the shortlisting target.** *Shortlisting clock* shows on track / getting close /
overdue / waiting for candidate. **Run reminder check** records one notice per application.
An approver can change the target (default 48 hours, warning at 75%).

**Publish a policy.** *Settings > Policies & guides*: write a draft, **Approve** to publish,
**Revise** to make a new version. Employees read and acknowledge it; the HR assistant answers
only from approved policies and names the source.

**Handle a privacy request.** *Settings > Privacy & retention > Privacy requests*: enter the
email the person applied with, choose the request type, record it, and close it when done.

## Messages: what each status means

| Status | Meaning |
|---|---|
| Sent | A real email or messaging service accepted it. |
| Demo only: not really delivered | Demo mode. Recorded so you can follow the process; nothing left the system. |
| Not sent: no provider connected | No service connected. Use the message's ready-to-send link to send it yourself. |
| Failed | A service rejected it; the reason is shown. |

Messages never contain scores or internal notes. Wording is edited (and versioned) in
*Settings > Connections & message wording*.

## What works locally, and what is a placeholder

`python run_local.py` starts everything with email and WhatsApp in **demo mode** (recorded, not
delivered), so the whole journey can be followed on one computer.

| Feature | Today | Needed to connect it |
|---|---|---|
| Email | Demo mode locally; `ORA_NOTIFICATION_EMAIL_MODE=smtp` delivers via SMTP (MailHog works) | Mail server / Microsoft 365 |
| WhatsApp | Placeholder: recorded only | WhatsApp Business provider, approved templates, opt-in |
| Calendar | Placeholder: slot suggestions use the slots you created | Calendar access approved by IT |
| Automatic reminders | Placeholder: reminders run when you press the button | Background scheduler (Dramatiq workers) |
| SLA hours | Calendar hours | Business-hours and holiday calendar |
| Document verification | Rule-based checks on what HR types in | AI/OCR reading of files (placeholder) |
| Feedback summary | Built from interviewers' own scores and notes | Optional AI summary (placeholder) |
| HR assistant | Matches approved policy text and quotes it | Optional AI phrasing (placeholder); holiday calendar |
| ZingHR | Preview of the record that would be sent | ZingHR API access and sandbox |
| Naukri / NOCR | Not connected | Feasibility study, terms, consent |
| AI avatar induction | Not built; recorded video is used | Vendor review and consent |
| Public-link rate limiting | Not wired | Rate-limit middleware |

The **Connections** page (`/integrations`) shows the live state of each one.

## Who does what

- **Recruiter** — sets up campaigns, screens, reviews, collects joining documents. Cannot approve own work.
- **Recruiter admin** — everything a recruiter does, plus approvals, interviews, decisions, offers, joining sign-off, policies and message wording.
- **Interview panel** — checks in, assesses and checks out assigned candidates.
- **System admin** — accounts, retention, privacy requests. No candidate content.
- **Management / audit viewer** — read-only figures / audit log.
- **Employee** — induction video and certificate, policies, Ask HR.

## Questions

- *Can the system reject someone by itself?* No.
- *Why is a button greyed out?* Missing permission or an earlier step not done; the line under the button explains.
- *A candidate's link does not work.* Links work once and expire; send a new one.
- *Can I edit an approved policy or JD?* No; revise it to create a new version.
