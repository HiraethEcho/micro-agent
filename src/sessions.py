"""将会话元数据、消息和 system append 持久化到 JSONL。"""

import json
from datetime import datetime
from pathlib import Path
from uuid import uuid4


class SessionStore:
    """管理工作目录 `.micro/sessions/` 下的单个 JSONL 会话文件。"""

    def __init__(
        self, path: Path, session_id: str, created_at: str, name: str | None = None
    ):
        self.path = path
        self.session_id = session_id
        self.created_at = created_at
        self.name = name
        self.system_appends: list[dict] = []
        self.agents_initialized = False
        self.agents_removed_paths: list[str] = []
        self.skill_states: dict[str, dict] = {}

    @classmethod
    def create(
        cls,
        project_dir: Path | None = None,
        system_appends: list[dict] | None = None,
        agents_initialized: bool = False,
    ) -> "SessionStore":
        """创建新会话文件并写入首行元数据。"""
        project_dir = (project_dir or Path.cwd()).resolve()
        sessions_dir = project_dir / ".micro" / "sessions"
        sessions_dir.mkdir(parents=True, exist_ok=True)
        created_at = datetime.now().astimezone().isoformat(timespec="seconds")
        session_id = datetime.now().strftime("%Y%m%d-%H%M%S") + "-" + uuid4().hex[:8]
        path = sessions_dir / f"{session_id}.jsonl"
        prompt_items = [dict(item) for item in (system_appends or [])]
        for item in prompt_items:
            item.setdefault("id", uuid4().hex[:8])
            item.setdefault("enabled", True)
        store = cls(path, session_id, created_at)
        store.system_appends = prompt_items
        store.agents_initialized = agents_initialized
        store._write(
            {
                "type": "session",
                "id": session_id,
                "created_at": created_at,
                "cwd": str(project_dir),
                "name": None,
                "system_appends": prompt_items,
                "agents_initialized": agents_initialized,
                "agents_removed_paths": [],
            }
        )
        return store

    @classmethod
    def load(
        cls, session_id: str, project_dir: Path | None = None
    ) -> tuple["SessionStore", list[dict], list[dict]]:
        """恢复指定会话，并重放消息及 system append 记录。"""
        project_dir = (project_dir or Path.cwd()).resolve()
        path = project_dir / ".micro" / "sessions" / f"{session_id}.jsonl"
        sessions_dir = (project_dir / ".micro" / "sessions").resolve()
        if not path.is_file() or path.resolve().parent != sessions_dir:
            raise FileNotFoundError(f"Session not found: {session_id}")

        records = []
        for line_number, line in enumerate(path.read_text(encoding="utf-8").splitlines(), 1):
            try:
                records.append(json.loads(line))
            except json.JSONDecodeError as error:
                raise ValueError(
                    f"Invalid JSONL in {path} at line {line_number}: {error.msg}"
                ) from error
        if (
            not records
            or not isinstance(records[0], dict)
            or records[0].get("type") != "session"
            or not isinstance(records[0].get("id"), str)
            or not isinstance(records[0].get("created_at"), str)
        ):
            raise ValueError(f"Invalid session file: {path}")

        header = records[0]
        name = header.get("name")
        system_appends = [
            dict(item)
            for item in header.get("system_appends", [])
            if isinstance(item, dict)
        ]
        store = cls(path, header["id"], header["created_at"], name)
        store.agents_initialized = bool(header.get("agents_initialized", False))
        store.agents_removed_paths = list(header.get("agents_removed_paths", []))
        store.system_appends = system_appends
        for record in records[1:]:
            if not isinstance(record, dict):
                continue
            if record.get("type") == "skill_state" and isinstance(record.get("name"), str):
                store.skill_states[record["name"]] = {
                    "enabled": bool(record.get("enabled")),
                    "path": record.get("path"),
                }
        messages = [
            record["message"]
            for record in records[1:]
            if isinstance(record, dict)
            and record.get("type") == "message"
            and isinstance(record.get("message"), dict)
        ]
        # 中断可能发生在 assistant 发出工具调用后、工具结果写入前；移除未完成的尾部调用。
        for index in range(len(messages) - 1, -1, -1):
            message = messages[index]
            if not isinstance(message, dict):
                continue
            if message.get("role") != "assistant" or not message.get("tool_calls"):
                continue
            expected_ids = {
                call.get("id")
                for call in message["tool_calls"]
                if isinstance(call, dict) and call.get("id")
            }
            received_ids = {
                later.get("tool_call_id")
                for later in messages[index + 1 :]
                if later.get("role") == "tool"
            }
            if expected_ids - received_ids:
                messages = messages[:index]
            break
        return store, messages, system_appends

    @classmethod
    def list_sessions(cls, project_dir: Path | None = None) -> list[dict]:
        """读取当前工作目录中可用会话的元数据。"""
        project_dir = (project_dir or Path.cwd()).resolve()
        sessions_dir = project_dir / ".micro" / "sessions"
        if not sessions_dir.is_dir():
            return []

        sessions = []
        for path in sorted(sessions_dir.glob("*.jsonl"), reverse=True):
            try:
                with path.open(encoding="utf-8") as file:
                    first_line = file.readline()
                    metadata = json.loads(first_line)
                    if not isinstance(metadata, dict):
                        continue
                    for line in file:
                        try:
                            record = json.loads(line)
                        except json.JSONDecodeError:
                            continue
                        if isinstance(record, dict) and record.get("type") == "name":
                            metadata["name"] = record.get("name")
            except (OSError, json.JSONDecodeError):
                continue
            if metadata.get("type") == "session":
                sessions.append(metadata)
        return sessions

    def append_message(self, message: dict) -> None:
        """将一条对话消息追加到 JSONL。"""
        self._write(
            {
                "type": "message",
                "timestamp": datetime.now().strftime("%Y%m%dT%H%M%S"),
                "message": message,
            }
        )

    def set_skill_enabled(self, name: str, path: str, enabled: bool) -> None:
        """追加 skill 状态事件，恢复会话时按事件顺序重建状态。"""
        state = {"enabled": enabled, "path": path}
        self.skill_states[name] = state
        self._write(
            {
                "type": "skill_state",
                "timestamp": datetime.now().strftime("%Y%m%dT%H%M%S"),
                "name": name,
                **state,
            }
        )

    @staticmethod
    def _new_prompt_item(
        kind: str,
        *,
        content: str | None = None,
        path: str | None = None,
    ) -> dict:
        """创建带稳定 ID 和状态的 system append 项。"""
        if kind not in {"default", "setting", "file", "text"}:
            raise ValueError(f"Unsupported system prompt source type: {kind}")
        item = {"id": uuid4().hex[:8], "kind": kind, "enabled": True}
        if content is not None:
            item["content"] = content
        if path is not None:
            item["path"] = path
        return item

    def add_system_prompt_item(
        self, kind: str, *, content: str | None = None, path: str | None = None
    ) -> dict:
        """把新来源加入会话开头的管理列表并持久化。"""
        item = self._new_prompt_item(kind, content=content, path=path)
        self.system_appends.append(item)
        self._rewrite_header({"system_appends": self.system_appends})
        return item

    def set_system_prompt_enabled(self, item_id: str, enabled: bool) -> bool:
        """启用或禁用指定追加项，并更新 JSONL 首行。"""
        item = next((entry for entry in self.system_appends if entry["id"] == item_id), None)
        if item is None:
            return False
        item["enabled"] = enabled
        self._rewrite_header({"system_appends": self.system_appends})
        return True

    def remove_system_prompt_item(self, item_id: str) -> bool:
        """移除指定追加项，并更新 JSONL 首行。"""
        remaining = [entry for entry in self.system_appends if entry["id"] != item_id]
        if len(remaining) == len(self.system_appends):
            return False
        removed = next(entry for entry in self.system_appends if entry["id"] == item_id)
        self.system_appends = remaining
        updates = {"system_appends": self.system_appends}
        if removed.get("managed") == "agents" and removed.get("path"):
            self.agents_removed_paths.append(removed["path"])
            updates["agents_removed_paths"] = self.agents_removed_paths
        self._rewrite_header(updates)
        return True

    def ensure_project_instruction_sources(self, paths: list[Path]) -> None:
        """Add newly discovered AGENTS.md paths to this session's source list."""
        removed = set(self.agents_removed_paths)
        known = {
            item.get("path")
            for item in self.system_appends
            if item.get("managed") == "agents"
        }
        additions = []
        for path in paths:
            resolved = str(path.resolve())
            if resolved in known or resolved in removed:
                continue
            item = self._new_prompt_item("file", path=resolved)
            item["managed"] = "agents"
            self.system_appends.append(item)
            additions.append(item)
        if additions or not self.agents_initialized:
            self.agents_initialized = True
            self._rewrite_header(
                {
                    "system_appends": self.system_appends,
                    "agents_initialized": True,
                    "agents_removed_paths": self.agents_removed_paths,
                }
            )

    def set_name(self, name: str) -> None:
        """更新会话显示名称并把更名事件写入 JSONL。"""
        self.name = name.strip()
        self._rewrite_header({"name": self.name})

    def _rewrite_header(self, updates: dict) -> None:
        """更新 JSONL 首行的会话管理状态，同时保留后续对话记录。"""
        lines = self.path.read_text(encoding="utf-8").splitlines()
        header = json.loads(lines[0])
        header.update(updates)
        retained = []
        for line in lines[1:]:
            retained.append(line)
        temporary_path = self.path.with_suffix(".tmp")
        with temporary_path.open("w", encoding="utf-8") as file:
            file.write(json.dumps(header, ensure_ascii=False) + "\n")
            for line in retained:
                file.write(line + "\n")
            file.flush()
        temporary_path.replace(self.path)

    def _write(self, record: dict) -> None:
        """以 UTF-8 JSON Lines 格式追加记录并立即刷新到磁盘。"""
        with self.path.open("a", encoding="utf-8") as file:
            file.write(json.dumps(record, ensure_ascii=False) + "\n")
            file.flush()
