# Deployed resources: account 917511768830 (Orient_Internal_AI), ap-south-1

Snapshot taken 9 Nov 2026 from `terraform state list` and CloudFormation. Prefix `ora-staging-`.

## App URLs
| What | URL / ID |
|---|---|
| Web app (Amplify Hosting) | https://main.d34zadd4sik8o2.amplifyapp.com |
| API (API Gateway HTTP API) | https://2psjcbnlvk.execute-api.ap-south-1.amazonaws.com |
| Source repo (CodeCommit) | `orient-recruitment-accelerator` (GitHub `origin` = backup) |

## 1. Terraform-managed (state: `s3://ora-tfstate-917511768830-ap-south-1/hr-accelerator/staging/terraform.tfstate`)

| Service | Resource | Purpose |
|---|---|---|
| Amplify | App `ora-staging-web` (`d34zadd4sik8o2`), branch `main` | Hosts the React SPA, builds from CodeCommit on every push, `/api/*` rewrite to API Gateway |
| IAM | Role `ora-staging-amplify-service` (+ `AmplifyBackendDeployFullAccess`, CodeCommit pull policy) | Lets Amplify pull the repo and deploy the Gen 2 backend |
| CodeCommit | Repo `orient-recruitment-accelerator` | Deployment source |
| API Gateway | HTTP API `ora-staging-http`, integration, route `ANY /{proxy+}`, stage `$default` | Only entry to the API Lambda; 50 rps / burst 100; access logs |
| Lambda | `ora-staging-api` (Python 3.12, 1024 MB, 29 s, no VPC) | FastAPI backend |
| Lambda | `ora-staging-ops` (15 min, IAM invoke only) | Migrations / seed |
| Lambda | Permission `AllowApiGatewayInvoke` | Only API Gateway may invoke `api` |
| IAM | Role `ora-staging-lambda` (+ basic logging, inline `app-access`) | S3 files, Data API on this cluster, DB secret, SES send |
| RDS | Aurora Serverless v2 cluster `ora-staging-db` (PostgreSQL 16.8, 0-2 ACU, auto-pause, Data API on, encrypted, deletion protection, 7-day backups) + instance `ora-staging-db-1` | Application database |
| RDS / VPC | DB subnet group, VPC `10.40.0.0/16`, 2 subnets, security group (no inbound rules) | Network placement for Aurora only; no internet gateway, no NAT |
| Secrets Manager | `ora-staging/db-credentials` | DB credentials used by the Data API |
| S3 | `ora-staging-files-917511768830` (private, encrypted, TLS-only) | Resumes, JDs, induction video |
| S3 | `ora-staging-artifacts-917511768830` (private, encrypted) + Lambda zip object | Lambda deployment package |
| CloudWatch Logs | `/aws/lambda/ora-staging-api`, `/aws/lambda/ora-staging-ops`, `/aws/apigateway/ora-staging-http` (30 days) | Logs |
| (Terraform only) | `random_password` db, jwt, webhook, seed | Generated secrets, stored in Terraform state |

## 2. Amplify Gen 2 backend (CloudFormation, deployed by the Amplify build)
Stacks `amplify-d34zadd4sik8o2-main-branch-9883a66c73` and nested `...-auth179371D7-...`:

| Service | Resource |
|---|---|
| Cognito | User pool `ap-south-1_G8u0ELZhD` (email sign-in, MFA off, admin-created users only, deletion protection) |
| Cognito | App client `1puef4koitu3ddvc53p4p892mh` |
| Cognito | Identity pool `ap-south-1:237ea499-8a62-4ea0-bea1-832860050bf7` + role attachment |
| Cognito | 8 groups: HRHead, RecruitmentAdmin, Recruiter, HiringManager, PanelMember, ManagementViewer, AuditViewer, SystemAdmin |
| IAM | 10 roles (one per group + authenticated + unauthenticated) |
| Lambda | 2 `AmplifyBranchLinkerCustom...` functions (Amplify-internal) |

**Not used by the app yet.** Login is the app's own (Aurora `app_user` table + JWT).

## 3. Bootstrap / supporting
| Resource | Created by |
|---|---|
| S3 `ora-tfstate-917511768830-ap-south-1` (versioned, encrypted, private) | `scripts/bootstrap-backend.ps1` |
| CloudFormation `CDKToolkit`: S3 `cdk-hnb659fds-assets-...`, ECR `cdk-hnb659fds-container-assets-...`, 5 IAM roles, 2 policies, SSM parameter | `cdk bootstrap` (needed by Amplify Gen 2 and AgentCore) |

## 4. Database contents
55 tables, migrated to `0012_long_term_automation`. Seeded: 1 synthetic organisation, roles, 7 synthetic staff users, sample policies, placeholder induction video.

## Not deployed
- AgentCore interview agent (AI interview feature off)
- AWS WAF, SES sender identity, Cognito JWT authorizer on API Gateway

## Cost-tag gaps
Tagged with `Project=orient-recruitment-accelerator` + 5 other tags: all Terraform resources, Cognito, CDKToolkit, state bucket.
Missing the `Project` tag (Amplify-managed): the parent Amplify CloudFormation stack and the 2 `AmplifyBranchLinkerCustom` Lambdas. Their cost is negligible.
