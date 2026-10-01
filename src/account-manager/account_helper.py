from __future__ import annotations

import argparse
import importlib.util
import json
import os
import re
import shutil
import sys
import time
import uuid
from datetime import datetime, timezone
from pathlib import Path

NAME_RE = re.compile(r"^[A-Za-z0-9_-]{1,48}$")
READY = "ready"
AUTHENTICATING = "authenticating"
FAILED = "failed"


def now_iso() -> str:
    return datetime.now(timezone.utc).isoformat().replace("+00:00", "Z")


def hermes_home() -> Path:
    explicit = os.environ.get("HERMES_HOME", "").strip()
    if explicit:
        return Path(explicit)
    local = os.environ.get("LOCALAPPDATA", "").strip()
    if not local:
        raise RuntimeError("LOCALAPPDATA is not defined")
    return Path(local) / "hermes"


def roots():
    hh = hermes_home()
    account_root = hh / "antigravity-accounts"
    profiles = account_root / "profiles"
    active = account_root / "active.txt"
    legacy = hh / "antigravity-gemini-home"
    tools = hh / "antigravity-tools"
    return hh, account_root, profiles, active, legacy, tools


def validate_name(name: str) -> str:
    if not NAME_RE.fullmatch(name or ""):
        raise RuntimeError(
            "Profile name must be 1-48 characters: letters, digits, '-' or '_'."
        )
    return name


def load_json(path: Path, default):
    try:
        return json.loads(path.read_text(encoding="utf-8-sig"))
    except Exception:
        return default


def write_json(path: Path, value: dict):
    path.parent.mkdir(parents=True, exist_ok=True)
    tmp = path.with_name(path.name + ".tmp-" + uuid.uuid4().hex)
    tmp.write_text(json.dumps(value, indent=2), encoding="utf-8")
    os.replace(tmp, path)


def atomic_text(path: Path, text: str):
    path.parent.mkdir(parents=True, exist_ok=True)
    tmp = path.with_name(path.name + ".tmp-" + uuid.uuid4().hex)
    tmp.write_text(text, encoding="utf-8")
    os.replace(tmp, path)


def metadata(profile_dir: Path) -> dict:
    return load_json(profile_dir / "profile.json", {})


def profile_home(profile_dir: Path) -> Path:
    return profile_dir / "gemini-home"


def ensure_oauth_settings(home: Path):
    cfg = home / "antigravity-acp"
    cfg.mkdir(parents=True, exist_ok=True)
    write_json(cfg / "settings.json", {"auth": {"type": "oauth-personal"}})


def active_name(active_file: Path) -> str | None:
    try:
        name = active_file.read_text(encoding="utf-8").strip()
        return name if NAME_RE.fullmatch(name) else None
    except Exception:
        return None


def remove_tree_retry(path: Path, attempts: int = 12, delay: float = 0.25) -> bool:
    if not path.exists():
        return True
    for _ in range(attempts):
        try:
            shutil.rmtree(path)
            return True
        except FileNotFoundError:
            return True
        except (PermissionError, OSError):
            time.sleep(delay)
    return not path.exists()


def ready_profile(profile_dir: Path) -> bool:
    meta = metadata(profile_dir)
    return meta.get("status") == READY and profile_home(profile_dir).is_dir()


def cleanup_old_pending(profiles: Path):
    # Clean leftovers from v4.4 staging and failed/incomplete v4.5 auth runs.
    now = time.time()
    for p in profiles.iterdir() if profiles.exists() else []:
        if not p.is_dir():
            continue
        if p.name.startswith(".new-"):
            try:
                if now - p.stat().st_mtime > 3600:
                    remove_tree_retry(p)
            except OSError:
                pass
            continue
        meta = metadata(p)
        if meta.get("status") in {AUTHENTICATING, FAILED}:
            stamp = meta.get("updatedAt") or meta.get("createdAt")
            # Do not parse timestamp aggressively; only remove obvious stale dirs by mtime.
            try:
                if now - p.stat().st_mtime > 86400:
                    remove_tree_retry(p)
            except OSError:
                pass


def cmd_list(_args) -> int:
    hh, account_root, profiles, active, legacy, tools = roots()
    profiles.mkdir(parents=True, exist_ok=True)
    cleanup_old_pending(profiles)

    current = active_name(active)
    rows = []
    valid_names = set()

    for p in sorted(profiles.iterdir(), key=lambda x: x.name.lower()):
        if not p.is_dir() or not NAME_RE.fullmatch(p.name) or not ready_profile(p):
            continue
        valid_names.add(p.name)
        meta = metadata(p)
        rows.append(
            {
                "name": p.name,
                "active": p.name == current,
                "createdAt": meta.get("createdAt"),
                "verifiedAt": meta.get("verifiedAt"),
                "modelsSeen": meta.get("modelsSeen"),
            }
        )

    # If a profile was manually removed, do not leave a dangling active pointer.
    if current and current not in valid_names:
        active.unlink(missing_ok=True)
        current = None

    print(
        json.dumps(
            {
                "profiles": rows,
                "active": current,
                "mode": "profile" if current else "original",
                "legacyExists": legacy.exists(),
                "originalLabel": "Original Hermes login",
            },
            ensure_ascii=False,
        )
    )
    return 0


def cmd_switch(args) -> int:
    name = validate_name(args.name)
    hh, account_root, profiles, active, legacy, tools = roots()
    p = profiles / name
    if not ready_profile(p):
        raise RuntimeError(f"Saved account '{name}' is not ready or does not exist.")
    atomic_text(active, name + "\n")
    print(json.dumps({"ok": True, "active": name}))
    return 0


def cmd_original(_args) -> int:
    hh, account_root, profiles, active, legacy, tools = roots()
    active.unlink(missing_ok=True)
    print(json.dumps({"ok": True, "active": None, "mode": "original"}))
    return 0


def cmd_delete(args) -> int:
    name = validate_name(args.name)
    hh, account_root, profiles, active, legacy, tools = roots()
    if active_name(active) == name:
        raise RuntimeError("Cannot delete the active account. Switch accounts first.")

    p = profiles / name
    if not p.exists():
        raise RuntimeError(f"Saved account '{name}' does not exist.")

    if not remove_tree_retry(p):
        raise RuntimeError(
            f"Could not remove '{name}' because Windows is still holding files open. "
            "Close any account-auth terminal and try again."
        )

    print(json.dumps({"ok": True, "deleted": name}))
    return 0


def load_runtime_config() -> dict:
    hh, account_root, profiles, active, legacy, tools = roots()
    cfg = load_json(tools / "config.json", {})
    acp = str(cfg.get("acpCommand") or "").strip()
    provider_dir = Path(str(cfg.get("providerDir") or "")).expanduser()
    workdir = Path(str(cfg.get("workdir") or "")).expanduser()

    if not acp or not Path(acp).is_file():
        raise RuntimeError("Official ACP command is not configured or no longer exists.")
    if not (provider_dir / "native_acp_client.py").is_file():
        raise RuntimeError("Installed Antigravity provider client was not found.")

    workdir.mkdir(parents=True, exist_ok=True)
    return {
        "acp": acp,
        "acpVersion": str(cfg.get("acpVersion") or "unknown"),
        "providerDir": provider_dir,
        "workdir": workdir,
    }


def load_client(provider_dir: Path):
    path = provider_dir / "native_acp_client.py"
    spec = importlib.util.spec_from_file_location(
        "hermes_antigravity_account_client", path
    )
    if not spec or not spec.loader:
        raise RuntimeError("Could not load Antigravity ACP client.")
    mod = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(mod)
    return mod.AntigravityACPClient



def catalog_path() -> Path:
    return hermes_home() / "antigravity-tools" / "catalog.json"


def display_model_name(model_id: str) -> str:
    # Model IDs are already clear and stable; keep display text deterministic
    # instead of inventing marketing labels that could become stale.
    return model_id


def save_catalog(models: list[str], acp_version: str):
    unique = list(dict.fromkeys(str(x).strip() for x in models if str(x).strip()))
    write_json(
        catalog_path(),
        {
            "source": "official-acp",
            "acpVersion": acp_version,
            "updatedAt": now_iso(),
            "models": [
                {"id": model_id, "name": display_model_name(model_id)}
                for model_id in unique
            ],
        },
    )


def load_catalog() -> list[dict]:
    data = load_json(catalog_path(), {})
    rows = []
    for item in data.get("models") or []:
        if isinstance(item, str):
            model_id = item.strip()
            name = model_id
        elif isinstance(item, dict):
            model_id = str(item.get("id") or "").strip()
            name = str(item.get("name") or model_id).strip()
        else:
            continue
        if model_id:
            rows.append({"id": model_id, "name": name or model_id})
    return rows


def selected_gemini_home() -> Path:
    hh, account_root, profiles, active, legacy, tools = roots()
    name = active_name(active)
    if name:
        p = profiles / name
        if ready_profile(p):
            return profile_home(p)
    return legacy


def cmd_status(args) -> int:
    runtime = load_runtime_config()
    models = load_catalog()

    if args.refresh or not models:
        Client = load_client(runtime["providerDir"])
        client = Client(
            command=runtime["acp"],
            args=[],
            cwd=str(runtime["workdir"]),
            gemini_home=str(selected_gemini_home()),
        )
        try:
            model_ids = list(client.list_models(timeout_seconds=300) or [])
            save_catalog(model_ids, runtime["acpVersion"])
            models = load_catalog()
        finally:
            try:
                client.close()
            except Exception:
                pass

    hh, account_root, profiles, active, legacy, tools = roots()
    current = active_name(active)

    print(
        json.dumps(
            {
                "connected": Path(runtime["acp"]).is_file(),
                "version": runtime["acpVersion"],
                "models": models,
                "active": current,
            },
            ensure_ascii=False,
        )
    )
    return 0

def cmd_auth(args) -> int:
    name = validate_name(args.name)
    hh, account_root, profiles, active, legacy, tools = roots()
    profiles.mkdir(parents=True, exist_ok=True)
    cleanup_old_pending(profiles)

    final_dir = profiles / name
    if final_dir.exists():
        meta = metadata(final_dir)
        if meta.get("status") == READY:
            raise RuntimeError(
                f"Account profile '{name}' already exists. Remove it first if you want a fresh login."
            )
        if not remove_tree_retry(final_dir):
            raise RuntimeError(
                f"A previous incomplete profile '{name}' is still locked. "
                "Close its auth terminal and try again."
            )

    runtime = load_runtime_config()

    # Important Windows behavior:
    # authenticate directly in the final profile path. Older builds authenticated
    # in .new-<name> and then renamed the directory while the ACP runtime
    # still held handles inside GEMINI_HOME, causing WinError 5.
    home = profile_home(final_dir)
    final_dir.mkdir(parents=True, exist_ok=False)
    ensure_oauth_settings(home)

    meta = {
        "name": name,
        "status": AUTHENTICATING,
        "createdAt": now_iso(),
        "updatedAt": now_iso(),
        "verifiedAt": None,
        "modelsSeen": 0,
    }
    write_json(final_dir / "profile.json", meta)

    print("")
    print(f"Creating Antigravity account profile: {name}")
    print("Google OAuth will open in your browser if authentication is needed.")
    print("Complete sign-in, then return to this window.")
    print("")

    Client = load_client(runtime["providerDir"])
    client = Client(
        command=runtime["acp"],
        args=[],
        cwd=str(runtime["workdir"]),
        gemini_home=str(home),
    )

    auth_error = None
    models = []
    try:
        models = client.list_models(timeout_seconds=600) or []
    except Exception as exc:
        auth_error = exc
    finally:
        # Release the ACP server and its local harness BEFORE changing profile
        # state or trying to remove files. This is mandatory on Windows.
        try:
            client.close()
        except Exception:
            pass
        time.sleep(0.5)

    if auth_error is not None:
        meta["status"] = FAILED
        meta["updatedAt"] = now_iso()
        meta["error"] = str(auth_error)[:1200]
        try:
            write_json(final_dir / "profile.json", meta)
        except Exception:
            pass

        # Best effort. If AV/Windows still holds a file briefly, leave the FAILED
        # profile hidden from list/switch instead of deleting valid user state blindly.
        remove_tree_retry(final_dir, attempts=8, delay=0.25)
        raise auth_error

    meta["status"] = READY
    meta["updatedAt"] = now_iso()
    meta["verifiedAt"] = now_iso()
    meta["modelsSeen"] = len(models)
    write_json(final_dir / "profile.json", meta)
    save_catalog(list(models), runtime["acpVersion"])

    print("")
    print(f"AUTH_OK: {name}")
    print(f"Models visible: {meta['modelsSeen']}")
    print("Return to Hermes, click Refresh, then Switch.")
    return 0


def main() -> int:
    ap = argparse.ArgumentParser(prog="antigravity-account")
    sub = ap.add_subparsers(dest="cmd", required=True)

    sub.add_parser("list")

    p = sub.add_parser("status")
    p.add_argument("--refresh", action="store_true")

    p = sub.add_parser("switch")
    p.add_argument("name")

    sub.add_parser("original")

    p = sub.add_parser("delete")
    p.add_argument("name")

    p = sub.add_parser("auth")
    p.add_argument("name")

    args = ap.parse_args()
    return {
        "list": cmd_list,
        "status": cmd_status,
        "switch": cmd_switch,
        "original": cmd_original,
        "delete": cmd_delete,
        "auth": cmd_auth,
    }[args.cmd](args)


if __name__ == "__main__":
    try:
        raise SystemExit(main())
    except KeyboardInterrupt:
        print("Cancelled.", file=sys.stderr)
        raise SystemExit(130)
    except Exception as exc:
        print(f"ERROR: {exc}", file=sys.stderr)
        raise SystemExit(1)
