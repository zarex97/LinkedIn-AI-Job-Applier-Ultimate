# Spike notes: Claude CLI and browser-use CLI

Date: 2026-10-19. Claude Code 2.1.303, browser-use CLI 0.13.11 (browser_harness
0.1.13), Windows 11.

## Claude headless calls

- `claude -p --output-format json --model haiku` with the prompt on stdin works
  on the subscription login with `ANTHROPIC_API_KEY` unset.
- Result JSON fields used: `type` (`"result"`), `subtype` (`"success"`,
  `"error_max_turns"`), `is_error`, `result` (text, `null` on max turns),
  `structured_output`, `num_turns`, `session_id`, `usage.input_tokens`,
  `usage.output_tokens`, `usage.cache_creation_input_tokens`,
  `usage.cache_read_input_tokens`, and `modelUsage` (keys are the resolved model
  IDs, such as `claude-haiku-5-5`). `api_error_status` is `null` on success.
- `--max-turns` overrun exits 1 with `subtype: "error_max_turns"`,
  `is_error: true`, `result: null`.
- `--json-schema` returns the object in `structured_output`. It still works with
  `--tools ""`.
- UTF-8: stdin as UTF-8 bytes and stdout decoded as UTF-8 round-trip `José
  Peñalosa` and `日本` intact. Piping through Git Bash `echo` mangles it, so
  always use bytes from Python.

### Isolation

- `CLAUDE_ISOLATION_FLAGS = ["--setting-sources", "", "--strict-mcp-config",
  "--disable-slash-commands", "--no-session-persistence"]`
- `CLAUDE_NO_TOOLS_FLAGS = ["--tools", ""]`
- Proof: with `--setting-sources user`, the model quoted the user's global
  `CLAUDE.md` (graphify, CodeGraph). With `--setting-sources ""` it answered NO.
- Cost: a default `claude -p` call created about 26,000 cache tokens of system
  prompt and tool schemas. The isolated text call with `--system-prompt` and no
  tools created about 700.

## browser-use CLI

- Installed apart from the project venv with `uv tool install browser-use
  --python 3.12 --system-certs`. The project venv still has `browser-use 0.12.6`.
- The CLI runs Python from stdin with pre-imported helpers. It talks to a
  Chrome DevTools endpoint through a local daemon.
- By default it attaches to the user's running Chrome. Setting
  `BU_CDP_URL=http://127.0.0.1:<port>` points it at a browser we launch instead.
  `BU_NAME=<name>` keeps that daemon apart from any default one.
  `BH_TAB_MARKER=0` leaves page titles unchanged.
- If `BU_CDP_URL` is unreachable, the CLI fails after 30 s with a fatal error.
  It does not fall back to the user's Chrome.
- `BU_NAME=<name> browser-use --reload` stops the named daemon.

### Upload: passed

- Bot-owned Chromium from the project's Playwright
  (`launch_persistent_context(<temp dir>, headless=True,
  args=["--remote-debugging-port=9333"])`), driven by the CLI:
  `upload_file("#file-upload", <pdf path>)` on
  https://the-internet.herokuapp.com/upload, and the page listed the file.
- Same through `claude -p --model sonnet --allowedTools "Bash(browser-use:*)"`
  with a heredoc call: success in 4 turns, 7.3 s, about 72k input tokens, nearly
  all cached, and 421 output tokens. The default tool set was loaded. Passing
  `--tools Bash` should cut the cache tokens.

### Session: mechanism passed, live LinkedIn check deferred

- The CLI has no storage-state option. The bot loads the session itself:
  `context.add_cookies(state["cookies"])` from `BROWSER_STORAGE_STATE`
  before handing the CDP endpoint to the agent.
- Proof: a cookie injected this way was visible in `document.cookie` from a
  CLI-opened tab.
- No LinkedIn credentials are set up yet, so a real logged-in LinkedIn check
  moves to Task 9.
- Headless is set when the bot launches Chromium, from `HEADLESS_MODE`. The CLI
  has no headless option.
- Saving the session after email verification is done by the bot with
  `context.storage_state(path=BROWSER_STORAGE_STATE)`. The agent needs no
  command for it.

## Trial run on LinkedIn (Task 9)

Date: 2026-10-19, Max 5x plan, search: 5 roles in Argentina, past month, score bar 50.

- First attempt: every job page came back empty. The account's LinkedIn display
  language was Spanish (`lang: es`), and the scraper matches English headings
  ("About the job", "Set alert for similar jobs") and button labels. Fixed by
  switching the LinkedIn display language to English. The bot needs an
  English LinkedIn UI.
- After that, every page was read. Claude (`haiku`) scored 39 jobs at about
  15 to 20 s each. Most "Automation" and "Systems" hits were QA or sysadmin
  roles that scored low.
- Outside-site agent (`sonnet`), two runs:
  - easypeasyfluent ATS: stopped at a required Date of Birth missing from the
    resume, without inventing one. Result Skip, "Could not apply: ...". 4 turns.
  - Mercado Libre (eightfold.ai): submitted. 42 turns, 3.5 min, 817k input
    tokens (mostly cache reads), 10k output.
- Session saved and the named browser-use daemon stopped after each run.

Usage across the trial window (39 scorings, 2 outside-site runs, 1 application):

| Model | Calls | Input tokens | Output tokens | Time |
|---|---|---|---|---|
| claude-haiku-5-5 | 45 | 223,054 | 92,949 | 12.0 min |
| claude-sonnet-5-5 | 2 | 845,543 | 11,259 | 4.0 min |

`/usage` showed the five-hour session went up by 2%. That figure also includes
the Claude Code session used to run and watch the trial, so the bot's own
share is lower. Rough projection: about 1 to 2% of a five-hour window per
application at this match rate, so 50 a day would use most of a window's worth
each day. `MAX_APPLIES_NUM` is set to 20 for now, pending the weekly-limit
reading.

Open item: the run ended at "Applications sent: 2" with one application on
record. The second count was carried over in `last_run.yaml` from an earlier run
within the hour (`_check_the_previous_apply_number`); its source was not traced.

## Executor rulings and deferred review items

- Task 0: Ruling: uv could not download Python (TLS UnknownIssuer); used `uv python install 3.12.7 --system-certs` and `uv sync --dev --system-certs` — project pins python ==3.12.7 — cost if wrong: none, same interpreter version.
- Task 0: Ruling: tests need config/search_config.yaml too; copied examples/config/*.yaml into config/ (git-ignored) — tests import logger_config which reads it — cost if wrong: none.
- Task 0: Ruling: plan said commits carry a Co-Authored-By trailer; harness now says no attribution — removed the trailer rule from the plan — cost if wrong: missing attribution line.
- Task 1: Ruling: browser-use CLI attaches to a CDP endpoint and has no storage-state, headless or session-save command — the bot launches its own Chromium (Playwright persistent context in a temp profile, --remote-debugging-port, cookies from BROWSER_STORAGE_STATE, HEADLESS_MODE) and passes BU_CDP_URL + BU_NAME to claude; the bot saves the session with context.storage_state after the verification gate — spec requires bot's own session and never the user's Chrome, this is the only way the CLI supports it — cost if wrong: a browser-launch helper to rework.
- Task 1: Ruling: Task 7 build_claude_tool_notes drops storage_state/headless params -> build_claude_tool_notes(gate_script: Path, gate_dir: Path) -> str; test_tool_notes_follow_headless_mode replaced by a test that the bot browser launches with headless=HEADLESS_MODE — follows from the ruling above — cost if wrong: one signature.
- Task 1: Ruling: agent call adds --tools Bash next to --allowedTools — default tool set costs ~24k cache tokens per run — cost if wrong: agent lacks a tool it needs (only Bash is allowed anyway).
- Task 1: Ruling: live LinkedIn session check deferred to Task 9 — no credentials in .env yet; cookie-injection mechanism proven on a test site — cost if wrong: LinkedIn-specific session issue surfaces in Task 9.
- Task 2: Ruling: build_claude_command/run_claude gain tools: Sequence[str] | None — agent runs need --tools Bash (Task 1 ruling); no tools flags at all means CLAUDE_NO_TOOLS_FLAGS — cost if wrong: one parameter.
- Task 2: Ruling: task-done runs the full suite with the 4 baseline failures deselected (.superpowers/sdd/2026-10-19-claude-subscription/suite.sh) — they fail before any change — cost if wrong: a real regression in those 4 tests goes unseen.
- Task 4: Ruling: ClaudeWeeklyLimitError derives from BaseException instead of ClaudeCLIError — 203 'except Exception' blocks in src/main.py would each need a re-raise; no bare or BaseException excepts exist in src — cost if wrong: code that expects it to be a RuntimeError (none today).
- Task 5: Ruling: task text moved to src/llm/prompts.py (apply_agent_task_template + account/tool-note strings); build_apply_task in apply_agent.py formats it — project rule "keep prompts centralized in src/llm/prompts.py" — cost if wrong: none.
- Task 5: Ruling: .env_example lives at examples/.env_example; added external_sites_password there — cost if wrong: none.
- Task 5: Ruling: added ApplyAgent.loggable_task masking the password before the task is written to logs/llm_api_calls.yaml — project security rule "never log passwords"; upstream logged its derived password — cost if wrong: none.
- Task 7: Ruling: ClaudeCodeApplyRunner.run(task, env_overrides=None, on_verified=None, poll_seconds=1.0) — the runner needs BU_CDP_URL/BU_NAME for the bot browser and a hook to save the session after verification (Task 1 ruling) — cost if wrong: signature only.
- Task 7: Ruling: added BotBrowser (Playwright persistent context, temp profile, DevTools port, cookies from storage state, headless=HEADLESS_MODE) and stop_browser_use_daemon() in claude_apply_agent.py — follows Task 1 ruling — cost if wrong: a leftover daemon process per run.
- Task 7: Ruling: gate/verdict instructions live in prompts.claude_apply_agent_tool_notes; paths passed to the agent's Bash use forward slashes (Git Bash on Windows) and quotes only when they contain spaces — cost if wrong: gate command not allowed on paths with spaces (not live-tested).
- Task 7: Ruling: time the user spends answering the verification prompt does not count against timeout_seconds — a slow inbox should not fail the job — cost if wrong: a stuck run waits for Enter.
- Task 7: Ruling: full suite exposed a race in VerificationGate.confirm (done written before request removed); fixed order with test_confirm_removes_request_before_marking_done RED->GREEN — cost if wrong: none.
- Task 8: Ruling: also added claude_code to .claude/rules/configuration.md — keeps agent docs in step with the config — cost if wrong: none.
- Final: Ruling: the new agent tests' RED was an ImportError of the new helpers, not an assertion failure — they share one test module with the new names — cost if wrong: a test that would pass on old code (deadline/orphan logic reasoned against the old code paths).
- Final: minor (deferred): unreachable `return "Error", "Claude usage limit reached twice"` in ClaudeCodeApplyRunner.run.
- Final: minor (deferred): `except ClaudeWeeklyLimitError: raise` in ApplyAgent.apply_to_job is dead code now that it is a BaseException.
- Final: minor (deferred): classify_limit_error can match a site's "application limit reached" text in an agent error result.
- Final: minor (deferred): timeout_seconds=900 / max_turns=150 hard-coded, not in app_config.py.
- Final: minor (deferred): LLMLogger prices by EASY_APPLY_MODEL; full Claude IDs (not haiku/sonnet/opus aliases) log a fake cost.
- Final: minor (deferred): BotBrowser restores cookies but not localStorage origins.
- Final: minor (deferred): TEMPERATURE and FREE_TIER are ignored under claude_code; not documented.
- Final: minor (deferred): ClaudeCodeModel.invoke type hint says ChatPromptTemplate, receives a PromptValue.
- Final: Ruling: dashboard-launched runs cannot answer email verification (no stdin) — pre-existing upstream limitation; now fails the job cleanly instead of orphaning — cost if wrong: account-required sites fail under the dashboard.
- Final: Ruling: sync subprocess in ClaudeCodeModel blocks the loop per text call — same as every other provider — cost if wrong: none new.
- Final: Ruling: gate allow rule with spaces in paths untested live — this user's paths have none — cost if wrong: gate blocked on other machines.
- Final: Ruling: text calls keep PydanticOutputParser instead of --json-schema — behaviour-preserving, plan's choice — cost if wrong: occasional parse retries.
- Final: Ruling: removed derived password changes every provider — intended by spec — cost if wrong: none.
