# Security

Please avoid posting OAuth credentials, token files, or full account-state directories in issues.

This integration:
- does not parse or copy Google OAuth tokens;
- gives each saved account its own `GEMINI_HOME`;
- stores only a profile name in the active-account pointer;
- downloads the ACP server from the official ACP Registry URL;
- never patches Hermes core.

For a security issue, use a private disclosure channel on the repository before opening a public issue.
