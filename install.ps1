<#
.SYNOPSIS
    Install DonnyT on this machine. Works with no internet access.

.DESCRIPTION
    Creates a virtual environment, installs the one optional dependency
    ('mcp'), seeds .env and config.toml from their templates, generates
    .mcp.json for Claude Code, and runs the doctor.

    'mcp' is looked for, in order, in:
      1. vendor\wheels            the offline bundle shipped in the zip
      2. a package index         -IndexUrl, or whatever pip is already
                                 configured to use (pip.ini, PIP_INDEX_URL)
    If neither has it, the install still succeeds in CLI-only mode: every
    tool works as `python -m donnyt.cli <command>`, just not as MCP tools.

    Safe to re-run: nothing already configured is overwritten.

.PARAMETER Source
    auto (default) tries the bundle, then the index, then falls back to
    CLI-only. bundle / index use only that source and fail if it fails.
    none skips 'mcp' entirely.

.PARAMETER IndexUrl
    An internal package mirror (Artifactory, Nexus, devpi...), e.g.
    https://artifactory.corp/api/pypi/pypi/simple. Also read from
    DONNYT_INDEX_URL.

.EXAMPLE
    .\install.ps1
    Use whatever is available; never fails for want of 'mcp'.

.EXAMPLE
    .\install.ps1 -Source index -IndexUrl https://artifactory.corp/api/pypi/pypi/simple
    Install 'mcp' from an internal mirror.

.EXAMPLE
    .\install.ps1 -Online
    Allow PyPI. Only for a machine with internet access.
#>
[CmdletBinding()]
param(
    [ValidateSet("auto", "bundle", "index", "none")]
    [string]$Source = "auto",
    [string]$IndexUrl = $env:DONNYT_INDEX_URL,
    [string]$McpSpec = "mcp>=1.2",
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
Write-Step 3 "Installing the MCP dependency (optional)"

# donnyt itself is never installed as a package -- a .pth file below points at
# src/, so edits to this repo take effect with no reinstall. Only the MCP
# server's dependency needs installing, and even that is optional.
if ($Online) { $Source = "index"; $IndexUrl = "" }

$wheelCount = 0
if (Test-Path $Wheels) { $wheelCount = (Get-ChildItem $Wheels -Filter *.whl -ErrorAction SilentlyContinue).Count }

function Install-FromBundle {
    if ($wheelCount -eq 0) {
        Write-Warn2 "No offline bundle: vendor\wheels is empty."
        return $false
    }
    Write-Ok "Trying the offline bundle ($wheelCount wheels in vendor\wheels)"
    & $VenvPython -m pip install --quiet --disable-pip-version-check --no-index --find-links $Wheels $McpSpec | Out-Host
    if ($LASTEXITCODE -eq 0) { return $true }
    Write-Warn2 "The bundle does not fit this machine's Python/OS (see vendor\wheels\MANIFEST.txt)."
    return $false
}

function Install-FromIndex {
    $pipArgs = @("-m", "pip", "install", "--quiet", "--disable-pip-version-check", "--timeout", "15", "--retries", "1")
    if ($IndexUrl) {
        Write-Ok "Trying package index $IndexUrl"
        $pipArgs += @("--index-url", $IndexUrl)
        # Plain-http mirrors are common inside; pip refuses them unless trusted.
        $indexHost = ([uri]$IndexUrl).Host
        if (([uri]$IndexUrl).Scheme -eq "http") { $pipArgs += @("--trusted-host", $indexHost) }
    } else {
        Write-Ok "Trying pip's configured index (pip.ini / PIP_INDEX_URL, else PyPI)"
    }
    & $VenvPython @pipArgs $McpSpec | Out-Host
    if ($LASTEXITCODE -eq 0) { return $true }
    Write-Warn2 "The package index did not provide '$McpSpec'."
    return $false
}

$mcpReady = $false
switch ($Source) {
    "bundle" { $mcpReady = Install-FromBundle }
    "index"  { $mcpReady = Install-FromIndex }
    "auto"   { $mcpReady = (Install-FromBundle) -or (Install-FromIndex) }
    "none"   { Write-Ok "Skipped (-Source none)" }
}

if ($mcpReady) {
    Write-Ok "MCP dependency installed"
} elseif ($Source -in @("bundle", "index")) {
    Write-Err "Could not install '$McpSpec' from the requested source ($Source)."
    Write-Err "Re-run with -Source auto to fall back to CLI-only mode, or see INSTALL.md step 3."
    exit 1
} else {
    Write-Warn2 "Continuing in CLI-only mode: every tool works as 'python -m donnyt.cli <command>'."
    Write-Warn2 "To add the MCP server later, re-run with -IndexUrl <mirror>, or ship a"
    Write-Warn2 "vendor\wheels bundle built for this machine (INSTALL.md step A2)."
}

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
if (-not $mcpReady) {
    # A server entry that cannot start is worse than none: Claude Code would
    # report a broken server instead of the skills falling back to the CLI.
    if (Test-Path $mcpJson) { Remove-Item $mcpJson }
    Write-Warn2 "Skipped - no 'mcp' package. The skills will drive the CLI instead."
} else {
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
}

# --- 6. Doctor --------------------------------------------------------------
Write-Step 6 "Running the doctor"

& $VenvPython -m donnyt.cli doctor
$doctorExit = $LASTEXITCODE

Write-Host "`n=== Next steps ===" -ForegroundColor White
if ($doctorExit -ne 0) {
    Write-Host "  1. Edit .env         - add your Atlassian and GitLab tokens   (INSTALL.md step 4)"
    Write-Host "  2. Edit config.toml  - site URL, project key, board id, team  (INSTALL.md step 5)"
    Write-Host "  3. Re-run:  .\.venv\Scripts\python.exe -m donnyt.cli doctor"
    if ($mcpReady) { Write-Host "  4. Open this folder in Claude Code and approve the 'donnyt' MCP server." }
    else           { Write-Host "  4. Open this folder in Claude Code (CLI-only mode - no server to approve)." }
} else {
    Write-Host "  Everything checks out." -ForegroundColor Green
    if ($mcpReady) { Write-Host "  Open this folder in Claude Code, approve the 'donnyt' MCP server, then try:" }
    else           { Write-Host "  Open this folder in Claude Code (CLI-only mode), then try:" }
    Write-Host "      /sprint-plan" -ForegroundColor Cyan
}
Write-Host ""
exit $doctorExit
