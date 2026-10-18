"""读取 micro 配置并提供独立的终端 REPL。"""

import json
import shlex
import sys
from pathlib import Path

import typer
from prompt_toolkit import PromptSession
from prompt_toolkit import prompt
from prompt_toolkit.history import InMemoryHistory
from rich.console import Console

from agent import MicroAgent, Mode, find_project_instruction_files
from config import DEFAULT_SYSTEM_PROMPT, MicroConfig, load_config
from json_mode import run_json_protocol
from sessions import SessionStore

console = Console(highlight=False)
app = typer.Typer(add_completion=False, help="A small conversational coding agent.")


def build_agent(
    config: MicroConfig, session_store: SessionStore | None = None
) -> MicroAgent:
    """仅用 micro 自身的配置构造对话代理。"""
    return MicroAgent(config, session_store)


def create_session(config: MicroConfig) -> SessionStore:
    """把默认 prompt 和已配置 prompt 初始化为可管理的前置来源项。"""
    system_appends = [{"kind": "default", "content": DEFAULT_SYSTEM_PROMPT}]
    if config.system_prompt != DEFAULT_SYSTEM_PROMPT:
        system_appends.append(
            {"kind": "setting", "content": config.system_prompt}
        )
    for path in find_project_instruction_files():
        system_appends.append(
            {"kind": "file", "path": str(path.resolve()), "managed": "agents"}
        )
    return SessionStore.create(system_appends=system_appends, agents_initialized=True)


def choose_session(
    sessions: list[dict],
) -> tuple[SessionStore, list[dict], list[dict]] | None:
    """显示会话清单并让用户按编号选择要恢复的记录。"""
    for index, session in enumerate(sessions, 1):
        display_name = session.get("name") or session["id"]
        console.print(
            f'{index}. {display_name} [{session["id"]}]  {session["created_at"]}',
            markup=False,
        )
    choice = prompt("Resume which session? Enter number (blank to cancel): ").strip()
    if not choice:
        return None
    try:
        index = int(choice) - 1
    except ValueError:
        console.print("Invalid session number.", style="yellow")
        return None
    if index < 0 or index >= len(sessions):
        console.print("Invalid session number.", style="yellow")
        return None
    try:
        return SessionStore.load(sessions[index]["id"])
    except (FileNotFoundError, ValueError) as error:
        console.print(str(error), style="yellow", markup=False)
        return None


def parse_system_prompt_source(argument: str) -> tuple[str, str, str | None]:
    """将命令参数解析为文本来源或规范化的文件路径。"""
    raw = argument.strip()
    explicit_file = raw.startswith("file:")
    value = raw[5:].strip() if explicit_file else raw
    parts = shlex.split(value)
    value = " ".join(parts).strip()
    if not value:
        raise ValueError("System prompt source cannot be empty.")

    path = Path(value).expanduser()
    path_like = explicit_file or value.startswith(("~", "./", "../")) or path.is_file()
    if path_like:
        resolved_path = path.resolve()
        if not resolved_path.is_file():
            raise FileNotFoundError(f"System prompt file not found: {resolved_path}")
        return "file", "", str(resolved_path)
    return "text", value, None


def manage_system_prompts(agent: MicroAgent) -> None:
    """交互显示追加来源，并对所选项执行启用、禁用或删除。"""
    if agent.session_store is None:
        console.print("No active session.", style="yellow")
        return
    agent.refresh_project_instruction_sources()
    items = agent.session_store.system_appends
    if not items:
        console.print("No system prompt sources.", style="yellow")
        return

    for index, item in enumerate(items, 1):
        state = "enabled" if item.get("enabled", True) else "disabled"
        source = item.get("path") or item.get("content", "")
        source = " ".join(source.split())
        if len(source) > 72:
            source = source[:69] + "..."
        console.print(
            f'{index}. {item["id"]} [{item["kind"]}, {state}] {source}',
            markup=False,
        )

    choice = prompt("Select source number (blank to cancel): ").strip()
    if not choice:
        return
    try:
        index = int(choice) - 1
    except ValueError:
        console.print("Invalid source number.", style="yellow")
        return
    if index < 0 or index >= len(items):
        console.print("Invalid source number.", style="yellow")
        return

    item = items[index]
    action = prompt("Action: [e]nable, [d]isable, [r]emove: ").strip().lower()
    if action in {"e", "enable"}:
        changed = agent.session_store.set_system_prompt_enabled(item["id"], True)
    elif action in {"d", "disable"}:
        changed = agent.session_store.set_system_prompt_enabled(item["id"], False)
    elif action in {"r", "remove"}:
        changed = agent.session_store.remove_system_prompt_item(item["id"])
    else:
        console.print("Unknown action; no change made.", style="yellow")
        return
    agent.system_append = agent.session_store.system_appends
    if changed:
        console.print("System prompt sources updated.", style="yellow")


def manage_skills(agent: MicroAgent) -> None:
    """列出发现的 Skills，并切换所选 Skill 的 system prompt 元信息状态。"""
    skills = agent.available_skills()
    if not skills:
        console.print("No skills found.", style="yellow")
        return
    for index, skill in enumerate(skills, 1):
        enabled = agent.skill_states.get(skill.name, {}).get("enabled", True)
        state = "enabled" if enabled else "disabled"
        console.print(
            f"{index}. [{state}] {skill.name} — {skill.title}\n"
            f"   {skill.description}\n   {skill.path}",
            markup=False,
        )
    choice = prompt("Select skill number (blank to cancel): ").strip()
    if not choice:
        return
    try:
        index = int(choice) - 1
    except ValueError:
        console.print("Invalid skill number.", style="yellow")
        return
    if index < 0 or index >= len(skills):
        console.print("Invalid skill number.", style="yellow")
        return
    skill = skills[index]
    current = agent.skill_states.get(skill.name, {}).get("enabled", True)
    action = prompt("Action: [e]nable or [d]isable: ").strip().lower()
    if action in {"e", "enable"}:
        agent.set_skill_enabled(skill, True)
    elif action in {"d", "disable"}:
        agent.set_skill_enabled(skill, False)
    else:
        console.print("Unknown action; no change made.", style="yellow")
        return
    updated = action in {"e", "enable"}
    if updated != current:
        console.print("Skill state updated.", style="yellow")


def process_command(agent: MicroAgent, text: str) -> bool:
    """处理 REPL 内置命令；返回 False 表示用户要求退出。"""
    command, _, argument = text.partition(" ")
    if command == "/quit":
        return False
    if command == "/help":
        console.print("/mode yolo|ask|auto  Switch tool execution mode")
        console.print("/append-system-prompt <text|file>  Add a system prompt source")
        console.print("/system-prompts        Manage prompt sources")
        console.print("/skills                List and enable or disable skills")
        console.print("/skill:<name> [text]   Inject a skill and optional task text")
        console.print("/print-system-prompt  Show the current system prompt")
        console.print("/resume                Choose and resume a saved session")
        console.print("/new-session           Start a new session")
        console.print("/name <name>           Set the current session display name")
        console.print("/help                 Show this help")
        console.print("/quit                 Exit micro")
        console.print(f"Current mode: {agent.mode}")
    elif command == "/mode":
        if argument in {"yolo", "ask", "auto"}:
            agent.set_mode(argument)
        else:
            console.print("Usage: /mode yolo|ask|auto", style="yellow")
    elif command == "/append-system-prompt":
        if argument:
            try:
                kind, content, path = parse_system_prompt_source(argument)
                item = agent.append_system_prompt(kind, content=content, path=path)
            except (ValueError, FileNotFoundError) as error:
                console.print(str(error), style="yellow", markup=False)
            else:
                console.print(
                    f'Added {kind} system prompt source {item["id"]}.',
                    style="yellow",
                )
        else:
            console.print(
                '/append-system-prompt "text" | ./prompt.md | ~/prompt.md | file:/path/prompt.md',
                style="yellow",
            )
    elif command == "/system-prompts":
        manage_system_prompts(agent)
    elif command == "/skills":
        manage_skills(agent)
    elif command.startswith("/skill:"):
        skill_name = command.removeprefix("/skill:")
        if not skill_name:
            console.print("Usage: /skill:<name> [additional message]", style="yellow")
        else:
            try:
                skill_message = agent.inject_skill(skill_name, argument)
            except (OSError, UnicodeError, ValueError) as error:
                console.print(str(error), style="yellow", markup=False)
            else:
                console.print(f"Injected skill: {skill_name}", style="yellow")
                agent.run_turn(skill_message)
    elif command == "/print-system-prompt":
        console.print(agent.get_system_prompt(), markup=False)
    elif command == "/resume":
        sessions = SessionStore.list_sessions()
        if not sessions:
            console.print("No saved sessions.", style="yellow")
        else:
            selected = choose_session(sessions)
            if selected:
                store, messages, system_append = selected
                agent.switch_session(store, messages, system_append)
                console.print(f"Resumed session {store.session_id}.", style="yellow")
    elif command == "/new-session":
        store = create_session(agent.config)
        agent.switch_session(store)
        console.print(f"Started session {store.session_id}.", style="yellow")
    elif command == "/name":
        if not argument.strip():
            console.print("Usage: /name <new name>", style="yellow")
        elif agent.session_store is None:
            console.print("No active session.", style="yellow")
        else:
            try:
                parts = shlex.split(argument)
            except ValueError:
                console.print("Invalid quoting in session name.", style="yellow")
            else:
                name = " ".join(parts).strip()
                if not name:
                    console.print("Session name cannot be empty.", style="yellow")
                else:
                    agent.session_store.set_name(name)
                    console.print(f"Session renamed to {name}.", style="yellow")
    else:
        return True
    return True


@app.command()
def main(
    continue_last: bool = typer.Option(
        False, "--continue", "-c", help="Continue the most recent session."
    ),
    resume: bool = typer.Option(
        False, "--resume", "-r", help="Choose a session to resume."
    ),
    json_mode: bool = typer.Option(
        False, "--json", help="Use JSON Lines on stdin and stdout."
    ),
    json_prompt: str | None = typer.Option(
        None, "-p", "--prompt", help="Send one prompt in JSON mode."
    ),
    session_id: str | None = typer.Option(
        None, "--session", help="Resume a specific session by ID."
    ),
    new_session: bool = typer.Option(
        False, "--new-session", help="Start a new session."
    ),
    session_name: str | None = typer.Option(
        None, "--name", help="Set the session display name."
    ),
    no_session: bool = typer.Option(
        False, "--no-session", help="Do not persist a session (JSON mode only)."
    ),
    mode: Mode | None = typer.Option(
        None, "--mode", help="Override the configured tool mode: yolo, ask, or auto."
    ),
) -> None:
    """根据 CLI 选项运行交互式 REPL 或 JSON Lines 协议。"""
    if sum((continue_last, resume, session_id is not None, new_session)) > 1:
        raise typer.BadParameter(
            "Choose only one of -c, -r, --session, or --new-session."
        )
    if json_mode and resume:
        raise typer.BadParameter(
            "Interactive -r cannot be used with --json; use --session ID."
        )
    if no_session and not json_mode:
        raise typer.BadParameter("--no-session requires --json.")
    if json_prompt is not None and not json_mode:
        raise typer.BadParameter("-p/--prompt requires --json.")
    if no_session and (continue_last or session_id is not None):
        raise typer.BadParameter("--no-session cannot be combined with -c or --session.")
    if no_session and new_session:
        raise typer.BadParameter("--no-session cannot be combined with --new-session.")
    if no_session and session_name is not None:
        raise typer.BadParameter("--name requires a persistent session.")

    config = load_config()
    if mode is not None:
        config.default_mode = mode

    restored = None
    if session_id is not None:
        try:
            restored = SessionStore.load(session_id)
        except (FileNotFoundError, ValueError) as error:
            raise typer.BadParameter(str(error)) from error
    elif continue_last:
        sessions = SessionStore.list_sessions()
        if sessions:
            try:
                restored = SessionStore.load(sessions[0]["id"])
            except (FileNotFoundError, ValueError) as error:
                if json_mode:
                    raise typer.BadParameter(str(error)) from error
                console.print(str(error), style="yellow", markup=False)
    elif resume:
        sessions = SessionStore.list_sessions()
        if sessions:
            restored = choose_session(sessions)
            if restored is None:
                return
        else:
            console.print("No saved sessions; starting a new session.", style="yellow")

    store = None
    if not no_session:
        store = restored[0] if restored else create_session(config)
        if session_name is not None:
            store.set_name(session_name)
    agent = build_agent(config, store)
    if restored:
        agent.switch_session(*restored)

    if json_mode:
        write_event = _write_json_event
        write_event(
            {
                "type": "session",
                "session_id": store.session_id if store else None,
                "name": store.name if store else None,
                "persistent": store is not None,
                "resumed": restored is not None,
                "mode": agent.mode,
            }
        )
        return_code = run_json_protocol(
            agent,
            sys.stdin,
            write_event,
            initial_prompt=json_prompt,
        )
        if return_code:
            raise typer.Exit(code=return_code)
        return

    console.print(f"micro — mode: {agent.mode}")
    if store:
        session_label = store.name or store.session_id
        console.print(f"Session: {session_label} [{store.session_id}]")
    console.print("Type /help for commands.")

    # 主输入复用同一 history，向上键可调出本次运行中之前的输入。
    input_session = PromptSession(history=InMemoryHistory())
    while True:
        text = input_session.prompt("\n> ").strip()
        if text.startswith("/"):
            if not process_command(agent, text):
                return
            continue
        if text:
            agent.run_turn(text)


def _write_json_event(event: dict) -> None:
    """将单个紧凑 JSON 事件写入 stdout 并立即刷新。"""
    sys.stdout.write(json.dumps(event, ensure_ascii=False, separators=(",", ":")) + "\n")
    sys.stdout.flush()


if __name__ == "__main__":
    app()
