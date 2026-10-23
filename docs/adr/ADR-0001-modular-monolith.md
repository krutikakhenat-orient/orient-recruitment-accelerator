# ADR-0001: Modular monolith over microservices

Status: Accepted
Date: 2026-10-08

## Context

Orient Recruitment Accelerator spans ~23 bounded modules with strong consistency needs
(immutable versions, deterministic screening, audit chains, separation-of-duties). The
MVP targets a single organisation and a single operations team.

## Decision

Build a modular monolith: one deployable FastAPI application composed of bounded modules
with enforced internal layering (`router -> service -> policy -> repository -> db`). Do
not adopt microservices or Kubernetes unless a later ADR demonstrates a concrete
operational need (independent scaling, team autonomy, or fault isolation that the monolith
cannot meet).

## Consequences

- Simpler local development, transactions, and testing; one migration history.
- Strong consistency for screening, versioning, and audit without distributed-transaction
  complexity.
- Module boundaries are enforced by convention and review (services, not shared
  repositories) so a future extraction to services remains feasible.
- Risk: boundaries can erode. Mitigation: lint/review for cross-module repository access
  and circular imports; keep inter-module calls at the service interface.
