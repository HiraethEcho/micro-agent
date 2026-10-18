# micro specification

## Goal

Build a small, standalone conversational agent under `src`, inspired by mini. Keep the implementation focused on conversation and tool calls.

- Do not import or depend on `minisweagent` code. Keep micro's model calls, conversation loop, and local tool execution inside `src`.
- Add Chinese comments to micro code blocks and functions. Explain the purpose of each code block and function. Keep comments clear and useful; do not add comments that only repeat a line of code.

## Configuration

Read JSON configuration files only; do not use mini environment configuration methods. Never load `.config/mini-swe-agent/.env` or another dotenv file.

- User configuration: `~/.config/micro/config.json`.
- Project configuration: `.micro/settings.json` in the project directory.
- Load user configuration first. Project configuration overrides matching user settings.
- Configuration fields: `model`, `url`, `key`, `system_prompt`, `default_mode`, `allow`, and `approve_on_enter`.
- `allow` is a list of command patterns for auto mode. Patterns support `*`, such as `git status *`. It defaults to an empty list, so auto asks before every command until patterns are configured.
- `approve_on_enter` controls the default response to a blank approval prompt. It defaults to `false`, which rejects the tool call.
- Default model: `ornith:9b`.
- Default Ollama URL: `http://localhost:11434`.
- `key` may be an empty string. Ollama does not require an API key by default.
- `default_mode` must be `yolo`, `ask`, or `auto`.

## Conversation and tools

- Provide a simple terminal REPL for user prompts and model responses.
- Support model tool calls.
- Do not import LiteLLM or calculate, fetch, or display model cost information.
- Mark thinking, messages, and tool calls with simple, distinct labels.
- Keep the system prompt in configuration.

## Modes

Switch modes with `/mode yolo`, `/mode ask`, or `/mode auto`.

- `yolo`: execute all model tool calls without asking.
- `ask`: ask for confirmation before every model tool call.
- `auto`: execute only read-only commands that match a pattern in `allow`. Patterns support `*`. Ask before executing write operations, unrecognized commands, command chains, pipelines, or redirections, even when a pattern matches.

## REPL commands

- `/mode yolo`, `/mode ask`, `/mode auto`: change the active mode.
- `/append-system-prompt <text|file>`: add a direct text or file source to the current session. File paths support `~`, `./`, `../`, absolute paths, and `file:` prefix.
- `/system-prompts`: interactively list sources and enable, disable, or remove one.
- `/print-system-prompt`: display the current enabled system prompt sources.
- Applicable `AGENTS.md` files are default-enabled `file` sources stored in the session header and reread before each model request. They can be managed with `/system-prompts`.
- `/resume`: list saved sessions and interactively choose one to resume.
- `/new-session`: create and switch to a new session.
- `/name <name>`: set the current session's display name.
- Skills discovery, `/skills` enable/disable, and `/skill:<name>` body injection are planned but not implemented. See `notes/skills-loading-design.md` for the design.
- `/help`: display available commands and the active mode.
- `/quit`: exit the REPL.
- Persist each session as JSONL under `.micro/sessions/` in the current working directory. Store prompt source definitions and state in the first JSONL record; append messages as they are produced with `YYYYMMDDTHHMMSS` timestamps.
- In modes that require confirmation, ask before executing the applicable tool call. `y/yes` approves and `n/no` rejects. Enter follows `approve_on_enter`.

## CLI session options

- `-c` / `--continue`: restore the most recent session in the current working directory.
- `-r` / `--resume`: show saved sessions at startup and interactively select one to restore. Blank input cancels startup.
- The options are mutually exclusive. Without either option, start a new session.

## Phase 2: steer and follow-up prompts

Do not implement these features in the first phase. In phase 2, keep the REPL able to accept `/steer xxx` and `/follow xxx` while the model is responding.

A turn is the agent's current response and tool-call sequence for a user request.

- **Steer**: `/steer xxx` adds `xxx` to the conversation while the turn is unfinished, such as when the model returns a tool call. Interrupt the current turn and continue with the added prompt.
- **Follow-up**: `/follow xxx` queues `xxx` while the model is responding. Let the current turn end naturally, then add the prompt and continue with the next turn.

## Out of scope

- Environment selection or environment configuration.
- Active model cost lookup or reporting.
- JSON mode, subagents, and active steer/follow-up prompts.
