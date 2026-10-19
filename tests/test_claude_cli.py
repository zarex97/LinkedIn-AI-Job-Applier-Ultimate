"""Test suite for src/llm/claude_cli.py"""

import json
import subprocess
from datetime import datetime
from pathlib import Path
from unittest.mock import patch

import pytest

from src.llm.claude_cli import (
    CLAUDE_ISOLATION_FLAGS,
    CLAUDE_NO_TOOLS_FLAGS,
    CLAUDE_WORKDIR,
    ClaudeCLIError,
    ClaudeResult,
    ClaudeUsageLimitError,
    ClaudeWeeklyLimitError,
    build_claude_command,
    classify_limit_error,
    clean_env,
    ensure_claude_available,
    parse_claude_output,
    run_claude,
)

FIXTURES = Path(__file__).parent / "fixtures" / "claude_cli"


def _fixture(name: str) -> str:
    return (FIXTURES / name).read_text(encoding="utf-8")


def _contains_sequence(items: list[str], sequence: list[str]) -> bool:
    n = len(sequence)
    return any(items[i : i + n] == sequence for i in range(len(items) - n + 1))


def test_clean_env_drops_api_keys():
    env = {"ANTHROPIC_API_KEY": "x", "ANTHROPIC_AUTH_TOKEN": "y", "PATH": "p"}
    assert clean_env(env) == {"PATH": "p"}


def test_build_command_text_call():
    cmd = build_claude_command(model="haiku", system_prompt="Be brief.")
    assert cmd[:6] == ["claude", "-p", "--output-format", "json", "--model", "haiku"]
    assert _contains_sequence(cmd, CLAUDE_ISOLATION_FLAGS)
    assert _contains_sequence(cmd, CLAUDE_NO_TOOLS_FLAGS)
    assert _contains_sequence(cmd, ["--system-prompt", "Be brief."])
    assert "--bare" not in cmd


def test_build_command_agent_call():
    schema = {"type": "object", "properties": {"ok": {"type": "boolean"}}}
    cmd = build_claude_command(
        model="sonnet",
        json_schema=schema,
        tools=["Bash"],
        allowed_tools=["Bash(browser-use:*)"],
        max_turns=150,
    )
    assert _contains_sequence(cmd, ["--allowedTools", "Bash(browser-use:*)"])
    assert _contains_sequence(cmd, ["--tools", "Bash"])
    assert _contains_sequence(cmd, ["--max-turns", "150"])
    assert _contains_sequence(cmd, ["--json-schema", json.dumps(schema)])
    assert not _contains_sequence(cmd, CLAUDE_NO_TOOLS_FLAGS)
    assert "--bare" not in cmd


def test_parse_success_text():
    result = parse_claude_output(_fixture("success_text.json"), 0)
    assert isinstance(result, ClaudeResult)
    assert result.text == "José Peñalosa"
    assert result.structured_output is None
    # input counts fresh, cache-write and cache-read tokens together
    assert result.input_tokens == 2 + 0 + 667
    assert result.output_tokens == 9
    assert result.model == "claude-haiku-5-5"
    assert result.num_turns == 1
    assert result.session_id == "37fa7401-b800-4be7-b3c7-6c777ccbbd35"


def test_parse_success_structured():
    result = parse_claude_output(_fixture("success_structured.json"), 0)
    assert result.structured_output["is_prime"] is True
    assert result.structured_output["reason"]
    assert result.input_tokens == 2 + 1182 + 0
    assert result.output_tokens == 202


def test_parse_max_turns_raises():
    with pytest.raises(ClaudeCLIError) as exc_info:
        parse_claude_output(_fixture("error_max_turns.json"), 1)
    assert not isinstance(exc_info.value, ClaudeUsageLimitError)
    assert "error_max_turns" in str(exc_info.value)


def test_parse_non_json_raises():
    with pytest.raises(ClaudeCLIError) as exc_info:
        parse_claude_output("oops", 1, "boom")
    assert "boom" in str(exc_info.value)


NOW = datetime(2026, 10, 19, 10, 0)


@pytest.mark.parametrize(
    "text, expected_type, expected_reset",
    [
        (
            "Claude AI usage limit reached|1760900000",
            ClaudeUsageLimitError,
            datetime.fromtimestamp(1760900000),
        ),
        ("5-hour limit reached ∙ resets 3pm", ClaudeUsageLimitError, datetime(2026, 10, 19, 15, 0)),
        ("You've hit your limit · resets 3pm", ClaudeUsageLimitError, datetime(2026, 10, 19, 15, 0)),
        (
            "Weekly limit reached ∙ resets Oct 21, 3pm",
            ClaudeWeeklyLimitError,
            datetime(2026, 10, 21, 15, 0),
        ),
        ("usage limit reached, try again later", ClaudeUsageLimitError, None),
    ],
)
def test_classify_limit_messages(text, expected_type, expected_reset):
    error = classify_limit_error(text, NOW)
    assert type(error) is expected_type
    assert error.resets_at == expected_reset


def test_classify_reset_time_already_passed_rolls_to_tomorrow():
    error = classify_limit_error("5-hour limit reached ∙ resets 9am", NOW)
    assert error.resets_at == datetime(2026, 10, 20, 9, 0)


def test_classify_non_limit_message():
    assert classify_limit_error("Invalid API key", NOW) is None


def test_parse_error_result_with_limit_raises_usage_limit():
    payload = json.dumps(
        {
            "type": "result",
            "subtype": "success",
            "is_error": True,
            "result": "Weekly limit reached ∙ resets Oct 21, 3pm",
            "num_turns": 1,
            "session_id": "s",
            "usage": {"input_tokens": 0, "output_tokens": 0},
            "modelUsage": {},
        }
    )
    with pytest.raises(ClaudeWeeklyLimitError):
        parse_claude_output(payload, 1)


def test_parse_non_json_with_limit_in_stderr_raises_usage_limit():
    with pytest.raises(ClaudeUsageLimitError):
        parse_claude_output("", 1, "Claude AI usage limit reached|1760900000")


def test_run_claude_passes_utf8_stdin_and_clean_env(monkeypatch):
    monkeypatch.setenv("ANTHROPIC_API_KEY", "should-not-leak")
    stdout = _fixture("success_text.json").encode("utf-8")
    completed = subprocess.CompletedProcess(args=[], returncode=0, stdout=stdout, stderr=b"")
    with patch("src.llm.claude_cli.subprocess.run", return_value=completed) as mock_run:
        result = run_claude("José Peñalosa", model="haiku")
    kwargs = mock_run.call_args.kwargs
    assert kwargs["input"] == "José Peñalosa".encode("utf-8")
    assert "ANTHROPIC_API_KEY" not in kwargs["env"]
    assert kwargs["cwd"] == CLAUDE_WORKDIR
    assert result.text == "José Peñalosa"


def test_run_claude_timeout_raises():
    with patch(
        "src.llm.claude_cli.subprocess.run",
        side_effect=subprocess.TimeoutExpired(cmd="claude", timeout=1),
    ):
        with pytest.raises(ClaudeCLIError, match="timed out"):
            run_claude("hi", model="haiku", timeout=1)


def test_ensure_claude_available_raises_when_missing():
    with patch("src.llm.claude_cli.shutil.which", return_value=None):
        with pytest.raises(ClaudeCLIError, match="Claude Code CLI not found"):
            ensure_claude_available()


def test_ensure_claude_available_passes_when_found():
    with patch("src.llm.claude_cli.shutil.which", return_value="C:/bin/claude.exe"):
        ensure_claude_available()


def test_run_claude_uses_resolved_executable():
    stdout = _fixture("success_text.json").encode("utf-8")
    completed = subprocess.CompletedProcess(args=[], returncode=0, stdout=stdout, stderr=b"")
    with (
        patch("src.llm.claude_cli.shutil.which", return_value="C:/bin/claude.exe"),
        patch("src.llm.claude_cli.subprocess.run", return_value=completed) as mock_run,
    ):
        run_claude("hi", model="haiku")
    assert mock_run.call_args.args[0][0] == "C:/bin/claude.exe"


def test_claude_workdir_is_outside_repo():
    repo_root = Path(__file__).resolve().parent.parent
    assert repo_root not in CLAUDE_WORKDIR.resolve().parents
    assert CLAUDE_WORKDIR.resolve() != repo_root



def test_parse_rate_limit_status_without_known_words_raises_usage_limit():
    """The CLI's HTTP status is a format-independent limit signal"""
    payload = json.dumps(
        {
            "type": "result",
            "subtype": "success",
            "is_error": True,
            "api_error_status": 429,
            "result": "You're out of usage for now",
            "num_turns": 1,
            "session_id": "s",
            "usage": {"input_tokens": 0, "output_tokens": 0},
            "modelUsage": {},
        }
    )
    with pytest.raises(ClaudeUsageLimitError):
        parse_claude_output(payload, 1)
