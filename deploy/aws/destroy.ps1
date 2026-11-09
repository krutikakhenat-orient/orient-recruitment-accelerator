# Remove the whole trial stack (CloudFront, Lambda, Aurora, buckets) so nothing keeps billing.
#   .\destroy.ps1 -Profile OTL_GenAi
param(
    [Parameter(Mandatory = $true)][string]$Profile,
    [string]$Region = "ap-south-1"
)
$ErrorActionPreference = "Stop"
$env:AWS_PROFILE = $Profile
$env:AWS_DEFAULT_REGION = $Region
$env:CDK_DEFAULT_REGION = $Region
$id = aws sts get-caller-identity --output json | ConvertFrom-Json
$env:CDK_DEFAULT_ACCOUNT = $id.Account
Write-Host "This DELETES stack OraTrial (database included) in account $($id.Account), $Region."
if ((Read-Host "Type 'destroy' to continue") -ne "destroy") { Write-Host "Cancelled."; exit 1 }
Push-Location $PSScriptRoot
try { cdk destroy OraTrial --force } finally { Pop-Location }
