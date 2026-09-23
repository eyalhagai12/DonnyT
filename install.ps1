<#
.SYNOPSIS
    Install DonnyT on this machine. Works with no internet access.

.DESCRIPTION
    Creates a virtual environment, installs from the bundled wheels in
    vendor/wheels, seeds .env and config.toml from their templates, generates
    .mcp.json for Claude Code, and runs the doctor.

    Safe to re-run: nothing already configured is overwritten.

.EXAMPLE
    .\install.ps1
    Offline install using vendor/wheels.

.EXAMPLE
    .\install.ps1 -Online
    Allow PyPI. Only for a machine with internet access.
#>
[CmdletBinding()]
param(
    [switch]$Online,
    [string]$Python = "",
    [switch]$Force
)

$ErrorActionPreference = "Stop"
$Root = $PSScriptRoot
$Venv = Join-Path $Root ".venv"
$Wheels = Join-Path $Root "vendor\wheels"

function Write-Step($n, $text) { Write-Host "`n[$n] $text" -ForegroundColor Cyan }
function Write-Ok($text)       { Write-Host "      $text" -ForegroundColor Green }
function Write-Warn2($text)    { Write-Host "      $text" -ForegroundColor Yellow }
function Write-Err($text)      { Write-Host "      $text" -ForegroundColor Red }

Write-Host "`n=== DonnyT install ===" -ForegroundColor White
Write-Host "Repo: $Root"

# --- 1. Find a usable Python ------------------------------------------------
Write-Step 1 "Locating Python 3.11 or newer"

$candidates = if ($Python) { @($Python) } else { @("python", "python3", "py") }
$PythonExe = $null
foreach ($candidate in $candidates) {
    try {
        # NB: not $args -- that is an automatic variable in PowerShell.
        $probe = if ($candidate -eq "py") { @("-3", "-c", "import sys; print(sys.version_info[:2])") }
                 else { @("-c", "import sys; print(sys.version_info[:2])") }
        $out = & $candidate @probe 2>$null
        if ($LASTEXITCODE -eq 0 -and $out -match "\((\d+), (\d+)\)") {
            if ([int]$Matches[1] -gt 3 -or ([int]$Matches[1] -eq 3 -and [int]$Matches[2] -ge 11)) {
                $PythonExe = $candidate
                Write-Ok "Using '$candidate' -> Python $($Matches[1]).$($Matches[2])"
                break
            }
        }
    } catch { }
}

if (-not $PythonExe) {
    Write-Err "No Python 3.11+ found."
    Write-Err "Install Python 3.11 or newer, then re-run. If it is installed but not on PATH:"
    Write-Err "    .\install.ps1 -Python 'C:\Python311\python.exe'"
    exit 1
}

# --- 2. Virtual environment -------------------------------------------------
Write-Step 2 "Creating the virtual environment"

$VenvPython = Join-Path $Venv "Scripts\python.exe"
if ((Test-Path $VenvPython) -and -not $Force) {
    Write-Ok ".venv already exists (use -Force to rebuild)"
} else {
    if ($Force -and (Test-Path $Venv)) { Remove-Item -Recurse -Force $Venv }
    $venvArgs = if ($PythonExe -eq "py") { @("-3", "-m", "venv", $Venv) } else { @("-m", "venv", $Venv) }
    & $PythonExe @venvArgs
    if ($LASTEXITCODE -ne 0) { Write-Err "Could not create .venv"; exit 1 }
    Write-Ok "Created $Venv"
}

# --- 3. Install dependencies ------------------------------------------------
Write-Step 3 "Installing dependencies"

# donnyt itself is never installed as a package -- a .pth file below points at
# src/, so edits to this repo take effect with no reinstall. Only the MCP
# server's dependency needs installing.
$wheelCount = 0
if (Test-Path $Wheels) { $wheelCount = (Get-ChildItem $Wheels -Filter *.whl -ErrorAction SilentlyContinue).Count }

$mcpReady = $false
if ($Online) {
    Write-Warn2 "Online mode: installing 'mcp' from PyPI"
    & $VenvPython -m pip install --quiet --upgrade pip
    & $VenvPython -m pip install --quiet "mcp>=1.2"
    $mcpReady = ($LASTEXITCODE -eq 0)
} elseif ($wheelCount -gt 0) {
    Write-Ok "Offline mode: $wheelCount wheels in vendor\wheels"
    & $VenvPython -m pip install --quiet --no-index --find-links $Wheels "mcp>=1.2"
    $mcpReady = ($LASTEXITCODE -eq 0)
    if (-not $mcpReady) {
        Write-Err "Offline install failed. The bundle may not match this machine's Python or OS."
        Write-Err "Check vendor\wheels\MANIFEST.txt, then rebuild it on a connected machine:"
        Write-Err "    python scriptsuild_offline_bundle.py --platform win_amd64 --python-version 3.11"
        exit 1
    }
} else {
    Write-Warn2 "vendor\wheels is empty - no offline bundle shipped with this copy."
    Write-Warn2 "The CLI will work; the MCP server will not."
    Write-Warn2 "To enable it, run this on a connected machine:"
    Write-Warn2 "    python scriptsuild_offline_bundle.py"
    Write-Warn2 "then re-zip, copy across, and re-run this installer."
}
if ($mcpReady) { Write-Ok "MCP dependency installed" }

# Put src/ on the interpreter's path so `python -m donnyt.cli` just works.
$SitePackages = Join-Path $Venv "Lib\site-packages"
if (Test-Path $SitePackages) {
    Set-Content -Path (Join-Path $SitePackages "donnyt_src.pth") -Value (Join-Path $Root "src") -Encoding ascii
    Write-Ok "Linked src\ into the virtual environment"
}

# --- 4. Seed the config files ----------------------------------------------
Write-Step 4 "Seeding configuration files"

foreach ($pair in @(@(".env.example", ".env"), @("config.example.toml", "config.toml"))) {
    $src = Join-Path $Root $pair[0]
    $dst = Join-Path $Root $pair[1]
    if (Test-Path $dst) {
        Write-Ok "$($pair[1]) already exists - left untouched"
    } elseif (Test-Path $src) {
        Copy-Item $src $dst
        Write-Ok "Created $($pair[1]) from $($pair[0]) - YOU MUST EDIT THIS"
    }
}

# --- 5. Generate .mcp.json --------------------------------------------------
Write-Step 5 "Registering the MCP server for Claude Code"

$mcpJson = Join-Path $Root ".mcp.json"
# DONNYT_HOME pins the repo so the server finds .env and config.toml
# regardless of the directory Claude Code launches it from.
$config = @{
    mcpServers = @{
        donnyt = @{
            command = $VenvPython
            args    = @("-m", "donnyt.mcp_server")
            env     = @{ DONNYT_HOME = $Root }
        }
    }
}
$config | ConvertTo-Json -Depth 6 | Set-Content -Path $mcpJson -Encoding utf8
Write-Ok "Wrote .mcp.json pointing at $VenvPython"

# --- 6. Doctor --------------------------------------------------------------
Write-Step 6 "Running the doctor"

& $VenvPython -m donnyt.cli doctor
$doctorExit = $LASTEXITCODE

Write-Host "`n=== Next steps ===" -ForegroundColor White
if ($doctorExit -ne 0) {
    Write-Host "  1. Edit .env         - add your Atlassian and GitLab tokens   (INSTALL.md step 4)"
    Write-Host "  2. Edit config.toml  - site URL, project key, board id, team  (INSTALL.md step 5)"
    Write-Host "  3. Re-run:  .\.venv\Scripts\python.exe -m donnyt.cli doctor"
    Write-Host "  4. Open this folder in Claude Code and approve the 'donnyt' MCP server."
} else {
    Write-Host "  Everything checks out." -ForegroundColor Green
    Write-Host "  Open this folder in Claude Code, approve the 'donnyt' MCP server, then try:"
    Write-Host "      /sprint-plan" -ForegroundColor Cyan
}
Write-Host ""
exit $doctorExit
