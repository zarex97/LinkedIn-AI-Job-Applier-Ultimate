"""
Run Claude Code in headless mode (`claude -p`) on the user's Claude subscription.

Every call goes through the `claude` CLI itself: the subscription login is never
read or reused directly. ANTHROPIC_API_KEY and ANTHROPIC_AUTH_TOKEN are removed
from the child environment, because in `-p` mode the CLI bills a present API key
instead of the subscription.
"""

import json
import os
import re
import shutil
import subprocess
import tempfile
from dataclasses import dataclass
from datetime import datetime, timedelta
from pathlib import Path
from typing import Mapping, Sequence

# Runs outside the repo so the repo's own .claude/ folder never loads into bot prompts
CLAUDE_WORKDIR = Path(tempfile.gettempdir()) / "job_applier_claude"

# Skip user, project and local settings (CLAUDE.md, hooks, skills, MCP servers)
CLAUDE_ISOLATION_FLAGS = [
    "--setting-sources",
    "",
    "--strict-mcp-config",
    "--disable-slash-commands",
    "--no-session-persistence",
]
CLAUDE_NO_TOOLS_FLAGS = ["--tools", ""]

# Wait used when a usage-limit message carries no reset time we can read
CLAUDE_LIMIT_DEFAULT_WAIT_SECONDS = 1800

_STRIPPED_ENV_KEYS = ("ANTHROPIC_API_KEY", "ANTHROPIC_AUTH_TOKEN")

_EPOCH_RESET = re.compile(r"\|\s*(\d{9,})")
_TEXT_RESET = re.compile(
    r"resets\s+(?:(?P<month>[A-Za-z]{3})[a-z]*\s+(?P<day>\d{1,2}),?\s*(?:at\s+)?)?"
    r"(?P<hour>\d{1,2})(?::(?P<minute>\d{2}))?\s*(?P<ampm>am|pm)",
    re.IGNORECASE,
)
_MONTHS = ["jan", "feb", "mar", "apr", "may", "jun", "jul", "aug", "sep", "oct", "nov", "dec"]


@dataclass(frozen=True)
class ClaudeResult:
    text: str
    structured_output: dict | None
    input_tokens: int
    output_tokens: int
    model: str
    num_turns: int
    session_id: str


class ClaudeCLIError(RuntimeError):
    """The claude CLI failed or returned an error result."""


class ClaudeUsageLimitError(ClaudeCLIError):
    """The subscription's five-hour usage limit was reached."""

    def __init__(self, message: str, resets_at: datetime | None = None):
        super().__init__(message)
        self.resets_at = resets_at


class ClaudeWeeklyLimitError(BaseException):
    """
    The subscription's weekly usage limit was reached.

    Derives from BaseException on purpose, like KeyboardInterrupt: the bot wraps
    LLM calls and job steps in many `except Exception` blocks, and this error must
    pass through all of them to end the run in main().
    """

    def __init__(self, message: str, resets_at: datetime | None = None):
        super().__init__(message)
        self.resets_at = resets_at


def clean_env(env: Mapping[str, str]) -> dict[str, str]:
    """Copy of env without Anthropic API credentials."""
    return {key: value for key, value in env.items() if key.upper() not in _STRIPPED_ENV_KEYS}


def build_claude_command(
    *,
    model: str,
    system_prompt: str | None = None,
    json_schema: dict | None = None,
    tools: Sequence[str] | None = None,
    allowed_tools: Sequence[str] | None = None,
    max_turns: int | None = None,
) -> list[str]:
    """Build the argument list for one headless claude call. The prompt goes on stdin."""
    cmd = ["claude", "-p", "--output-format", "json", "--model", model, *CLAUDE_ISOLATION_FLAGS]
    if system_prompt:
        cmd += ["--system-prompt", system_prompt]
    if tools is None and allowed_tools is None:
        cmd += CLAUDE_NO_TOOLS_FLAGS
    if tools is not None:
        cmd += ["--tools", *tools]
    if allowed_tools is not None:
        cmd += ["--allowedTools", *allowed_tools]
    if max_turns is not None:
        cmd += ["--max-turns", str(max_turns)]
    if json_schema is not None:
        cmd += ["--json-schema", json.dumps(json_schema)]
    return cmd


def _parse_reset_time(text: str, now: datetime) -> datetime | None:
    epoch = _EPOCH_RESET.search(text)
    if epoch:
        return datetime.fromtimestamp(int(epoch.group(1)))

    match = _TEXT_RESET.search(text)
    if not match:
        return None
    hour = int(match.group("hour")) % 12
    if match.group("ampm").lower() == "pm":
        hour += 12
    minute = int(match.group("minute") or 0)

    if match.group("month"):
        month_name = match.group("month").lower()[:3]
        if month_name not in _MONTHS:
            return None
        reset = datetime(now.year, _MONTHS.index(month_name) + 1, int(match.group("day")), hour, minute)
        if reset <= now:
            reset = reset.replace(year=now.year + 1)
        return reset

    reset = now.replace(hour=hour, minute=minute, second=0, microsecond=0)
    if reset <= now:
        reset += timedelta(days=1)
    return reset


def classify_limit_error(
    text: str, now: datetime
) -> ClaudeUsageLimitError | ClaudeWeeklyLimitError | None:
    """Return a usage-limit error if text reports one, else None."""
    lowered = text.lower()
    if "limit" not in lowered or not ("reached" in lowered or "hit" in lowered):
        return None
    resets_at = _parse_reset_time(text, now)
    if "weekly" in lowered:
        return ClaudeWeeklyLimitError(text.strip(), resets_at)
    return ClaudeUsageLimitError(text.strip(), resets_at)


def parse_claude_output(stdout: str, returncode: int, stderr: str = "") -> ClaudeResult:
    """Parse `claude -p --output-format json` output. Raises ClaudeCLIError on failure."""
    try:
        data = json.loads(stdout)
    except json.JSONDecodeError:
        limit_error = classify_limit_error(f"{stdout}\n{stderr}", datetime.now())
        if limit_error:
            raise limit_error from None
        raise ClaudeCLIError(
            f"claude returned no JSON (exit code {returncode}): {stderr.strip() or stdout.strip()}"
        ) from None

    result_text = data.get("result") or ""
    if data.get("is_error") or data.get("subtype") != "success":
        limit_error = classify_limit_error(f"{result_text}\n{stderr}", datetime.now())
        if limit_error:
            raise limit_error
        if data.get("api_error_status") == 429:
            raise ClaudeUsageLimitError(result_text.strip() or "Claude rate limit (HTTP 429)")
        raise ClaudeCLIError(
            f"claude failed ({data.get('subtype')}, exit code {returncode}): "
            f"{result_text or stderr.strip()}"
        )

    usage = data.get("usage") or {}
    input_tokens = (
        usage.get("input_tokens", 0)
        + usage.get("cache_creation_input_tokens", 0)
        + usage.get("cache_read_input_tokens", 0)
    )
    return ClaudeResult(
        text=result_text,
        structured_output=data.get("structured_output"),
        input_tokens=input_tokens,
        output_tokens=usage.get("output_tokens", 0),
        model=next(iter(data.get("modelUsage") or {}), ""),
        num_turns=data.get("num_turns", 0),
        session_id=data.get("session_id", ""),
    )


def ensure_claude_available() -> None:
    """Raise ClaudeCLIError if the claude CLI is not on PATH."""
    if shutil.which("claude") is None:
        raise ClaudeCLIError(
            "Claude Code CLI not found. Install it and run `claude` once to log in."
        )


def run_claude(
    prompt: str,
    *,
    model: str,
    system_prompt: str | None = None,
    json_schema: dict | None = None,
    tools: Sequence[str] | None = None,
    allowed_tools: Sequence[str] | None = None,
    max_turns: int | None = None,
    timeout: float = 300,
) -> ClaudeResult:
    """Run one headless claude call and return its parsed result."""
    cmd = build_claude_command(
        model=model,
        system_prompt=system_prompt,
        json_schema=json_schema,
        tools=tools,
        allowed_tools=allowed_tools,
        max_turns=max_turns,
    )
    cmd[0] = shutil.which("claude") or "claude"
    CLAUDE_WORKDIR.mkdir(parents=True, exist_ok=True)
    try:
        completed = subprocess.run(
            cmd,
            input=prompt.encode("utf-8"),
            capture_output=True,
            env=clean_env(os.environ),
            cwd=CLAUDE_WORKDIR,
            timeout=timeout,
        )
    except subprocess.TimeoutExpired as e:
        raise ClaudeCLIError(f"claude timed out after {timeout} s") from e
    return parse_claude_output(
        completed.stdout.decode("utf-8", errors="replace"),
        completed.returncode,
        completed.stderr.decode("utf-8", errors="replace"),
    )
