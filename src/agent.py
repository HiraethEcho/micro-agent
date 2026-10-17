"""Micro 的独立对话循环、Ollama 请求和本地工具执行。"""

import json
import shlex
import subprocess
from fnmatch import fnmatchcase
from typing import Literal

from openai import OpenAI
from prompt_toolkit import prompt
from rich.console import Console
from rich.panel import Panel
from rich.syntax import Syntax

from config import MicroConfig

console = Console(highlight=False)
Mode = Literal["yolo", "ask", "auto"]
BASH_TOOL = {
    "type": "function",
    "function": {
        "name": "bash",
        "description": "Run a shell command in the current project directory.",
        "parameters": {
            "type": "object",
            "properties": {"command": {"type": "string", "description": "The shell command to run."}},
            "required": ["command"],
        },
    },
}


class MicroAgent:
    """管理对话历史，直接调用 Ollama 并执行模型返回的 bash 工具调用。"""

    def __init__(self, config: MicroConfig):
        """初始化 Ollama 客户端和空的对话历史。"""
        self.config = config
        self.mode: Mode = config.default_mode
        self.messages: list[dict] = []
        api_url = config.url.rstrip("/")
        if not api_url.endswith("/v1"):
            api_url += "/v1"

        # OpenAI 客户端要求提供 key；本地 Ollama 不校验占位 key。
        self.client = OpenAI(base_url=api_url, api_key=config.key or "ollama")

    def run_turn(self, prompt: str) -> None:
        """加入用户输入，并循环请求模型直到本轮不再返回工具调用。"""
        if not self.messages:
            self.messages.append({"role": "system", "content": self.config.system_prompt})
        self.messages.append({"role": "user", "content": prompt})

        # 每次响应都保留 assistant 工具请求和工具结果，供后续模型调用续接。
        while True:
            with console.status("Waiting for the model..."):
                response = self.client.chat.completions.create(
                    model=self.config.model,
                    messages=self.messages,
                    tools=[BASH_TOOL],
                )
            assistant = response.choices[0].message
            message = {"role": "assistant", "content": assistant.content or ""}
            if assistant.tool_calls:
                message["tool_calls"] = [call.model_dump(exclude_none=True) for call in assistant.tool_calls]
            if reasoning := getattr(assistant, "reasoning_content", None):
                message["reasoning_content"] = reasoning
            self.messages.append(message)
            self._display_assistant(message)

            if not assistant.tool_calls:
                return
            self._execute_tool_calls(message["tool_calls"])

    def set_mode(self, mode: Mode) -> None:
        """验证并切换工具执行模式。"""
        if mode not in {"yolo", "ask", "auto"}:
            raise ValueError(f"Unsupported mode: {mode}")
        self.mode = mode
        console.print(f"Mode: {mode}", style="yellow")

    def _display_assistant(self, message: dict) -> None:
        """用不同标签输出模型的思考字段和普通回答。"""
        if reasoning := message.get("reasoning_content"):
            console.print("[thinking]", style="magenta", markup=False)
            console.print(str(reasoning), markup=False)
        if content := message.get("content"):
            console.print("[assistant]", style="cyan", markup=False)
            console.print(str(content), markup=False)

    def _execute_tool_calls(self, tool_calls: list[dict]) -> None:
        """按当前模式确认工具调用，并把每项结果追加到对话历史。"""
        for call in tool_calls:
            function = call.get("function", {})
            name = function.get("name", "")
            arguments = json.loads(function.get("arguments", "{}"))
            command = arguments.get("command", "") if isinstance(arguments, dict) else ""
            if command:
                self._display_command(command, "待执行", "yellow")
            else:
                console.print(f"Unsupported tool: {name}", markup=False)

            if name != "bash" or not isinstance(command, str) or not command:
                output = "Unsupported or invalid tool call."
            elif (
                self.mode == "ask" or (self.mode == "auto" and not is_auto_allowed(command, self.config.allow))
            ) and not self._confirm():
                output = "Execution rejected by user."
            else:
                output = self._run_command(command)

            self.messages.append({"role": "tool", "tool_call_id": call["id"], "content": output})
            console.print("[tool result]", style="green", markup=False)
            console.print(output, markup=False)

    def _confirm(self) -> bool:
        """显示批准和拒绝方式，并按配置处理回车输入。"""
        enter_action = "approve" if self.config.approve_on_enter else "reject"
        console.print(
            f"Approve tool call? Type y/yes to approve; n/no to reject. Enter to {enter_action}.",
            markup=False,
        )
        return approval_granted(prompt("> "), self.config.approve_on_enter)

    @staticmethod
    def _display_command(command: str, title: str, color: str) -> None:
        """用 shell 语法高亮面板显示待执行或实际执行的命令。"""
        console.print(Panel(Syntax(command, "bash", theme="monokai", word_wrap=True), title=title, border_style=color))

    def _run_command(self, command: str) -> str:
        """在当前目录运行 shell 命令，并把输出和退出码交给模型。"""
        self._display_command(command, "实际执行", "green")
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
        return f"returncode: {result.returncode}\n{result.stdout}"


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
        part in {"-exec", "-execdir", "-delete", "-ok", "-okdir", "-fprint", "-fprintf", "-fls"} for part in parts[1:]
    ):
        return False

    # 即使通配符匹配，也只允许已知的只读命令和 git status。
    if parts[0] == "git":
        safe = (
            len(parts) >= 2 and parts[1] == "status" and not any(part in {"-c", "--config-env"} for part in parts[1:])
        )
    else:
        safe = parts[0] in {"cat", "find", "grep", "head", "ls", "pwd", "rg", "stat", "tail", "tree", "wc"}
    return safe and any(fnmatchcase(command, pattern) for pattern in allow)
