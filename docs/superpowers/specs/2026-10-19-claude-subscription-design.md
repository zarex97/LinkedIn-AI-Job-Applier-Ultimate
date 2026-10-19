# Run the job applier on a Claude subscription

Date: 2026-10-19
Upstream: https://github.com/beatwad/LinkedIn-AI-Job-Applier-Ultimate (branch `release`)

## Intent

The user wants this bot to apply to jobs for them, about 50 a day. They pay
for Claude Max 5x and have no API key of any kind. Today every LLM path in the
bot needs a provider API key (`llm_api_key` in `.env`). The fork adds a way to
run the whole bot on the user's own Claude subscription instead.

The fork is for the user's personal use on their own Windows 11 PC. It is not a
product offered to anyone else.

## Goals

- A new provider, `LLM_MODEL_TYPE = "claude_code"`, that needs no API key.
- Both kinds of applications work under it:
  - Easy Apply forms, handled by the existing bot flow.
  - Non-Easy Apply jobs on outside company sites, handled today by
    `src/llm/apply_agent.py`.
- About 50 applications a day in total, Easy Apply and outside sites
  together. That is `MAX_APPLIES_NUM = 50`, which already counts both kinds,
  with `EASY_APPLY_ONLY_MODE = False`. (User's decision.)
- That load fits inside Max 5x usage limits. If the spike shows it does not,
  lower `MAX_APPLIES_NUM` and keep the models as they are. Fewer jobs, same
  quality. (User's decision.)

## Non-goals

- Changing how the bot searches, scores, or fills Easy Apply forms.
- Supporting other people's subscriptions or a hosted service.
- Removing the existing providers. They should keep working as before.

## Anti-goals (a failure even if it runs)

- Reading, copying, or reusing the subscription's OAuth token to call the
  Anthropic API directly. Anthropic's terms forbid it. The only sanctioned
  route is running the `claude` CLI itself.
- Burning the user's weekly limit so they can't use Claude for anything else.

## Constraints

- Calls go through Claude Code headless mode: `claude -p` with
  `--output-format json`. Anthropic documents running the CLI as a subprocess
  this way. Usage counts against the same limits as the Claude app.
- `ANTHROPIC_API_KEY` must be unset in the subprocess environment. In `-p` mode
  the CLI always uses that key when present, which would bill the API instead.
- Do not use `--bare`. Bare mode never reads the subscription login.
- `--json-schema` returns schema-checked output in the `structured_output`
  field. Use it wherever the bot needs structured replies.
- Image input in `-p` is not documented. The current browser agent already
  runs with `use_vision=False`, so text-only is the baseline.
- Usage limits reset every five hours, plus a weekly cap. Hitting the
  five-hour limit pauses and retries after the reset, without marking jobs as
  failed. Hitting the weekly cap ends the run cleanly with a clear message.
  (Claude's call: sleeping for days is worse than a clean stop.)
- The bot spends text calls on every job it looks at, not only the ones it
  applies to: scoring, skill extraction, resume generation.
- LinkedIn itself limits Easy Apply to about 50 a day.

## How it works

### Part 1: Easy Apply and every other text call

All text calls already funnel through one place:

- `AIAdapter._create_model` in `src/llm/llm_manager.py` (around line 332)
  picks a model class from `LLM_MODEL_TYPE`.
- Each model class has `invoke(prompt)` taking a LangChain prompt value and
  returning an `AIMessage`. Most prepend
  `SystemMessage(prompts.custom_instructions)`.
- `LoggerChatModel` wraps it and reads `content`, `response_metadata` and
  `usage_metadata` from the returned `AIMessage`.
- Chains are `prompt | llm_cheap | StrOutputParser()` or a
  `PydanticOutputParser`.

Add a `ClaudeCodeModel(AIModel)` that runs `claude -p` as a subprocess,
returns an `AIMessage`, and fills `usage_metadata` from the CLI's JSON result.
Wire it into `AIAdapter._create_model` under `"claude_code"`. It must not
require an API key.

Every caller that builds a `GPTAnswerer`, `ApplyAgent` or `ResumeManager`
passes `secrets.get("llm_api_key")` along. With `claude_code` that value is
empty. The checks that raise "API key is required" must not fire for it.
Callers: `main.py`, `linkedin_messages.py`,
`src/job_manager/linkedin/easy_applier_linkedin.py`,
`src/job_manager/indeed/easy_applier_indeed.py`,
`src/resume_builder/resume_manager.py`, and the `__main__` block of
`src/llm/apply_agent.py`.

Model for these calls: `EASY_APPLY_MODEL`, set to a Haiku model by default.
(Claude's call: cheap and fast, saves the limit for the outside-site agent.)

### Part 2: outside company sites

Today `ApplyAgent.apply()` builds a `browser_use.Agent` from the Python library
(`browser-use==0.12.6`) with its own LLM client. That LLM client needs a key.

Under `claude_code`, replace that path. Claude Code itself is the agent, and it
drives the browser through the browser-use CLI
(https://github.com/browser-use/browser-use, "Path 2: CLI", installed with
`browser-use skill install`). The user chose the browser-use CLI over
Playwright MCP.

`ApplyAgent.apply_to_job(job_url)` keeps its signature and its
`("Success", "")` / `("Error", msg)` return. Callers are
`src/job_manager/linkedin/job_manager_linkedin.py` (around line 376) and
`src/job_manager/indeed/job_manager_indeed.py` (around line 330).

The existing task prompt in `ApplyAgent.apply()` carries over: job URL, resume
text, resume PDF path, fill every required field, stop if it can't apply, and
the final three-part summary.

The agent's final reply uses `--json-schema` to say whether it really
submitted. Submitted maps to `("Success", "")`. "Could not apply" maps to the
`Skip` result the job managers already handle, so it does not count toward
`MAX_APPLIES_NUM`. Today any finished run counts as Success. (Claude's call:
the daily count should only hold real applications. The builder confirms that
both job managers treat the new result as a skip.)

Accounts on outside sites. (User's decision.)

- When a site needs an account, the agent creates one with the user's email.
- The password comes from a new `.env` value, `external_sites_password`, that
  the user sets to a strong password. The old derived password
  (`<email prefix>123456`) goes away. If the value is missing, the agent
  treats account-only sites as "could not apply".
- Email verification still pauses for the user, as
  `wait_for_email_verification` does today. Because `claude -p` runs headless,
  the agent needs a new way to ask: for example, a small helper command it
  runs that blocks until the user presses Enter in the bot's console. After
  the pause, the browser session is saved as it is today.

Browser identity. (User's decision.) The agent uses the bot's own browser
session, loaded from `BROWSER_STORAGE_STATE` as today. It never uses the
user's real Chrome profile. `HEADLESS_MODE` still applies.

Model: `APPLY_AGENT_MODEL`, set to a Sonnet model by default. (Claude's call.)

### Config and setup

- `examples/config/app_config.py` lists `"claude_code"` as a possible value,
  with Haiku and Sonnet model examples.
- README gets a short section: install Claude Code, log in with the
  subscription, install the browser-use CLI and skill, set
  `LLM_MODEL_TYPE = "claude_code"`, leave `llm_api_key` empty.

## Must verify early

Run a throwaway spike before building Part 2:

1. `claude -p` can call the browser-use CLI and upload the resume PDF to a
   file input on a real application form.
2. The browser the CLI drives can load the bot's saved session from
   `BROWSER_STORAGE_STATE`.
3. Measure one Easy Apply job and one outside job: how many calls, how long,
   and how much of the five-hour limit each uses. Check that 50 a day fits.
   If not, pick a lower `MAX_APPLIES_NUM` and tell the user the number.

If item 1 or 2 fails, stop and bring it back to the user before going
further.

## Left to the builder

- The exact `claude -p` flags for text calls: system prompt handling, turning
  off tools, timeouts, how the prompt is passed on Windows.
- Running the subprocess in a clean working directory so no `CLAUDE.md`,
  hooks or project settings leak into bot prompts.
- How usage-limit errors are detected and how long to wait.
- Tests, following the repo's existing `pytest` setup.
