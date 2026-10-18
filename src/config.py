"""读取 micro 的 JSON 配置，并提供安全的默认值。"""

import json
from dataclasses import dataclass, field
from pathlib import Path
from typing import Literal

DEFAULT_SYSTEM_PROMPT = "You are a helpful assistant. Use tools when they help answer the user's request."


@dataclass
class MicroConfig:
    """保存 micro 使用的模型、提示词和运行模式。"""

    model: str = "ornith:9b"
    url: str = "http://localhost:11434"
    key: str = ""
    system_prompt: str = DEFAULT_SYSTEM_PROMPT
    default_mode: Literal["yolo", "ask", "auto"] = "auto"
    allow: list[str] = field(default_factory=list)
    approve_on_enter: bool = False


def load_config(project_dir: Path | None = None, user_config_path: Path | None = None) -> MicroConfig:
    """按用户级、项目级的顺序读取配置，让项目配置覆盖用户配置。"""
    project_dir = project_dir or Path.cwd()
    user_config_path = user_config_path or Path.home() / ".micro/settings.json"
    settings = {}

    # 用户级配置提供跨项目的默认设置。
    if user_config_path.is_file():
        settings.update(json.loads(user_config_path.read_text()))

    # 项目级配置优先，允许每个项目覆盖用户级设置。
    project_config_path = project_dir / ".micro" / "settings.json"
    if project_config_path.is_file():
        settings.update(json.loads(project_config_path.read_text()))

    # 用数据类校验字段名，并拒绝未定义的模式。
    config = MicroConfig(**settings)
    if config.default_mode not in {"yolo", "ask", "auto"}:
        raise ValueError(f"Unsupported default mode: {config.default_mode}")
    return config
