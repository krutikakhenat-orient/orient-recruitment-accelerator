# Start a backend release on the CodePipeline (normally a push to CodeCommit main does this).
#   .\release-api.ps1          release the current CodeCommit main if backend code changed
#   .\release-api.ps1 -Force   release even without a code change, e.g. after a local Terraform
#                              change to Lambda configuration (env vars, memory, timeout): the new
#                              configuration only reaches live traffic when a new version is published.
param(
    [switch]$Force,
    [string]$Profile = "Orient_Internal_AI",
    [string]$Region = "ap-south-1",
    [string]$Pipeline = "ora-staging-backend"
)
$ErrorActionPreference = "Continue"
$env:AWS_PROFILE = $Profile

# Not "$force": PowerShell variable names are case-insensitive and would collide with the -Force switch.
$forceValue = if ($Force.IsPresent) { "true" } else { "false" }
$id = aws codepipeline start-pipeline-execution --name $Pipeline --region $Region `
    --variables "name=FORCE_RELEASE,value=$forceValue" --query pipelineExecutionId --output text
if ($LASTEXITCODE) { throw "Could not start $Pipeline (aws sso login --profile $Profile ?)" }
Write-Host "Started $Pipeline execution $id (FORCE_RELEASE=$forceValue)"
Write-Host "Watch: https://$Region.console.aws.amazon.com/codesuite/codepipeline/pipelines/$Pipeline/executions/$id/timeline?region=$Region"
Write-Host "It waits at Approve for your approval (email or console) before anything is deployed."
