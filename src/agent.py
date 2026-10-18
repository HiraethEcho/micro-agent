"""Micro 的独立对话循环、Ollama 请求和本地工具执行。"""

import json
import shlex
import subprocess
from datetime import datetime
from fnmatch import fnmatchcase
from pathlib import Path
from typing import Literal

from openai import OpenAI
from prompt_toolkit import prompt
from rich.console import Console
from rich.panel import Panel
from rich.syntax import Syntax

from config import DEFAULT_SYSTEM_PROMPT, MicroConfig
from sessions import SessionStore
from skills import Skill, discover_skills

console = Console(highlight=False)
Mode = Literal["yolo", "ask", "auto"]
BASH_TOOL = {
    "type": "function",
    "function": {
        "name": "bash",
        "description": "Run a shell command in the current project directory.",
        "parameters": {
            "type": "object",
            "properties": {
                "command": {
                    "type": "string",
                    "description": "The shell command to run.",
                }
            },
            "required": ["command"],
        },
    },
}


def find_project_instruction_files(project_dir: Path | None = None) -> list[Path]:
    """按仓库根目录到当前目录的顺序查找适用的 AGENTS.md 文件。"""
    current_dir = (project_dir or Path.cwd()).resolve()
    ancestors = [current_dir, *current_dir.parents]
    repo_root = next((path for path in ancestors if (path / ".git").exists()), None)

    # 有 Git 仓库时只读取仓库范围内的规则，避免意外加载仓库外的个人文件。
    scope = [current_dir]
    if repo_root is not None:
        scope = []
        path = current_dir
        while True:
            scope.append(path)
            if path == repo_root:
                break
            path = path.parent
        scope.reverse()

    return [directory / "AGENTS.md" for directory in scope if (directory / "AGENTS.md").is_file()]


class MicroAgent:
    """管理对话历史，直接调用 Ollama 并执行模型返回的 bash 工具调用。"""

    def __init__(self, config: MicroConfig, session_store: SessionStore | None = None):
        """初始化 Ollama 客户端、空的对话历史和当前会话存储。"""
        self.config = config
        self.mode: Mode = config.default_mode
        self.messages: list[dict] = []
        if session_store:
            self.system_append = session_store.system_appends
        else:
            self.system_append = [
                SessionStore._new_prompt_item(
                    "default", content=DEFAULT_SYSTEM_PROMPT
                )
            ]
            if config.system_prompt != DEFAULT_SYSTEM_PROMPT:
                self.system_append.append(
                    SessionStore._new_prompt_item(
                        "setting", content=config.system_prompt
                    )
                )
        self.session_store = session_store
        self.skill_states = session_store.skill_states if session_store else {}
        api_url = config.url.rstrip("/")
        if not api_url.endswith("/v1"):
            api_url += "/v1"

        # OpenAI 客户端要求提供 key；本地 Ollama 不校验占位 key。
        self.client = OpenAI(base_url=api_url, api_key=config.key or "ollama")

    def run_turn(self, prompt: str) -> None:
        """加入用户输入，并循环请求模型直到本轮不再返回工具调用。"""
        self._append_message({"role": "user", "content": prompt})

        # 每次响应都保留 assistant 工具请求和工具结果，供后续模型调用续接。
        while True:
            request_messages = self._messages_with_system_append()
            with console.status("Waiting for the model..."):
                response = self.client.chat.completions.create(
                    model=self.config.model,
                    messages=request_messages,
                    tools=[BASH_TOOL],
                )
            assistant = response.choices[0].message
            message = {"role": "assistant", "content": assistant.content or ""}
            if assistant.tool_calls:
                message["tool_calls"] = [
                    call.model_dump(exclude_none=True) for call in assistant.tool_calls
                ]
            if reasoning := getattr(assistant, "reasoning_content", None):
                message["reasoning_content"] = reasoning
            message_timestamp = self._message_timestamp()
            self._append_message(message)
            self._display_assistant(message, message_timestamp)

            if not assistant.tool_calls:
                return
            self._execute_tool_calls(message["tool_calls"])

    def append_system_prompt(
        self, kind: str, *, content: str | None = None, path: str | None = None
    ) -> dict:
        """把文本或文件来源加入本会话的可管理 system append 列表。"""
        if self.session_store:
            item = self.session_store.add_system_prompt_item(
                kind, content=content, path=path
            )
        else:
            item = SessionStore._new_prompt_item(kind, content=content, path=path)
            self.system_append.append(item)
        return item

    def switch_session(
        self,
        session_store: SessionStore,
        messages: list[dict] | None = None,
        system_append: list[dict] | None = None,
    ) -> None:
        """切换到已恢复或新建的会话。"""
        self.session_store = session_store
        self.messages = messages or []
        self.system_append = (
            system_append if system_append is not None else session_store.system_appends
        )
        self.skill_states = session_store.skill_states

    def _append_message(self, message: dict) -> None:
        """把消息加入内存历史并立即写入当前会话文件。"""
        self.messages.append(message)
        if self.session_store:
            self.session_store.append_message(message)

    @staticmethod
    def _message_timestamp() -> str:
        """为输出标签生成 YYYYMMDDTHHMMSS 格式的本地时间。"""
        return datetime.now().strftime("%Y%m%dT%H%M%S")

    def get_system_prompt(self) -> str:
        """返回当前会话实际发给模型的 system 消息内容。"""
        return self._system_append_content()

    def _system_append_content(self) -> str:
        """合并当前启用的来源，并在请求时重新读取文件来源。"""
        self.refresh_project_instruction_sources()
        appended_sections = []
        for item in self.system_append:
            if not item.get("enabled", True):
                continue
            if item.get("kind") == "file":
                path = Path(item["path"])
                try:
                    appended_sections.append(path.read_text(encoding="utf-8"))
                except OSError as error:
                    console.print(
                        f"Cannot read system prompt file {path}: {error}",
                        style="yellow",
                        markup=False,
                    )
            elif item.get("content"):
                appended_sections.append(item["content"])
        skill_directory = self._enabled_skills_prompt()
        if skill_directory:
            appended_sections.append(skill_directory)
        return "\n\n".join(appended_sections)

    def available_skills(self) -> list[Skill]:
        """按已配置优先级返回当前工作目录和用户目录中的 Skills。"""
        return discover_skills()

    def set_skill_enabled(self, skill: Skill, enabled: bool) -> None:
        """更新当前会话中指定 skill 的暴露状态。"""
        state = {"enabled": enabled, "path": str(skill.path)}
        self.skill_states[skill.name] = state
        if self.session_store:
            self.session_store.set_skill_enabled(skill.name, str(skill.path), enabled)

    def inject_skill(self, name: str, additional_message: str = "") -> str:
        """读取 Skill 正文并构造成一条 user 消息。"""
        skill = next((item for item in self.available_skills() if item.name == name), None)
        if skill is None:
            available = ", ".join(item.name for item in self.available_skills()) or "none"
            raise ValueError(f"Skill not found: {name}. Available skills: {available}")
        body = skill.path.read_text(encoding="utf-8").strip()
        if additional_message.strip():
            return f"{body}\n\nAdditional user message:\n{additional_message.strip()}"
        return body

    def _enabled_skills_prompt(self) -> str:
        """将启用 Skills 的元信息目录加入 system prompt，不包含正文。"""
        enabled = []
        for skill in self.available_skills():
            state = self.skill_states.get(skill.name, {})
            if not state.get("enabled", True):
                continue
            enabled.append(
                "- "
                + json.dumps(
                    {
                        "name": skill.name,
                        "title": skill.title,
                        "description": skill.description,
                        "path": str(skill.path),
                    },
                    ensure_ascii=False,
                )
            )
        if not enabled:
            return ""
        return (
            "Available skills (metadata only; read the listed skill file with the available tools "
            "before applying it when relevant):\n" + "\n".join(enabled)
        )

    def refresh_project_instruction_sources(self) -> None:
        """将适用的 AGENTS.md 注册为可管理的默认文件来源。"""
        paths = find_project_instruction_files()
        if self.session_store:
            self.session_store.ensure_project_instruction_sources(paths)
            self.system_append = self.session_store.system_appends
            return
        known_paths = {
            item.get("path")
            for item in self.system_append
            if item.get("managed") == "agents"
        }
        for path in paths:
            resolved = str(path.resolve())
            if resolved not in known_paths:
                item = SessionStore._new_prompt_item("file", path=resolved)
                item["managed"] = "agents"
                self.system_append.append(item)
                known_paths.add(resolved)

    def _messages_with_system_append(self) -> list[dict]:
        """每次请求前重读 AGENTS.md，并将动态补充指令放在对话历史前部。"""
        appended_content = self._system_append_content()
        request_messages = list(self.messages)
        if appended_content:
            request_messages.insert(
                0,
                {
                    "role": "system",
                    "content": appended_content,
                },
            )
        return request_messages

    def set_mode(self, mode: Mode) -> None:
        """验证并切换工具执行模式。"""
        if mode not in {"yolo", "ask", "auto"}:
            raise ValueError(f"Unsupported mode: {mode}")
        self.mode = mode
        console.print(f"Mode: {mode}", style="yellow")

    def _display_assistant(self, message: dict, timestamp: str) -> None:
        """用不同标签输出模型的思考字段和普通回答。"""
        if reasoning := message.get("reasoning_content"):
            console.print("[thinking]", style="magenta", markup=False)
            console.print(str(reasoning), markup=False)
        if content := message.get("content"):
            console.print(f"[assistant] {timestamp}", style="cyan", markup=False)
            console.print(str(content), markup=False)

    def _execute_tool_calls(self, tool_calls: list[dict]) -> None:
        """按当前模式确认工具调用，并把每项结果追加到对话历史。"""
        for call in tool_calls:
            tool_timestamp = self._message_timestamp()
            function = call.get("function", {})
            name = function.get("name", "")
            arguments = json.loads(function.get("arguments", "{}"))
            command = (
                arguments.get("command", "") if isinstance(arguments, dict) else ""
            )
            console.print(f"[tool] {tool_timestamp}", style="yellow", markup=False)
            if command:
                self._display_command(command, "yellow")
            else:
                console.print(f"Unsupported tool: {name}", markup=False)

            if name != "bash" or not isinstance(command, str) or not command:
                output = "Unsupported or invalid tool call."
            elif (
                self.mode == "ask"
                or (
                    self.mode == "auto"
                    and not is_auto_allowed(command, self.config.allow)
                )
            ) and not self._confirm():
                output = "Execution rejected by user."
            else:
                output = self._run_command(command)

            result_timestamp = self._message_timestamp()
            tool_message = {
                "timestamp": result_timestamp,
                "role": "tool",
                "tool_call_id": call["id"],
                "content": output,
            }
            self._append_message(tool_message)
            console.print(f"[result] {result_timestamp}", style="green", markup=False)
            self._display_result(output, "Green")

    def _confirm(self) -> bool:
        """显示批准和拒绝方式，并按配置处理回车输入。"""
        enter_action = "approve" if self.config.approve_on_enter else "reject"
        console.print(
            f"Approve? y/yes or n/no. Enter to {enter_action}.",
            markup=False,
        )
        return approval_granted(prompt("> "), self.config.approve_on_enter)

    @staticmethod
    def _display_command(command: str, color: str) -> None:
        """用 shell 语法高亮面板显示待执行的命令。"""
        console.print(
            Panel(
                Syntax(command, "bash", theme="monokai", word_wrap=True),
                border_style=color,
            )
        )

    def _display_result(self, result: str, color: str) -> None:
        """用面板显示实际执行的结果。"""
        console.print(
            Panel(
                Syntax(
                    result,
                    "bash",
                    theme="github-dark",
                    word_wrap=True,
                ),
                border_style=color,
                padding=(0, 1),
            )
        )

    def _run_command(self, command: str) -> str:
        """在当前目录运行 shell 命令，并把合并后的输出交给模型。"""
        # self._display_command(command, "green")
        try:
            result = subprocess.run(
                command,
                shell=True,
                check=False,
                text=True,
                stdout=subprocess.PIPE,
                stderr=subprocess.STDOUT,
                timeout=30,
            )
        except subprocess.TimeoutExpired as error:
            partial_output = error.stdout or ""
            if isinstance(partial_output, bytes):
                partial_output = partial_output.decode(errors="replace")
            return f"Command timed out after 30 seconds.\n{partial_output}"
        return result.stdout.rstrip("\n")


def approval_granted(response: str, approve_on_enter: bool) -> bool:
    """将用户输入映射为批准结果，并按配置处理空输入。"""
    answer = response.strip().lower()
    return answer in {"y", "yes"} or (not answer and approve_on_enter)


def is_auto_allowed(command: str, allow: list[str]) -> bool:
    """只放行白名单匹配的只读命令；遇到 shell 组合语法时默认要求确认。"""
    if any(character in command for character in ";|&><\n\r$`"):
        return False

    try:
        parts = shlex.split(command)
    except ValueError:
        return False
    if not parts:
        return False

    # find 的执行、删除和写入参数会改变文件或启动其他命令，必须询问。
    if parts[0] == "find" and any(
        part
        in {
            "-exec",
            "-execdir",
            "-delete",
            "-ok",
            "-okdir",
            "-fprint",
            "-fprintf",
            "-fls",
        }
        for part in parts[1:]
    ):
        return False

    # 即使通配符匹配，也只允许已知的只读命令和 git status。
    if parts[0] == "git":
        safe = (
            len(parts) >= 2
            and parts[1] == "status"
            and not any(part in {"-c", "--config-env"} for part in parts[1:])
        )
    else:
        safe = parts[0] in {
            "cat",
            "find",
            "grep",
            "head",
            "ls",
            "pwd",
            "rg",
            "stat",
            "tail",
            "tree",
            "wc",
        }
    return safe and any(fnmatchcase(command, pattern) for pattern in allow)
