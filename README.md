# Hermes Antigravity ACP

A Windows integration that connects **Hermes Agent / Hermes Desktop** directly to
Google Antigravity through Google's official Agent Client Protocol (ACP) runtime.

> Independent community project. Not affiliated with or endorsed by Nous Research or Google.

## What it includes

- Native persistent ACP transport
- Official Google Antigravity ACP runtime downloaded from the ACP Registry
- No Hermes core patch
- No external Antigravity CLI dependency
- Isolated `GEMINI_HOME` and workspace
- PyInstaller extraction isolation and runtime integrity checks
- Capacity-aware live installation validation
- Compact Hermes Desktop Antigravity tab
- Multiple official-ACP Google accounts
- Manual account switching with no background polling
- Account-specific OAuth state with no token parsing or copying
- Model catalog read directly from the official ACP session and cached locally

## Requirements

- Windows 10/11 x64
- Hermes Agent / Hermes Desktop
- Internet access for the official ACP runtime and Google OAuth

No separate Antigravity command-line tool is required.

## Install

Extract the Windows release and run:

```bat
Install.cmd
```

For diagnostics:

```bat
Install.cmd --verbose
```

A successful installation opens Hermes Desktop automatically.

## Accounts

Open **Antigravity** in the Hermes Desktop sidebar.

- **Original Hermes login** is the default isolated ACP login.
- **Sign in** creates another isolated official-ACP OAuth profile.
- Wait for `AUTH_OK`, return to Hermes, click **Refresh**, then **Use**.
- Switching accounts restarts the Hermes gateway so the persistent ACP session is
  recreated under the selected account.

## Architecture

```text
Hermes
  -> Antigravity provider
  -> persistent AntigravityACPClient
  -> Google official Antigravity ACP runtime
  -> Antigravity model backend
```

The Desktop tab and Hermes model discovery read the model catalog from ACP itself;
there is no second CLI or model source.

See [`docs/ARCHITECTURE.md`](docs/ARCHITECTURE.md).

## Validated baseline

- Hermes Agent `v0.21.5+4927.g3294d68`
- OpenAI SDK `2.24.0`
- Google Antigravity ACP `1.2.1`
- Windows x64

## Build a release

```powershell
pwsh ./scripts/build-release.ps1
```

## License

MIT for this integration. Google Antigravity and its ACP runtime retain their own
licenses and terms. The official runtime is downloaded at install time and is not
redistributed by this repository.
