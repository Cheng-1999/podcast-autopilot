# One-command dashboard runner: creates .venv if missing, installs
# dependencies, checks ffmpeg/ffprobe, builds the web/ frontend if present
# and stale, then serves the FastAPI dashboard (API + built SPA) with
# uvicorn on the LAN.
#
# Usage:
#   .\dashboard.ps1
#   .\dashboard.ps1 -Port 9000 -NoBrowser
param(
    [int]$Port = 8765,
    [switch]$NoBrowser
)

$ErrorActionPreference = "Stop"
$RepoRoot = $PSScriptRoot
Set-Location $RepoRoot
# Whisper model downloads: no symlinks in the Hugging Face cache (they need
# Developer Mode / admin on Windows and otherwise fail with WinError 1314).
$env:HF_HUB_DISABLE_SYMLINKS = "1"

function Test-PortFree {
    param([int]$Port)
    try {
        $listener = [System.Net.Sockets.TcpListener]::new([System.Net.IPAddress]::Any, $Port)
        $listener.Start()
        $listener.Stop()
        return $true
    } catch {
        return $false
    }
}

if (-not (Test-PortFree -Port $Port)) {
    # Port already bound. Most common cause: this dashboard is already running
    # from an earlier launch (browser tab closed without hitting "Quit").
    # Reuse it instead of failing with a raw socket-bind error after a slow
    # rebuild, and only treat it as a real conflict if nothing answers there.
    $existing = $null
    try {
        $existing = Invoke-RestMethod -Uri "http://localhost:$Port/api/health" -TimeoutSec 3 -ErrorAction Stop
    } catch {
        $existing = $null
    }
    # An unrelated HTTP service on this port could still answer with a truthy
    # 200 body (e.g. "{}"). Only treat it as our dashboard if it has the
    # fields our own /api/health always returns.
    $isOurDashboard = $existing -and
        ($existing.PSObject.Properties.Name -contains "ffmpeg_ok") -and
        ($existing.PSObject.Properties.Name -contains "whisper_models")
    if ($isOurDashboard) {
        Write-Host "A podcast-autopilot dashboard is already running on port $Port -- reusing it."
        if (-not $NoBrowser) {
            Start-Process "http://localhost:$Port"
        }
        exit 0
    }
    Write-Error "Port $Port is already in use by another process (not this dashboard). Close it, or run '.\dashboard.ps1 -Port <other>' to use a different port."
    exit 1
}

$VenvDir = Join-Path $RepoRoot ".venv"
$VenvPython = Join-Path $VenvDir "Scripts\python.exe"

if (-not (Test-Path $VenvPython)) {
    Write-Host "Creating virtual environment at $VenvDir ..."
    $bootstrapPython = if ($env:AGENTBOARD_PYTHON -and (Test-Path $env:AGENTBOARD_PYTHON)) { $env:AGENTBOARD_PYTHON } else { "python" }
    & $bootstrapPython -m venv $VenvDir
}

Write-Host "Installing dependencies ..."
& $VenvPython -m pip install --quiet --upgrade pip
& $VenvPython -m pip install --quiet -r (Join-Path $RepoRoot "requirements.txt")
if ($LASTEXITCODE -ne 0) { Write-Error "pip install -r requirements.txt failed (exit $LASTEXITCODE)."; exit 1 }
& $VenvPython -m pip install --quiet -e $RepoRoot
if ($LASTEXITCODE -ne 0) { Write-Error "pip install -e . failed (exit $LASTEXITCODE)."; exit 1 }

Write-Host "Checking ffmpeg/ffprobe ..."
& $VenvPython -c "from podcast_autopilot.config import resolve_ffmpeg_binaries; ffmpeg, ffprobe = resolve_ffmpeg_binaries(); print(f'ffmpeg: {ffmpeg}'); print(f'ffprobe: {ffprobe}')"
if ($LASTEXITCODE -ne 0) {
    Write-Error "ffmpeg/ffprobe not found. Install with 'winget install Gyan.FFmpeg', or drop ffmpeg.exe/ffprobe.exe into tools\ffmpeg\bin\ (see README)."
    exit 1
}

$WebDir = Join-Path $RepoRoot "web"
$PackageJson = Join-Path $WebDir "package.json"
$DistDir = Join-Path $WebDir "dist"
if (Test-Path $PackageJson) {
    $needsBuild = -not (Test-Path $DistDir)
    if (-not $needsBuild) {
        $distTime = (Get-ChildItem $DistDir -Recurse -File -ErrorAction SilentlyContinue |
            Sort-Object LastWriteTime -Descending | Select-Object -First 1).LastWriteTime
        $srcDir = Join-Path $WebDir "src"
        $srcTime = $null
        if (Test-Path $srcDir) {
            $srcTime = (Get-ChildItem $srcDir -Recurse -File -ErrorAction SilentlyContinue |
                Sort-Object LastWriteTime -Descending | Select-Object -First 1).LastWriteTime
        }
        if (-not $distTime -or ($srcTime -and $srcTime -gt $distTime)) {
            $needsBuild = $true
        }
    }
    if ($needsBuild) {
        Write-Host "Building web/ frontend ..."
        Push-Location $WebDir
        try {
            npm ci
            if ($LASTEXITCODE -ne 0) { Write-Error "npm ci failed (exit $LASTEXITCODE)."; exit 1 }
            npm run build
            if ($LASTEXITCODE -ne 0) { Write-Error "npm run build failed (exit $LASTEXITCODE)."; exit 1 }
        } finally {
            Pop-Location
        }
    } else {
        Write-Host "web/dist is up to date, skipping build."
    }
} else {
    Write-Host "web/package.json not found, skipping frontend build (API-only)."
}

Write-Host "Bundled example manifest: generating placeholder audio if missing ..."
& $VenvPython -m podcast_autopilot make-example --out-dir (Join-Path $RepoRoot "examples")
if ($LASTEXITCODE -ne 0) { Write-Error "make-example failed (exit $LASTEXITCODE)."; exit 1 }

$LanIp = Get-NetIPAddress -AddressFamily IPv4 -ErrorAction SilentlyContinue |
    Where-Object { $_.IPAddress -notlike "127.*" -and $_.IPAddress -notlike "169.254.*" } |
    Select-Object -First 1 -ExpandProperty IPAddress

Write-Host "Dashboard: http://localhost:$Port"
if ($LanIp) {
    Write-Host "LAN:       http://${LanIp}:$Port"
}

if (-not $NoBrowser) {
    Start-Process "http://localhost:$Port"
}

& $VenvPython -m uvicorn "podcast_autopilot.server:create_app" --factory --host 0.0.0.0 --port $Port
exit $LASTEXITCODE
