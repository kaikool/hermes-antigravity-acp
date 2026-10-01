param(
    [string]$Version = "4.6.0"
)

$ErrorActionPreference = "Stop"
$Repo = Split-Path -Parent (Split-Path -Parent $MyInvocation.MyCommand.Path)
$Dist = Join-Path $Repo "dist"
$Stage = Join-Path $Dist "hermes-antigravity-acp-v$Version-windows"

if (Test-Path $Stage) { Remove-Item $Stage -Recurse -Force }
New-Item -ItemType Directory -Force $Stage | Out-Null

Copy-Item (Join-Path $Repo "installer\Install.cmd") $Stage
Copy-Item (Join-Path $Repo "installer\install.ps1") $Stage
Copy-Item (Join-Path $Repo "installer\Smoke-Test-Provider.ps1") $Stage
Copy-Item (Join-Path $Repo "installer\Smoke-Test-E2E.ps1") $Stage
Copy-Item (Join-Path $Repo "README.md") $Stage
Copy-Item (Join-Path $Repo "LICENSE") $Stage

New-Item -ItemType Directory -Force (Join-Path $Stage "model-provider\antigravity") | Out-Null
Copy-Item (Join-Path $Repo "src\provider\antigravity\*") (Join-Path $Stage "model-provider\antigravity") -Recurse

New-Item -ItemType Directory -Force (Join-Path $Stage "antigravity-manager\desktop") | Out-Null
Copy-Item (Join-Path $Repo "src\desktop-plugin\plugin.js") (Join-Path $Stage "antigravity-manager\desktop\plugin.js")
Copy-Item (Join-Path $Repo "src\account-manager\account_helper.py") (Join-Path $Stage "antigravity-manager\account_helper.py")

$zip = Join-Path $Dist "hermes-antigravity-acp-v$Version-windows.zip"
if (Test-Path $zip) { Remove-Item $zip -Force }
Compress-Archive -Path $Stage -DestinationPath $zip -CompressionLevel Optimal
Write-Host $zip
