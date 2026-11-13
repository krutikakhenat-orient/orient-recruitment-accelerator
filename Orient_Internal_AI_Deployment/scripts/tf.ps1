# Run Terraform for ONE environment with its own state and settings, so UAT settings can never be
# applied to production by accident.
#   .\tf.ps1 uat plan
#   .\tf.ps1 prod apply
#   .\tf.ps1 uat output -raw amplify_url
param(
    [Parameter(Mandatory = $true, Position = 0)][ValidateSet("uat", "prod")][string]$Env,
    [Parameter(Position = 1, ValueFromRemainingArguments = $true)][string[]]$TfArgs,
    [string]$Profile = "Orient_Internal_AI"
)
$ErrorActionPreference = "Continue"
$env:AWS_PROFILE = $Profile
$dir = (Resolve-Path (Join-Path $PSScriptRoot "..\terraform")).Path
$stateKey = @{ prod = "hr-accelerator/staging/terraform.tfstate"; uat = "hr-accelerator/uat/terraform.tfstate" }[$Env]

# Separate working data per environment (provider cache + backend binding).
$env:TF_DATA_DIR = Join-Path $dir ".terraform-$Env"
if (-not (Test-Path (Join-Path $env:TF_DATA_DIR "terraform.tfstate"))) {
    terraform "-chdir=$dir" init -input=false "-backend-config=backend.hcl" "-backend-config=key=$stateKey"
    if ($LASTEXITCODE) { Remove-Item Env:\TF_DATA_DIR -ErrorAction SilentlyContinue; throw "terraform init failed for $Env" }
}
if (-not $TfArgs) { $TfArgs = @("plan") }
$cmd = $TfArgs[0]
$rest = @($TfArgs | Select-Object -Skip 1)
$varFile = @()
if ($cmd -in @("plan", "apply", "destroy", "import", "refresh", "console")) { $varFile = @("-var-file=env/$Env.tfvars") }
Write-Host "[$Env] terraform $cmd (state $stateKey)"
try {
    terraform "-chdir=$dir" $cmd @varFile @rest
    $code = $LASTEXITCODE
}
finally {
    # Do not leak this environment's data dir into the caller's shell.
    Remove-Item Env:\TF_DATA_DIR -ErrorAction SilentlyContinue
}
exit $code
