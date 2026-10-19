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
