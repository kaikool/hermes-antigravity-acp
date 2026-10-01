param(
    [switch]$VerboseInstall,
    [switch]$NoLaunch
)

$ErrorActionPreference = "Stop"

function STEP($m)  { Write-Host "[..] $m" -ForegroundColor Cyan }
function OK($m)    { Write-Host "[OK] $m" -ForegroundColor Green }
function WARN($m)  { Write-Host "[WARN] $m" -ForegroundColor Yellow }
function FAIL($m)  { Write-Host "[FAIL] $m" -ForegroundColor Red; exit 1 }
function DEBUG($m) { if ($VerboseInstall) { Write-Host "[debug] $m" -ForegroundColor DarkGray } }

$Here = Split-Path -Parent $MyInvocation.MyCommand.Path
$Parent = Split-Path -Parent $Here

# Support both layouts:
#   source repo: installer\install.ps1 + src\...
#   release ZIP: install.ps1 + model-provider\... + antigravity-manager\...
$SourceRepo = $null
$ReleaseRoot = $null

if (Test-Path (Join-Path $Parent "src\provider\antigravity")) {
    $SourceRepo = $Parent
} elseif (Test-Path (Join-Path $Here "model-provider\antigravity")) {
    $ReleaseRoot = $Here
} elseif (Test-Path (Join-Path $Parent "model-provider\antigravity")) {
    $ReleaseRoot = $Parent
} else {
    FAIL "Package layout is invalid: provider source was not found."
}

if ($SourceRepo) {
    $ProviderSource = Join-Path $SourceRepo "src\provider\antigravity"
    $DesktopPluginSource = Join-Path $SourceRepo "src\desktop-plugin\plugin.js"
    $AccountHelperSource = Join-Path $SourceRepo "src\account-manager\account_helper.py"
} else {
    $ProviderSource = Join-Path $ReleaseRoot "model-provider\antigravity"
    $DesktopPluginSource = Join-Path $ReleaseRoot "antigravity-manager\desktop\plugin.js"
    $AccountHelperSource = Join-Path $ReleaseRoot "antigravity-manager\account_helper.py"
}

if (-not $env:LOCALAPPDATA) { FAIL "LOCALAPPDATA is not defined." }

$HH = if ($env:HERMES_HOME) { $env:HERMES_HOME } else { Join-Path $env:LOCALAPPDATA "hermes" }
$Root = Join-Path $HH "hermes-agent"
$AcpRoot = Join-Path $HH "antigravity-acp"
$HermesGeminiHome = Join-Path $HH "antigravity-gemini-home"
$HermesAcpCfg = Join-Path $HermesGeminiHome "antigravity-acp"
$HermesWorkdir = Join-Path $HH "antigravity-workspace"
$Registry = "https://raw.githubusercontent.com/agentclientprotocol/registry/main/antigravity-acp/agent.json"

Write-Host ""
Write-Host "Hermes Antigravity ACP 4.6.0" -ForegroundColor Cyan
Write-Host "Official ACP provider + Desktop account manager" -ForegroundColor DarkGray
Write-Host ""

$hc = Get-Command hermes -ErrorAction SilentlyContinue
if (-not $hc) { FAIL "Hermes is not installed or is not on PATH." }
$Hermes = $hc.Source

$oldPref = $ErrorActionPreference
try {
    $ErrorActionPreference = "Continue"
    $hv = (& $Hermes --version 2>&1 | Out-String).Trim()
    $hec = $LASTEXITCODE
} finally {
    $ErrorActionPreference = $oldPref
}
if ($hec -ne 0) { FAIL "Hermes command is not healthy." }
DEBUG $hv
OK "Hermes detected"

New-Item -ItemType Directory -Force $HermesAcpCfg | Out-Null
New-Item -ItemType Directory -Force $HermesWorkdir | Out-Null

[Environment]::SetEnvironmentVariable("HERMES_ANTIGRAVITY_GEMINI_HOME", $HermesGeminiHome, "User")
[Environment]::SetEnvironmentVariable("HERMES_ANTIGRAVITY_WORKDIR", $HermesWorkdir, "User")
$env:HERMES_ANTIGRAVITY_GEMINI_HOME = $HermesGeminiHome
$env:HERMES_ANTIGRAVITY_WORKDIR = $HermesWorkdir

@'
{
  "auth": {
    "type": "oauth-personal"
  }
}
'@ | Set-Content -LiteralPath (Join-Path $HermesAcpCfg "settings.json") -Encoding UTF8

STEP "Preparing Google Antigravity ACP..."

try {
    $meta = Invoke-RestMethod -Uri $Registry -UseBasicParsing -TimeoutSec 30
} catch {
    FAIL "Cannot read the official ACP registry: $($_.Exception.Message)"
}

$target = $meta.distribution.binary.'windows-x86_64'
if (-not $target -or -not $target.archive) {
    FAIL "The ACP registry has no Windows x86_64 Antigravity binary."
}

$version = [string]$meta.version
$url = [string]$target.archive
$VersionDir = Join-Path $AcpRoot $version
$Exe = Join-Path $VersionDir "agy_acp_server.exe"

$ExpectedExeSha256 = $null
$ExpectedExeSize = $null
if ($version -eq "1.2.1" -and [Environment]::Is64BitOperatingSystem) {
    $ExpectedExeSha256 = "04FD51B5C6DFB6D11E649C2CFC61A64CA31D9A4A58A9A3E5C93DB934CD7A9695"
    $ExpectedExeSize = 81231712
}

function Install-OfficialAcpArchive {
    param([string]$ArchiveUrl, [string]$Destination, [string]$ExePath)

    if (Test-Path $Destination) {
        Remove-Item $Destination -Recurse -Force -ErrorAction SilentlyContinue
    }
    New-Item -ItemType Directory -Force $Destination | Out-Null

    $zip = Join-Path $env:TEMP "agy-acp-$version-$PID.zip"
    try {
        DEBUG "Downloading $ArchiveUrl"
        Invoke-WebRequest -Uri $ArchiveUrl -OutFile $zip -UseBasicParsing -TimeoutSec 300
        Expand-Archive -LiteralPath $zip -DestinationPath $Destination -Force
    } catch {
        FAIL "Official ACP download/extraction failed: $($_.Exception.Message)"
    } finally {
        Remove-Item $zip -Force -ErrorAction SilentlyContinue
    }

    if (-not (Test-Path $ExePath)) {
        FAIL "Official ACP executable was not found after extraction."
    }
}

function Test-AcpBinaryIntegrity {
    param([string]$Path)
    if (-not (Test-Path $Path)) { return $false }

    if ($ExpectedExeSize -and ((Get-Item $Path).Length -ne $ExpectedExeSize)) {
        return $false
    }

    if ($ExpectedExeSha256) {
        $actual = (Get-FileHash -LiteralPath $Path -Algorithm SHA256).Hash.ToUpperInvariant()
        if ($actual -ne $ExpectedExeSha256) { return $false }
    }
    return $true
}

if (-not (Test-Path $Exe)) {
    Install-OfficialAcpArchive -ArchiveUrl $url -Destination $VersionDir -ExePath $Exe
}

if (-not (Test-AcpBinaryIntegrity -Path $Exe)) {
    WARN "Cached ACP runtime failed integrity verification; downloading a clean copy."
    Install-OfficialAcpArchive -ArchiveUrl $url -Destination $VersionDir -ExePath $Exe
    if (-not (Test-AcpBinaryIntegrity -Path $Exe)) {
        FAIL "Official ACP runtime still fails integrity verification after a clean download."
    }
}

DEBUG "ACP registry version: $version"
DEBUG "ACP executable: $Exe"

$PyiTempBase = Join-Path $AcpRoot "pyi-temp"
New-Item -ItemType Directory -Force $PyiTempBase | Out-Null

Get-ChildItem $PyiTempBase -Directory -ErrorAction SilentlyContinue |
    Where-Object { $_.LastWriteTime -lt (Get-Date).AddHours(-12) } |
    Remove-Item -Recurse -Force -ErrorAction SilentlyContinue

$driveName = [IO.Path]::GetPathRoot($PyiTempBase).TrimEnd('\').TrimEnd(':')
$drive = Get-PSDrive -Name $driveName -ErrorAction SilentlyContinue
if ($drive -and $drive.Free -lt 1GB) {
    FAIL ("At least 1 GB free disk space is required for ACP startup. Free: {0:N2} GB" -f ($drive.Free / 1GB))
}
if ($drive) { DEBUG ("ACP extraction free space: {0:N2} GB" -f ($drive.Free / 1GB)) }

# Best-effort cleanup of the Hermes-owned ACP process tree.
$managed = Get-CimInstance Win32_Process -ErrorAction SilentlyContinue |
    Where-Object {
        $_.ExecutablePath -and
        $_.ExecutablePath.StartsWith($AcpRoot, [System.StringComparison]::OrdinalIgnoreCase)
    }

foreach ($p in ($managed | Where-Object { $_.Name -ieq "agy_acp_server.exe" })) {
    $pidToKill = [int]$p.ProcessId
    if (-not (Get-Process -Id $pidToKill -ErrorAction SilentlyContinue)) { continue }

    $oldPref = $ErrorActionPreference
    try {
        $ErrorActionPreference = "Continue"
        $null = & taskkill.exe /PID $pidToKill /T /F 2>&1
        $taskkillExit = $LASTEXITCODE
    } finally {
        $ErrorActionPreference = $oldPref
    }

    if ($taskkillExit -ne 0 -and (Get-Process -Id $pidToKill -ErrorAction SilentlyContinue)) {
        WARN "A stale ACP process could not be stopped (PID $pidToKill)."
    }
}

Start-Sleep -Milliseconds 300

Get-CimInstance Win32_Process -ErrorAction SilentlyContinue |
    Where-Object {
        $_.Name -ieq "localharness_external.exe" -and
        $_.ExecutablePath -and
        $_.ExecutablePath.StartsWith($AcpRoot, [System.StringComparison]::OrdinalIgnoreCase)
    } |
    ForEach-Object {
        Stop-Process -Id ([int]$_.ProcessId) -Force -ErrorAction SilentlyContinue
    }

$CurrentExe = $Exe
OK "Official ACP $version ready"

STEP "Installing provider and account manager..."
DEBUG "Provider source: $ProviderSource"
DEBUG "Desktop plugin source: $DesktopPluginSource"
DEBUG "Account helper source: $AccountHelperSource"

$dst = Join-Path $HH "plugins\model-providers\antigravity"
if (Test-Path $dst) { Remove-Item $dst -Recurse -Force }
New-Item -ItemType Directory -Force $dst | Out-Null
Copy-Item (Join-Path $ProviderSource "*") $dst -Recurse -Force

$legacy = Join-Path $HH "plugins\antigravity-manager"
if (Test-Path $legacy) { Remove-Item $legacy -Recurse -Force }

$PyCandidates = @(
    (Join-Path $Root "venv\Scripts\python.exe"),
    (Join-Path $Root ".venv\Scripts\python.exe")
)
$PyCandidates += @(Get-ChildItem (Join-Path $HH "tools") -Filter python.exe -Recurse -ErrorAction SilentlyContinue | Select-Object -ExpandProperty FullName)
$PyCandidates += @(Get-ChildItem (Join-Path $HH "installs") -Filter python.exe -Recurse -ErrorAction SilentlyContinue | Select-Object -ExpandProperty FullName)
$HermesPy = $PyCandidates | Where-Object { $_ -and (Test-Path $_) } | Select-Object -First 1
if (-not $HermesPy) { FAIL "Hermes Python runtime was not found." }

$Tools = Join-Path $HH "antigravity-tools"
New-Item -ItemType Directory -Force $Tools | Out-Null
Copy-Item $AccountHelperSource (Join-Path $Tools "account_helper.py") -Force

@{
    acpCommand = $CurrentExe
    acpVersion = $version
    providerDir = $dst
    workdir = $HermesWorkdir
} | ConvertTo-Json | Set-Content -LiteralPath (Join-Path $Tools "config.json") -Encoding UTF8

$AccountCmd = Join-Path $Tools "antigravity-account.cmd"
$cmdText = @"
@echo off
setlocal
"$HermesPy" "$Tools\account_helper.py" %*
exit /b %ERRORLEVEL%
"@
Set-Content -LiteralPath $AccountCmd -Value $cmdText -Encoding ASCII

$desk = Join-Path $HH "desktop-plugins\antigravity-manager"
if (Test-Path $desk) { Remove-Item $desk -Recurse -Force }

$desktopJs = $DesktopPluginSource
if (-not (Test-Path $desktopJs)) { FAIL "Desktop Antigravity plugin source is missing." }

New-Item -ItemType Directory -Force $desk | Out-Null
$js = Get-Content $desktopJs -Raw
$js = $js.Replace('__ACCOUNT_CMD__', $AccountCmd.Replace('\', '\\'))
Set-Content (Join-Path $desk "plugin.js") $js -Encoding UTF8

[Environment]::SetEnvironmentVariable("HERMES_ANTIGRAVITY_ACP_COMMAND", $CurrentExe, "User")
$env:HERMES_ANTIGRAVITY_ACP_COMMAND = $CurrentExe

OK "Provider and account manager installed"

STEP "Verifying installation..."

$oldPref = $ErrorActionPreference
try {
    $ErrorActionPreference = "Continue"
    $authOutput = (& $Hermes auth status antigravity 2>&1 | Out-String).Trim()
    $authExit = $LASTEXITCODE
} finally {
    $ErrorActionPreference = $oldPref
}
if ($authExit -ne 0) {
    if ($authOutput) { Write-Host $authOutput }
    FAIL "Hermes did not recognize the Antigravity provider."
}
DEBUG $authOutput

$oldPref = $ErrorActionPreference
try {
    $ErrorActionPreference = "Continue"
    $providerOutput = (& powershell.exe -NoProfile -ExecutionPolicy Bypass -File (Join-Path $Here "Smoke-Test-Provider.ps1") 2>&1 | Out-String).Trim()
    $providerExit = $LASTEXITCODE
} finally {
    $ErrorActionPreference = $oldPref
}
if ($providerExit -ne 0) {
    if ($providerOutput) { Write-Host $providerOutput }
    FAIL "Provider compatibility validation failed."
}
DEBUG "Provider import/create_client validation passed."

$e2eArgs = @("-NoProfile", "-ExecutionPolicy", "Bypass", "-File", (Join-Path $Here "Smoke-Test-E2E.ps1"))
if ($VerboseInstall) { $e2eArgs += "-VerboseOutput" }

$oldPref = $ErrorActionPreference
try {
    $ErrorActionPreference = "Continue"
    $e2eOutput = (& powershell.exe @e2eArgs 2>&1 | Out-String).Trim()
    $e2eExit = $LASTEXITCODE
} finally {
    $ErrorActionPreference = $oldPref
}

$marker = ($e2eOutput -split "\r?\n" | Where-Object { $_ -like "HERMES_AG_E2E|*" } | Select-Object -Last 1)
if ($VerboseInstall -and $e2eOutput) { Write-Host $e2eOutput }

if ($e2eExit -eq 0 -and $marker) {
    $parts = $marker.Split("|")
    $model = if ($parts.Length -gt 2) { $parts[2] } else { "Antigravity" }
    $seconds = if ($parts.Length -gt 3) { $parts[3] } else { "?" }
    OK "Live inference verified ($model, ${seconds}s)"
} elseif ($e2eExit -eq 10) {
    WARN "Google model capacity is temporarily exhausted; integration checks passed."
} else {
    if ($e2eOutput) { Write-Host $e2eOutput }
    FAIL "End-to-end Antigravity validation failed."
}

Write-Host ""
OK "Hermes Antigravity ACP 4.6.0 installed"
Write-Host "     Provider: official Google ACP" -ForegroundColor DarkGray
Write-Host "     Accounts: Antigravity tab in Hermes Desktop" -ForegroundColor DarkGray
Write-Host ""

if (-not $NoLaunch) {
    STEP "Opening Hermes Desktop..."
    try {
        Start-Process -FilePath $Hermes -ArgumentList @("desktop") | Out-Null
        OK "Hermes Desktop launched"
    } catch {
        WARN "Installation succeeded, but Hermes Desktop could not be opened automatically."
        DEBUG $_.Exception.Message
    }
}
