# Contributing

1. Keep Hermes core unmodified.
2. Keep the official ACP runtime external; do not commit Google binaries.
3. Do not parse, copy, or expose OAuth tokens.
4. Preserve account isolation and manual switching.
5. Run `python -m py_compile` on Python sources and `node --check` on the Desktop plugin.
6. Keep default installer output concise; diagnostics belong behind `--verbose`.
7. Any change to ACP lifecycle must preserve end-to-end validation.

Pull requests should describe Windows/Hermes/ACP versions used for testing.
