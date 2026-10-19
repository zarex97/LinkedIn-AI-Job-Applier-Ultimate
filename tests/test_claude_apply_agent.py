"""Test suite for src/llm/claude_apply_agent.py"""

import asyncio
import json
import subprocess
import threading
import time
from pathlib import Path
from unittest.mock import AsyncMock, MagicMock, patch

import pytest

from src.llm.apply_agent import ApplyAgent
from src.llm.claude_apply_agent import (
    APPLY_RESULT_SCHEMA,
    BotBrowser,
    ClaudeCodeApplyRunner,
    build_claude_tool_notes,
    map_apply_result,
    stop_browser_use_daemon,
)
from src.llm.claude_cli import CLAUDE_WORKDIR, ClaudeWeeklyLimitError
from src.llm.verification_gate import VerificationGate

FIXTURES = Path(__file__).parent / "fixtures" / "claude_cli"


def _result_json(structured=None, *, is_error=False, subtype="success", result_text=""):
    return json.dumps(
        {
            "type": "result",
            "subtype": subtype,
            "is_error": is_error,
            "result": result_text,
            "structured_output": structured,
            "num_turns": 5,
            "session_id": "s-1",
            "usage": {"input_tokens": 100, "output_tokens": 20},
            "modelUsage": {"claude-sonnet-5-5": {}},
        }
    ).encode("utf-8")


SUBMITTED = {"submitted": True, "reason": "", "summary": "Applied.", "questions": []}


class FakeProcess:
    """Stand-in for asyncio.subprocess.Process"""

    def __init__(self, stdout: bytes = b"", returncode: int = 0, hang: bool = False, delay: float = 0):
        self._stdout = stdout
        self._hang = hang
        self._delay = delay
        self._killed = asyncio.Event()
        self.returncode = None
        self._final_returncode = returncode
        self.stdin_data = None
        self.kill = MagicMock(side_effect=self._kill)

    def _kill(self):
        self._killed.set()

    async def communicate(self, input=None):
        self.stdin_data = input
        if self._hang:
            await self._killed.wait()
            self.returncode = -9
            return b"", b""
        if self._delay:
            await asyncio.sleep(self._delay)
        self.returncode = self._final_returncode
        return self._stdout, b""

    async def wait(self):
        return self.returncode


def _runner(tmp_path, **kwargs):
    return ClaudeCodeApplyRunner(model="sonnet", gate_dir=tmp_path / "gate", **kwargs)


def test_map_submitted():
    assert map_apply_result(SUBMITTED) == ("Success", "")


def test_map_not_submitted():
    structured = {"submitted": False, "reason": "site needs SSN", "summary": "s", "questions": []}
    assert map_apply_result(structured) == ("Skip", "Could not apply: site needs SSN")


def test_map_missing_output():
    assert map_apply_result(None) == ("Error", "Agent ended without a verdict")


def test_schema_requires_verdict_fields():
    assert set(APPLY_RESULT_SCHEMA["required"]) == {"submitted", "reason", "summary", "questions"}


def test_tool_notes_include_guide_and_gate(tmp_path):
    gate_script = Path("C:/repo/src/llm/verification_gate.py")
    notes = build_claude_tool_notes(gate_script, tmp_path / "gate")
    assert "browser-use <<'PY'" in notes
    assert "upload_file(selector, path)" in notes
    # the agent's Bash tool is Git Bash on Windows: paths use forward slashes
    assert gate_script.as_posix() in notes
    assert (tmp_path / "gate").as_posix() in notes
    assert " wait " in notes


@pytest.mark.asyncio
async def test_runner_command(tmp_path, monkeypatch):
    monkeypatch.setenv("ANTHROPIC_API_KEY", "should-not-leak")
    process = FakeProcess(_result_json(SUBMITTED))
    with patch(
        "src.llm.claude_apply_agent.asyncio.create_subprocess_exec",
        new=AsyncMock(return_value=process),
    ) as mock_exec:
        result = await _runner(tmp_path, max_turns=150).run("TASK", env_overrides={"BU_NAME": "x"})

    assert result == ("Success", "")
    args = list(mock_exec.call_args.args)
    kwargs = mock_exec.call_args.kwargs
    assert "Bash(browser-use:*)" in args
    assert any("verification_gate.py" in arg and arg.startswith("Bash(") for arg in args)
    assert args[args.index("--model") + 1] == "sonnet"
    assert args[args.index("--max-turns") + 1] == "150"
    assert args[args.index("--tools") + 1] == "Bash"
    assert json.loads(args[args.index("--json-schema") + 1]) == APPLY_RESULT_SCHEMA
    assert kwargs["cwd"] == CLAUDE_WORKDIR
    assert "ANTHROPIC_API_KEY" not in kwargs["env"]
    assert kwargs["env"]["BU_NAME"] == "x"
    assert process.stdin_data == "TASK".encode("utf-8")


@pytest.mark.asyncio
async def test_runner_relays_verification(tmp_path):
    runner = _runner(tmp_path)
    gate = VerificationGate(tmp_path / "gate")
    process = FakeProcess(_result_json(SUBMITTED), delay=1.5)
    on_verified = AsyncMock()

    def agent_asks_for_verification():
        time.sleep(0.3)
        gate.request()

    threading.Thread(target=agent_asks_for_verification, daemon=True).start()
    with (
        patch(
            "src.llm.claude_apply_agent.asyncio.create_subprocess_exec",
            new=AsyncMock(return_value=process),
        ),
        patch("builtins.input", return_value=""),
        patch.object(VerificationGate, "confirm", autospec=True, side_effect=VerificationGate.confirm) as mock_confirm,
    ):
        result = await runner.run("TASK", on_verified=on_verified, poll_seconds=0.05)

    assert result == ("Success", "")
    assert mock_confirm.called
    on_verified.assert_awaited_once()


@pytest.mark.asyncio
async def test_runner_timeout_kills_process(tmp_path):
    process = FakeProcess(hang=True)
    with patch(
        "src.llm.claude_apply_agent.asyncio.create_subprocess_exec",
        new=AsyncMock(return_value=process),
    ):
        result = await _runner(tmp_path, timeout_seconds=0.1).run("TASK", poll_seconds=0.02)

    process.kill.assert_called_once()
    assert result == ("Error", "Agent timed out after 0.1 s")


@pytest.mark.asyncio
async def test_runner_retries_once_after_usage_limit(tmp_path):
    limited = FakeProcess(
        _result_json(is_error=True, result_text="5-hour limit reached ∙ resets 3pm"), returncode=1
    )
    succeeded = FakeProcess(_result_json(SUBMITTED))
    with (
        patch(
            "src.llm.claude_apply_agent.asyncio.create_subprocess_exec",
            new=AsyncMock(side_effect=[limited, succeeded]),
        ),
        patch("src.llm.claude_apply_agent.pause") as mock_pause,
    ):
        result = await _runner(tmp_path).run("TASK")

    assert result == ("Success", "")
    mock_pause.assert_called_once()


@pytest.mark.asyncio
async def test_runner_raises_weekly(tmp_path):
    weekly = FakeProcess(
        _result_json(is_error=True, result_text="Weekly limit reached ∙ resets Oct 21, 3pm"),
        returncode=1,
    )
    with patch(
        "src.llm.claude_apply_agent.asyncio.create_subprocess_exec",
        new=AsyncMock(return_value=weekly),
    ):
        with pytest.raises(ClaudeWeeklyLimitError):
            await _runner(tmp_path).run("TASK")


@pytest.mark.asyncio
async def test_runner_max_turns_returns_error(tmp_path):
    """Hitting max turns has no verdict: it is an Error, never a Success"""
    stdout = (FIXTURES / "error_max_turns.json").read_bytes()
    process = FakeProcess(stdout, returncode=1)
    with patch(
        "src.llm.claude_apply_agent.asyncio.create_subprocess_exec",
        new=AsyncMock(return_value=process),
    ):
        result, reason = await _runner(tmp_path).run("TASK")

    assert result == "Error"
    assert "error_max_turns" in reason


@pytest.mark.asyncio
async def test_runner_keeps_last_result_for_logging(tmp_path):
    runner = _runner(tmp_path)
    with patch(
        "src.llm.claude_apply_agent.asyncio.create_subprocess_exec",
        new=AsyncMock(return_value=FakeProcess(_result_json(SUBMITTED))),
    ):
        await runner.run("TASK")
    assert runner.last_result.input_tokens == 100
    assert runner.last_result.output_tokens == 20


@pytest.mark.asyncio
@pytest.mark.parametrize("headless", [True, False])
async def test_bot_browser_launches_with_headless_mode(tmp_path, headless):
    state = tmp_path / "state.json"
    state.write_text(json.dumps({"cookies": [{"name": "li_at", "value": "v"}], "origins": []}))
    context = AsyncMock()
    playwright = MagicMock()
    playwright.chromium.launch_persistent_context = AsyncMock(return_value=context)
    manager = MagicMock()
    manager.start = AsyncMock(return_value=playwright)
    playwright.stop = AsyncMock()

    with patch("src.llm.claude_apply_agent.async_playwright", return_value=manager):
        async with BotBrowser(str(state), headless=headless, port=9555) as browser:
            assert browser.cdp_url == "http://127.0.0.1:9555"

    kwargs = playwright.chromium.launch_persistent_context.call_args.kwargs
    assert kwargs["headless"] is headless
    assert "--remote-debugging-port=9555" in kwargs["args"]
    context.add_cookies.assert_awaited_once_with([{"name": "li_at", "value": "v"}])
    context.close.assert_awaited_once()


@pytest.mark.asyncio
async def test_bot_browser_saves_session(tmp_path):
    context = AsyncMock()
    playwright = MagicMock()
    playwright.chromium.launch_persistent_context = AsyncMock(return_value=context)
    playwright.stop = AsyncMock()
    manager = MagicMock()
    manager.start = AsyncMock(return_value=playwright)

    with patch("src.llm.claude_apply_agent.async_playwright", return_value=manager):
        async with BotBrowser(None, headless=True, port=9556) as browser:
            await browser.save_session(str(tmp_path / "out.json"))

    context.storage_state.assert_awaited_once_with(path=str(tmp_path / "out.json"))
    context.add_cookies.assert_not_awaited()


@pytest.mark.asyncio
@patch("src.llm.apply_agent.LLM_MODEL_TYPE", "claude_code")
async def test_apply_to_job_reraises_weekly(tmp_path):
    agent = ApplyAgent(None, str(tmp_path / "state.json"))
    with patch.object(
        agent, "apply", new=AsyncMock(side_effect=ClaudeWeeklyLimitError("weekly limit reached"))
    ):
        with pytest.raises(ClaudeWeeklyLimitError):
            await agent.apply_to_job("https://jobs.example.com/1")


@pytest.mark.asyncio
@patch("src.llm.apply_agent.LLM_MODEL_TYPE", "claude_code")
async def test_apply_to_job_returns_runner_verdict(tmp_path):
    agent = ApplyAgent(None, str(tmp_path / "state.json"))
    with patch.object(
        agent, "apply", new=AsyncMock(return_value=("Skip", "Could not apply: needs SSN"))
    ):
        assert await agent.apply_to_job("https://jobs.example.com/1") == (
            "Skip",
            "Could not apply: needs SSN",
        )


def test_stop_browser_use_daemon_targets_named_daemon():
    with (
        patch("src.llm.claude_apply_agent.shutil.which", return_value="C:/bin/browser-use.exe"),
        patch("src.llm.claude_apply_agent.subprocess.run") as mock_run,
    ):
        stop_browser_use_daemon()
    assert mock_run.call_args.args[0] == ["C:/bin/browser-use.exe", "--reload"]
    assert mock_run.call_args.kwargs["env"]["BU_NAME"] == "job_applier"


def test_stop_browser_use_daemon_ignores_missing_cli():
    with patch("src.llm.claude_apply_agent.shutil.which", return_value=None):
        stop_browser_use_daemon()


def test_stop_browser_use_daemon_ignores_timeout():
    with (
        patch("src.llm.claude_apply_agent.shutil.which", return_value="C:/bin/browser-use.exe"),
        patch(
            "src.llm.claude_apply_agent.subprocess.run",
            side_effect=subprocess.TimeoutExpired(cmd="browser-use", timeout=30),
        ),
    ):
        stop_browser_use_daemon()
