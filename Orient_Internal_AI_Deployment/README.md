# Orient_Internal_AI deployment

Account `Orient_Internal_AI` (917511768830), region `ap-south-1`. Architecture: `docs/architecture-v2.md`.
Deployed resources: `docs/deployed-resources.md`. Backend release pipeline: `docs/backend-cicd-pipeline.md`.

## Who deploys what

| Part | How | Where | When |
|---|---|---|---|
| Infrastructure: API Gateway, Lambda config, Aurora (Data API), Secrets Manager, S3, IAM, Amplify app, CodeCommit | Terraform, **applied locally only** | `terraform/` | rarely, by hand |
| Release pipeline itself | Terraform, applied locally only | `terraform-pipeline/` | rarely, by hand |
| Backend **code** (`ora-staging-api`, `ora-staging-ops`) + DB migrations | CodePipeline `ora-staging-backend` | `pipeline/`, `buildspec/` | every push to CodeCommit `main`, after approval |
| Frontend (React SPA) + Cognito (Amplify Gen 2) | Amplify Hosting, repo-connected | `amplify.yml`, `amplify-backend/` | every push to CodeCommit `main` |
| Interview voice agent | AgentCore CLI (`@aws/agentcore`, CodeZip) | `scripts/deploy-agent.ps1` | by hand |

Git remotes: **CodeCommit** `orient-recruitment-accelerator` is the deployment source; GitHub `origin` is a backup.

All resources carry the cost tags Project, Application, Environment, Owner, CostCenter, ManagedBy.

## Everyday release
1. Push to CodeCommit `main`.
2. Amplify builds the frontend. The pipeline tests, scans and builds the backend; if backend code changed it emails
   the approvers and waits.
3. Approve in the email link or the CodePipeline console. The pipeline publishes the new Lambda version, migrates the
   database, tests the new version, switches the `live` alias and smoke-tests. It rolls back the alias by itself if
   the smoke test fails.

Manual: `scripts\release-api.ps1` (start a release; `-Force` after a Lambda configuration change),
`scripts\rollback-api.ps1` (point `live` at an earlier version in seconds).

## Infrastructure change (local)
```powershell
aws sso login --profile Orient_Internal_AI
cd Orient_Internal_AI_Deployment\terraform
terraform plan        # review
terraform apply
```
Changes to Lambda configuration (environment variables, memory, timeout) reach live traffic at the next release:
run `scripts\release-api.ps1 -Force`. `scripts\deploy.ps1` applies both Terraform roots in order.

## First-time setup of a new environment
1. `aws sso login --profile Orient_Internal_AI`
2. `scripts\deploy.ps1` (state bucket, app stack, pipeline). The Lambdas start with a placeholder that answers 503.
3. Confirm the SNS email subscription for release approvals.
4. Push to CodeCommit `main` and approve the first release. Seed synthetic users if needed:
   `aws lambda invoke --function-name ora-staging-ops --payload '{"action":"seed"}' ...`
5. Deploy the interview agent: `scripts\deploy-agent.ps1`, then set `agentcore_runtime_arn` in `terraform/` and apply.

## Never commit
`terraform/backend.hcl`, `.build/`, `.agent_runtime_arn`, any `*.tfstate`, `*.tfvars`, `*.env` (see `.gitignore`).

## Tear down
`deletion_protection` is on for Aurora and Cognito. Disable it first, then `terraform destroy` in
`terraform-pipeline/` and `terraform/`; remove the AgentCore stack `AgentCore-InterviewAgent-default` with the
AgentCore CLI and the Amplify Gen 2 stack from CloudFormation.
