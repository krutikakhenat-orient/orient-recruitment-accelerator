# Deploy the serverless HR trial to AWS.
#   .\deploy.ps1 -Profile OTL_GenAi [-Region ap-south-1] [-VideoPath C:\path\induction.mp4]
# Idempotent: safe to re-run for updates. Secrets are generated once into .secrets.json
# (git-ignored) and reused. Requires: AWS CLI, CDK CLI, Python (aws-cdk-lib), Node.
param(
    [Parameter(Mandatory = $true)][string]$Profile,
    [string]$Region = "ap-south-1",
    [string]$VideoPath = "",
    [switch]$SkipBuild   # reuse the existing build\lambda and frontend\dist (config-only changes)
)
$ErrorActionPreference = "Stop"
$here = $PSScriptRoot
$root = Resolve-Path (Join-Path $here "..\..")
$env:AWS_PROFILE = $Profile
$env:AWS_DEFAULT_REGION = $Region
$env:CDK_DEFAULT_REGION = $Region

function Step($m) { Write-Host "`n==> $m" -ForegroundColor Cyan }
function Run-Aws { & aws @args; if ($LASTEXITCODE -ne 0) { throw "aws $($args -join ' ') failed" } }

Step "Verifying AWS identity ($Profile)"
$id = aws sts get-caller-identity --output json | ConvertFrom-Json
if (-not $id.Account) { throw "Not logged in. Run: aws sso login --profile $Profile" }
$env:CDK_DEFAULT_ACCOUNT = $id.Account
Write-Host "Account $($id.Account) in $Region as $($id.Arn)"

Step "Preparing secrets (.secrets.json, git-ignored)"
$secretsFile = Join-Path $here ".secrets.json"
function New-Secret([int]$n) {
    $chars = (48..57) + (65..90) + (97..122)
    -join (1..$n | ForEach-Object { [char]($chars | Get-Random) })
}
if (Test-Path $secretsFile) { $secrets = Get-Content $secretsFile -Raw | ConvertFrom-Json }
else {
    $secrets = [pscustomobject]@{
        DbPassword   = New-Secret 28
        JwtSecret    = New-Secret 64
        SeedPassword = "Trial" + (New-Secret 12) + "9"
        AppBaseUrl   = ""
    }
    $secrets | ConvertTo-Json | Set-Content $secretsFile
}

if (-not $SkipBuild) {
    Step "Building Lambda package"
    & (Join-Path $here "build_lambda.ps1")

    Step "Building frontend"
    Push-Location (Join-Path $root "frontend")
    try { npm ci --silent 2>&1 | Out-Null; npm run build --silent; if ($LASTEXITCODE -ne 0) { throw "frontend build failed" } }
    finally { Pop-Location }
} else { Write-Host "Skipping builds (-SkipBuild)" }

Push-Location $here
try {
    function Deploy-Stack {
        $ctx = @()
        if ($secrets.AppBaseUrl) { $ctx = @("-c", "app_base_url=$($secrets.AppBaseUrl)") }
        cdk deploy OraTrial --require-approval never --outputs-file cdk-outputs.json @ctx `
            --parameters "DbPassword=$($secrets.DbPassword)" `
            --parameters "JwtSecret=$($secrets.JwtSecret)" `
            --parameters "SeedPassword=$($secrets.SeedPassword)"
        if ($LASTEXITCODE -ne 0) { throw "cdk deploy failed" }
    }

    Step "Deploying stack OraTrial (Aurora + Lambda + CloudFront; first run takes ~10-15 min)"
    Deploy-Stack
    $out = (Get-Content (Join-Path $here "cdk-outputs.json") -Raw | ConvertFrom-Json).OraTrial

    if ($secrets.AppBaseUrl -ne $out.SiteUrl) {
        Step "Second pass: give the API its public site URL"
        $secrets.AppBaseUrl = $out.SiteUrl
        $secrets | ConvertTo-Json | Set-Content $secretsFile
        Deploy-Stack
        $out = (Get-Content (Join-Path $here "cdk-outputs.json") -Raw | ConvertFrom-Json).OraTrial
    }
}
finally { Pop-Location }

Step "Uploading induction video (if provided)"
if (-not $VideoPath) {
    $sample = Join-Path $root "backend\local_dev_objectstore\_sample\sample-induction.mp4"
    if (Test-Path $sample) { $VideoPath = $sample }
}
if ($VideoPath -and (Test-Path $VideoPath)) {
    Run-Aws s3 cp $VideoPath "s3://$($out.FilesBucketName)/_seed/induction-video.mp4" --only-show-errors
    Write-Host "Video uploaded from $VideoPath"
} else { Write-Host "No video file found - the blank placeholder video will be used." }

Step "Running migrations + seeding synthetic data (first request may wake the paused database)"
$payload = Join-Path $env:TEMP "ora_ops_event.json"
'{"action":"migrate_and_seed"}' | Set-Content $payload -NoNewline -Encoding ascii
$result = Join-Path $env:TEMP "ora_ops_result.json"
Run-Aws lambda invoke --function-name $out.OpsFunctionName --payload "fileb://$payload" `
    --cli-read-timeout 900 --output json $result | Out-Null
$r = Get-Content $result -Raw
Write-Host "Ops result: $r"
if ($r -match "errorMessage") { throw "Migration/seed failed - see the ops Lambda logs in CloudWatch" }

Step "Smoke test"
$health = Invoke-RestMethod "$($out.ApiUrl)/health" -TimeoutSec 60
Write-Host "API /health -> $($health | ConvertTo-Json -Compress)" -ForegroundColor Green
$ready = Invoke-RestMethod "$($out.ApiUrl)/ready" -TimeoutSec 60
Write-Host "API /ready  -> $($ready | ConvertTo-Json -Compress)" -ForegroundColor Green
$site = Invoke-WebRequest $out.SiteUrl -UseBasicParsing -TimeoutSec 60
Write-Host "Site        -> HTTP $($site.StatusCode)" -ForegroundColor Green
$body = @{ email = "synthetic.employee@example.com"; password = $secrets.SeedPassword } | ConvertTo-Json
$login = Invoke-RestMethod "$($out.SiteUrl)/api/v1/auth/login" -Method Post -ContentType "application/json" -Body $body -TimeoutSec 60
if (-not $login.access_token) { throw "Login through CloudFront failed" }
Write-Host "Login via CloudFront -> OK" -ForegroundColor Green

Write-Host "`nDONE." -ForegroundColor Green
Write-Host "Site URL : $($out.SiteUrl)"
Write-Host "Login    : synthetic.recruiter_admin@example.com  (also synthetic.<role>@example.com, e.g. synthetic.employee@example.com)"
Write-Host "Password : stored in $secretsFile (SeedPassword)"
