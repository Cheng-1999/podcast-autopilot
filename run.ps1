# One-command runner: creates .venv if missing, installs dependencies,
# checks for ffmpeg/ffprobe, and runs the full episode pipeline.
#
# Usage:
#   .\run.ps1 examples\episode.example.yaml
#   .\run.ps1 examples\episode.example.yaml -Profile spotify -ExtraArgs --dry-run
#   .\run.ps1 examples\episode.example.yaml -ExtraArgs "--skip","transcribe","--force"
param(
    [Parameter(Mandatory = $true, Position = 0)]
    [string]$EpisodeYaml,

    [string]$Profile = "default",

    [Parameter(ValueFromRemainingArguments = $true)]
    [string[]]$ExtraArgs = @()
)

$ErrorActionPreference = "Stop"
$RepoRoot = $PSScriptRoot
Set-Location $RepoRoot
# Whisper model downloads: no symlinks in the Hugging Face cache (they need
# Developer Mode / admin on Windows and otherwise fail with WinError 1314).
$env:HF_HUB_DISABLE_SYMLINKS = "1"

$VenvDir = Join-Path $RepoRoot ".venv"
$VenvPython = Join-Path $VenvDir "Scripts\python.exe"

if (-not (Test-Path $VenvPython)) {
    Write-Host "Creating virtual environment at $VenvDir ..."
    python -m venv $VenvDir
}

Write-Host "Installing dependencies ..."
& $VenvPython -m pip install --quiet --upgrade pip
& $VenvPython -m pip install --quiet -r (Join-Path $RepoRoot "requirements.txt")
& $VenvPython -m pip install --quiet -e $RepoRoot

Write-Host "Checking ffmpeg/ffprobe ..."
& $VenvPython -c "from podcast_autopilot.config import resolve_ffmpeg_binaries; ffmpeg, ffprobe = resolve_ffmpeg_binaries(); print(f'ffmpeg: {ffmpeg}'); print(f'ffprobe: {ffprobe}')"
if ($LASTEXITCODE -ne 0) {
    Write-Error "ffmpeg/ffprobe not found. Install with 'winget install Gyan.FFmpeg', or drop ffmpeg.exe/ffprobe.exe into tools\ffmpeg\bin\ (see README)."
    exit 1
}

$BundledExample = Join-Path $RepoRoot "examples\episode.example.yaml"
if ((Resolve-Path $EpisodeYaml).Path -eq (Resolve-Path $BundledExample -ErrorAction SilentlyContinue).Path) {
    Write-Host "Bundled example manifest: generating placeholder audio if missing ..."
    & $VenvPython -m podcast_autopilot make-example --out-dir (Join-Path $RepoRoot "examples")
}

Write-Host "Running: python -m podcast_autopilot run `"$EpisodeYaml`" --profile $Profile $ExtraArgs"
& $VenvPython -m podcast_autopilot run $EpisodeYaml --profile $Profile @ExtraArgs
exit $LASTEXITCODE
