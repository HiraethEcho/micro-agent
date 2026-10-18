# micro specification

## Goal

Build a small, standalone conversational agent under `src`, inspired by mini. Keep the implementation focused on conversation and tool calls.

- Do not import or depend on `minisweagent` code. Keep micro's model calls, conversation loop, and local tool execution inside `src`.
- Add Chinese comments to micro code blocks and functions. Explain the purpose of each code block and function. Keep comments clear and useful; do not add comments that only repeat a line of code.

## Configuration

Read JSON configuration files only; do not use mini environment configuration methods. Never load `.config/mini-swe-agent/.env` or another dotenv file.

- User configuration: `~/.config/micro/config.json`.
- Project configuration: `.micro.json` in the project directory.
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
- `/system_prompt_append <text>`: append session-only system instructions. Reload applicable `AGENTS.md` files before each model request so edits take effect during a session.
- `/print-system-prompt`: display the configured system prompt together with current session append and freshly loaded `AGENTS.md` instructions.
- `/help`: display available commands and the active mode.
- `/quit`: exit the REPL.
- In modes that require confirmation, ask before executing the applicable tool call. `y/yes` approves and `n/no` rejects. Enter follows `approve_on_enter`.

## Phase 2: steer and follow-up prompts

Do not implement these features in the first phase. In phase 2, keep the REPL able to accept `/steer xxx` and `/follow xxx` while the model is responding.

A turn is the agent's current response and tool-call sequence for a user request.

- **Steer**: `/steer xxx` adds `xxx` to the conversation while the turn is unfinished, such as when the model returns a tool call. Interrupt the current turn and continue with the added prompt.
- **Follow-up**: `/follow xxx` queues `xxx` while the model is responding. Let the current turn end naturally, then add the prompt and continue with the next turn.

## Out of scope

- Environment selection or environment configuration.
- Active model cost lookup or reporting.
- Features beyond conversation, tool calls, mode switching, help, exit, and steer/follow-up prompts.
