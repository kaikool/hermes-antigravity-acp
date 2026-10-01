$ErrorActionPreference = "Stop"

$HH = if ($env:HERMES_HOME) { $env:HERMES_HOME } else { Join-Path $env:LOCALAPPDATA "hermes" }
$Root = Join-Path $HH "hermes-agent"
$Provider = Join-Path $HH "plugins\model-providers\antigravity\__init__.py"

$candidates = @(
    (Join-Path $Root "venv\Scripts\python.exe"),
    (Join-Path $Root ".venv\Scripts\python.exe")
)
$candidates += @(Get-ChildItem (Join-Path $HH "tools") -Filter python.exe -Recurse -ErrorAction SilentlyContinue | Select-Object -ExpandProperty FullName)
$candidates += @(Get-ChildItem (Join-Path $HH "installs") -Filter python.exe -Recurse -ErrorAction SilentlyContinue | Select-Object -ExpandProperty FullName)

$Py = $candidates | Where-Object { $_ -and (Test-Path $_) } | Select-Object -First 1
if (-not $Py) { Write-Error "Hermes Python runtime not found."; exit 20 }

$T = Join-Path $env:TEMP "hermes-antigravity-provider-smoke-$PID.py"
@"
import importlib.util, pathlib, sys
root = pathlib.Path(r'$Root')
provider = pathlib.Path(r'$Provider')
sys.path.insert(0, str(root))

spec = importlib.util.spec_from_file_location(
    'providers.antigravity',
    provider,
    submodule_search_locations=[str(provider.parent)],
)
mod = importlib.util.module_from_spec(spec)
sys.modules['providers.antigravity'] = mod
spec.loader.exec_module(mod)

profile = mod.AntigravityProfile(
    name='antigravity',
    auth_type='external_process',
    base_url='acp://antigravity',
)
client = profile.create_client(
    api_key='antigravity',
    base_url='acp://antigravity',
    command=r'$env:HERMES_ANTIGRAVITY_ACP_COMMAND',
    args=[],
)
assert type(client).__name__ == 'AntigravityACPClient'
client.close()
"@ | Set-Content $T -Encoding UTF8

try {
    & $Py $T
    exit $LASTEXITCODE
} finally {
    Remove-Item $T -Force -ErrorAction SilentlyContinue
}
