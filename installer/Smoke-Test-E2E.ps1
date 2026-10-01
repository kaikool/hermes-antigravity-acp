param([switch]$VerboseOutput)
$ErrorActionPreference = "Stop"

$HH = if ($env:HERMES_HOME) { $env:HERMES_HOME } else { Join-Path $env:LOCALAPPDATA "hermes" }
$Root = Join-Path $HH "hermes-agent"
$Provider = Join-Path $HH "plugins\model-providers\antigravity"

$env:HERMES_ANTIGRAVITY_GEMINI_HOME = Join-Path $HH "antigravity-gemini-home"
$env:HERMES_ANTIGRAVITY_WORKDIR = Join-Path $HH "antigravity-workspace"
$env:HERMES_ANTIGRAVITY_PERMISSION_POLICY = "safe"

$candidates = @(
    (Join-Path $Root "venv\Scripts\python.exe"),
    (Join-Path $Root ".venv\Scripts\python.exe")
)
$candidates += @(Get-ChildItem (Join-Path $HH "tools") -Filter python.exe -Recurse -ErrorAction SilentlyContinue | Select-Object -ExpandProperty FullName)
$candidates += @(Get-ChildItem (Join-Path $HH "installs") -Filter python.exe -Recurse -ErrorAction SilentlyContinue | Select-Object -ExpandProperty FullName)
$Py = $candidates | Where-Object { $_ -and (Test-Path $_) } | Select-Object -First 1

if (-not $Py) { Write-Output "HERMES_AG_E2E|FAIL|python-runtime-not-found"; exit 20 }
if (-not $env:HERMES_ANTIGRAVITY_ACP_COMMAND) { Write-Output "HERMES_AG_E2E|FAIL|acp-command-not-set"; exit 21 }

$T = Join-Path $env:TEMP "hermes-antigravity-e2e-$PID.py"
@"
import importlib.util, json, os, pathlib, sys, time
root = pathlib.Path(r'$Root')
p = pathlib.Path(r'$Provider')
sys.path.insert(0, str(root))

spec = importlib.util.spec_from_file_location(
    'providers.antigravity',
    p / '__init__.py',
    submodule_search_locations=[str(p)],
)
m = importlib.util.module_from_spec(spec)
sys.modules['providers.antigravity'] = m
spec.loader.exec_module(m)

profile = m.AntigravityProfile(
    name='antigravity',
    auth_type='external_process',
    base_url='acp://antigravity',
)
client = profile.create_client(
    command=r'$env:HERMES_ANTIGRAVITY_ACP_COMMAND',
    args=[],
)

verbose = bool($VerboseOutput)
capacity_markers = (
    'MODEL_CAPACITY_EXHAUSTED',
    'No capacity available for model',
    'OVERLOADED_TOO_MANY_RETRIES_PER_REQUEST',
    'Status: UNAVAILABLE',
    'request failed (code 503)',
)

def capacity(text):
    t = str(text)
    return any(x in t for x in capacity_markers)

preferred = [
    'gemini-3.8-flash-low',
    'gemini-3.8-flash-medium',
    'gemini-3.8-flash-high',
    'gemini-3.7-flash-low',
    'gemini-3.7-flash-medium',
    'gemini-3.7-flash-high',
    'gemini-3.6-flash-low',
    'gemini-3.6-flash-medium',
    'gemini-3.6-flash-high',
    'gemini-3.1-pro-low',
    'gemini-3.1-pro-high',
    'claude-sonnet-4-6',
    'claude-opus-4-6-thinking',
    'gpt-oss-120b-medium',
]

def order(model):
    try: return preferred.index(model)
    except ValueError: return len(preferred) + 100

capacity_models = []
unexpected = []

try:
    try:
        models = list(client.list_models(timeout_seconds=300))
    except Exception as exc:
        if verbose: print('catalog warning:', str(exc).replace('\\n', ' ')[:800])
        models = []

    if not models:
        models = preferred[:]

    full_models = list(dict.fromkeys(str(x) for x in models if x))

    # Cache the official ACP catalog for Hermes model discovery and the Desktop
    # Antigravity tab. No external CLI is required.
    catalog_path = pathlib.Path(r'$HH') / 'antigravity-tools' / 'catalog.json'
    catalog_path.parent.mkdir(parents=True, exist_ok=True)
    catalog_path.write_text(
        json.dumps(
            {
                'source': 'official-acp',
                'models': [{'id': x, 'name': x} for x in full_models],
            },
            indent=2,
        ),
        encoding='utf-8',
    )

    models = sorted(full_models, key=order)[:6]

    for model in models:
        started = time.monotonic()
        if verbose: print('trying', model)
        try:
            response = client.chat.completions.create(
                model=model,
                messages=[{'role':'user','content':'Reply exactly: ANTIGRAVITY_V4_OK'}],
                timeout=180,
            )
            elapsed = time.monotonic() - started
            text = str(response.choices[0].message.content).strip()

            if 'ANTIGRAVITY_V4_OK' in text:
                print(f'HERMES_AG_E2E|OK|{model}|{elapsed:.1f}')
                raise SystemExit(0)
            if capacity(text):
                capacity_models.append(model)
                continue
            unexpected.append((model, text[:1000]))
        except SystemExit:
            raise
        except Exception as exc:
            text = str(exc)
            if capacity(text):
                capacity_models.append(model)
                continue
            unexpected.append((model, text[:1000]))

    if capacity_models and not unexpected:
        print('HERMES_AG_E2E|CAPACITY|' + ','.join(capacity_models))
        raise SystemExit(10)

    detail = '; '.join(
        f'{model}: {text}'.replace('\\n', ' ') for model, text in unexpected
    )[:1800]
    print('HERMES_AG_E2E|FAIL|' + (detail or 'unknown-e2e-failure'))
    raise SystemExit(7)
finally:
    client.close()
"@ | Set-Content $T -Encoding UTF8

try {
    & $Py $T
    exit $LASTEXITCODE
} finally {
    Remove-Item $T -Force -ErrorAction SilentlyContinue
}
