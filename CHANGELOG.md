# Changelog

## 4.6.0

- Renamed the project/release branding to **Hermes Antigravity ACP**.
- Removed the external Antigravity CLI dependency completely.
- Removed CLI probing from the installer and Desktop plugin.
- Model discovery now comes directly from the official ACP session and is cached locally.
- Hermes provider model discovery reads the same ACP catalog cache as the Desktop tab.
- Desktop status now shows ACP runtime version rather than a separate CLI version.
- Removed old migration code that modified the user's normal Antigravity CLI/IDE configuration.
- Kept the compact account manager, persistent transport, isolated OAuth profiles,
  PyInstaller hardening, process-tree cleanup, and capacity-aware validation.

## 4.5.2

- Reworked the Hermes Desktop Antigravity page for a compact release UI.
- Converted all Desktop plugin labels/messages to ASCII-only text to prevent mojibake/encoding artifacts.
- Replaced the full model list with one compact dropdown plus selected-model details.
- Condensed account rows and added top-level connection/account/version summary cards.
- Kept model selection informational; actual inference model remains controlled by Hermes model settings.
- No transport, OAuth, account storage, or Hermes core changes.

## 4.5.1

- Fixed release ZIP installer path resolution.
- Installer now supports both repository layout (`src/...`) and packaged runtime layout
  (`model-provider/...`, `antigravity-manager/...`).
- Added validation that the packaged release can resolve all provider/UI/account-manager sources.

## 4.5.0

- Productionized installer output; verbose diagnostics are opt-in.
- Automatically launches Hermes Desktop after a successful install.
- Reworked account creation to avoid Windows directory-renaming locks.
- Account profiles now use explicit lifecycle states: `authenticating`, `ready`, `failed`.
- Official ACP is closed before a profile becomes switchable.
- Added stale/incomplete profile cleanup.
- Added GitHub-ready repository structure, CI validation, release builder, architecture docs,
  troubleshooting guide, contribution guide, and MIT license.
- Retains all 4.3.x transport reliability fixes and the 4.4 multi-account UI.

## 4.4.1

- Fixed harmless `taskkill` process-disappearance race aborting installation.

## 4.4.0

- Added official-ACP multi-account manager and Hermes Desktop Antigravity tab.

## 4.3.3

- Added isolated per-process PyInstaller TEMP, runtime integrity checks, and targeted bootstrap retry.

## 4.3.2

- Added capacity-aware multi-model E2E validation.

## 4.3.1

- Switched to immutable versioned ACP runtime and full Windows process-tree cleanup.

## 4.3.0

- Hardened ACP lifecycle, permissions, timeout/cancel behavior, and isolated workspace/config.
