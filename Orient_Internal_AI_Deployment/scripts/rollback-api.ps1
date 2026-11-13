# Roll the API back in seconds by pointing the `live` alias (API Gateway's target) at an earlier,
# already-published Lambda version. Code only: the database schema is not touched.
#   .\rollback-api.ps1              list versions and roll back to the one before the current
#   .\rollback-api.ps1 -Version 7   roll back (or forward) to version 7
#   .\rollback-api.ps1 -List        only list versions
#   .\rollback-api.ps1 -Env uat     same for UAT (default: prod)
param(
    [string]$Version = "",
    [switch]$List,
    [ValidateSet("prod", "uat")][string]$Env = "prod",
    [string]$Profile = "Orient_Internal_AI",
    [string]$Region = "ap-south-1",
    [string]$Alias = "live"
)
$ErrorActionPreference = "Continue"
$env:AWS_PROFILE = $Profile
$Function = @{ prod = "ora-staging-api"; uat = "ora-uat-api" }[$Env]
$ApiUrl = aws apigatewayv2 get-apis --region $Region --query "Items[?Name=='$($Function -replace '-api$','-http')'].ApiEndpoint | [0]" --output text
Write-Host "[$Env] function $Function, API $ApiUrl"

$current = aws lambda get-alias --function-name $Function --name $Alias --region $Region --query FunctionVersion --output text
if ($LASTEXITCODE) { throw "Could not read alias $Alias (aws sso login --profile $Profile ?)" }
$versions = (aws lambda list-versions-by-function --function-name $Function --region $Region --output json | ConvertFrom-Json).Versions |
    Where-Object { $_.Version -ne '$LATEST' } | Sort-Object { [int]$_.Version }

Write-Host "Alias $Alias -> version $current"
$versions | Select-Object -Last 10 | ForEach-Object {
    $mark = if ($_.Version -eq $current) { "*" } else { " " }
    Write-Host ("{0} v{1,-4} {2,-22} {3}" -f $mark, $_.Version, $_.LastModified.Substring(0, 19), $_.Description)
}
if ($List) { return }

if (-not $Version) {
    $older = $versions | Where-Object { [int]$_.Version -lt [int]$current } | Select-Object -Last 1
    if (-not $older) { throw "No earlier published version than $current" }
    $Version = $older.Version
}
if ($Version -eq $current) { Write-Host "Already on version $Version"; return }

aws lambda update-alias --function-name $Function --name $Alias --function-version $Version `
    --description "manual rollback from $current" --region $Region | Out-Null
if ($LASTEXITCODE) { throw "update-alias failed" }
Write-Host "Alias $Alias -> version $Version (was $current)"

try {
    $code = (Invoke-WebRequest "$ApiUrl/health" -UseBasicParsing -TimeoutSec 60).StatusCode
} catch { $code = [int]$_.Exception.Response.StatusCode }
Write-Host "GET /health -> $code"
Write-Host "Note: the next pipeline release moves the alias forward again. Revert or fix the bad commit first."
