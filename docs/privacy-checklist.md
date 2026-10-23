# Privacy Checklist

## Consent
- ✅ Purpose-specific consent recorded with notice version + timestamp
- ✅ Separate, explicit talent-pool opt-in (distinct from application consent)
- ✅ Consent withdrawal (talent pool) with audit
- ✅ Privacy consent is mandatory to submit an application

## Data minimisation
- ✅ Prohibited fields (DOB, gender, religion, disability, caste, race, photo, etc.) are
  rejected on the application form and never enter screening
- ✅ Compensation fields off by default; enabled only when authorised
- ✅ Accessibility-assistance fields are non-scoring

## Candidate rights (privacy requests)
- ✅ Access/export, correction, deletion, processing-restriction, consent-withdrawal request
  types with an auditable lifecycle (received → completed)
- ◻ Automated export package generation (workflow present; artefact generation is a follow-up)

## Retention
- ✅ Configurable retention policy per record category
- ✅ Every retention action (notify/restrict/delete/anonymise/legal-hold) logged (AC-17)
- ◻ Scheduled retention worker (Dramatiq) — destructive actions run only after owner
  notification window; worker wiring is a deployment follow-up

## Logging & exposure
- ✅ No candidate PII in logs (redaction filter)
- ✅ Candidate communications never include internal scores or reviewer notes
- ✅ Management dashboards suppress small-group breakdowns

## Non-claim
This product provides technical controls that support organisational compliance. It is
not claimed to be automatically legally compliant with any specific regulation.
