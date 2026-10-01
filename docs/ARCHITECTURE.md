# Architecture

## Inference path

```text
Hermes runtime
  -> provider `antigravity`
  -> `AntigravityACPClient`
  -> persistent ACP stdio process
  -> Google Antigravity
```

The provider keeps one ACP process/session alive for the lifetime of the Hermes client.

## Model catalog

There is one source of truth: the official ACP session.

During installation and manual refresh, the integration calls ACP model discovery and
writes a small cache:

```text
%LOCALAPPDATA%\hermes\antigravity-tools\catalog.json
```

Hermes provider discovery and the Desktop tab read this cache. No separate command-line
tool is required.

## Account isolation

Default login:

```text
%LOCALAPPDATA%\hermes\antigravity-gemini-home
```

Saved accounts:

```text
%LOCALAPPDATA%\hermes\antigravity-accounts\profiles\<name>\gemini-home
```

The selected account is a name-only pointer:

```text
%LOCALAPPDATA%\hermes\antigravity-accounts\active.txt
```

Each saved account is authenticated directly in its final directory. The profile is
marked `ready` only after the ACP process and its child harness are closed cleanly.

## Windows runtime bootstrap

The official Windows ACP runtime is a PyInstaller one-file executable. Each process gets
a private `TEMP/TMP/TMPDIR` under:

```text
%LOCALAPPDATA%\hermes\antigravity-acp\pyi-temp\run-*
```

The integration terminates the full ACP process tree on close because the runtime starts
a child local harness process.
