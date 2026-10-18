# micro-agent

基于 mini-SWE-agent 的 micro-agent

极简循环和界面

- bash is all it has
- 3 modes, ask/auto/yolo
- global and local config in json

todo

- session manager
- steer and follow up prompt
- auto read AGENTS.md
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
```

REPL 支持 `/mode yolo`、`/mode ask`、`/mode auto`、`/system_prompt_append "额外指令"`、`/print-system-prompt`、`/help` 和 `/quit`。`/print-system-prompt` 显示当前基础 system prompt、会话追加内容和最新读取的 `AGENTS.md` 指令。追加指令只在当前会话生效；适用路径上的 `AGENTS.md` 会在每次模型请求前重新读取。

### JSON 配置

用户级配置路径是 `~/.config/micro/config.json`。项目级配置路径是项目根目录下的 `.micro.json`。项目配置会覆盖用户配置中的同名字段。

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
