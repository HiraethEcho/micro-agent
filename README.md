# micro-agent

基于 mini-SWE-agent 的 micro-agent

极简循环和界面

- bash is all it has
- 3 modes, ask/auto/yolo
- global and local config in json

todo

- steer and follow up prompt
- skills
- json mode
- subagents

## 使用说明

### 安装依赖

需要 Python 3.10 或更高版本。安装 micro 直接使用的 Python 包：

```bash
uv sync
```

### 启动

在项目根目录运行：

```bash
uv run micro
uv run micro -c  # continue the most recent session
uv run micro -r  # choose a session to resume
```

`micro` 默认创建新会话；`-c` 恢复最近会话，`-r` 在启动时显示会话列表并交互选择。REPL 支持 `/mode yolo`、`/mode ask`、`/mode auto`、`/append-system-prompt <文本或文件>`、`/system-prompts`、`/print-system-prompt`、`/resume`、`/new-session`、`/name <新名称>`、`/help` 和 `/quit`。消息及 system prompt 来源以 JSONL 即时保存在当前工作目录的 `.micro/sessions/` 下，来源定义放在文件首行，每条消息记录包含 `YYYYMMDDTHHMMSS` 时间戳。`/system-prompts` 可交互启用、禁用或删除来源。文件来源每次请求模型前重读；`~` 和 `./` 分别按用户主目录和当前工作目录展开。

`AGENTS.md` 会作为默认启用的 `file` 来源写入会话 JSONL，并在每次请求前重读；可通过 `/system-prompts` 禁用或移除。新发现的适用 `AGENTS.md` 会自动加入当前会话。`/print-system-prompt` 显示当前启用来源的实际内容。直接文本及文件路径都可以通过 `/append-system-prompt` 添加。

### JSON 配置

用户级配置路径是 `~/.config/micro/config.json`。项目级配置路径是项目根目录下的 `.micro/settings.json`。项目配置会覆盖用户配置中的同名字段。

```json
{
  "model": "ornith:9b",
  "url": "http://localhost:11434",
  "key": "",
  "system_prompt": "You are a helpful assistant. Use tools when they help answer the user's request.",
  "default_mode": "auto",
  "allow": ["ls *", "git status *", "grep *"],
  "approve_on_enter": false
}
```

`allow` 列表只匹配 auto 模式下的只读命令。`*` 是通配符。写入命令、命令链、管道和重定向仍会要求确认。`approve_on_enter` 为 `true` 时，确认提示中的回车表示批准；为 `false` 时表示拒绝。

### 依赖说明

- `openai` 调用 Ollama 的 OpenAI 兼容接口。
- `prompt_toolkit` 提供方向键、退格和中文输入编辑。
- `rich` 提供终端颜色、面板和 Bash 命令高亮。
- `typer` 提供 CLI 入口。
