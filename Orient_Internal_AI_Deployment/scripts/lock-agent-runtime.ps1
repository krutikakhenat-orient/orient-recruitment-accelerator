# Restrict who can invoke the interview AgentCore runtime (IAM/SigV4 inbound auth):
# only the API Lambda role (plus optional extra admin principals) may call it; everyone else is denied,
# even if their own IAM policy allows it. The runtime must use IAM auth (a runtime supports IAM OR JWT, not both).
# Requires an AWS CLI that has `bedrock-agentcore-control put-resource-policy` (update the CLI if missing).
param(
    [Parameter(Mandatory = $true)][string]$RuntimeArn,
    [Parameter(Mandatory = $true)][string]$ApiLambdaRoleArn,
    [string[]]$ExtraAllowedPrincipalArns = @(),
    [string]$Profile = "Orient_Internal_AI",
    [string]$Region = "ap-south-1"
)
$ErrorActionPreference = "Stop"
$env:AWS_PROFILE = $Profile
$allowed = @($ApiLambdaRoleArn) + $ExtraAllowedPrincipalArns
$actions = @("bedrock-agentcore:InvokeAgentRuntime", "bedrock-agentcore:InvokeAgentRuntimeWithWebSocketStream")

$policy = @{
    Version   = "2012-10-17"
    Statement = @(
        @{ Sid = "AllowApiAndAdmins"; Effect = "Allow"; Principal = @{ AWS = $allowed }; Action = $actions; Resource = $RuntimeArn },
        @{
            Sid = "DenyEveryoneElse"; Effect = "Deny"; Principal = @{ AWS = "*" }; Action = $actions; Resource = $RuntimeArn
            Condition = @{ ArnNotEquals = @{ "aws:PrincipalArn" = $allowed } }
        },
        # No user-id delegation: not needed, and the header is not verified against an identity.
        @{
            Sid = "DenyUserIdDelegation"; Effect = "Deny"; Principal = @{ AWS = "*" }; Resource = $RuntimeArn
            Action = @("bedrock-agentcore:InvokeAgentRuntimeForUser", "bedrock-agentcore:InvokeAgentRuntimeWithWebSocketStreamForUser")
        }
    )
} | ConvertTo-Json -Depth 8

$file = Join-Path $env:TEMP "ora_agent_policy.json"
[IO.File]::WriteAllText($file, $policy)
aws bedrock-agentcore-control put-resource-policy --resource-arn $RuntimeArn --policy "file://$file" --region $Region
if ($LASTEXITCODE) { throw "put-resource-policy failed (update the AWS CLI if the command is unknown)" }
Write-Host "Runtime locked to: $($allowed -join ', ')"
