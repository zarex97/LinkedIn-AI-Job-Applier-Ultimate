"""
Apply on outside company sites with Claude Code as the agent (LLM_MODEL_TYPE = "claude_code").

One `claude -p` session per job drives a browser the bot launches itself, through
the browser-use CLI. The bot's browser loads the saved session from
BROWSER_STORAGE_STATE, so the agent never touches the user's own Chrome.
The session ends with a schema-checked verdict.
"""

import asyncio
import json
import os
import shutil
import socket
import subprocess
import sys
import tempfile
import time
from pathlib import Path
from typing import Awaitable, Callable

from playwright.async_api import async_playwright

import src.llm.prompts as prompts
from config.logger_config import logger
from src.llm.claude_cli import (
    CLAUDE_LIMIT_DEFAULT_WAIT_SECONDS,
    CLAUDE_WORKDIR,
    ClaudeCLIError,
    ClaudeResult,
    ClaudeUsageLimitError,
    build_claude_command,
    clean_env,
    parse_claude_output,
)
from src.llm.verification_gate import VerificationGate
from src.utils.utils import pause

APPLY_RESULT_SCHEMA = {
    "type": "object",
    "properties": {
        "submitted": {"type": "boolean"},
        "reason": {"type": "string"},
        "summary": {"type": "string"},
        "questions": {"type": "array", "items": {"type": "string"}},
    },
    "required": ["submitted", "reason", "summary", "questions"],
}

BROWSER_GUIDE_FILE = Path(__file__).parent / "browser_use_cli_guide.md"
GATE_SCRIPT = Path(__file__).parent / "verification_gate.py"
BROWSER_USE_DAEMON_NAME = "job_applier"


def _bash_arg(path: Path | str) -> str:
    """Path for the agent's Bash tool (Git Bash on Windows): forward slashes, quoted if needed"""
    text = Path(path).as_posix()
    return f'"{text}"' if " " in text else text


def _gate_command(gate_script: Path, gate_dir: Path) -> str:
    return f"{_bash_arg(sys.executable)} {_bash_arg(gate_script)} wait {_bash_arg(gate_dir)}"


def map_apply_result(structured: dict | None) -> tuple[str, str]:
    """Turn the agent's verdict into the (result, reason) pair the job managers expect"""
    if not structured:
        return "Error", "Agent ended without a verdict"
    if structured.get("submitted") is True:
        return "Success", ""
    reason = structured.get("reason") or "no reason given"
    return "Skip", f"Could not apply: {reason}"


def build_claude_tool_notes(gate_script: Path, gate_dir: Path) -> str:
    """Browser-use CLI guide plus email-verification and verdict instructions"""
    return prompts.claude_apply_agent_tool_notes.format(
        browser_guide=BROWSER_GUIDE_FILE.read_text(encoding="utf-8"),
        gate_command=_gate_command(gate_script, gate_dir),
    )


def stop_browser_use_daemon() -> None:
    """Stop the bot's named browser-use daemon; it outlives each CLI call"""
    executable = shutil.which("browser-use")
    if executable is None:
        return
    try:
        subprocess.run(
            [executable, "--reload"],
            env={**os.environ, "BU_NAME": BROWSER_USE_DAEMON_NAME},
            capture_output=True,
            timeout=30,
        )
    except (subprocess.TimeoutExpired, OSError) as e:
        logger.warning(f"Could not stop the browser-use daemon: {e}")


def _free_port() -> int:
    with socket.socket(socket.AF_INET, socket.SOCK_STREAM) as sock:
        sock.bind(("127.0.0.1", 0))
        return sock.getsockname()[1]


class BotBrowser:
    """Bot-owned Chromium with a DevTools port, preloaded with the saved session cookies"""

    def __init__(self, storage_state: str | None, headless: bool, port: int | None = None):
        self.storage_state = storage_state
        self.headless = headless
        self.port = port or _free_port()
        self._playwright = None
        self._context = None

    @property
    def cdp_url(self) -> str:
        return f"http://127.0.0.1:{self.port}"

    async def __aenter__(self) -> "BotBrowser":
        self._playwright = await async_playwright().start()
        self._context = await self._playwright.chromium.launch_persistent_context(
            tempfile.mkdtemp(prefix="job_applier_browser_"),
            headless=self.headless,
            args=[f"--remote-debugging-port={self.port}"],
        )
        if self.storage_state and Path(self.storage_state).exists():
            state = json.loads(Path(self.storage_state).read_text(encoding="utf-8"))
            if state.get("cookies"):
                await self._context.add_cookies(state["cookies"])
        return self

    async def save_session(self, path: str) -> None:
        await self._context.storage_state(path=path)
        logger.info(f"Browser session saved to {path}")

    async def __aexit__(self, *exc_info) -> None:
        try:
            if self._context is not None:
                await self._context.close()
        finally:
            if self._playwright is not None:
                await self._playwright.stop()


class ClaudeCodeApplyRunner:
    """Runs one outside-site application as a headless Claude Code session"""

    def __init__(
        self,
        model: str,
        gate_dir: Path,
        timeout_seconds: float = 900,
        max_turns: int = 150,
    ):
        self.model = model
        self.gate = VerificationGate(gate_dir)
        self.timeout_seconds = timeout_seconds
        self.max_turns = max_turns
        self.last_result: ClaudeResult | None = None

    def _command(self) -> list[str]:
        gate_rule = f"Bash({_bash_arg(sys.executable)} {_bash_arg(GATE_SCRIPT)} wait:*)"
        return build_claude_command(
            model=self.model,
            json_schema=APPLY_RESULT_SCHEMA,
            tools=["Bash"],
            allowed_tools=["Bash(browser-use:*)", gate_rule],
            max_turns=self.max_turns,
        )

    async def _relay_verification(self, on_verified: Callable[[], Awaitable[None]] | None) -> None:
        print("\n" + "=" * 60)
        print("EMAIL VERIFICATION REQUIRED")
        print("Please check your email and confirm your account.")
        print("Once done, press Enter to continue...")
        print("=" * 60 + "\n")
        await asyncio.get_running_loop().run_in_executor(None, input)
        if on_verified is not None:
            await on_verified()
        self.gate.confirm()

    async def _run_once(
        self,
        task: str,
        env: dict[str, str],
        on_verified: Callable[[], Awaitable[None]] | None,
        poll_seconds: float,
    ) -> tuple[str, str] | ClaudeResult:
        cmd = self._command()
        CLAUDE_WORKDIR.mkdir(parents=True, exist_ok=True)
        process = await asyncio.create_subprocess_exec(
            *cmd,
            stdin=asyncio.subprocess.PIPE,
            stdout=asyncio.subprocess.PIPE,
            stderr=asyncio.subprocess.PIPE,
            cwd=CLAUDE_WORKDIR,
            env=env,
        )
        communicate = asyncio.ensure_future(process.communicate(task.encode("utf-8")))
        deadline = time.monotonic() + self.timeout_seconds
        while not communicate.done():
            await asyncio.wait({communicate}, timeout=poll_seconds)
            if communicate.done():
                break
            if self.gate.pending():
                await self._relay_verification(on_verified)
                # time spent waiting for the user does not count against the agent
                deadline = max(deadline, time.monotonic() + poll_seconds)
            if time.monotonic() > deadline:
                process.kill()
                await communicate
                return "Error", f"Agent timed out after {self.timeout_seconds} s"
        stdout, stderr = communicate.result()
        return parse_claude_output(
            stdout.decode("utf-8", errors="replace"),
            process.returncode,
            stderr.decode("utf-8", errors="replace"),
        )

    async def run(
        self,
        task: str,
        env_overrides: dict[str, str] | None = None,
        on_verified: Callable[[], Awaitable[None]] | None = None,
        poll_seconds: float = 1.0,
    ) -> tuple[str, str]:
        """Run the agent on task; returns ("Success" | "Skip" | "Error", reason)"""
        env = {**clean_env(os.environ), **(env_overrides or {})}
        for attempt in range(2):
            self.gate.reset()
            try:
                outcome = await self._run_once(task, env, on_verified, poll_seconds)
            except ClaudeUsageLimitError as e:
                if attempt == 1:
                    return "Error", str(e)
                if e.resets_at is not None:
                    wait_time = max(e.resets_at.timestamp() - time.time(), 0) + 60
                else:
                    wait_time = CLAUDE_LIMIT_DEFAULT_WAIT_SECONDS
                logger.warning(
                    f"Claude usage limit reached ({e}). Waiting {wait_time:.0f} seconds, then retrying the job..."
                )
                pause(wait_time, wait_time + 1)
                continue
            except ClaudeCLIError as e:
                logger.error(f"Claude apply agent failed: {e}")
                return "Error", str(e)
            if isinstance(outcome, tuple):
                return outcome
            self.last_result = outcome
            return map_apply_result(outcome.structured_output)
        return "Error", "Claude usage limit reached twice"
