# Deploy the interview voice agent to AgentCore in the Orient_Internal_AI account with the AgentCore CLI
# (@aws/agentcore, CodeZip, no Docker). The existing project (interview-agent/InterviewAgent) is copied to
# a staging folder so its original OTL_GenAi target and tags are NOT modified; the copy gets this account's
# deployment target and cost-allocation tags.
# Output: writes the runtime ARN to Orient_Internal_AI_Deployment\.agent_runtime_arn
# Cross-platform PowerShell (works on Windows and the GitHub ubuntu runner).
param(
    [string]$Profile = "Orient_Internal_AI",
    [string]$Region = "ap-south-1",
    [string]$Environment = "staging"
)
$ErrorActionPreference = "Stop"
if ($Profile) { $env:AWS_PROFILE = $Profile }

$deployRoot = Resolve-Path (Join-Path $PSScriptRoot "..")
$repoRoot = Resolve-Path (Join-Path $deployRoot "..")
$srcProject = Join-Path $repoRoot "interview-agent\InterviewAgent"
$srcCode = Join-Path $repoRoot "interview-agent\src"
$stage = Join-Path $deployRoot ".build\agent"

$account = (aws sts get-caller-identity --query Account --output text)
if ($LASTEXITCODE) { throw "AWS credentials not available (aws sso login --profile $Profile)" }

# --- stage a clean copy (project root keeps the ../src layout the runtime codeLocation expects)
if (Test-Path $stage) { Remove-Item $stage -Recurse -Force }
New-Item -ItemType Directory -Force (Join-Path $stage "InterviewAgent") | Out-Null
$skip = @("node_modules", ".cache", "cdk.out", "__pycache__", ".venv")
function Copy-Filtered($from, $to) {
    New-Item -ItemType Directory -Force $to | Out-Null
    Get-ChildItem $from -Force | Where-Object { $skip -notcontains $_.Name -and $_.Name -notin @(".env.local", "interview_agent.zip") } | ForEach-Object {
        if ($_.PSIsContainer) { Copy-Filtered $_.FullName (Join-Path $to $_.Name) }
        else { Copy-Item $_.FullName (Join-Path $to $_.Name) }
    }
}
Copy-Filtered $srcProject (Join-Path $stage "InterviewAgent")
Copy-Filtered $srcCode (Join-Path $stage "src")

# --- point the staged copy at this account and tag it for cost allocation
$agentcoreDir = Join-Path $stage "InterviewAgent\agentcore"
$targets = @(@{ name = "orientinternalai"; description = "Orient_Internal_AI account"; account = $account; region = $Region })
ConvertTo-Json -InputObject $targets -Depth 5 | Set-Content (Join-Path $agentcoreDir "aws-targets.json") -Encoding utf8

$specPath = Join-Path $agentcoreDir "agentcore.json"
$spec = Get-Content $specPath -Raw | ConvertFrom-Json
$spec.tags.Environment = $Environment
$spec.tags.CostCenter = "Orient_Internal_AI"
$spec.tags.ManagedBy = "agentcore-cli"
foreach ($rt in $spec.runtimes) {
    foreach ($e in $rt.envVars) {
        if ($e.name -eq "INTERVIEW_AGENT_ENVIRONMENT") { $e.value = $Environment }
        if ($e.name -eq "INTERVIEW_AGENT_AWS_REGION") { $e.value = $Region }
    }
}
$spec | ConvertTo-Json -Depth 20 | Set-Content $specPath -Encoding utf8

Push-Location (Join-Path $stage "InterviewAgent")
try {
    # CDK bootstrap (once per account/region)
    aws cloudformation describe-stacks --stack-name CDKToolkit --region $Region --query "Stacks[0].StackStatus" --output text 2>$null | Out-Null
    if ($LASTEXITCODE) {
        Push-Location "agentcore\cdk"
        npm install --no-audit --no-fund
        npx cdk bootstrap "aws://$account/$Region"
        if ($LASTEXITCODE) { throw "cdk bootstrap failed" }
        Pop-Location
    }

    agentcore validate
    if ($LASTEXITCODE) { throw "agentcore validate failed" }
    agentcore deploy --target orientinternalai --yes
    if ($LASTEXITCODE) { throw "agentcore deploy failed" }

    $status = (agentcore status --json | Out-String)
    $m = [regex]::Match($status, 'arn:aws:bedrock-agentcore:[a-z0-9-]+:\d{12}:runtime/[A-Za-z0-9_-]+')
    if (-not $m.Success) { throw "Could not find the runtime ARN in 'agentcore status --json' output" }
    Set-Content (Join-Path $deployRoot ".agent_runtime_arn") $m.Value -NoNewline
    Write-Host "Runtime ARN: $($m.Value)"
}
finally { Pop-Location }
