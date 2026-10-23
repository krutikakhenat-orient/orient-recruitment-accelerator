---
inclusion: always
---

# Coding standards

## General
- Use clear domain language. Avoid generic names (manager, handler, processor) where a
  specific domain name exists.
- Keep routers thin; keep business logic in services and policies.
- Keep ORM models separate from API schemas. Never serialize ORM objects directly.
- Avoid circular dependencies. Use dependency injection.
- Handle errors explicitly. Do not swallow exceptions. Do not log sensitive inputs.
- Document security-sensitive code with a short rationale comment.
- Avoid premature abstraction and unnecessary design patterns.

## Python
- Type hints throughout. mypy/pyright clean.
- Format with ruff/black; lint with ruff.
- Pydantic v2 for all request/response boundaries.
- SQLAlchemy 2.x typed models; no raw string SQL built from user input.

## TypeScript / React
- `strict` mode on; no implicit any.
- Zod schemas validate all external data; React Hook Form for forms.
- TanStack Query for server state; no sensitive data in localStorage/sessionStorage.
- Components accessible by default (labels, roles, focus management).

## Absolute prohibitions
- No arbitrary code execution. No `eval`, `exec`.
- No dynamic SQL constructed from user input.
- No deserialization of untrusted Python objects. No `pickle` for uploaded/external data.
- No OS shell calls using user input.
- No hard-coded credentials or secrets. Secrets come from environment/secret store.

## Rules engine specifics
- Rules are data (typed JSON DSL), never code. The evaluator interprets a whitelisted set
  of node types and operators and rejects anything else at validation time.
