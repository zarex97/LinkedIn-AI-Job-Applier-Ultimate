# Claude Subscription Provider Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Add `LLM_MODEL_TYPE = "claude_code"` so the whole bot, Easy Apply and outside-site applications, runs on the user's Claude Max subscription through the `claude` CLI, with no API key.

**Architecture:** One small module, `src/llm/claude_cli.py`, owns every `claude -p` call: command building, a clean environment, JSON parsing, and usage-limit errors. Text calls go through a new `ClaudeCodeModel` behind the existing `AIAdapter`. Outside-site applications go through a new `ClaudeCodeApplyRunner`: a single `claude -p` session that drives the browser with the browser-use CLI, pauses for email codes through a file-based gate, and ends with a schema-checked verdict.

**Tech Stack:** Python 3.12, uv, pytest, LangChain core messages, Claude Code CLI (`claude -p --output-format json`), browser-use CLI.

**Spec:** `docs/superpowers/specs/2026-10-19-claude-subscription-design.md`

## Global Constraints

- Every `claude` call uses `-p` and `--output-format json`. Never `--bare`.
- `ANTHROPIC_API_KEY` and `ANTHROPIC_AUTH_TOKEN` are removed from every `claude` subprocess environment. `load_dotenv()` copies `.env` into `os.environ`, so remove them there too, not only from the shell.
- Never read, copy or reuse the subscription's OAuth token.
- Every `claude` subprocess runs with `cwd` outside the repo: `Path(tempfile.gettempdir()) / "job_applier_claude"`. The repo has its own `.claude/` folder, which must not load into bot prompts.
- Default models under `claude_code`: `EASY_APPLY_MODEL = "haiku"`, `APPLY_AGENT_MODEL = "sonnet"`.
- Existing providers keep their behavior. The one exception is the outside-site password, which changes for every provider (Task 5).
- Do not change the pinned `browser-use==0.12.6` in `pyproject.toml`. The browser-use CLI installs separately with `uv tool install`.
- No test runs the real `claude` or browser-use CLI. Tests mock `subprocess` and `asyncio.create_subprocess_exec`.
- Target: Windows 11. Subprocess input and output are UTF-8 bytes, never the console code page.
- The fork's working branch is `claude-subscription`, cut from upstream `release`.
- Commit messages carry no attribution trailer.

## Review Focus

1. A usage-limit message in a format the patterns don't know. Expected: treated as the five-hour limit with a 30-minute default wait, never a crash or a failed job. Test in Task 2.
2. The weekly-limit error raised inside a job manager that catches `Exception`. Expected: it still reaches `main()` and ends the run. Test in Task 4.
3. `ANTHROPIC_API_KEY` present in `os.environ`, from the shell or `.env`. Expected: the child process never sees it. Test in Task 2.
4. The agent ends without a valid `structured_output`: max turns hit, crash, or timeout. Expected: `("Error", ...)`, never `Success`. Test in Task 7.
5. Resume and job text with non-ASCII characters, such as `José Peñalosa`. Expected: sent and received intact as UTF-8. Test in Task 2.

---

### Task 0: Fork, workspace and baseline

**Files:**
- Create: `config/app_config.py` (copy of `examples/config/app_config.py`, git-ignored)

**Interfaces:**
- Produces: a git repo at `C:\Users\isaac\OneDrive\Documentos\GitHub\linkedIn_jobApplier` on branch `claude-subscription`, with the spec and this plan committed.

- [ ] **Step 1: Fork on GitHub.** Run `gh auth status`. If not logged in, ask the user to run `! gh auth login`. Then run `gh repo fork beatwad/LinkedIn-AI-Job-Applier-Ultimate --clone=false`. Expected: the fork exists under the user's account.
- [ ] **Step 2: Turn the working folder into the clone.** The folder already holds `docs/superpowers/`, so `git clone` would refuse it. Run `git init`, then add the fork as `origin` and upstream as `upstream`. Then `git fetch origin` and `git checkout -b claude-subscription origin/release`. Expected: checkout succeeds and `docs/superpowers/` stays as untracked files.
- [ ] **Step 3: Install.** Run `cp examples/config/app_config.py config/app_config.py`, then `uv sync --dev`, then `uv run playwright install chromium`.
- [ ] **Step 4: Baseline tests.** Run `uv run pytest -q`. Record the pass and fail counts in the commit message. Later tasks must not add failures.
- [ ] **Step 5: Commit** `docs/superpowers/specs/2026-10-19-claude-subscription-design.md` and this plan. Message: `docs: add claude subscription design and plan`.

### Task 1: Spike — prove the CLI paths (throwaway, gated)

Throwaway exploration. Only the three outputs below are kept. **Gate:** if the resume upload (step 4) or the session load (step 5) fails, stop and report to the user before any later task.

**Files:**
- Create: `tests/fixtures/claude_cli/` with real `claude -p` JSON outputs: `success_text.json`, `success_structured.json`, `error_max_turns.json`
- Create: `src/llm/browser_use_cli_guide.md` — a command reference of at most about 60 lines, for the agent prompt
- Create: `docs/superpowers/specs/2026-10-19-spike-notes.md`

**Interfaces:**
- Produces: `CLAUDE_ISOLATION_FLAGS` and `CLAUDE_NO_TOOLS_FLAGS` values, recorded in the spike notes and used by Task 2. Also the exact browser-use CLI commands for opening a page with `BROWSER_STORAGE_STATE`, uploading a file, and saving the session, recorded in the guide.

- [ ] **Step 1: Headless auth.** In an empty temp folder, with `ANTHROPIC_API_KEY` unset, pipe a prompt on stdin to `claude -p --output-format json --model haiku`. Expected: a JSON result, no API billing. Save as `success_text.json`. Note the field names for result text, usage tokens, model, `num_turns`, `session_id` and `is_error`.
- [ ] **Step 2: Isolation and no tools.** Check `claude --help` for the flags that skip user, project and local settings, `CLAUDE.md` memory and tools. Prove it: ask "What instructions mention graphify?". The user's `~/.claude/CLAUDE.md` mentions it. Expected: the model knows nothing about it. Record the flags as `CLAUDE_ISOLATION_FLAGS` and `CLAUDE_NO_TOOLS_FLAGS`. Also confirm `--system-prompt`, `--json-schema` and `--max-turns`. Save a `--json-schema` run as `success_structured.json` and a `--max-turns 1` overrun as `error_max_turns.json`.
- [ ] **Step 3: Install the browser-use CLI apart from the project venv.** Run `uv tool install browser-use --python 3.12`. Expected: `browser-use --help` works, and `uv run python -c "import browser_use; print(browser_use.__version__)"` in the repo still prints `0.12.6`.
- [ ] **Step 4: Resume upload.** From `claude -p` with `--allowedTools "Bash(browser-use:*)"` and the isolation flags, have Claude open a public test form with a file input and upload any local PDF. Expected: the file shows as attached.
- [ ] **Step 5: Session load.** Log in once with the bot, by running `uv run python main.py` until login succeeds, so `browser_session/browser_state.json` exists. The run may fail after login, since no provider is set up yet. That is fine. Also find the CLI's headless option. Then have the CLI open `https://www.linkedin.com/feed/` with that state. Expected: logged in, no login page. Also find the command that saves the session back to that file.
- [ ] **Step 6: Write the guide and the notes.** The guide covers only commands the agent needs: open with state, read the page as text, click, type, select, upload, save the session, close. The notes record flags, field names, timings and anything that surprised you.
- [ ] **Step 7: Commit** the three outputs. Message: `chore: record claude and browser-use CLI spike results`.

### Task 2: `claude_cli` module

**Files:**
- Create: `src/llm/claude_cli.py`
- Test: `tests/test_claude_cli.py`

**Interfaces:**
- Consumes: the fixtures and flags from Task 1.
- Produces:
  - `CLAUDE_WORKDIR: Path`, `CLAUDE_ISOLATION_FLAGS: list[str]`, `CLAUDE_NO_TOOLS_FLAGS: list[str]`
  - `@dataclass(frozen=True) class ClaudeResult: text: str; structured_output: dict | None; input_tokens: int; output_tokens: int; model: str; num_turns: int; session_id: str`
  - `class ClaudeCLIError(RuntimeError)`
  - `class ClaudeUsageLimitError(ClaudeCLIError)` with attribute `resets_at: datetime | None` (the five-hour limit)
  - `class ClaudeWeeklyLimitError(ClaudeCLIError)` with attribute `resets_at: datetime | None`
  - `def clean_env(env: Mapping[str, str]) -> dict[str, str]`
  - `def build_claude_command(*, model: str, system_prompt: str | None = None, json_schema: dict | None = None, allowed_tools: Sequence[str] | None = None, max_turns: int | None = None) -> list[str]`
  - `def classify_limit_error(text: str, now: datetime) -> ClaudeCLIError | None`
  - `def parse_claude_output(stdout: str, returncode: int, stderr: str = "") -> ClaudeResult`
  - `def run_claude(prompt: str, *, model: str, system_prompt: str | None = None, json_schema: dict | None = None, allowed_tools: Sequence[str] | None = None, max_turns: int | None = None, timeout: float = 300) -> ClaudeResult`
  - `def ensure_claude_available() -> None` raises `ClaudeCLIError("Claude Code CLI not found. Install it and run `claude` once to log in.")` when `shutil.which("claude")` is `None`

- [ ] **Step 1: Write failing tests.**
  - `test_clean_env_drops_api_keys`: `clean_env({"ANTHROPIC_API_KEY": "x", "ANTHROPIC_AUTH_TOKEN": "y", "PATH": "p"}) == {"PATH": "p"}`.
  - `test_build_command_text_call`: the result starts with `["claude", "-p", "--output-format", "json", "--model", "haiku"]`, contains every item of `CLAUDE_ISOLATION_FLAGS` and `CLAUDE_NO_TOOLS_FLAGS`, contains `"--system-prompt"` followed by the given text, and contains no `"--bare"`.
  - `test_build_command_agent_call`: with `allowed_tools=["Bash(browser-use:*)"]`, `max_turns=150` and a schema, it holds `"--allowedTools"`, `"Bash(browser-use:*)"`, `"--max-turns"`, `"150"`, `"--json-schema"` and `json.dumps(schema)`. It holds none of `CLAUDE_NO_TOOLS_FLAGS`.
  - `test_parse_success_text` and `test_parse_success_structured`: load the Task 1 fixtures and assert text, tokens, model and `structured_output`.
  - `test_parse_max_turns_raises`: the `error_max_turns.json` fixture raises `ClaudeCLIError`.
  - `test_parse_non_json_raises`: `parse_claude_output("oops", 1, "boom")` raises `ClaudeCLIError` with `"boom"` in the message.
  - `test_classify_limit_messages`, parametrized with `now = datetime(2026, 10, 19, 10, 0)`:
    - `"Claude AI usage limit reached|1760900000"` gives `ClaudeUsageLimitError` with `resets_at == datetime.fromtimestamp(1760900000)`.
    - `"5-hour limit reached ∙ resets 3pm"` gives `ClaudeUsageLimitError` with `resets_at == datetime(2026, 10, 19, 15, 0)`.
    - `"You've hit your limit · resets 3pm"` gives `ClaudeUsageLimitError`.
    - `"Weekly limit reached ∙ resets Oct 21, 3pm"` gives `ClaudeWeeklyLimitError` with `resets_at == datetime(2026, 10, 21, 15, 0)`.
    - `"usage limit reached, try again later"` gives `ClaudeUsageLimitError` with `resets_at is None`.
    - `"Invalid API key"` gives `None`.
  - `test_parse_error_result_with_limit_raises_usage_limit`: an `is_error` JSON whose result text is a limit message raises the matching subclass.
  - `test_run_claude_passes_utf8_stdin_and_clean_env`: patch `subprocess.run`. Call `run_claude("José Peñalosa", model="haiku")` with `ANTHROPIC_API_KEY` set through `monkeypatch.setenv`. Assert `input == "José Peñalosa".encode("utf-8")`, `"ANTHROPIC_API_KEY" not in env`, and `cwd == CLAUDE_WORKDIR`. Also assert stdout bytes with `ñ` decode intact.
  - `test_ensure_claude_available_raises_when_missing`: patch `shutil.which` to return `None`.
- [ ] **Step 2: Run** `uv run pytest tests/test_claude_cli.py -q`. Expected: FAIL on import.
- [ ] **Step 3: Implement** `src/llm/claude_cli.py`. Pass the prompt on stdin as bytes, never as an argument, to dodge Windows length and quoting limits. `run_claude` creates `CLAUDE_WORKDIR` if missing. A timeout raises `ClaudeCLIError`. In `classify_limit_error`, "weekly" wins over "5-hour". Any text with "limit" plus "reached" or "hit" counts as a limit error. A reset time already passed today rolls to tomorrow.
- [ ] **Step 4: Run** the same tests. Expected: PASS.
- [ ] **Step 5: Commit.** Message: `feat: add claude CLI wrapper with usage-limit errors`.

### Task 3: `ClaudeCodeModel` behind `AIAdapter`

**Files:**
- Modify: `src/llm/llm_manager.py` (new class after `ClaudeModel`, new branch in `AIAdapter._create_model` around line 332)
- Modify: `config/constants.py` (`PRICE_DICT`)
- Test: `tests/test_llm_manager.py`

**Interfaces:**
- Consumes: `run_claude`, `ClaudeResult` from Task 2.
- Produces: `class ClaudeCodeModel(AIModel)` with `__init__(self, llm_model: str) -> None` and `invoke(self, prompt) -> AIMessage`. `AIAdapter` builds it when `LLM_MODEL_TYPE == "claude_code"`, needs no API key, and calls `ensure_claude_available()` first.

- [ ] **Step 1: Write failing tests.**
  - `test_claude_code_model_invoke`: patch `src.llm.llm_manager.run_claude` to return a `ClaudeResult` with text `"hi"`, 10 in and 3 out. Invoke with `ChatPromptTemplate.from_template("Q: {q}").invoke({"q": "x"})`. Assert:
    - `run_claude` got `system_prompt=prompts.custom_instructions` and `model="haiku"`, and its prompt contains `"Q: x"`.
    - The result is an `AIMessage` with `content == "hi"` and `usage_metadata == {"input_tokens": 10, "output_tokens": 3, "total_tokens": 13}`.
    - `response_metadata["model_name"]` is the result's model.
  - `test_ai_adapter_claude_code_needs_no_key`: with `@patch("src.llm.llm_manager.LLM_MODEL_TYPE", "claude_code")` and `ensure_claude_available` patched, `AIAdapter(api_key=None)` builds a `ClaudeCodeModel`.
  - `test_logger_chat_model_parses_claude_code_reply`: `LoggerChatModel.parse_llmresult` on that `AIMessage` reports the token counts.
  - `test_price_dict_claude_aliases_are_free`: `cost_per_token("haiku", 1000, 1000) == (0.0, 0.0)`, and the same for `"sonnet"` and `"opus"`.
- [ ] **Step 2: Run** `uv run pytest tests/test_llm_manager.py -q`. Expected: the new tests FAIL.
- [ ] **Step 3: Implement.** Build the prompt by joining `m.content` from `prompt.to_messages()` with blank lines. Add `"haiku"`, `"sonnet"` and `"opus"` to `PRICE_DICT` at `0.0`, since subscription use costs nothing per token.
- [ ] **Step 4: Run** the full suite with `uv run pytest -q`. Expected: no new failures against the Task 0 baseline.
- [ ] **Step 5: Commit.** Message: `feat: add claude_code provider for text calls`.

### Task 4: Usage-limit behavior across the run

**Files:**
- Modify: `src/llm/llm_manager.py` (`LoggerChatModel.__call__` retry loop)
- Modify: `main.py` (the `try` block in `main()` around line 449)
- Modify: any job-manager `except Exception` that would swallow the weekly error. Find them with `grep -rn "except Exception" src/job_manager`.
- Test: `tests/test_llm_manager.py`, `tests/test_job_manager_linkedin.py`, `tests/test_main.py`

**Interfaces:**
- Consumes: `ClaudeUsageLimitError`, `ClaudeWeeklyLimitError` from Task 2.
- Produces: the five-hour limit waits and retries inside `LoggerChatModel`. The weekly limit propagates to `main()`, which logs `"Claude weekly usage limit reached. Stopping until it resets at <time>."`, emits `run_stopped`, and sets `should_exit = True`.

- [ ] **Step 1: Write failing tests.**
  - `test_logger_chat_model_waits_on_usage_limit`: the model raises `ClaudeUsageLimitError(resets_at=None)` once, then returns. Patch `pause`. Assert `pause` was called with `(1800, 1801)` and the reply came back.
  - `test_logger_chat_model_waits_until_reset`: with `resets_at` = now + 10 minutes, assert the first `pause` argument is within 5 seconds of 660.
  - `test_logger_chat_model_reraises_weekly_limit`: `ClaudeWeeklyLimitError` propagates.
  - `test_weekly_limit_propagates_through_job_manager`: make the LinkedIn job manager's apply path raise `ClaudeWeeklyLimitError` from `llm_answerer_component`. Assert it reaches the caller. Use the existing fixtures in `tests/test_job_manager_linkedin.py`.
  - `test_main_stops_on_weekly_limit`: patch `create_and_run_bot` to raise it, with `RESTART_EVERY_DAY = True`. Assert `main()` returns without the hourly sleep and logs the message.
- [ ] **Step 2: Run** those tests. Expected: FAIL.
- [ ] **Step 3: Implement.** The wait is `(resets_at - now).total_seconds() + 60`, or `1800` when `resets_at` is `None`, passed as `pause(wait, wait + 1)`. Add `except ClaudeWeeklyLimitError: raise` above each swallowing `except Exception` that Step 1 shows matters.
- [ ] **Step 4: Run** `uv run pytest -q`. Expected: no new failures.
- [ ] **Step 5: Commit.** Message: `feat: wait on five-hour limit, stop cleanly on weekly limit`.

### Task 5: Shared apply task prompt and outside-site password

**Files:**
- Modify: `src/llm/apply_agent.py` (pull the task string out of `ApplyAgent.apply()`, add a constructor parameter, fix the `__main__` key check)
- Modify: `src/pydantic_models/config_models.py` (`Secrets`)
- Modify: `main.py:319` (pass the password)
- Modify: `.env_example`, if present
- Test: `tests/test_apply_agent.py` (new)

**Interfaces:**
- Produces:
  - `def build_apply_task(job_url: str, resume_readable: str, resume_pdf_path: str, user_email: str | None, external_sites_password: str | None, tool_notes: str) -> str`
  - `Secrets.external_sites_password: Optional[str] = None`
  - `ApplyAgent.__init__(self, api_key=None, browser_storage_state=None, llm_api_url=None, user_email=None, external_sites_password=None)`

- [ ] **Step 1: Write failing tests.**
  - `test_task_uses_configured_password`: with `user_email="ana@x.com"` and password `"S3cure!pw"`, the task contains `"ana@x.com"` and `"S3cure!pw"`, and does not contain `"ana123456"`.
  - `test_task_without_password_says_cannot_register`: with password `None`, the task contains `"If the site requires creating an account, stop: you cannot apply."` and contains no `"123456"`.
  - `test_task_keeps_core_rules`: the task contains the job URL, the resume text, the PDF path, `"Do not skip required fields"` and `tool_notes`.
  - `test_secrets_accepts_external_sites_password`.
  - `test_apply_agent_claude_code_needs_no_key`: with `LLM_MODEL_TYPE` patched to `"claude_code"`, `ApplyAgent(None, "x.json")` builds without raising, and `agent.llm is None`.
- [ ] **Step 2: Run** `uv run pytest tests/test_apply_agent.py -q`. Expected: FAIL.
- [ ] **Step 3: Implement.** The existing browser_use path calls `build_apply_task` with its current tool notes about `upload_resume`, `upload_file_to_element` and `wait_for_email_verification`. `select_model_type("claude_code", ...)` returns `None`. The `__main__` block skips its key check under `claude_code`. Add `external_sites_password=""` with a comment to `.env_example`.
- [ ] **Step 4: Run** `uv run pytest -q`. Expected: no new failures.
- [ ] **Step 5: Commit.** Message: `feat: configurable outside-site password, shared apply task`.

### Task 6: Email verification gate

**Files:**
- Create: `src/llm/verification_gate.py` (importable, and runnable as a script: `python <path>/verification_gate.py wait <gate_dir>`)
- Test: `tests/test_verification_gate.py`

**Interfaces:**
- Produces: `class VerificationGate` with:
  - `__init__(self, gate_dir: Path)`
  - `request(self) -> None` writes `gate_dir/request`
  - `pending(self) -> bool`
  - `confirm(self) -> None` writes `gate_dir/done` and removes `request`
  - `wait_for_confirmation(self, poll_seconds: float = 1.0, timeout: float = 1800) -> bool`
  - `reset(self) -> None`
- The script's `wait` command calls `request()` then `wait_for_confirmation()`. It prints `"User confirmed email verification."` and exits 0, or prints `"Timed out waiting for the user."` and exits 1.

- [ ] **Step 1: Write failing tests.** These use `tmp_path`.
  - `test_request_then_pending`.
  - `test_confirm_releases_waiter`: a thread confirms after 0.2 seconds. `wait_for_confirmation(poll_seconds=0.05)` returns `True`.
  - `test_wait_times_out`: `timeout=0.2` returns `False`.
  - `test_reset_clears_files`.
  - `test_script_wait_exit_codes`: run the script through `subprocess.run([sys.executable, path, "wait", str(tmp_path)])` with a confirming thread. Expected exit code 0.
- [ ] **Step 2: Run** them. Expected: FAIL.
- [ ] **Step 3: Implement** with only the standard library, so the script runs from any `cwd` with no repo imports. Add a `--timeout` option, default 1800.
- [ ] **Step 4: Run** them. Expected: PASS.
- [ ] **Step 5: Commit.** Message: `feat: add file-based email verification gate`.

### Task 7: Outside-site applications through Claude Code

**Files:**
- Create: `src/llm/claude_apply_agent.py`
- Modify: `src/llm/apply_agent.py` (`apply()` and `apply_to_job()`)
- Test: `tests/test_claude_apply_agent.py`

**Interfaces:**
- Consumes: `build_claude_command`, `clean_env`, `parse_claude_output`, `CLAUDE_WORKDIR`, and the limit errors from Task 2. `build_apply_task` from Task 5. `VerificationGate` from Task 6. `src/llm/browser_use_cli_guide.md` from Task 1.
- Produces:
  - `APPLY_RESULT_SCHEMA: dict` with required `submitted: boolean`, `reason: string`, `summary: string`, `questions: array of string`
  - `def map_apply_result(structured: dict | None) -> tuple[str, str]`
  - `def build_claude_tool_notes(gate_script: Path, gate_dir: Path, storage_state: str, headless: bool) -> str` — the CLI guide text plus gate, session-save and headless instructions. `headless` comes from `HEADLESS_MODE`, using the guide's headless option.
  - `class ClaudeCodeApplyRunner` with `__init__(self, model: str, gate_dir: Path, timeout_seconds: float = 900, max_turns: int = 150)` and `async run(self, task: str) -> tuple[str, str]`
  - `ApplyAgent.apply()` returns `tuple[str, str]`. `apply_to_job()` returns that tuple, re-raises `ClaudeWeeklyLimitError`, and keeps returning `("Error", str(e))` for other exceptions.

- [ ] **Step 1: Write failing tests.**
  - `test_map_submitted`: `map_apply_result({"submitted": True, "reason": "", "summary": "s", "questions": []}) == ("Success", "")`.
  - `test_map_not_submitted`: `{"submitted": False, "reason": "site needs SSN", ...}` gives `("Skip", "Could not apply: site needs SSN")`. The `"Could not"` prefix makes `job_manager_linkedin.py` collect it for the user's report.
  - `test_map_missing_output`: `map_apply_result(None) == ("Error", "Agent ended without a verdict")`.
  - `test_runner_command`: patch `asyncio.create_subprocess_exec` and capture its args. The command allows `Bash(browser-use:*)` plus the gate script command, uses `--model sonnet`, `--max-turns 150` and `--json-schema` with `APPLY_RESULT_SCHEMA`, and runs with `cwd=CLAUDE_WORKDIR` and an env without `ANTHROPIC_API_KEY`.
  - `test_tool_notes_follow_headless_mode`: `build_claude_tool_notes(..., headless=True)` contains the guide's headless option, and `headless=False` does not.
  - `test_runner_relays_verification`: a fake process stays running while a test thread calls `VerificationGate(gate_dir).request()`. Patch `input` to return `""`. Assert `confirm()` happened and `run` returns the mapped result.
  - `test_runner_timeout_kills_process`: with `timeout_seconds=0.1` and a fake process that never ends, assert `kill()` was called and the result is `("Error", "Agent timed out after 0.1 s")`.
  - `test_runner_retries_once_after_usage_limit`: the first process output is a five-hour limit error and the second succeeds. Patch `pause`. The result is `("Success", "")`, with exactly one `pause`.
  - `test_runner_raises_weekly`: a weekly-limit output raises `ClaudeWeeklyLimitError`.
  - `test_apply_to_job_reraises_weekly`.
- [ ] **Step 2: Run** `uv run pytest tests/test_claude_apply_agent.py -q`. Expected: FAIL.
- [ ] **Step 3: Implement.**
  - `run` writes the task to stdin as UTF-8.
  - While the process runs, it polls the gate every second. When a request is pending, it prints the same banner as `wait_for_email_verification`, reads `input()` in an executor, then calls `confirm()`.
  - It calls `gate.reset()` before each run.
  - The tool notes tell the agent to run `"<sys.executable>" "<gate_script>" wait "<gate_dir>"` when a site asks for email verification, then save the session to `BROWSER_STORAGE_STATE` with the guide's command.
  - `ApplyAgent.apply()` under `claude_code` builds the task with these notes, runs the runner with `APPLY_AGENT_MODEL`, and appends an `LLMCall` to `llm_api_calls.yaml` with the result's tokens and `total_cost=0.0`.
- [ ] **Step 4: Run** `uv run pytest -q`. Expected: no new failures.
- [ ] **Step 5: Commit.** Message: `feat: apply on outside sites through Claude Code and browser-use CLI`.

### Task 8: Config example and README

**Files:**
- Modify: `examples/config/app_config.py` (the `LLM type` docstring around line 155 and the model lines)
- Modify: `README.md` (the "Supported LLM models" section)

- [ ] **Step 1: Example config.** Add `"claude_code"` to the possible values. Add commented examples `# EASY_APPLY_MODEL = "haiku"  # with claude_code` and `# APPLY_AGENT_MODEL = "sonnet"  # with claude_code`.
- [ ] **Step 2: README section "Claude subscription (no API key)"**, as numbered setup steps:
  1. Install Claude Code and run `claude` once to log in with the subscription.
  2. Run `uv tool install browser-use --python 3.12`.
  3. Set `LLM_MODEL_TYPE = "claude_code"`, `EASY_APPLY_MODEL = "haiku"`, `APPLY_AGENT_MODEL = "sonnet"` and `EASY_APPLY_ONLY_MODE = False`.
  4. Leave `llm_api_key` empty. Make sure `ANTHROPIC_API_KEY` is not set.
  5. Set `external_sites_password` to a strong password.
  6. Note that usage counts against the plan's limits, shared with the Claude app. The bot waits out the five-hour limit and stops at the weekly cap.
- [ ] **Step 3: Check.** Run `uv run python -c "import ast; ast.parse(open('examples/config/app_config.py').read())"`. Expected: no error.
- [ ] **Step 4: Commit.** Message: `docs: document claude_code provider`.

### Task 9: Trial run and daily cap

Live run with the user present. It touches the user's real LinkedIn account and real applications, so ask before starting.

**Files:**
- Modify: `config/app_config.py` (user-owned, not committed)
- Modify: `docs/superpowers/specs/2026-10-19-spike-notes.md` (add measurements)

- [ ] **Step 1: Configure** as in the README section. Set `MAX_APPLIES_NUM = 2` for the trial.
- [ ] **Step 2: Run** `uv run python main.py` until one Easy Apply and one outside-site application finish. Expected: both show in the logs with a real result. `logs/llm_api_calls.yaml` holds token counts.
- [ ] **Step 3: Measure** calls, minutes and tokens per job of each kind. Read `claude` usage with `/usage` in an interactive `claude` session before and after. Estimate the share of the five-hour window and the week that 50 jobs would use, assuming the user's real Easy Apply to outside-site mix.
- [ ] **Step 4: Pick the cap.** If 50 fits with room left for the user's own Claude use, set `MAX_APPLIES_NUM = 50`. If not, pick the highest number that fits and keep the models. Tell the user the number and why.
- [ ] **Step 5: Commit** the notes. Message: `docs: record trial-run usage measurements`. Then push the branch with `git push -u origin claude-subscription`.
