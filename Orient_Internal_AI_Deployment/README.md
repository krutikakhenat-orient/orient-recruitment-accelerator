# Orient_Internal_AI deployment

Account `Orient_Internal_AI` (917511768830), region `ap-south-1`. Architecture: `docs/architecture-v2.md`.
Deployed resources: `docs/deployed-resources.md`. Backend release pipeline: `docs/backend-cicd-pipeline.md`.

## Environments

| | UAT | Production |
|---|---|---|
| Git branch | `develop` | `main` |
| Web app | https://develop.dtenlsz7vp8yv.amplifyapp.com (Amplify app `ora-uat-web`) | https://main.d34zadd4sik8o2.amplifyapp.com (`ora-staging-web`) |
| API | https://soqus6ksfg.execute-api.ap-south-1.amazonaws.com | https://2psjcbnlvk.execute-api.ap-south-1.amazonaws.com |
| Resources | `ora-uat-*` (own Aurora, Lambdas, buckets, Cognito, secrets) | `ora-staging-*` (historical prefix; this IS production) |
| Data | **synthetic only**; never copy production candidate data here | real |
| Terraform | `scripts\tf.ps1 uat plan|apply` (state `hr-accelerator/uat/...`) | `scripts\tf.ps1 prod plan|apply` (state `hr-accelerator/staging/...`) |
| AI interview | off (no UAT agent runtime yet) | on |

## Who deploys what

| Part | How | Where | When |
|---|---|---|---|
| Infrastructure (both environments) | Terraform, **applied locally only**, one environment at a time | `terraform/` + `terraform/env/*.tfvars`, via `scripts\tf.ps1` | rarely, UAT first |
| Release pipeline itself | Terraform, applied locally only | `terraform-pipeline/` | rarely, by hand |
| Backend **code** + DB migrations, UAT then production | CodePipeline `ora-release` | `pipeline/`, `buildspec/` | every push to `develop`; production after approval |
| Frontend + Cognito, UAT | Amplify app `ora-uat-web` | `amplify.yml`, `amplify-backend/` | every push to `develop` |
| Frontend + Cognito, production | Amplify app `ora-staging-web` | same | when the pipeline promotes `main` |
| Interview voice agent | AgentCore CLI (`@aws/agentcore`, CodeZip) | `scripts/deploy-agent.ps1` | by hand |

Git remotes: **CodeCommit** `orient-recruitment-accelerator` is the deployment source; GitHub `origin` is a backup.

All resources carry the cost tags Project, Application, Environment, Owner, CostCenter, ManagedBy.

## Everyday release (UAT -> production)
1. Merge your feature branch into `develop` and push to CodeCommit. **Never push to `main` directly**: the pipeline
   moves `main`.
2. Automatically: the UAT frontend builds (Amplify), and `ora-release` tests, scans and builds the backend **once**,
   then releases it to UAT (publish version, migrate, test, switch alias, smoke test, roll back on failure).
3. Test in UAT. The pipeline waits at **Approve** and emails the approvers with the UAT link.
4. Approve: the **same package** is released to production, then `main` is fast-forwarded to the same commit and
   Amplify builds the production frontend from it. Reject: nothing reaches production.
5. Commits that change no backend code skip the deploy stages but still need approval, because their frontend
   reaches production through the `main` promotion.

Rules: production only ever receives a commit that ran in UAT; `main` is only fast-forwarded (never forced), so a
direct change to `main` makes the promotion fail until the branches are reconciled. Migrations must keep the previous
version working (expand / contract) because code rolls back in seconds and the schema does not.

Manual: `scripts\release-api.ps1` (start a release of current `develop`; `-Force` after a Lambda configuration
change), `scripts\rollback-api.ps1 [-Env uat]` (point `live` at an earlier version in seconds).

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
