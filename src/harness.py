# -*- coding: utf-8 -*-
# =============================================================================
#  Hex AI Girlfriend — DeepSeek Harness bridge (v2)
#  Copyright (C) 2026 Hex-电脑课堂
#  SPDX-License-Identifier: GPL-3.0-or-later
# =============================================================================
"""Run one deep task through the `dsh --profile headless --json` CLI.

The bridge owns the subprocess, parses the newline-delimited JSON event stream,
enforces a timeout, and turns the terminal `final` event into a small result
object.  It deliberately does not know about TTS or the avatar; the orchestrator
decides how a result is spoken and displayed.
"""
from __future__ import annotations

import asyncio
import json
import logging
import os
import shutil
import signal
import time
from dataclasses import dataclass, field
from pathlib import Path
from typing import Any, Awaitable, Callable

log = logging.getLogger("hexgf.harness")

EventCallback = Callable[[dict[str, Any]], Any | Awaitable[Any]]


def _expand(value: str) -> str:
    return os.path.abspath(os.path.expanduser(os.path.expandvars(str(value))))


def _load_env_file(path: Path) -> None:
    """Load simple KEY=VALUE lines without overriding the real environment."""
    try:
        text = path.read_text(encoding="utf-8")
    except OSError:
        return
    for raw in text.splitlines():
        line = raw.strip()
        if not line or line.startswith("#") or "=" not in line:
            continue
        key, value = line.split("=", 1)
        key = key.strip()
        value = value.strip().strip("'").strip('"')
        if key and key not in os.environ:
            os.environ[key] = value


def _redact(text: str, limit: int = 4000) -> str:
    """Keep diagnostics useful without leaking credentials or unbounded output."""
    if not text:
        return ""
    for key in ("DEEPSEEK_API_KEY", "OPENAI_API_KEY", "API_KEY", "TOKEN", "SECRET"):
        value = os.environ.get(key)
        if value and len(value) >= 8:
            text = text.replace(value, "[redacted]")
    # Common bearer / sk- patterns.
    import re

    text = re.sub(r"(?i)(bearer\s+)[A-Za-z0-9._\-]+", r"\1[redacted]", text)
    text = re.sub(r"\bsk-[A-Za-z0-9._\-]{8,}\b", "sk-[redacted]", text)
    return text[-limit:]


@dataclass
class HarnessResult:
    ok: bool
    final: str
    session_id: str | None = None
    exit_code: int | None = None
    error: str | None = None
    timed_out: bool = False
    duration_s: float = 0.0
    events: list[dict[str, Any]] = field(default_factory=list)
    stderr_tail: str = ""


class HarnessClient:
    """One-task-at-a-time headless DSH runner.

    Configuration (``config.mac.yaml``)::

        harness:
          enabled: true
          command: ["dsh", "--profile", "headless", "--json"]
          workspace: "~/Documents/HexHarnessWorkspace"
          dsh_home: "~/.dsh-v2"
          full_access: true
          timeout_s: 300
          max_events: 500
    """

    def __init__(self, cfg: dict[str, Any], base_dir: str):
        hc = cfg.get("harness", {}) if isinstance(cfg, dict) else {}
        self.enabled = bool(hc.get("enabled", False))
        command = hc.get("command", ["dsh", "--profile", "headless", "--json"])
        if isinstance(command, str):
            command = [command]
        self.command: list[str] = [str(part) for part in command]
        self.workspace = _expand(hc.get("workspace", "~/Documents/HexHarnessWorkspace"))
        self.dsh_home = _expand(hc.get("dsh_home", "~/.dsh-v2"))
        self.full_access = bool(hc.get("full_access", False))
        self.timeout_s = float(hc.get("timeout_s", 300))
        self.max_events = int(hc.get("max_events", 500))
        self.max_output_chars = int(hc.get("max_output_chars", 20000))
        self.env_file = _expand(hc.get("env_file", os.path.join(base_dir, ".env")))
        self.base_dir = base_dir
        # `./scripts/install-harness.sh` installs a pinned local CLI.  Use it
        # automatically when `dsh` is not on PATH, so the default config works
        # without a global npm install.
        if self.command:
            first = self.command[0]
            if first.startswith(".") and not os.path.isabs(first):
                self.command[0] = os.path.abspath(os.path.join(base_dir, first))
                first = self.command[0]
            if not os.path.isabs(first) and not first.startswith("."):
                local = os.path.join(base_dir, ".harness-cli", "node_modules", ".bin", "dsh")
                if shutil.which(first) is None and os.path.isfile(local):
                    self.command[0] = os.path.abspath(local)
        self._proc: asyncio.subprocess.Process | None = None
        self._cancelled = False

    # ---------------------------------------------------------------- status

    @property
    def command_available(self) -> bool:
        if not self.command:
            return False
        first = self.command[0]
        if os.path.isabs(first) or first.startswith("."):
            return os.path.isfile(first) and os.access(first, os.X_OK)
        return shutil.which(first) is not None

    @property
    def available(self) -> bool:
        return self.enabled and self.command_available

    def unavailable_reason(self) -> str:
        if not self.enabled:
            return "Harness 未启用"
        if not self.command:
            return "Harness 命令为空"
        if not self.command_available:
            return f"找不到 Harness 命令：{self.command[0]}"
        return ""

    @property
    def busy(self) -> bool:
        return self._proc is not None

    # ---------------------------------------------------------------- run

    async def run(
        self,
        task: str,
        *,
        session_id: str | None = None,
        on_event: EventCallback | None = None,
    ) -> HarnessResult:
        """Run exactly one task.  Concurrent calls are rejected by the caller."""
        if not self.enabled:
            return HarnessResult(ok=False, final="", error=self.unavailable_reason())
        if self._proc is not None:
            return HarnessResult(ok=False, final="", error="Harness 正在处理上一个任务")
        if not task or not task.strip():
            return HarnessResult(ok=False, final="", error="空任务")

        self._cancelled = False
        workspace = Path(self.workspace)
        try:
            workspace.mkdir(parents=True, exist_ok=True)
        except OSError as exc:
            # The configured workspace may live outside a sandboxed launch
            # context.  Fall back to a repo-local directory instead of turning
            # every deep task into a hard failure.
            log.warning("harness workspace %s unavailable (%s); using repo-local fallback",
                        workspace, exc)
            workspace = Path(self.base_dir) / ".harness-workspace"
            try:
                workspace.mkdir(parents=True, exist_ok=True)
            except OSError as fallback_exc:
                return HarnessResult(ok=False, final="",
                                     error=f"无法创建 Harness 工作区：{fallback_exc}")

        env = os.environ.copy()
        _load_env_file(Path(self.env_file))
        # Re-read after the env file so a key placed only in .env is visible.
        env.update(os.environ)
        env["DSH_HOME"] = self.dsh_home
        env["DSH_PERMISSION_MODE"] = "danger-full-access" if self.full_access else "workspace-write"
        env.setdefault("NO_COLOR", "1")
        env.setdefault("TERM", "dumb")
        try:
            Path(self.dsh_home).mkdir(parents=True, exist_ok=True)
        except OSError:
            pass

        cmd = list(self.command)
        if "--json" not in cmd:
            cmd.append("--json")
        if session_id:
            cmd.extend(["--session-id", session_id])
        cmd.append(task)

        events: list[dict[str, Any]] = []
        final_text = ""
        found_session: str | None = None
        stream_error: str | None = None
        stderr_tail = ""
        started = time.monotonic()

        async def emit(event: dict[str, Any]) -> None:
            nonlocal final_text, found_session, stream_error
            if len(events) < self.max_events:
                events.append(event)
            if event.get("type") == "session" and isinstance(event.get("sessionId"), str):
                found_session = event["sessionId"]
            elif event.get("type") == "final" and isinstance(event.get("text"), str):
                final_text = event["text"]
            elif event.get("type") == "error" and isinstance(event.get("message"), str):
                stream_error = event["message"]
            if on_event is not None:
                try:
                    result = on_event(event)
                    if asyncio.iscoroutine(result):
                        await result
                except Exception:
                    log.exception("harness event callback failed")

        try:
            self._proc = await asyncio.create_subprocess_exec(
                *cmd,
                cwd=str(workspace),
                env=env,
                stdin=asyncio.subprocess.DEVNULL,
                stdout=asyncio.subprocess.PIPE,
                stderr=asyncio.subprocess.PIPE,
                start_new_session=True,
            )
        except FileNotFoundError:
            self._proc = None
            return HarnessResult(ok=False, final="", error=f"找不到 Harness 命令：{cmd[0]}")
        except Exception as exc:
            self._proc = None
            return HarnessResult(ok=False, final="", error=f"启动 Harness 失败：{exc}")

        proc = self._proc
        if self._cancelled:
            # cancel() may have arrived before the process was created.
            await self._terminate(proc)

        async def read_stdout() -> None:
            assert proc.stdout is not None
            while True:
                line = await proc.stdout.readline()
                if not line:
                    return
                try:
                    event = json.loads(line)
                except json.JSONDecodeError:
                    log.debug("harness non-JSON stdout: %r", line[:300])
                    continue
                if isinstance(event, dict):
                    await emit(event)

        async def read_stderr() -> str:
            assert proc.stderr is not None
            chunks: list[bytes] = []
            while True:
                chunk = await proc.stderr.read(4096)
                if not chunk:
                    return _redact(b"".join(chunks).decode("utf-8", "replace"))
                chunks.append(chunk)
                # Keep only the tail to bound memory.
                if sum(len(c) for c in chunks) > 32768:
                    chunks = chunks[-4:]

        out_task = asyncio.create_task(read_stdout())
        err_task = asyncio.create_task(read_stderr())
        timed_out = False
        try:
            await asyncio.wait_for(proc.wait(), timeout=self.timeout_s)
        except asyncio.TimeoutError:
            timed_out = True
            await self._terminate(proc)
        except asyncio.CancelledError:
            self._cancelled = True
            await self._terminate(proc)
            raise
        finally:
            try:
                await asyncio.wait_for(asyncio.gather(out_task, err_task), timeout=5)
            except Exception:
                for task in (out_task, err_task):
                    task.cancel()
            try:
                stderr_tail = err_task.result() if err_task.done() and not err_task.cancelled() else ""
            except Exception:
                stderr_tail = ""
            self._proc = None

        duration = time.monotonic() - started
        code = proc.returncode
        ok = (not timed_out) and (not self._cancelled) and code == 0 and bool(final_text)
        error = None
        if timed_out:
            error = f"Harness 超时（{self.timeout_s:.0f}s）"
        elif self._cancelled:
            error = "Harness 已取消"
        elif code != 0:
            error = stream_error or (f"Harness 退出码 {code}" + (f"：{stderr_tail[-300:]}" if stderr_tail else ""))
        elif not final_text:
            error = stream_error or "Harness 没有返回最终结果"
        if found_session:
            session_id = found_session

        return HarnessResult(
            ok=ok,
            final=final_text[: self.max_output_chars],
            session_id=session_id,
            exit_code=code,
            error=error,
            timed_out=timed_out,
            duration_s=duration,
            events=events,
            stderr_tail=stderr_tail,
        )

    async def _terminate(self, proc: asyncio.subprocess.Process) -> None:
        """Terminate the whole process group, then escalate if it refuses."""
        if proc.returncode is not None:
            return
        try:
            os.killpg(os.getpgid(proc.pid), signal.SIGTERM)
        except Exception:
            try:
                proc.terminate()
            except Exception:
                pass
        try:
            await asyncio.wait_for(proc.wait(), timeout=5)
        except asyncio.TimeoutError:
            try:
                os.killpg(os.getpgid(proc.pid), signal.SIGKILL)
            except Exception:
                try:
                    proc.kill()
                except Exception:
                    pass
            try:
                await asyncio.wait_for(proc.wait(), timeout=2)
            except Exception:
                pass

    async def cancel(self) -> None:
        self._cancelled = True
        proc = self._proc
        if proc is not None:
            await self._terminate(proc)
