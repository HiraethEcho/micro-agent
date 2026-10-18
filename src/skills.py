"""发现、解析并按优先级合并 micro Skills。"""

from dataclasses import dataclass
from pathlib import Path
import re


@dataclass(frozen=True)
class Skill:
    """保存从 SKILL.md 元数据发现的 skill 信息。"""

    name: str
    title: str
    description: str
    path: Path


def _parse_scalar(value: str) -> str:
    """读取简单 YAML frontmatter 标量，去掉常见引号。"""
    value = value.strip()
    if len(value) >= 2 and value[0] == value[-1] and value[0] in {"'", '"'}:
        return value[1:-1]
    return value


def parse_skill_metadata(path: Path) -> dict[str, str]:
    """解析 SKILL.md frontmatter 中规范要求的 name、description 和可选 title。"""
    text = path.read_text(encoding="utf-8")
    lines = text.splitlines()
    if not lines or lines[0].strip() != "---":
        raise ValueError(f"Missing YAML frontmatter in {path}")
    try:
        end = next(i for i, line in enumerate(lines[1:], 1) if line.strip() == "---")
    except StopIteration as error:
        raise ValueError(f"Unclosed YAML frontmatter in {path}") from error

    metadata: dict[str, str] = {}
    index = 1
    while index < end:
        line = lines[index]
        match = re.match(r"^(name|title|description)\s*:\s*(.*)$", line)
        if not match:
            index += 1
            continue
        key, value = match.groups()
        value = value.strip()
        if key == "description" and value in {"|", "|-", ">", ">-", "|+", ">+"}:
            block = []
            index += 1
            while index < end and (not lines[index].strip() or lines[index][:1].isspace()):
                block.append(lines[index].strip())
                index += 1
            metadata[key] = (" " if value.startswith(">") else "\n").join(
                part for part in block if part
            ).strip()
            continue
        metadata[key] = _parse_scalar(value)
        index += 1

    name = metadata.get("name", "")
    if (
        not 1 <= len(name) <= 64
        or not re.fullmatch(r"[a-z0-9]+(?:-[a-z0-9]+)*", name)
    ):
        raise ValueError(f"Invalid skill metadata name in {path}")
    if path.parent.name != name:
        raise ValueError(f"Skill name must match its directory in {path}")
    description = metadata.get("description", "")
    if not 1 <= len(description) <= 1024:
        raise ValueError(f"Invalid skill metadata description in {path}")
    metadata.setdefault("title", metadata["name"])
    return metadata


def discover_skills(project_dir: Path | None = None, home_dir: Path | None = None) -> list[Skill]:
    """按项目到用户目录的优先级发现 skills，同名时保留首个定义。"""
    project = (project_dir or Path.cwd()).resolve()
    home = (home_dir or Path.home()).expanduser().resolve()
    roots = [
        project / ".micro" / "skills",
        project / ".agents" / "skills",
        home / ".micro" / "skills",
        home / ".agents" / "skills",
    ]
    discovered: dict[str, Skill] = {}
    for root in roots:
        if not root.is_dir():
            continue
        try:
            candidates = sorted(root.glob("*/SKILL.md"))
        except OSError:
            continue
        for path in candidates:
            try:
                metadata = parse_skill_metadata(path)
            except (OSError, UnicodeError, ValueError):
                continue
            name = metadata["name"]
            discovered.setdefault(
                name,
                Skill(
                    name=name,
                    title=metadata["title"],
                    description=metadata["description"],
                    path=path.resolve(),
                ),
            )
    return list(discovered.values())
