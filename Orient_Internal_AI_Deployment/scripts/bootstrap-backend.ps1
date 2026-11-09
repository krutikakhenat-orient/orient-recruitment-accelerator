# One-time: create the encrypted, versioned S3 bucket that holds Terraform remote state,
# and write terraform\backend.hcl. State locking uses the S3 native lockfile (no DynamoDB).
param(
    [string]$Profile = "Orient_Internal_AI",
    [string]$Region = "ap-south-1"
)
$ErrorActionPreference = "Stop"
$env:AWS_PROFILE = $Profile

$account = (aws sts get-caller-identity --query Account --output text)
if ($LASTEXITCODE -ne 0) { throw "Not logged in. Run: aws sso login --profile $Profile" }
$bucket = "ora-tfstate-$account-$Region"

# Windows PowerShell 5.1 turns native stderr into a terminating error under "Stop"; relax it for this probe.
$ErrorActionPreference = "Continue"
aws s3api head-bucket --bucket $bucket 2>$null
$bucketMissing = ($LASTEXITCODE -ne 0)
$ErrorActionPreference = "Stop"
if ($bucketMissing) {
    aws s3api create-bucket --bucket $bucket --region $Region `
        --create-bucket-configuration LocationConstraint=$Region | Out-Null
    aws s3api put-public-access-block --bucket $bucket --public-access-block-configuration `
        "BlockPublicAcls=true,IgnorePublicAcls=true,BlockPublicPolicy=true,RestrictPublicBuckets=true"
    aws s3api put-bucket-versioning --bucket $bucket --versioning-configuration Status=Enabled
    # JSON passed via file: Windows PowerShell 5.1 strips quotes from inline JSON arguments.
    $enc = Join-Path ([IO.Path]::GetTempPath()) "ora_tfstate_enc.json"
    [IO.File]::WriteAllText($enc, '{"Rules":[{"ApplyServerSideEncryptionByDefault":{"SSEAlgorithm":"AES256"}}]}')
    aws s3api put-bucket-encryption --bucket $bucket --server-side-encryption-configuration "file://$enc"
    if ($LASTEXITCODE) { throw "put-bucket-encryption failed" }
    aws s3api put-bucket-tagging --bucket $bucket --tagging `
        'TagSet=[{Key=Project,Value=orient-recruitment-accelerator},{Key=Application,Value=Terraform State},{Key=Environment,Value=staging},{Key=Owner,Value=sumanpramanik@orientindia.net},{Key=CostCenter,Value=Orient_Internal_AI},{Key=ManagedBy,Value=script}]'
    Write-Host "Created state bucket $bucket"
} else { Write-Host "State bucket $bucket already exists" }

@"
bucket       = "$bucket"
key          = "hr-accelerator/staging/terraform.tfstate"
region       = "$Region"
profile      = "$Profile"
encrypt      = true
use_lockfile = true
"@ | Set-Content (Join-Path $PSScriptRoot "..\terraform\backend.hcl") -Encoding ascii
Write-Host "Wrote terraform\backend.hcl"
