# Build the Lambda package for architecture v2 (no Docker): pinned backend dependencies as Linux wheels,
# the application source, Alembic migrations, and the Aurora Data API SQLAlchemy dialect.
# Output: Orient_Internal_AI_Deployment\.build\lambda   (self-contained; does not use deploy\aws)
$ErrorActionPreference = "Stop"
$deployRoot = Resolve-Path (Join-Path $PSScriptRoot "..")
$backend = Join-Path (Resolve-Path (Join-Path $deployRoot "..")) "backend"
$out = Join-Path $deployRoot ".build\lambda"
$py = Join-Path $backend ".venv\Scripts\python.exe"
if (-not (Test-Path $py)) { throw "Backend venv not found at $py" }

if (Test-Path $out) { Remove-Item $out -Recurse -Force }
New-Item -ItemType Directory -Force $out | Out-Null

$req = Join-Path ([IO.Path]::GetTempPath()) "ora_lambda_requirements.txt"
& $py -c "import tomllib; print('\n'.join(tomllib.load(open(r'$backend\pyproject.toml','rb'))['project']['dependencies']))" | Set-Content $req

# pip writes warnings to stderr; Windows PowerShell 5.1 would treat that as a terminating error.
function Invoke-Pip([string[]]$PipArgs) {
    $prev = $ErrorActionPreference; $ErrorActionPreference = "Continue"
    & $py -m pip install --quiet --no-cache-dir @PipArgs 2>&1 | Out-Host
    $code = $LASTEXITCODE; $ErrorActionPreference = $prev
    if ($code -ne 0) { throw "pip install failed: $PipArgs" }
}
Invoke-Pip @("-r", $req, "-t", $out, "--platform", "manylinux2014_x86_64", "--implementation", "cp", "--python-version", "3.12", "--only-binary=:all:")
Invoke-Pip @("--no-deps", "-r", (Join-Path $deployRoot "lambda-extra-requirements.txt"), "-t", $out, "--only-binary=:all:")

Copy-Item (Join-Path $backend "app") (Join-Path $out "app") -Recurse
# "migrations", not "alembic": a same-named folder would collide with the installed Alembic library.
Copy-Item (Join-Path $backend "alembic") (Join-Path $out "migrations") -Recurse
Copy-Item (Join-Path $backend "alembic.ini") $out
Get-ChildItem $out -Recurse -Directory -Filter "__pycache__" | Remove-Item -Recurse -Force -ErrorAction SilentlyContinue

$mb = [math]::Round((Get-ChildItem $out -Recurse -File | Measure-Object Length -Sum).Sum / 1MB, 1)
Write-Host "Lambda package built: $out ($mb MB unzipped; limit 250 MB)"
if ($mb -gt 245) { throw "Package too large for a Lambda zip" }
if (-not (Test-Path (Join-Path $out "sqlalchemy_aurora_data_api"))) { throw "Data API dialect missing from package" }
