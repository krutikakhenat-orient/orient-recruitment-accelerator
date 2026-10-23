---
inclusion: always
---

# Repository structure

```
orient-recruitment-accelerator/
├── .kiro/
│   ├── steering/        # product, architecture, technology, structure,
│   │                    # coding-standards, security, privacy, responsible-ai,
│   │                    # database, api-standards, testing, accessibility, devsecops
│   └── specs/recruitment-platform/   # requirements.md, design.md, tasks.md
├── docs/
│   ├── adr/             # ADR-0001 .. ADR-0016
│   ├── threat-model.md
│   ├── permission-matrix.md
│   ├── state-machines.md
│   ├── security-checklist.md
│   ├── privacy-checklist.md
│   ├── deployment.md
│   ├── backup-restore.md
│   ├── admin-guide.md
│   ├── hr-guide.md
│   └── candidate-privacy-flow.md
├── backend/
│   ├── app/
│   │   ├── main.py
│   │   ├── core/            # config, security, logging, errors, correlation
│   │   ├── db/              # session, base, mixins
│   │   ├── modules/<module>/  # router, service, policy, repository, models, schemas
│   │   ├── rules_engine/    # typed DSL parser + deterministic evaluator
│   │   ├── screening/       # screening orchestration service
│   │   ├── documents/       # validation, quarantine, extraction adapters
│   │   └── workers/         # Dramatiq actors
│   ├── alembic/
│   ├── tests/               # unit, integration, security, e2e-api
│   └── pyproject.toml
├── frontend/
│   ├── src/
│   │   ├── app/             # router, providers
│   │   ├── portals/         # candidate, recruiter-hr, hiring-manager, panel,
│   │   │                    # management, admin, privacy
│   │   ├── components/      # accessible shared UI
│   │   ├── api/             # typed client, TanStack Query hooks
│   │   └── lib/
│   ├── tests/
│   └── package.json
├── deploy/
│   ├── docker-compose.yml
│   ├── reverse-proxy/
│   └── .env.example
├── seed/                    # synthetic data + synthetic resume generator
├── .github/workflows/ci.yml
└── README.md
```

## Module internal layout (every backend module)

```
modules/<name>/
  router.py       # thin HTTP layer
  service.py      # application service (orchestration, transactions)
  policy.py       # domain policy / invariants / separation-of-duties
  repository.py   # data access, tenant/campaign-scoped
  models.py       # SQLAlchemy ORM
  schemas.py      # Pydantic request/response
```

## Naming
Use clear domain language. Avoid generic names (manager, handler, processor) when a
specific domain term exists (e.g. `ScreeningRun`, `TransitionService`, `JDVersion`).
