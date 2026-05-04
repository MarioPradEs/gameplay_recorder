# setup_scrcpy.ps1 -- local dev helper to fetch the scrcpy binary used at runtime.
#
# What it does:
#   1. Downloads scrcpy v3.3.4 (Windows x64) from the official Genymobile/scrcpy
#      GitHub release.
#   2. Extracts it into `resources/scrcpy/` at the repo root, where the
#      `_resolve_scrcpy()` helper in `capture/scrcpy_recorder.py` looks for it
#      (via `sys._MEIPASS` in frozen builds or `shutil.which` for dev).
#   3. Verifies `resources/scrcpy/scrcpy.exe` exists at the end.
#
# When to run it:
#   - Once per dev machine, after cloning the repo.
#   - After bumping the pinned scrcpy version (edit $ScrcpyVersion below).
#
# Why this script exists:
#   - CI bundles scrcpy via `.github/workflows/build.yml` (download step).
#   - For LOCAL smoke tests (Phase 8 of the scrcpy-pivot track), the dev needs
#     the same binary on disk. This avoids each dev hand-fetching the zip.
#   - The bundled binary is gitignored (`resources/scrcpy/*` except `.gitkeep`),
#     so it never bloats the repo.
#
# Usage (from the repo root):
#   .\scripts\setup_scrcpy.ps1
#
# Pinned version is intentional -- must match the version the codebase was
# written against (test_scrcpy_recorder.py + ScrcpyRecorder._resolve_scrcpy).
#
# Encoding note: this file is ASCII-only on purpose. PowerShell 5.1 (the default
# on Windows 10/11) reads .ps1 files without a BOM as Windows-1252, which
# corrupts non-ASCII characters and breaks the parser. Keep it ASCII and we
# avoid the whole class of "save with BOM" gotchas.

$ErrorActionPreference = 'Stop'

# --- Configuration ----------------------------------------------------------

$ScrcpyVersion = 'v3.3.4'
$ArchiveName   = "scrcpy-win64-$ScrcpyVersion.zip"
$DownloadUrl   = "https://github.com/Genymobile/scrcpy/releases/download/$ScrcpyVersion/$ArchiveName"

# Resolve the repo root: this script lives at scripts/setup_scrcpy.ps1, so the
# repo root is the parent of $PSScriptRoot.
$RepoRoot      = Split-Path -Parent $PSScriptRoot
$ResourcesDir  = Join-Path $RepoRoot 'resources\scrcpy'
$ArchivePath   = Join-Path $env:TEMP $ArchiveName
$ExtractTmp    = Join-Path $env:TEMP "scrcpy-extract-$([guid]::NewGuid().ToString('N'))"

# --- Pre-flight -------------------------------------------------------------

Write-Host "scrcpy local setup ($ScrcpyVersion)" -ForegroundColor Cyan
Write-Host "  Repo root      : $RepoRoot"
Write-Host "  Target dir     : $ResourcesDir"
Write-Host ""

if (-not (Test-Path $ResourcesDir)) {
    Write-Host "Creating $ResourcesDir ..."
    New-Item -ItemType Directory -Path $ResourcesDir -Force | Out-Null
}

# Idempotency: if scrcpy.exe already exists, ask before re-downloading.
$ScrcpyExe = Join-Path $ResourcesDir 'scrcpy.exe'
if (Test-Path $ScrcpyExe) {
    Write-Host "scrcpy.exe already present at $ScrcpyExe" -ForegroundColor Yellow
    $answer = Read-Host "Re-download and overwrite? [y/N]"
    if ($answer -notmatch '^[Yy]') {
        Write-Host "Aborted by user -- existing scrcpy.exe kept." -ForegroundColor Yellow
        exit 0
    }
}

# --- Download ---------------------------------------------------------------

Write-Host "Downloading $DownloadUrl ..." -ForegroundColor Cyan

# Use Invoke-WebRequest -- preinstalled in PowerShell, no extra deps.
# -UseBasicParsing for compatibility with PS 5.1 (default on Windows 10/11).
try {
    Invoke-WebRequest -Uri $DownloadUrl -OutFile $ArchivePath -UseBasicParsing
} catch {
    Write-Host "Download failed: $($_.Exception.Message)" -ForegroundColor Red
    exit 1
}

$archiveSizeMb = [math]::Round((Get-Item $ArchivePath).Length / 1MB, 2)
Write-Host "Downloaded $archiveSizeMb MB to $ArchivePath" -ForegroundColor Green

# --- Extract ----------------------------------------------------------------

Write-Host "Extracting to staging dir $ExtractTmp ..." -ForegroundColor Cyan
New-Item -ItemType Directory -Path $ExtractTmp -Force | Out-Null

try {
    # Expand-Archive ships with PowerShell 5.1+; no 7z dependency.
    Expand-Archive -Path $ArchivePath -DestinationPath $ExtractTmp -Force
} catch {
    Write-Host "Extraction failed: $($_.Exception.Message)" -ForegroundColor Red
    Remove-Item -Path $ArchivePath -Force -ErrorAction SilentlyContinue
    exit 1
}

# The zip contains a single top-level directory `scrcpy-win64-v3.3.4/` with all
# the binaries inside. We move its contents into resources/scrcpy/.
$ExtractedSubdir = Join-Path $ExtractTmp "scrcpy-win64-$ScrcpyVersion"
if (-not (Test-Path $ExtractedSubdir)) {
    Write-Host "Expected subdirectory not found: $ExtractedSubdir" -ForegroundColor Red
    Write-Host "Archive layout may have changed. Inspect $ExtractTmp manually." -ForegroundColor Red
    exit 1
}

Write-Host "Moving extracted files into $ResourcesDir ..." -ForegroundColor Cyan
# Copy (not move) so we can clean staging afterwards atomically. -Force so it
# overwrites on re-run.
Get-ChildItem -Path $ExtractedSubdir -Force | ForEach-Object {
    Copy-Item -Path $_.FullName -Destination $ResourcesDir -Recurse -Force
}

# --- Cleanup ----------------------------------------------------------------

Remove-Item -Path $ExtractTmp -Recurse -Force -ErrorAction SilentlyContinue
Remove-Item -Path $ArchivePath -Force -ErrorAction SilentlyContinue

# --- Verify -----------------------------------------------------------------

if (-not (Test-Path $ScrcpyExe)) {
    Write-Host "Verification FAILED -- $ScrcpyExe does not exist." -ForegroundColor Red
    exit 1
}

$exeSizeMb = [math]::Round((Get-Item $ScrcpyExe).Length / 1MB, 2)
Write-Host ""
Write-Host "Setup complete." -ForegroundColor Green
Write-Host "  $ScrcpyExe -- $exeSizeMb MB" -ForegroundColor Green
Write-Host ""
Write-Host "Smoke test next:" -ForegroundColor Cyan
Write-Host "  1. Connect the Android device (USB debugging enabled)"
Write-Host "  2. Run: .venv\Scripts\python.exe -m gameplay_recorder"
Write-Host "  3. Click Record, wait >=10s, click Stop"
Write-Host "  4. Verify the produced ZIP under ~\Documents\gameplay-recordings\"
