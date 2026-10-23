---
inclusion: always
---

# Accessibility

WCAG-oriented design across all portals.

## Requirements
- Semantic HTML; accessible labels for every control.
- Full keyboard navigation; visible focus states.
- Accessible error summaries; associate errors with fields.
- No colour-only status communication (pair colour with text/icon).
- Clear loading and empty states.
- Confirmation for consequential actions; unsaved-change warnings.
- Session-expiry handling with accessible messaging.
- Responsive layout.

## Testing
Automated axe checks in component and e2e tests. Note: full WCAG validation requires
manual testing with assistive technologies and expert review; automated checks are
necessary but not sufficient.

## Candidate assistance
Accessibility-assistance options may be offered on the application form but are never used
as a screening criterion.
