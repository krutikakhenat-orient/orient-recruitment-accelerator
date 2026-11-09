# Deploy the interview voice agent to AgentCore (Orient_Internal_AI account) with the npm AgentCore CLI
# (@aws/agentcore, CodeZip, no Docker), straight from interview-agent/InterviewAgent.
# Target account/region: interview-agent/InterviewAgent/agentcore/aws-targets.json ("default").
# The webhook HMAC secret is taken from Terraform (shared with the API) and passed via the environment,
# so it is never written to agentcore.json. Writes the runtime ARN to ..\.agent_runtime_arn.
param([string]$Profile = "Orient_Internal_AI")
# "Continue": Windows PowerShell 5.1 turns native stderr into terminating errors under "Stop".
$ErrorActionPreference = "Continue"
$env:AWS_PROFILE = $Profile
$deployRoot = (Resolve-Path (Join-Path $PSScriptRoot "..")).Path
$project = (Resolve-Path (Join-Path $deployRoot "..\interview-agent\InterviewAgent")).Path

aws sts get-caller-identity --query Account --output text | Out-Null
if ($LASTEXITCODE) { throw "Not logged in: aws sso login --profile $Profile" }

$env:INTERVIEW_AGENT_WEBHOOK_SECRET = (terraform "-chdir=$deployRoot\terraform" output -raw webhook_secret)
if ($LASTEXITCODE -or -not $env:INTERVIEW_AGENT_WEBHOOK_SECRET) { throw "Could not read webhook_secret from Terraform" }

Push-Location $project
try {
    agentcore validate
    if ($LASTEXITCODE) { throw "agentcore validate failed" }
    agentcore deploy --target default --yes
    if ($LASTEXITCODE) { throw "agentcore deploy failed" }
    $status = (agentcore status --json 2>&1 | Out-String)
    $m = [regex]::Match($status, 'arn:aws:bedrock-agentcore:[a-z0-9-]+:\d{12}:runtime/[A-Za-z0-9_-]+')
    if (-not $m.Success) { throw "Runtime ARN not found in 'agentcore status --json'" }
    [IO.File]::WriteAllText((Join-Path $deployRoot ".agent_runtime_arn"), $m.Value)
    Write-Host "Runtime ARN: $($m.Value)"
}
finally {
    Pop-Location
    Remove-Item Env:\INTERVIEW_AGENT_WEBHOOK_SECRET -ErrorAction SilentlyContinue
}
