# Build the Lambda deployment package (no Docker needed).
# Installs the pinned runtime dependencies as Linux (manylinux) wheels for Python 3.12, then
# copies the application source next to them. Output: deploy/aws/build/lambda/
$ErrorActionPreference = "Stop"
$root = Resolve-Path (Join-Path $PSScriptRoot "..\..")
$backend = Join-Path $root "backend"
$out = Join-Path $PSScriptRoot "build\lambda"
$py = Join-Path $backend ".venv\Scripts\python.exe"
if (-not (Test-Path $py)) { throw "Backend venv not found at $py (create it first, see README)." }

if (Test-Path $out) { Remove-Item $out -Recurse -Force }
New-Item -ItemType Directory -Force $out | Out-Null

$req = Join-Path $env:TEMP "ora_lambda_requirements.txt"
& $py -c "import tomllib; print('\n'.join(tomllib.load(open(r'$backend\pyproject.toml','rb'))['project']['dependencies']))" | Set-Content $req

& $py -m pip install --quiet --no-cache-dir -r $req -t $out `
    --platform manylinux2014_x86_64 --implementation cp --python-version 3.12 --only-binary=:all:
if ($LASTEXITCODE -ne 0) { throw "pip install for Lambda failed" }

Copy-Item (Join-Path $backend "app") (Join-Path $out "app") -Recurse
# Named "migrations" (not "alembic"): the installed Alembic library is itself a top-level
# package called "alembic", and a same-named folder would collide with it.
Copy-Item (Join-Path $backend "alembic") (Join-Path $out "migrations") -Recurse
Copy-Item (Join-Path $backend "alembic.ini") $out

# Trim files that are never needed at runtime.
Get-ChildItem $out -Recurse -Directory -Include "__pycache__", "tests", "test" -ErrorAction SilentlyContinue |
    Where-Object { $_.FullName -notmatch "\\app\\" } | Remove-Item -Recurse -Force -ErrorAction SilentlyContinue
Get-ChildItem $out -Recurse -File -Include "*.pyc" | Remove-Item -Force

$mb = [math]::Round((Get-ChildItem $out -Recurse -File | Measure-Object Length -Sum).Sum / 1MB, 1)
Write-Host "Lambda package built: $out ($mb MB unzipped; Lambda limit is 250 MB)"
if ($mb -gt 245) { throw "Package too large for a Lambda zip ($mb MB)" }
