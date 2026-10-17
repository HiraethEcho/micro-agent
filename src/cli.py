"""读取 micro 配置并提供独立的终端 REPL。"""

import typer
from prompt_toolkit import prompt
from rich.console import Console

from agent import MicroAgent
from config import MicroConfig, load_config

console = Console(highlight=False)
app = typer.Typer(add_completion=False, help="A small conversational coding agent.")


def build_agent(config: MicroConfig) -> MicroAgent:
    """仅用 micro 自身的配置构造对话代理。"""
    return MicroAgent(config)


def process_command(agent: MicroAgent, text: str) -> bool:
    """处理 REPL 内置命令；返回 False 表示用户要求退出。"""
    command, _, argument = text.partition(" ")
    if command == "/quit":
        return False
    if command == "/help":
        console.print("/mode yolo|ask|auto  Switch tool execution mode")
        console.print("/help                 Show this help")
        console.print("/quit                 Exit micro")
        console.print(f"Current mode: {agent.mode}")
    elif command == "/mode":
        if argument in {"yolo", "ask", "auto"}:
            agent.set_mode(argument)
        else:
            console.print("Usage: /mode yolo|ask|auto", style="yellow")
    else:
        return True
    return True


@app.command()
def main() -> None:
    """读取 JSON 配置并运行保留对话历史的终端循环。"""
    agent = build_agent(load_config())
    console.print(f"micro — mode: {agent.mode}")
    console.print("Type /help for commands.")

    # 每轮读取一条用户输入；普通文本会进入独立的模型对话循环。
    while True:
        text = prompt("\n> ").strip()
        if text.startswith("/"):
            if not process_command(agent, text):
                return
            continue
        if text:
            agent.run_turn(text)


if __name__ == "__main__":
    app()
