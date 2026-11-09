# Orient_Internal_AI deployment (architecture v2)

Design: `docs/architecture-v2.md`. Account profile `Orient_Internal_AI`, region `ap-south-1`.

| Part | Tool | Where |
|---|---|---|
| API Gateway, Lambda `api` + `ops`, Aurora Serverless v2 (Data API), Secrets Manager, S3, Amplify app + `/api` rewrite, GitHub OIDC role | Terraform (remote state in S3) | `terraform/` |
| Cognito user pool (staff, MFA off, admin-created users only) | Amplify Gen 2 | `frontend/amplify/` |
| SPA hosting | Amplify Hosting (zip deployment) | `scripts/deploy-frontend.ps1` |
| Interview voice agent | AgentCore CLI (`@aws/agentcore`, CodeZip, no Docker) | `scripts/deploy-agent.ps1` |
| Single CI/CD | GitHub Actions | `.github/workflows/deploy-orient-internal-ai.yml` |

All resources carry the cost tags Project, Application, Environment, Owner, CostCenter, ManagedBy
(Terraform `default_tags`, Amplify `Tags.of`, AgentCore `agentcore.json` tags in the staged copy).

## First deploy (from a developer machine)
1. `aws sso login --profile Orient_Internal_AI`
2. `.\scripts\deploy.ps1 -Seed` (omit `-Seed` for no synthetic users). Steps, in order:
   state bucket -> AgentCore agent -> Lambda package -> Terraform -> lock agent runtime -> DB migrate ->
   Amplify Gen 2 backend -> frontend. Use `-PlanOnly` to stop after `terraform plan`.
3. In GitHub: set repo variable `AWS_DEPLOY_ROLE_ARN` to Terraform output `github_deploy_role_arn`; create the
   `orient-internal-ai` environment (add required reviewers for release approval). Optional variables:
   `AGENT_ADMIN_ROLE_ARN` (IAM role ARN allowed to invoke the agent for testing), `CREATE_GITHUB_OIDC_PROVIDER=false`
   if the account already has the GitHub OIDC provider.
4. After that, every push to `main` deploys everything.

The AgentCore project in `interview-agent/InterviewAgent` is **not modified**: `deploy-agent.ps1` copies it to
`.build/agent`, retargets it to this account and applies this account's tags, then runs `agentcore deploy`.

## Data API prerequisite (must be verified before the first real deploy)
The Lambdas reach Aurora with `ORA_DATABASE_URL=postgresql+auroradataapi://...` (package
`sqlalchemy-aurora-data-api`, installed from `lambda-extra-requirements.txt`). The backend currently uses
`postgresql+psycopg`. **Not yet verified:** that the app's models, UUID/JSONB columns, transactions and Alembic
migrations work through that dialect, and that no psycopg-specific code (pool/connect args) breaks. Run the app tests
and `alembic upgrade head` against a real Data API cluster first. Data API limits: responses over 1 MB and statements
over about 45 s fail.

## Known gaps
- AgentCore -> HR API result webhook is not configured (results land in S3 only).
- Cognito is provisioned but the app does not use it yet (phase 2: OIDC login + API Gateway JWT authorizer).
- The CI role has AdministratorAccess (TODO: scope down). `ampx pipeline-deploy` outside Amplify Console builds,
  `agentcore status --json` ARN parsing, and the AgentCore resource-policy command are untested.
- Never commit `terraform/backend.hcl`, `.build/`, `.agent_runtime_arn` (already in `.gitignore`).

## Tear down
`deletion_protection` is on for Aurora and Cognito. Disable it first, then `terraform destroy`; the AgentCore stack
`AgentCore-InterviewAgent-orientinternalai` and the Amplify Gen 2 stack are removed from CloudFormation.
