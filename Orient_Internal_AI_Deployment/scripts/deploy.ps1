# Full v2 deploy from a developer machine (CI runs the same steps, see .github/workflows):
#   1 AgentCore agent (agentcore CLI) -> 2 Lambda package -> 3 Terraform -> 4 lock agent runtime
#   -> 5 DB migrations -> 6 Amplify Gen 2 backend (Cognito) -> 7 frontend to Amplify Hosting.
# Usage: .\deploy.ps1 [-Seed] [-SkipAgent] [-PlanOnly]
param(
    [string]$Profile = "Orient_Internal_AI",
    [string]$Region = "ap-south-1",
    [switch]$Seed,
    [switch]$SkipAgent,
    [switch]$PlanOnly
)
$ErrorActionPreference = "Stop"
$env:AWS_PROFILE = $Profile
$here = $PSScriptRoot
$deployRoot = Resolve-Path (Join-Path $here "..")
$root = Resolve-Path (Join-Path $deployRoot "..")
$tf = Join-Path $deployRoot "terraform"
$arnFile = Join-Path $deployRoot ".agent_runtime_arn"

aws sts get-caller-identity --query Account --output text | Out-Null
if ($LASTEXITCODE) { throw "Not logged in. Run: aws sso login --profile $Profile" }

if (-not (Test-Path (Join-Path $tf "backend.hcl"))) { & (Join-Path $here "bootstrap-backend.ps1") -Profile $Profile -Region $Region }

# 1. AgentCore agent
if (-not $SkipAgent) { & (Join-Path $here "deploy-agent.ps1") -Profile $Profile -Region $Region }
$agentArn = if (Test-Path $arnFile) { (Get-Content $arnFile -Raw).Trim() } else { "" }

# 2. Lambda package: backend + Data API dialect (pure-Python wheels)
& (Join-Path $here "build-lambda.ps1")

# 3. Terraform
Push-Location $tf
try {
    terraform init -input=false "-backend-config=backend.hcl"
    if ($LASTEXITCODE) { throw "terraform init failed" }
    $vars = @("-var", "region=$Region", "-var", "aws_profile=$Profile")
    # GitHub repo (owner/name) allowed to deploy through OIDC, taken from the git remote.
    $remote = (git -C $root remote get-url origin 2>$null)
    # Handles https://github.com/o/r.git and ssh host aliases such as git@github-work:o/r.git
    if ($remote -match '[:/](?<repo>[^/:]+/[^/]+?)(\.git)?$') { $vars += @("-var", "github_repo=$($Matches.repo)") }
    if ($agentArn) { $vars += @("-var", "agentcore_runtime_arn=$agentArn") }
    $urlFile = Join-Path $tf ".app_base_url"
    if (Test-Path $urlFile) { $vars += @("-var", "app_base_url=$((Get-Content $urlFile -Raw).Trim())") }

    if ($PlanOnly) { terraform plan -input=false @vars; return }
    terraform apply -input=false -auto-approve @vars
    if ($LASTEXITCODE) { throw "terraform apply failed" }

    $out = terraform output -json | ConvertFrom-Json
    # The Amplify URL is only known after the first apply; feed it back for CORS / app base URL.
    if (-not (Test-Path $urlFile) -or (Get-Content $urlFile -Raw).Trim() -ne $out.amplify_url.value) {
        Set-Content $urlFile $out.amplify_url.value -NoNewline
        $vars = @("-var", "region=$Region", "-var", "aws_profile=$Profile", "-var", "app_base_url=$($out.amplify_url.value)")
        if ($agentArn) { $vars += @("-var", "agentcore_runtime_arn=$agentArn") }
        terraform apply -input=false -auto-approve @vars
        if ($LASTEXITCODE) { throw "terraform second apply failed" }
    }
}
finally { Pop-Location }

# 4. Restrict who may invoke the agent runtime to the API Lambda role.
#    To keep your own admin/test access, pass the IAM ROLE ARN (not the sts session ARN) of your SSO role via
#    -ExtraAllowedPrincipalArns when running scripts\lock-agent-runtime.ps1 by hand.
if ($agentArn) {
    & (Join-Path $here "lock-agent-runtime.ps1") -RuntimeArn $agentArn -ApiLambdaRoleArn $out.api_lambda_role_arn.value `
        -Profile $Profile -Region $Region
}

# 5. Database migrations (and optional synthetic seed). Aurora may need ~30 s to resume from pause.
$action = if ($Seed) { "migrate_and_seed" } else { "migrate" }
$payload = Join-Path ([IO.Path]::GetTempPath()) "ora_ops_payload.json"
$resp = Join-Path ([IO.Path]::GetTempPath()) "ora_ops_response.json"
[IO.File]::WriteAllText($payload, "{`"action`":`"$action`"}")
aws lambda invoke --function-name $out.ops_function_name.value --region $Region `
    --cli-binary-format raw-in-base64-out --cli-read-timeout 900 --payload "file://$payload" $resp | Out-Null
Get-Content $resp

# 6. Amplify Gen 2 backend (Cognito)   7. Frontend
& (Join-Path $here "deploy-amplify-backend.ps1") -Profile $Profile -Region $Region -AppId $out.amplify_app_id.value
& (Join-Path $here "deploy-frontend.ps1") -Profile $Profile -Region $Region -AppId $out.amplify_app_id.value
Write-Host "`nApp URL: $($out.amplify_url.value)`nAPI URL: $($out.api_url.value)"
