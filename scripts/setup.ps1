#Requires -Version 5.1
<#
.SYNOPSIS
    Bootstrap script for LegalDataPlatform on Windows PowerShell.

.DESCRIPTION
    Mirrors scripts/setup.sh for Windows users who prefer PowerShell.
    Verifies prerequisites, creates the virtualenv, installs dependencies,
    starts the Docker stack, applies migrations and seeds data.

.EXAMPLE
    PS> powershell -ExecutionPolicy Bypass -File scripts\setup.ps1
#>

$ErrorActionPreference = "Stop"

function Write-Info    { param($m) Write-Host "[INFO]  $m" -ForegroundColor Cyan }
function Write-Ok      { param($m) Write-Host "[OK]    $m" -ForegroundColor Green }
function Write-WarnMsg { param($m) Write-Host "[WARN]  $m" -ForegroundColor Yellow }
function Write-Fail    { param($m) Write-Host "[FAIL]  $m" -ForegroundColor Red; exit 1 }

function Require-Cmd {
    param([string]$Name)
    if (-not (Get-Command $Name -ErrorAction SilentlyContinue)) {
        Write-Fail "Missing prerequisite: $Name. Install it and re-run."
    }
}

# Locate project root (one level up from scripts/)
$Root = Split-Path -Parent $PSScriptRoot
Set-Location $Root

Write-Info "Checking prerequisites..."
Require-Cmd python
Require-Cmd docker
Require-Cmd git
Write-Ok "Prerequisites present."

# ---------------------------------------------------------------------------
# Python version check
# ---------------------------------------------------------------------------
$pyVer = (python -c "import sys; print('.'.join(map(str, sys.version_info[:2])))").Trim()
$parts = $pyVer.Split(".")
if ([int]$parts[0] -lt 3 -or ([int]$parts[0] -eq 3 -and [int]$parts[1] -lt 11)) {
    Write-Fail "Python 3.11+ required; found $pyVer."
}
Write-Ok "Python $pyVer detected."

# ---------------------------------------------------------------------------
# .env
# ---------------------------------------------------------------------------
if (-not (Test-Path .env)) {
    Write-Info "Creating .env from .env.example..."
    Copy-Item .env.example .env
    Write-Ok ".env created. Edit it if you need non-default values."
} else {
    Write-Ok ".env already exists (not overwriting)."
}

# ---------------------------------------------------------------------------
# Virtualenv
# ---------------------------------------------------------------------------
if (-not (Test-Path .venv)) {
    Write-Info "Creating Python virtualenv in .venv..."
    python -m venv .venv
    Write-Ok "Virtualenv created."
}

$activate = ".\.venv\Scripts\Activate.ps1"
if (-not (Test-Path $activate)) {
    Write-Fail "Could not locate virtualenv activate script at $activate."
}
. $activate
Write-Ok "Virtualenv activated."

Write-Info "Upgrading pip..."
python -m pip install --upgrade pip --quiet
Write-Ok "pip upgraded."

Write-Info "Installing dependencies (this may take a few minutes the first time)..."
pip install -e ".[dev]" --quiet
Write-Ok "Dependencies installed."

# ---------------------------------------------------------------------------
# Docker
# ---------------------------------------------------------------------------
try {
    docker info | Out-Null
} catch {
    Write-Fail "Docker daemon is not running. Start Docker Desktop and re-run."
}

Write-Info "Starting Docker stack (postgres, pgbouncer, minio, prefect, prometheus, grafana)..."
docker compose up -d | Out-Null
Write-Ok "Containers requested."

Write-Info "Waiting for PostgreSQL to be ready..."
$maxAttempts = 30
for ($i = 1; $i -le $maxAttempts; $i++) {
    $ready = $false
    try {
        docker compose exec -T postgres pg_isready -U ldp_admin -d legaldata 2>&1 | Out-Null
        if ($LASTEXITCODE -eq 0) { $ready = $true }
    } catch {}
    if ($ready) {
        Write-Ok "PostgreSQL is accepting connections."
        break
    }
    if ($i -eq $maxAttempts) {
        Write-Fail "PostgreSQL did not become ready. Check 'docker compose logs postgres'."
    }
    Start-Sleep -Seconds 2
}

# ---------------------------------------------------------------------------
# Migrations + seed
# ---------------------------------------------------------------------------
Write-Info "Applying Alembic migrations..."
alembic upgrade head
Write-Ok "Schema ready."

Write-Info "Generating sample data..."
python scripts\seed_data.py
Write-Ok "Sample data generated in data\samples\."

# ---------------------------------------------------------------------------
# Summary
# ---------------------------------------------------------------------------
Write-Host ""
Write-Ok "Setup complete. Next steps:"
Write-Host "  make pipeline        # run the legal ingestion flow" -ForegroundColor Cyan
Write-Host "  make test            # run the test suite" -ForegroundColor Cyan
Write-Host "  make benchmark       # measure query performance" -ForegroundColor Cyan
Write-Host ""
Write-Host "UIs:"
Write-Host "  Prefect:    http://localhost:4200"
Write-Host "  MinIO:      http://localhost:9001  (minioadmin / minioadmin123)"
Write-Host "  Prometheus: http://localhost:9090"
Write-Host "  Grafana:    http://localhost:3000  (admin / admin)"
