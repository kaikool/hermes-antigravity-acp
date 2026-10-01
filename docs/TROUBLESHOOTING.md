# Troubleshooting

## `MODEL_CAPACITY_EXHAUSTED` / HTTP 503

Google has no serving capacity for that model at the moment. This is not an integration failure.
Choose another model or retry later.

## `[PYI-...] Failed to extract ... decompression return code -1`

The Windows ACP bootstrap could not unpack its PyInstaller payload. The provider uses an isolated
TEMP directory and retries one confirmed extraction failure. Ensure the system drive has at least
1 GB free.

## `localharness_external.exe` is locked

The installer/runtime kills the full ACP process tree. Do not manually replace the versioned ACP
directory while a Hermes Antigravity session is running.

## Account `Access is denied`

4.5.0 no longer renames authenticated profile directories. Close old auth terminals created by
4.4.x and run the add-account flow again.

## Desktop tab does not appear

Use Hermes Desktop's plugin reload command or restart Desktop. Confirm:

```text
%LOCALAPPDATA%\hermes\desktop-plugins\antigravity-manager\plugin.js
```

exists.
