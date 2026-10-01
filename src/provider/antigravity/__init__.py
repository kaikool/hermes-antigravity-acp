from __future__ import annotations

import json
import os
from pathlib import Path
from typing import Any

from providers import register_provider
from providers.base import ProviderProfile


def _hermes_home() -> Path:
    explicit = os.environ.get("HERMES_HOME", "").strip()
    if explicit:
        return Path(explicit)
    local = os.environ.get("LOCALAPPDATA") or os.path.expanduser("~")
    return Path(local) / "hermes"


def _official_acp() -> str:
    override = os.environ.get("HERMES_ANTIGRAVITY_ACP_COMMAND", "").strip()
    if override:
        return override

    # Compatibility fallback. Current installers always pin the immutable
    # registry-versioned runtime through HERMES_ANTIGRAVITY_ACP_COMMAND.
    return str(
        _hermes_home()
        / "antigravity-acp"
        / "current"
        / "agy_acp_server.exe"
    )


def _catalog_path() -> Path:
    return _hermes_home() / "antigravity-tools" / "catalog.json"


def _catalog() -> list[dict[str, str]]:
    try:
        data = json.loads(_catalog_path().read_text(encoding="utf-8-sig"))
    except Exception:
        return []

    raw = data.get("models") if isinstance(data, dict) else None
    rows: list[dict[str, str]] = []
    seen: set[str] = set()

    for item in raw or []:
        if isinstance(item, str):
            model_id = item.strip()
            label = model_id
        elif isinstance(item, dict):
            model_id = str(item.get("id") or "").strip()
            label = str(item.get("name") or item.get("label") or model_id).strip()
        else:
            continue

        if not model_id or model_id in seen:
            continue
        seen.add(model_id)
        rows.append(
            {
                "id": model_id,
                "label": label or model_id,
                "note": "Google Antigravity via official ACP",
            }
        )

    return rows


class AntigravityProfile(ProviderProfile):
    def fetch_models(self, *, api_key=None, base_url=None, timeout=8.0):
        rows = _catalog()
        return [x["id"] for x in rows] or None

    def discover_models(self, **kwargs: Any):
        return _catalog() or None

    def setup_status(self, **kwargs: Any):
        command = _official_acp()
        available = os.path.isfile(command)
        return {
            "available": available,
            # Authentication is owned by the official ACP server and verified
            # by the installer's end-to-end check / account profiles.
            "logged_in": available,
            "plan": None,
            "detail": (
                "Official Google Antigravity ACP runtime is ready."
                if available
                else "Official Google Antigravity ACP runtime is not installed."
            ),
            "login_command": None,
        }

    def supported_reasoning_efforts(self, model: str | None):
        # Antigravity model IDs already encode low/medium/high where applicable.
        return ()

    def create_client(self, **client_kwargs: Any):
        from .native_acp_client import AntigravityACPClient

        command = str(
            client_kwargs.get("command")
            or client_kwargs.get("process_command")
            or _official_acp()
        )
        args = list(
            client_kwargs.get("args")
            or client_kwargs.get("process_args")
            or []
        )
        workdir = (
            os.environ.get("HERMES_ANTIGRAVITY_WORKDIR")
            or str(_hermes_home() / "antigravity-workspace")
        )

        return AntigravityACPClient(
            command=command,
            args=args,
            cwd=workdir,
        )


register_provider(
    AntigravityProfile(
        name="antigravity",
        aliases=("google-antigravity", "antigravity-acp"),
        display_name="Google Antigravity",
        description="Google Antigravity through the official Agent Client Protocol server.",
        auth_type="external_process",
        base_url="acp://antigravity",
        process_command=_official_acp(),
        process_args=(),
        process_command_env_vars=("HERMES_ANTIGRAVITY_ACP_COMMAND",),
        process_args_env_var="HERMES_ANTIGRAVITY_ACP_ARGS",
        fallback_models=(),
    )
)
