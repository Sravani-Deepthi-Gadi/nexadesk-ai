<#
    NexaDesk AI - first-time setup.

        .\setup.ps1

    Creates the Python virtual environment, installs dependencies, prepares
    .env with a generated JWT secret, applies migrations and installs the
    frontend packages. Safe to re-run; it skips work already done.

    It does NOT ask for your Anthropic API key. You add that yourself in
    backend\.env afterwards.
#>

$ErrorActionPreference = "Stop"
$root     = $PSScriptRoot
$backend  = Join-Path $root "backend"
$frontend = Join-Path $root "frontend"

Write-Host "NexaDesk AI - setup" -ForegroundColor Cyan
Write-Host "-------------------"

# --- 1. virtual environment ----------------------------------------------
Set-Location $backend
if (-not (Test-Path ".venv\Scripts\python.exe")) {
    Write-Host "[1/6] Creating virtual environment (Python 3.12)..."
    py -3.12 -m venv .venv
} else {
    Write-Host "[1/6] Virtual environment already exists."
}
& ".\.venv\Scripts\Activate.ps1"

# --- 2. backend dependencies ----------------------------------------------
Write-Host "[2/6] Installing backend dependencies (PyTorch is ~2.5 GB, be patient)..."
python -m pip install --upgrade pip --quiet
pip install -r requirements.txt --quiet

# --- 3. .env ---------------------------------------------------------------
if (-not (Test-Path ".env")) {
    Write-Host "[3/6] Creating .env with a generated JWT secret..."
    Copy-Item .env.example .env
    $s = python -c "import secrets; print(secrets.token_urlsafe(48))"
    (Get-Content .env) `
        -replace '^JWT_SECRET=.*', "JWT_SECRET=$s" `
        -replace '^ANTHROPIC_API_KEY=.*', 'ANTHROPIC_API_KEY=' |
        Set-Content .env -Encoding ascii
    Remove-Variable s
} else {
    Write-Host "[3/6] .env already exists, leaving it alone."
}

# --- 4. migrations ----------------------------------------------------------
Write-Host "[4/6] Applying database migrations..."
$dbPath = Join-Path $backend "data\nexadesk.db"
if (Test-Path $dbPath) {
    # Tables may already exist if the app was started before migrations ran.
    # Stamping records the current revision without rebuilding them.
    $stamped = (alembic current 2>&1 | Out-String)
    if ($stamped -notmatch "head") { alembic stamp head }
} else {
    alembic upgrade head
}

# --- 5. admin account --------------------------------------------------------
$hasAdmin = python -c "from app.db.session import SessionLocal; from app.models import AdminUser; db=SessionLocal(); print(db.query(AdminUser).count()); db.close()"
if ($hasAdmin.Trim() -eq "0") {
    Write-Host "[5/6] No admin account yet - creating one now."
    Write-Host "      Password must be at least 12 characters. It will not echo as you type."
    python -m scripts.create_admin
} else {
    Write-Host "[5/6] Admin account already exists."
}

# --- 6. frontend --------------------------------------------------------------
Set-Location $frontend
if (-not (Test-Path "node_modules")) {
    Write-Host "[6/6] Installing frontend dependencies..."
    npm install --silent
} else {
    Write-Host "[6/6] Frontend dependencies already installed."
}

Set-Location $root
Write-Host ""
Write-Host "Setup complete." -ForegroundColor Green
Write-Host ""
Write-Host "Next:"
Write-Host "  1. Optional - add your key to backend\.env (ANTHROPIC_API_KEY=sk-ant-...)"
Write-Host "     Without it everything works except the chat replying."
Write-Host "  2. Load demo data:"
Write-Host "       cd backend; .\.venv\Scripts\Activate.ps1; python -m scripts.seed_demo"
Write-Host "  3. Start everything:"
Write-Host "       .\start.ps1"
