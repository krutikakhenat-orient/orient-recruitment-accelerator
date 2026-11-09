# Deploy the Amplify Gen 2 backend (Cognito) from frontend/amplify into the Terraform-created Amplify app/branch.
param(
    [string]$Profile = "Orient_Internal_AI",
    [string]$Region = "ap-south-1",
    [Parameter(Mandatory = $true)][string]$AppId,
    [string]$Branch = "main"
)
$ErrorActionPreference = "Stop"
if ($Profile) { $env:AWS_PROFILE = $Profile }
$env:AWS_REGION = $Region
$env:AWS_DEFAULT_REGION = $Region
$frontend = Resolve-Path (Join-Path $PSScriptRoot "..\..\frontend")

Push-Location $frontend
try {
    npm ci --no-audit --no-fund
    if ($LASTEXITCODE) { throw "npm ci failed" }
    npx ampx pipeline-deploy --branch $Branch --app-id $AppId
    if ($LASTEXITCODE) { throw "ampx pipeline-deploy failed" }
}
finally { Pop-Location }
Write-Host "Amplify Gen 2 backend deployed for app $AppId, branch $Branch"
