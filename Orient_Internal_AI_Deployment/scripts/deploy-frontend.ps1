# Build the React app and publish it to Amplify Hosting as a manual (zip) deployment.
param(
    [string]$Profile = "Orient_Internal_AI",
    [string]$Region = "ap-south-1",
    [Parameter(Mandatory = $true)][string]$AppId,
    [string]$Branch = "main"
)
$ErrorActionPreference = "Stop"
$env:AWS_PROFILE = $Profile
$frontend = Resolve-Path (Join-Path $PSScriptRoot "..\..\frontend")

Push-Location $frontend
try {
    npm ci
    if ($LASTEXITCODE) { throw "npm ci failed" }
    npm run build
    if ($LASTEXITCODE) { throw "npm run build failed" }
}
finally { Pop-Location }

$zip = Join-Path $env:TEMP "ora_frontend.zip"
if (Test-Path $zip) { Remove-Item $zip -Force }
Compress-Archive -Path (Join-Path $frontend "dist\*") -DestinationPath $zip

$dep = aws amplify create-deployment --app-id $AppId --branch-name $Branch --region $Region | ConvertFrom-Json
Invoke-WebRequest -Uri $dep.zipUploadUrl -Method Put -InFile $zip -ContentType "application/zip" -UseBasicParsing | Out-Null
aws amplify start-deployment --app-id $AppId --branch-name $Branch --job-id $dep.jobId --region $Region | Out-Null
Write-Host "Amplify deployment started (job $($dep.jobId))"
