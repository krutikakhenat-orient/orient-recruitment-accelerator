# Frontend — Orient Recruitment Accelerator

React 18 + TypeScript (strict) + Vite 6. React Router, TanStack Query, React Hook Form, Zod.

For product/architecture context see [../docs/PROJECT_DOCUMENTATION.md](../docs/PROJECT_DOCUMENTATION.md);
for workflow and conventions see [../CONTRIBUTING.md](../CONTRIBUTING.md).

## Setup & run

```powershell
npm install
npm run dev
```

Serves the app at http://localhost:5173 and proxies `/api/*` to the backend on port 8000.
Start the backend first (see [../backend/README.md](../backend/README.md)).

> Windows note: if `npm run dev` is blocked by PowerShell execution policy, run Vite
> directly: `node node_modules\vite\bin\vite.js --host --port 5173`.

Sign in with a synthetic account, e.g. `synthetic.hr_head@example.com` /
`SyntheticDevPassword123`.

## Scripts

```powershell
npm run dev          # dev server
npm run build        # tsc -b && vite build
npm run preview      # preview a production build
npm run typecheck    # tsc --noEmit (strict)
npm run lint         # eslint
npm run test         # vitest run
```

## Layout

```
src/
  api/           typed client (api/client.ts), auth, resource wrappers
  app/           router (App.tsx), layout (AppLayout.tsx), auth context
  components/    accessible UI kit (ui.tsx), toast, Orient HR Assistance
  pages/         one page per portal area (Dashboard, Projects, Campaigns,
                 CampaignDetail, ReviewQueue, TalentPool, Management, Privacy,
                 Admin, Login, PublicApply)
  main.tsx       app entry (providers: QueryClient, Router, Auth, Toast)
  styles.css     design system
tests/           Vitest + Testing Library
```

## Conventions

- Strict TypeScript; no implicit `any`. `exactOptionalPropertyTypes` is on — optional props
  must be typed `T | undefined` where appropriate.
- Zod validates all external/API data; React Hook Form for forms.
- TanStack Query for server state. **Tokens are kept in memory only — never localStorage.**
- Components accessible by default: labels, roles, visible focus, error summaries, clear
  loading/empty states. Automated axe checks in tests (necessary but not sufficient).
