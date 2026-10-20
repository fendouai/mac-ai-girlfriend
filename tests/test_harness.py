from __future__ import annotations

import asyncio
import os
import sys
from pathlib import Path

import pytest

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "src"))

from harness import HarnessClient  # noqa: E402
from harness_router import HarnessRouter  # noqa: E402

FAKE = ROOT / "tests" / "fake_dsh.py"


def make_client(tmp_path: Path, **overrides) -> HarnessClient:
    cfg = {
        "harness": {
            "enabled": True,
            "command": [sys.executable, str(FAKE)],
            "workspace": str(tmp_path / "workspace"),
            "dsh_home": str(tmp_path / "dsh-home"),
            "timeout_s": 5,
            "max_events": 50,
            "full_access": True,
        }
    }
    cfg["harness"].update(overrides)
    return HarnessClient(cfg, base_dir=str(tmp_path))


def test_router_social_vs_task():
    router = HarnessRouter({"harness": {"router": {"mode": "auto"}}})
    assert router.decide("你好呀").route == "chat"
    assert router.decide("在干嘛呢").route == "chat"
    assert router.decide("今天好累啊").route == "chat"
    assert router.decide("我想你了").route == "chat"
    assert router.decide("讲个笑话吧").route == "chat"
    assert router.decide("帮我查一下最近的提交").route == "harness"
    assert router.decide("运行测试并总结失败原因").route == "harness"
    assert router.decide("把这个项目打包").route == "harness"
    assert router.decide("地球为什么是圆的").route == "harness"
    assert router.decide("我有点难过").route == "chat"
    assert router.decide("我饿了").route == "chat"
    assert router.decide("今天几号").route == "harness"


def test_router_cancel_continue_and_modes():
    router = HarnessRouter({"harness": {"router": {"mode": "auto"}}})
    assert router.decide("算了").route == "cancel"
    assert router.decide("继续").route == "chat"
    assert router.decide("继续", has_session=True).route == "continue"
    explicit = HarnessRouter({"harness": {"router": {"mode": "explicit"}}})
    assert explicit.decide("帮我查一下").route == "chat"
    assert explicit.decide("调用 harness 查一下").route == "harness"
    off = HarnessRouter({"harness": {"router": {"mode": "off"}}})
    assert off.decide("帮我查一下").route == "chat"


def test_headless_success(tmp_path):
    client = make_client(tmp_path)
    seen = []
    result = asyncio.run(client.run("hello", on_event=seen.append))
    assert result.ok
    assert result.final == "FAKE RESULT: hello"
    assert result.session_id == "session-fake"
    assert result.exit_code == 0
    assert any(event["type"] == "tool_call" for event in seen)
    assert Path(tmp_path / "workspace").is_dir()


def test_headless_fail(tmp_path):
    client = make_client(tmp_path)
    result = asyncio.run(client.run("please fail"))
    assert not result.ok
    assert result.exit_code == 1
    assert "fake failure" in (result.error or "")


def test_headless_timeout(tmp_path):
    client = make_client(tmp_path, timeout_s=0.6)
    result = asyncio.run(client.run("sleep"))
    assert not result.ok
    assert result.timed_out
    assert "超时" in (result.error or "")


def test_headless_cancel(tmp_path):
    client = make_client(tmp_path, timeout_s=30)

    async def scenario():
        task = asyncio.create_task(client.run("sleep"))
        for _ in range(50):
            if client.busy:
                break
            await asyncio.sleep(0.05)
        assert client.busy
        await client.cancel()
        return await task

    result = asyncio.run(scenario())
    assert not result.ok
    assert "取消" in (result.error or "")


def test_missing_command(tmp_path):
    client = make_client(tmp_path, command=["no-such-dsh-binary-xyz"])
    assert not client.available
    result = asyncio.run(client.run("hello"))
    assert not result.ok
    assert "找不到" in (result.error or "")


def test_orchestrator_dispatches_and_emits_events(monkeypatch):
    from harness import HarnessResult
    from orchestrator import HexOrchestrator

    class FakeHarness:
        enabled = True
        full_access = True
        available = True

        def unavailable_reason(self):
            return ""

        async def run(self, task, *, session_id=None, on_event=None):
            if on_event:
                on_event({"type": "session", "sessionId": "hs-1"})
                on_event({"type": "tool_call", "tool": "read"})
            return HarnessResult(ok=True, final="FAKE RESULT", session_id="hs-1", duration_s=0.1)

        async def cancel(self):
            return None

    async def scenario():
        orch = HexOrchestrator.__new__(HexOrchestrator)
        orch.harness = FakeHarness()
        orch.harness_router = HarnessRouter({"harness": {"router": {"mode": "auto"}}})
        orch._harness_task = None
        orch._harness_session_id = None
        orch._session_id = "sess-test"
        orch.loop = asyncio.get_running_loop()
        orch.busy = False
        sent = []
        orch._send_sync = sent.append

        async def fake_speak(task, final):
            return None

        orch._speak_harness_result = fake_speak
        assert await orch._dispatch_harness("帮我查一下最近的提交") is True
        task = orch._harness_task
        assert task is not None
        await task
        kinds = [event["type"] for event in sent]
        assert "harness.started" in kinds
        assert "harness.event" in kinds
        assert "harness.result" in kinds
        assert orch._harness_session_id == "hs-1"

        # A social turn stays local.
        assert await orch._dispatch_harness("你好呀") is False

    asyncio.run(scenario())


def test_orchestrator_falls_back_when_credentials_missing():
    from harness import HarnessResult

    class FakeHarness:
        enabled = True
        full_access = True
        available = True

        def unavailable_reason(self):
            return ""

        async def run(self, task, *, session_id=None, on_event=None):
            return HarnessResult(
                ok=False,
                final="",
                error='Harness 退出码 1：dsh: MISSING_CREDENTIAL: no API key',
                exit_code=1,
            )

        async def cancel(self):
            return None

    async def scenario():
        from orchestrator import HexOrchestrator

        orch = HexOrchestrator.__new__(HexOrchestrator)
        orch.harness = FakeHarness()
        orch.harness_router = HarnessRouter({"harness": {"router": {"mode": "auto"}}})
        orch._harness_task = None
        orch._harness_session_id = None
        orch._session_id = "sess-test"
        orch.loop = asyncio.get_running_loop()
        orch.busy = False
        orch._history = []
        sent = []
        orch._send_sync = sent.append
        called = []

        async def fake_reply(messages=None):
            called.append(messages)

        orch._run_reply = fake_reply
        assert await orch._dispatch_harness("帮我查一下最近的提交") is True
        await orch._harness_task
        kinds = [event["type"] for event in sent]
        assert "harness.error" in kinds
        assert "harness.fallback" in kinds
        assert called

    asyncio.run(scenario())
