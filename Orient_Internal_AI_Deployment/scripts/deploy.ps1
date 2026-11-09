# Infrastructure deploy from a developer machine (Terraform is applied locally only).
#   1 state bucket (once) -> 2 app stack (terraform/) -> 3 release pipeline (terraform-pipeline/)
# Application CODE is not deployed here: push to CodeCommit main (or run release-api.ps1) and
# approve the release. The interview agent is deployed with deploy-agent.ps1.
# Usage: .\deploy.ps1 [-PlanOnly] [-SkipPipeline]
param(
    [string]$Profile = "Orient_Internal_AI",
    [string]$Region = "ap-south-1",
    [switch]$PlanOnly,
    [switch]$SkipPipeline
)
$ErrorActionPreference = "Continue"
$env:AWS_PROFILE = $Profile
$deployRoot = (Resolve-Path (Join-Path $PSScriptRoot "..")).Path
$app = Join-Path $deployRoot "terraform"
$pipe = Join-Path $deployRoot "terraform-pipeline"

aws sts get-caller-identity --query Account --output text | Out-Null
if ($LASTEXITCODE) { throw "Not logged in. Run: aws sso login --profile $Profile" }
if (-not (Test-Path (Join-Path $app "backend.hcl"))) { & (Join-Path $PSScriptRoot "bootstrap-backend.ps1") -Profile $Profile -Region $Region }

function Invoke-Terraform([string]$dir, [string[]]$initArgs) {
    terraform "-chdir=$dir" init -input=false @initArgs
    if ($LASTEXITCODE) { throw "terraform init failed in $dir" }
    if ($PlanOnly) { terraform "-chdir=$dir" plan -input=false; return }
    # Interactive: Terraform shows the plan and asks for "yes" before changing anything.
    terraform "-chdir=$dir" apply
    if ($LASTEXITCODE) { throw "terraform apply failed in $dir" }
}

Invoke-Terraform $app @("-backend-config=backend.hcl")
if (-not $SkipPipeline) {
    Invoke-Terraform $pipe @("-backend-config=$app\backend.hcl", "-backend-config=key=hr-accelerator/pipeline/terraform.tfstate")
}
Write-Host "Infrastructure done. Code: push to CodeCommit main, then approve the release (email / console)."
