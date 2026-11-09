# CI/CD pipeline (Orient_Internal_AI)

> **Superseded.** The GitHub Actions workflow described here was removed: CodeCommit is now the
> deployment source and GitHub is a backup only. See `backend-cicd-pipeline.md` for the current design.

Source: `.github/workflows/deploy-orient-internal-ai.yml`. One GitHub Actions pipeline deploys the AgentCore agent, infrastructure, backend and frontend. Account `Orient_Internal_AI`, region `ap-south-1`.

Status: documented from the workflow and scripts. The pipeline has not been run, and the architecture doc says nothing is deployed yet.

```mermaid
flowchart TB
  dev([Developer]) -->|git push / open PR| gh[(GitHub repo<br/>krutikakhenat-orient/<br/>orient-recruitment-accelerator)]

  gh -->|pull request to main| checks
  gh -->|push to main or manual run| checks

  subgraph wf["GitHub Actions: deploy-orient-internal-ai.yml (one run at a time)"]
    direction TB

    subgraph checks["Job 1: checks (PR and push)"]
      direction TB
      c1["Backend pytest"] --> c2["Frontend tests + build"] --> c3["Amplify Gen 2 type check"] --> c4["terraform fmt + validate"]
    end

    checks -->|push / manual only,<br/>not on PR| gate{{"Environment approval<br/>orient-internal-ai<br/>(required reviewers)"}}

    subgraph deploy["Job 2: deploy"]
      direction TB
      oidc["Assume AWS role via OIDC<br/>no stored keys<br/>repo + main branch only"]
      s1["1. Deploy AgentCore interview agent<br/>(agentcore CLI 0.31.1, CodeZip)"]
      s2["2. Build Lambda zip<br/>backend + Data API driver<br/>linux wheels, no Docker"]
      s3["3. Terraform init + apply<br/>(applied twice on first run<br/>to learn the Amplify URL)"]
      s4["4. Lock AgentCore runtime<br/>only the api Lambda role may invoke"]
      s5["5. DB migrations<br/>invoke ops Lambda: migrate"]
      s6["6. Amplify Gen 2 backend<br/>ampx pipeline-deploy (Cognito)"]
      s7["7. Publish frontend<br/>build, zip, Amplify create/start-deployment"]
      s8["8. Smoke test<br/>GET /health up to 6x, 20 s apart"]
      oidc --> s1 --> s2 --> s3 --> s4 --> s5 --> s6 --> s7 --> s8
    end
    gate --> oidc
  end

  subgraph aws["AWS account Orient_Internal_AI, ap-south-1"]
    role["IAM role github-deploy<br/>(AdministratorAccess, TODO scope down)"]
    state[("S3 Terraform state<br/>versioned + lockfile")]
    agent["AgentCore runtime<br/>interview agent"]
    tf["API Gateway, Lambda api + ops,<br/>Aurora Serverless v2, Secrets Manager,<br/>S3, Amplify app"]
    ops["ops Lambda"]
    db[("Aurora PostgreSQL<br/>via RDS Data API")]
    cog["Cognito user pool"]
    amp["Amplify Hosting<br/>React SPA + /api rewrite"]
    api["API Gateway /health"]
  end

  oidc -.-> role
  s1 --> agent
  s3 --> state
  s3 --> tf
  s4 --> agent
  s5 --> ops --> db
  s6 --> cog
  s7 --> amp
  s8 --> api

  s8 -->|healthy| done([Release live])
  s8 -->|no 200| fail([Run fails])
```

## How it works

- **Trigger:** a pull request to `main` runs the `checks` job only. A push to `main`, or a manual run, runs `checks` and then `deploy`. Only one run executes at a time, and a running deploy is never cancelled.
- **Approval gate:** `deploy` runs in the GitHub environment `orient-internal-ai`. Add required reviewers there to get a human release approval.
- **AWS access:** GitHub issues a short-lived OIDC token. AWS lets the job assume the `github-deploy` role only when the token subject matches `repo:<owner/repo>:ref:refs/heads/main`. No AWS keys are stored in GitHub.

## Job 1: checks

1. Backend `pytest`.
2. Frontend tests and build.
3. Type check of the Amplify Gen 2 (Cognito) code.
4. `terraform fmt -check`, `init -backend=false` and `validate`.

## Job 2: deploy

1. **AgentCore agent:** installs the pinned AgentCore CLI and runs `scripts/deploy-agent.ps1`, which copies the agent project, retargets it to this account, tags it and runs `agentcore deploy`.
2. **Lambda package:** installs backend dependencies as Linux wheels (no Docker), adds the Aurora Data API driver, the app code and the Alembic migrations.
3. **Terraform:** state is stored in `ora-tfstate-<account>-ap-south-1` with lockfile locking. It creates API Gateway, the `api` and `ops` Lambdas, Aurora Serverless v2, Secrets Manager, S3, the Amplify app and the OIDC role. The first run applies twice, because the Amplify URL is only known after the first apply and is then fed back as `app_base_url`.
4. **Lock AgentCore runtime:** a resource policy allows only the `api` Lambda role to invoke the interview agent and denies all other principals.
5. **Migrations:** invokes the `ops` Lambda with `{"action":"migrate"}`. The step fails if the response contains an error. Aurora may need about 30 seconds to resume from auto-pause.
6. **Amplify Gen 2 backend:** `ampx pipeline-deploy` creates the Cognito user pool for staff.
7. **Frontend:** builds the SPA, zips it, and publishes it with `aws amplify create-deployment` and `start-deployment`.
8. **Smoke test:** calls `API_URL/health` up to 6 times, 20 seconds apart. Any non-200 result on the last try fails the run.

## Known gaps

- The deploy role has `AdministratorAccess` (TODO: scope down).
- Untested: `ampx pipeline-deploy` outside the Amplify Console, `agentcore status --json` ARN parsing, and the AgentCore resource-policy command.
- Data API compatibility with the app's SQLAlchemy models and Alembic migrations is not verified. Data API fails on responses over 1 MB and statements over about 45 seconds.
- `architecture-v2.md` says `terraform/` still implements v1 (VPC plus fck-nat), while the README describes v2. Check `terraform/main.tf` to confirm which one it creates.
- The agent-to-HR-API result webhook is not wired.
- Cognito is provisioned but the app does not use it yet.

## Related files

- `docs/architecture-v2.md`: architecture and cost estimate.
- `README.md`: first-deploy steps from a developer machine.
- `terraform/cicd.tf`: OIDC provider and deploy role.
- `scripts/deploy.ps1`: the same steps run locally.
