# Backend update: build the Lambda package, then terraform apply (updates the api/ops Lambdas and any
# infrastructure change), then run DB migrations through the ops Lambda.
param([string]$Profile = "Orient_Internal_AI", [string]$Region = "ap-south-1")
$ErrorActionPreference = "Continue"
$env:AWS_PROFILE = $Profile
$deployRoot = (Resolve-Path (Join-Path $PSScriptRoot "..")).Path

& (Join-Path $PSScriptRoot "build-lambda.ps1")
if (-not (Test-Path (Join-Path $deployRoot ".build\lambda\app"))) { throw "Lambda build failed" }

terraform "-chdir=$deployRoot\terraform" apply -input=false -auto-approve
if ($LASTEXITCODE) { throw "terraform apply failed" }

$payload = Join-Path ([IO.Path]::GetTempPath()) "ora_migrate.json"
$resp = Join-Path ([IO.Path]::GetTempPath()) "ora_migrate_resp.json"
[IO.File]::WriteAllText($payload, '{"action":"migrate"}')
aws lambda invoke --function-name ora-staging-ops --region $Region --cli-binary-format raw-in-base64-out `
    --cli-read-timeout 900 --payload "file://$payload" $resp | Out-Null
Write-Host ("migrate: " + (Get-Content $resp -Raw))
Remove-Item $payload, $resp -ErrorAction SilentlyContinue
Write-Host "DEPLOY-API DONE"
