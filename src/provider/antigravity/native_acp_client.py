from __future__ import annotations

import json
import os
import queue
import re
import subprocess
import threading
import time
import webbrowser
import shutil
import tempfile
import uuid
from collections import deque
from pathlib import Path
from types import SimpleNamespace
from typing import Any

_INIT = {
    "protocolVersion": 1,
    # Hermes uses Antigravity strictly as a model provider. Do not advertise
    # client filesystem or terminal capabilities that we do not want the agent
    # to depend on.
    "clientCapabilities": {},
    "clientInfo": {
        "name": "hermes-antigravity",
        "title": "Hermes Antigravity",
        "version": "4.6.0",
    },
}

_OAUTH_URL = re.compile(
    r"https://accounts\.google\.com/o/oauth2/v2/auth\?[^\s\'\"<>]+"
)
_AUTH_PREF = ("oauth-personal", "oauth-business", "agent-platform", "gemini-api-key")
_SAFE_TOOL_KINDS = {"read", "search", "think", "fetch"}
_MUTATING_TOOL_KINDS = {"edit", "delete", "move", "execute", "switch_mode"}


class _Chat:
    def __init__(self, completions: Any):
        self.completions = completions


class AntigravityACPClient:
    """Persistent ACP v1 client for Google's official Antigravity ACP server.

    Design goals for Hermes:
    - one long-lived ACP process/session per provider client;
    - mcpServers=[] so IDE/CLI MCPs are never injected by Hermes;
    - isolated GEMINI_HOME and isolated workspace;
    - model-only posture: no client FS/terminal capability advertisement;
    - safe permission policy by default;
    - bounded prompt watchdog with session/cancel instead of silent hangs.
    """

    HERMES_SKIP_TRANSPORT_WRAP = True
    HERMES_SKIP_ASYNC_WRAP = True

    def __init__(
        self,
        command: str,
        args: list[str] | None = None,
        cwd: str | None = None,
        gemini_home: str | None = None,
    ):
        self.command = command
        self.args = list(args or [])
        self._explicit_gemini_home = (
            os.path.abspath(gemini_home) if gemini_home else None
        )

        local = os.environ.get("LOCALAPPDATA") or os.path.expanduser("~")
        default_workspace = os.path.join(local, "hermes", "antigravity-workspace")
        self.cwd = os.path.abspath(
            cwd
            or os.environ.get("HERMES_ANTIGRAVITY_WORKDIR", "").strip()
            or default_workspace
        )
        os.makedirs(self.cwd, exist_ok=True)

        self.chat = _Chat(self)
        self.completions = self

        self._lock = threading.RLock()
        self._proc: subprocess.Popen[str] | None = None
        self._inbox: queue.Queue[dict[str, Any]] = queue.Queue()
        self._stderr: deque[str] = deque(maxlen=120)
        self._events: deque[str] = deque(maxlen=80)
        self._rid = 0
        self._session: dict[str, Any] | None = None
        self._protocol_version = 1
        self._pyi_temp_root: str | None = None
        self.is_closed = False

    @staticmethod
    def _is_pyinstaller_extract_error(text: str) -> bool:
        t = str(text or "")
        return (
            "[PYI-" in t
            and (
                "Failed to extract" in t
                or "decompression resulted in return code" in t
                or "Failed to extract entry" in t
            )
        )

    def _new_pyinstaller_temp(self) -> str:
        local = os.environ.get("LOCALAPPDATA") or tempfile.gettempdir()
        base = os.path.join(local, "hermes", "antigravity-acp", "pyi-temp")
        os.makedirs(base, exist_ok=True)

        # Google's current Windows one-file bundle expands to roughly 327 MB.
        # Require comfortable headroom so PyInstaller does not fail mid-inflate.
        try:
            free = shutil.disk_usage(base).free
            if free < 1024 * 1024 * 1024:
                raise RuntimeError(
                    "Antigravity ACP needs at least 1 GB free disk space for "
                    f"PyInstaller extraction; only {free / (1024**3):.2f} GB is free "
                    f"on {os.path.splitdrive(base)[0] or base}."
                )
        except OSError:
            pass

        run = os.path.join(base, "run-" + uuid.uuid4().hex)
        os.makedirs(run, exist_ok=False)
        self._pyi_temp_root = run
        return run

    def _cleanup_pyinstaller_temp(self):
        run = self._pyi_temp_root
        self._pyi_temp_root = None
        if not run:
            return
        try:
            shutil.rmtree(run, ignore_errors=True)
        except Exception:
            pass

    # ---------- lifecycle ----------

    def close(self):
        with self._lock:
            self._stop()
            self.is_closed = True

    def _stop(self):
        p = self._proc
        self._proc = None
        self._session = None
        if p and p.poll() is None:
            # agy_acp_server.exe launches localharness_external.exe. On Windows,
            # terminating only the ACP parent can orphan the harness and leave
            # its executable locked. Kill the process tree owned by this ACP PID.
            if os.name == "nt":
                try:
                    subprocess.run(
                        ["taskkill", "/PID", str(p.pid), "/T", "/F"],
                        stdout=subprocess.DEVNULL,
                        stderr=subprocess.DEVNULL,
                        timeout=10,
                        creationflags=getattr(subprocess, "CREATE_NO_WINDOW", 0),
                    )
                except Exception:
                    pass
            try:
                if p.poll() is None:
                    p.terminate()
                    p.wait(timeout=2)
            except Exception:
                try:
                    p.kill()
                except Exception:
                    pass
        self._cleanup_pyinstaller_temp()

    def _event(self, text: str):
        stamp = time.strftime("%H:%M:%S")
        self._events.append(f"{stamp} {text}")

    def _diag(self) -> str:
        parts = []
        if self._events:
            parts.append("recent ACP events:\n" + "\n".join(self._events))
        if self._stderr:
            tail = "\n".join(self._stderr)
            parts.append("server stderr tail:\n" + tail[-5000:])
        return "\n\n".join(parts)

    def _isolated_gemini_home(self) -> str:
        if self._explicit_gemini_home:
            return self._explicit_gemini_home

        local = os.environ.get("LOCALAPPDATA") or self.cwd
        hermes_home = os.environ.get("HERMES_HOME") or os.path.join(local, "hermes")

        # v4.4 account manager: the active profile is a tiny name-only pointer.
        # Each saved account gets a completely separate GEMINI_HOME, so official
        # ACP OAuth/session state never needs token copying or credential parsing.
        active_file = os.path.join(
            hermes_home, "antigravity-accounts", "active.txt"
        )
        try:
            name = Path(active_file).read_text(encoding="utf-8").strip()
            if re.fullmatch(r"[A-Za-z0-9_-]{1,48}", name):
                home = os.path.join(
                    hermes_home,
                    "antigravity-accounts",
                    "profiles",
                    name,
                    "gemini-home",
                )
                if os.path.isdir(home):
                    return os.path.abspath(home)
        except Exception:
            pass

        # No saved profile selected: preserve the known-good v4.3.x login.
        return os.path.abspath(
            os.environ.get("HERMES_ANTIGRAVITY_GEMINI_HOME", "").strip()
            or os.path.join(hermes_home, "antigravity-gemini-home")
        )

    def _spawn(self, initial_model: str | None = None):
        self._stop()

        env = os.environ.copy()

        # agy_acp_server.exe 1.2.1 is a PyInstaller one-file executable. Give every
        # spawn its own local extraction root so concurrent/stale _MEI trees and
        # a polluted system %TEMP% cannot corrupt bootstrap extraction.
        pyi_temp = self._new_pyinstaller_temp()
        env["TEMP"] = pyi_temp
        env["TMP"] = pyi_temp
        env["TMPDIR"] = pyi_temp

        gemini_home = self._isolated_gemini_home()
        os.makedirs(os.path.join(gemini_home, "antigravity-acp"), exist_ok=True)
        env["GEMINI_HOME"] = gemini_home

        # Avoid a harness restart on session setup when Hermes already selected
        # a model. Google ACP 1.2.1 honors this before session/new.
        if initial_model:
            env["AGY_ACP_DEFAULT_MODEL"] = initial_model

        # Keep loopback OAuth out of corporate/system proxy paths where possible.
        existing_no_proxy = env.get("NO_PROXY") or env.get("no_proxy") or ""
        loopback = "127.0.0.1,localhost,::1"
        merged = ",".join(x for x in (existing_no_proxy, loopback) if x)
        env["NO_PROXY"] = merged
        env["no_proxy"] = merged

        flags = getattr(subprocess, "CREATE_NO_WINDOW", 0) if os.name == "nt" else 0
        try:
            p = subprocess.Popen(
            [self.command, *self.args],
            stdin=subprocess.PIPE,
            stdout=subprocess.PIPE,
            stderr=subprocess.PIPE,
            text=True,
            encoding="utf-8",
            errors="replace",
            bufsize=1,
            cwd=self.cwd,
            env=env,
            creationflags=flags,
            )
        except Exception:
            self._cleanup_pyinstaller_temp()
            raise
        if not p.stdin or not p.stdout:
            raise RuntimeError("Antigravity ACP stdio unavailable")
        self._proc = p
        self._event(f"spawn pid={p.pid}")

        def pump_out():
            assert p.stdout is not None
            for line in p.stdout:
                raw = line.rstrip("\r\n")
                if not raw:
                    continue
                try:
                    msg = json.loads(raw)
                    if isinstance(msg, dict):
                        self._inbox.put(msg)
                    else:
                        self._event("rx non-object JSON")
                except Exception:
                    # Preserve framing failures for diagnostics without crashing
                    # the reader thread.
                    self._event("rx invalid-json " + raw[:240])

        def pump_err():
            if not p.stderr:
                return
            for line in p.stderr:
                line = line.rstrip()
                self._stderr.append(line)

                # The official server owns OAuth callback/token exchange. We only
                # open the exact Google authorization endpoint it prints.
                m = _OAUTH_URL.search(line)
                if not m:
                    continue
                url = m.group(0).rstrip(".,);]}'\\\"")
                try:
                    from urllib.parse import urlsplit

                    u = urlsplit(url)
                    if (
                        u.scheme == "https"
                        and u.hostname == "accounts.google.com"
                        and u.path == "/o/oauth2/v2/auth"
                        and u.query
                    ):
                        webbrowser.open(url)
                        self._event("opened OAuth authorization URL")
                except Exception:
                    pass

        threading.Thread(target=pump_out, daemon=True).start()
        threading.Thread(target=pump_err, daemon=True).start()

    # ---------- wire helpers ----------

    def _send(self, obj: dict[str, Any]):
        p = self._proc
        if not p or p.poll() is not None or not p.stdin:
            raise RuntimeError("Antigravity ACP process is not running")
        p.stdin.write(json.dumps(obj, separators=(",", ":")) + "\n")
        p.stdin.flush()

        method = obj.get("method")
        if method:
            self._event(f"tx {method} id={obj.get('id', '-')}")
        elif "id" in obj:
            self._event(f"tx response id={obj.get('id')}")

    def _cancel_session(self):
        if not self._session or not self._session.get("sessionId"):
            return
        try:
            self._send(
                {
                    "jsonrpc": "2.0",
                    "method": "session/cancel",
                    "params": {"sessionId": self._session["sessionId"]},
                }
            )
        except Exception:
            pass

    @staticmethod
    def _extract_text(content: Any) -> str:
        if isinstance(content, str):
            return content
        if isinstance(content, dict):
            if content.get("type") == "text" and isinstance(content.get("text"), str):
                return content["text"]
            if isinstance(content.get("text"), str):
                return content["text"]
            return ""
        if isinstance(content, list):
            return "".join(AntigravityACPClient._extract_text(x) for x in content)
        return ""

    def _handle_update(
        self,
        msg: dict[str, Any],
        text: list[str] | None,
        reasoning: list[str] | None,
    ) -> tuple[bool, str | None]:
        params = msg.get("params") or {}
        u = params.get("update") or {}
        kind = str(u.get("sessionUpdate") or u.get("type") or "")
        self._event(f"rx update {kind or 'unknown'}")

        content = self._extract_text(u.get("content"))
        if content:
            kl = kind.lower()
            if "thought" in kl or "reason" in kl:
                if reasoning is not None:
                    reasoning.append(content)
            elif "agent_message" in kl or kl in {"message", "agent_message_chunk"}:
                if text is not None:
                    text.append(content)

        # ACP v2 compatibility: session/prompt response is only an insertion
        # acknowledgement; completion is an idle state_update.
        if kind == "state_update" and str(u.get("state")) == "idle":
            return True, str(u.get("stopReason") or "end_turn")
        return False, None

    def _permission_decision(self, params: dict[str, Any]) -> tuple[dict[str, Any], bool]:
        options = [x for x in (params.get("options") or []) if isinstance(x, dict)]

        tool = params.get("toolCall") or {}
        if not tool and isinstance(params.get("subject"), dict):
            subject = params["subject"]
            tool = subject.get("toolCall") or {}
            if not tool and subject.get("type") == "command":
                tool = {"kind": "execute"}

        kind = str((tool or {}).get("kind") or "other").lower()
        policy = os.environ.get("HERMES_ANTIGRAVITY_PERMISSION_POLICY", "safe").strip().lower()

        allow = None
        reject = None
        for opt in options:
            k = str(opt.get("kind") or "").lower()
            if allow is None and k in {"allow_once", "allow_always"}:
                allow = opt
            if reject is None and k in {"reject_once", "reject_always"}:
                reject = opt

        should_allow = (
            policy in {"allow", "allow_all", "yolo"}
            or (policy == "safe" and kind in _SAFE_TOOL_KINDS)
        )

        chosen = allow if should_allow else reject
        if chosen and chosen.get("optionId") is not None:
            self._event(
                f"permission {'allow' if should_allow else 'reject'} kind={kind}"
            )
            return (
                {
                    "outcome": {
                        "outcome": "selected",
                        "optionId": chosen["optionId"],
                    }
                },
                not should_allow,
            )

        self._event(f"permission cancelled kind={kind}")
        return ({"outcome": {"outcome": "cancelled"}}, True)

    def _server_request(self, msg: dict[str, Any]) -> bool:
        """Handle Agent->Client requests.

        Returns True when a permission was denied/cancelled. That lets the prompt
        watchdog avoid waiting forever after the agent has been told it cannot
        perform the requested action.
        """
        mid = msg.get("id")
        method = str(msg.get("method") or "")
        params = msg.get("params") or {}
        self._event(f"rx request {method} id={mid}")

        if method == "session/request_permission":
            result, denied = self._permission_decision(params)
            self._send({"jsonrpc": "2.0", "id": mid, "result": result})
            return denied

        if method == "elicitation/create":
            self._send(
                {
                    "jsonrpc": "2.0",
                    "id": mid,
                    "result": {"action": "decline"},
                }
            )
            return True

        # We intentionally do not advertise fs/terminal capabilities. If an
        # agent still asks for one, fail the request explicitly instead of
        # leaving it pending and deadlocking session/prompt.
        self._send(
            {
                "jsonrpc": "2.0",
                "id": mid,
                "error": {
                    "code": -32601,
                    "message": f"Unsupported Hermes model-provider client method: {method}",
                },
            }
        )
        return method.startswith(("fs/", "terminal/"))

    def _request(
        self,
        method: str,
        params: dict[str, Any],
        timeout: float = 180,
        text: list[str] | None = None,
        reasoning: list[str] | None = None,
    ):
        self._rid += 1
        rid = self._rid
        self._send({"jsonrpc": "2.0", "id": rid, "method": method, "params": params})

        end = time.monotonic() + timeout
        while time.monotonic() < end:
            p = self._proc
            if not p or p.poll() is not None:
                raise RuntimeError(
                    "Antigravity ACP exited unexpectedly.\n" + self._diag()
                )
            try:
                m = self._inbox.get(timeout=0.1)
            except queue.Empty:
                continue

            if "method" in m and "id" in m:
                self._server_request(m)
                continue

            if m.get("method") == "session/update":
                self._handle_update(m, text, reasoning)
                continue

            if m.get("id") != rid:
                self._event(f"rx unrelated response id={m.get('id')}")
                continue

            if "error" in m:
                e = m.get("error") or {}
                self._event(f"rx error {method}")
                raise RuntimeError(str(e.get("message") or e))

            self._event(f"rx response {method}")
            return m.get("result")

        raise TimeoutError(f"Antigravity ACP timeout waiting for {method}.\n{self._diag()}")

    # ---------- auth/session ----------

    def _choose_auth(self, methods: Any) -> str | None:
        ids: list[str] = []
        for m in methods or []:
            if not isinstance(m, dict):
                continue
            typ = str(m.get("type") or "agent")
            if typ == "terminal":
                continue
            mid = str(m.get("id") or m.get("methodId") or "")
            if mid:
                ids.append(mid)

        cfg = (
            Path(self._isolated_gemini_home())
            / "antigravity-acp"
            / "settings.json"
        )
        preferred = None
        try:
            preferred = (
                json.loads(cfg.read_text(encoding="utf-8-sig"))
                .get("auth", {})
                .get("type")
            )
        except Exception:
            pass

        candidates = ([preferred] if preferred else []) + list(_AUTH_PREF) + ids
        for x in candidates:
            if x and x in ids:
                return x
        return ids[0] if ids else None

    def _connect(self, timeout: float = 300, initial_model: str | None = None):
        if self._proc and self._proc.poll() is None and self._session:
            return

        self._spawn(initial_model)
        init = self._request("initialize", _INIT, timeout=timeout) or {}
        self._protocol_version = int(init.get("protocolVersion") or 1)
        methods = init.get("authMethods") or []

        try:
            sess = self._request(
                "session/new",
                {"cwd": self.cwd, "mcpServers": []},
                timeout=min(timeout, 120),
            )
        except RuntimeError as exc:
            msg = str(exc).lower()
            if "authentication required" not in msg and "auth_required" not in msg:
                raise

            method = self._choose_auth(methods)
            if not method:
                raise RuntimeError(
                    "Antigravity requires authentication but advertised no usable ACP auth method"
                )

            # Official Antigravity ACP 1.x is ACP v1 and uses authenticate.
            self._request(
                "authenticate",
                {"methodId": method},
                timeout=max(timeout, 300),
            )
            sess = self._request(
                "session/new",
                {"cwd": self.cwd, "mcpServers": []},
                timeout=timeout,
            )

        if not isinstance(sess, dict) or not sess.get("sessionId"):
            raise RuntimeError("Antigravity ACP session/new returned no sessionId")
        self._session = sess

    # ---------- models ----------

    def _models(self) -> list[str]:
        s = self._session or {}
        out: list[str] = []

        for opt in s.get("configOptions") or []:
            if not isinstance(opt, dict):
                continue
            oid = str(opt.get("id") or opt.get("configId") or "").lower()
            if oid != "model":
                continue
            for x in opt.get("options") or []:
                if isinstance(x, dict):
                    v = x.get("value") or x.get("id")
                    if v:
                        out.append(str(v))

        for x in ((s.get("models") or {}).get("availableModels") or []):
            if isinstance(x, dict) and x.get("modelId"):
                out.append(str(x["modelId"]))

        return list(dict.fromkeys(out))

    def list_models(self, timeout_seconds=300):
        with self._lock:
            self._connect(timeout_seconds)
            return self._models()

    def _select_model(self, model: str, timeout: float):
        if not model or not self._session:
            return

        sid = self._session.get("sessionId")
        for opt in self._session.get("configOptions") or []:
            if not isinstance(opt, dict):
                continue
            oid = str(opt.get("id") or opt.get("configId") or "")
            if oid.lower() != "model":
                continue

            current = str(opt.get("currentValue") or "")
            vals = [
                str(x.get("value") or x.get("id"))
                for x in (opt.get("options") or [])
                if isinstance(x, dict)
            ]
            if model == current:
                return
            if model in vals:
                result = self._request(
                    "session/set_config_option",
                    {
                        "sessionId": sid,
                        "configId": oid or "model",
                        "value": model,
                    },
                    timeout,
                )
                if isinstance(result, dict) and result.get("configOptions"):
                    self._session["configOptions"] = result["configOptions"]
                return

        # Older Antigravity builds expose the legacy set_model method.
        avail = [
            str(x.get("modelId"))
            for x in ((self._session.get("models") or {}).get("availableModels") or [])
            if isinstance(x, dict)
        ]
        if not avail or model in avail:
            try:
                self._request(
                    "session/set_model",
                    {"sessionId": sid, "modelId": model},
                    timeout,
                )
            except RuntimeError as exc:
                if "method" not in str(exc).lower():
                    raise

    # ---------- prompt ----------

    @staticmethod
    def _prompt(messages: Any) -> str:
        parts: list[str] = []
        for m in messages or []:
            if not isinstance(m, dict):
                continue
            c = m.get("content")
            if isinstance(c, list):
                chunks = []
                for x in c:
                    if isinstance(x, dict) and x.get("text"):
                        chunks.append(str(x["text"]))
                c = "\n".join(chunks)
            if c:
                parts.append(f"{str(m.get('role', 'context')).upper()}:\n{c}")
        return "\n\n".join(parts)

    def _prompt_turn(
        self,
        prompt_text: str,
        timeout: float,
    ) -> tuple[str, str | None, str]:
        if not self._session:
            raise RuntimeError("Antigravity ACP session is not initialized")

        self._rid += 1
        rid = self._rid
        sid = self._session["sessionId"]
        self._send(
            {
                "jsonrpc": "2.0",
                "id": rid,
                "method": "session/prompt",
                "params": {
                    "sessionId": sid,
                    "prompt": [{"type": "text", "text": prompt_text}],
                },
            }
        )

        text: list[str] = []
        reasoning: list[str] = []
        end = time.monotonic() + timeout
        denied_at: float | None = None
        prompt_ack = False

        while time.monotonic() < end:
            p = self._proc
            if not p or p.poll() is not None:
                raise RuntimeError(
                    "Antigravity ACP exited during session/prompt.\n" + self._diag()
                )

            try:
                m = self._inbox.get(timeout=0.1)
            except queue.Empty:
                # If a tool/elicitation was explicitly denied and the agent does
                # not settle the turn, cancel it rather than hanging Hermes.
                if denied_at and time.monotonic() - denied_at > 20:
                    self._cancel_session()
                    if text:
                        return "".join(text), "".join(reasoning) or None, "cancelled"
                    raise RuntimeError(
                        "Antigravity turn stalled after a denied tool/elicitation request.\n"
                        + self._diag()
                    )
                continue

            if "method" in m and "id" in m:
                if self._server_request(m):
                    denied_at = time.monotonic()
                continue

            if m.get("method") == "session/update":
                complete, stop = self._handle_update(m, text, reasoning)
                if complete:
                    return "".join(text), "".join(reasoning) or None, stop or "end_turn"
                continue

            if m.get("id") != rid:
                self._event(f"rx unrelated response id={m.get('id')}")
                continue

            if "error" in m:
                e = m.get("error") or {}
                raise RuntimeError(
                    f"Antigravity session/prompt failed: {e.get('message') or e}\n"
                    + self._diag()
                )

            result = m.get("result") or {}
            self._event("rx response session/prompt")

            # ACP v1: this response ends the turn.
            if isinstance(result, dict) and result.get("stopReason"):
                return (
                    "".join(text),
                    "".join(reasoning) or None,
                    str(result.get("stopReason")),
                )

            # ACP v2 compatibility: response only acknowledges prompt insertion.
            if isinstance(result, dict) and result.get("messageId"):
                prompt_ack = True
                continue

            # Some implementations may return an empty response after already
            # streaming all content. Treat it as completion only for negotiated
            # v1; for v2 wait for state_update idle.
            if self._protocol_version == 1:
                return "".join(text), "".join(reasoning) or None, "end_turn"

        self._cancel_session()
        raise TimeoutError(
            f"Antigravity ACP timeout waiting for session/prompt"
            f"{' after v2 prompt acknowledgement' if prompt_ack else ''}.\n"
            + self._diag()
        )

    def create(
        self,
        *,
        model=None,
        messages=None,
        timeout=None,
        stream=False,
        **kwargs,
    ):
        timeout = float(timeout or 420)
        model_id = str(model or "")

        with self._lock:
            try:
                self._connect(timeout, initial_model=model_id or None)
            except Exception as exc:
                detail = str(exc)
                self._stop()

                # Retry only bootstrap failures that are plausibly transient.
                # Do not blindly spawn a second ACP process for auth/protocol/model
                # errors; those should surface directly to Hermes.
                if self._is_pyinstaller_extract_error(detail):
                    self._event("retrying after PyInstaller extraction failure")
                    self._connect(timeout, initial_model=model_id or None)
                else:
                    raise

            self._select_model(model_id, timeout)
            content, reasoning, stop_reason = self._prompt_turn(
                self._prompt(messages),
                timeout,
            )

            msg = SimpleNamespace(
                content=content,
                tool_calls=None,
                reasoning=reasoning,
                reasoning_content=reasoning,
                reasoning_details=None,
            )
            comp = SimpleNamespace(
                choices=[
                    SimpleNamespace(
                        message=msg,
                        finish_reason=stop_reason or "stop",
                    )
                ],
                usage=SimpleNamespace(
                    prompt_tokens=0,
                    completion_tokens=0,
                    total_tokens=0,
                    prompt_tokens_details=SimpleNamespace(cached_tokens=0),
                ),
                model=model or "antigravity",
            )

            if not stream:
                return comp

            delta = SimpleNamespace(
                content=content,
                tool_calls=None,
                reasoning_content=reasoning,
            )
            return iter(
                [
                    SimpleNamespace(
                        choices=[
                            SimpleNamespace(
                                delta=delta,
                                finish_reason=stop_reason or "stop",
                            )
                        ],
                        model=model or "antigravity",
                    )
                ]
            )
