# `uv run micro` 启动流程

本文追踪 `micro-agent` 从 uv 命令入口到终端对话循环、模型请求和 bash 工具执行的调用顺序。本文描述当前 checkout 中独立实现的 `micro`，不再是旧的 `mini-swe-agent` 启动流程。

```bash
uv run micro
```

当前项目版本为 `micro-agent 0.1.0`。代码位置按仓库中的 `src/` 文件说明；行号会随代码修改而变化。

---

## 总览

```text
uv → 项目虚拟环境 → .venv/bin/micro
  → cli:app → cli.main()
  → load_config() 读取两级 JSON 配置
  → MicroAgent(config) 建立 Ollama OpenAI 兼容客户端
  → 读取仓库根目录至当前目录的 AGENTS.md 并合入 system 指令
  → REPL 读取输入
  → run_turn() ⇄ chat.completions.create()
  → 需要时确认并运行 bash 命令
```

---

## 第一段：uv 与命令入口

1. `uv run micro` 在项目环境中运行已安装的 `micro` 命令。首次运行时，uv 根据根目录的 `pyproject.toml` 创建或同步虚拟环境，并安装项目及其依赖。
2. `pyproject.toml` 将项目标识为 `micro-agent`，版本为 `0.1.0`，要求 Python `>=3.10`。直接依赖是 `openai`、`prompt_toolkit`、`rich` 和 `typer`。
3. `[project.scripts]` 将 `micro` 命令映射到 `cli:app`。`setuptools` 从 `src/` 安装 `cli.py`、`agent.py` 和 `config.py` 这些模块。
4. Typer 创建的 `app` 只有一个 `@app.command()`：`main()`。因此运行 `micro` 会直接进入该函数。

也可以用 `uv run python -m micro` 作为模块入口；`src/__main__.py` 中调用同一个 `cli.app`。

---

## 第二段：配置加载与代理初始化

`src/cli.py:main()` 按顺序执行：

1. 调用 `load_config()`（`src/config.py`）。配置只从 JSON 文件读取，不加载 dotenv，也不沿用 mini 的环境变量或配置文件。
2. `load_config()` 先读取用户配置 `~/.config/micro/config.json`（若文件存在）。
3. 再读取当前工作目录的 `.micro.json`（若文件存在）；同名字段由项目配置覆盖用户配置。
4. 将合并后的字段传给 `MicroConfig` 数据类。默认模型为 `ornith:9b`，默认 Ollama 地址为 `http://localhost:11434`，默认模式为 `auto`。未知字段或非法模式会报错。
5. `build_agent()` 创建 `MicroAgent(config)`。代理把地址补成 OpenAI 兼容 API 的 `/v1` 路径，并以配置中的 key 初始化 `OpenAI` 客户端；空 key 使用占位值 `ollama`。
6. `MicroAgent` 查找当前 Git 仓库根目录到工作目录路径上的 `AGENTS.md`，按根到叶的顺序读取，并在首次模型请求时追加到 system 消息。没有 Git 仓库时只检查当前目录。仓库外的祖先目录不会被读取。
7. CLI 显示当前模式和帮助提示，然后进入 REPL。没有启动时任务参数；每条普通输入由用户在提示符中提供。

---

## 第三段：REPL 命令与对话轮次

1. REPL 用 `prompt_toolkit.prompt()` 读取一行输入。
2. 以 `/` 开头的输入交给 `process_command()`：
   - `/quit` 结束程序。
   - `/help` 显示内置命令和当前模式。
   - `/mode yolo|ask|auto` 切换工具执行模式。
3. 其他非空输入交给 `MicroAgent.run_turn()`（`src/agent.py`）。
4. 首轮对话时，代理先把 `config.system_prompt` 作为 system 消息加入历史，再加入本轮 user 消息。后续轮次复用同一份 `messages`，保留完整对话历史。
5. 代理调用 `client.chat.completions.create()`，传入模型名、历史消息和唯一工具 `bash`。模型服务由 `url` 指定，默认对应本机 Ollama。
6. 将 assistant 的正文、工具调用，以及可用时的 `reasoning_content` 加入历史并显示在终端。
7. 若响应没有工具调用，本轮结束并回到 REPL；若有工具调用，则进入执行流程，执行结果作为 `role="tool"` 消息加入历史，然后继续请求模型，直到模型返回普通回答。

---

## 第四段：bash 工具执行与确认

1. `MicroAgent._execute_tool_calls()` 读取每个工具调用的名称和 JSON 参数，只支持 `bash` 工具及非空字符串命令。
2. 按当前模式决定是否需要用户批准：
   - `yolo`：直接执行有效的 bash 调用。
   - `ask`：每个有效命令都要求确认。
   - `auto`：只有命令通过 `is_auto_allowed()` 的限制并匹配配置 `allow` 中的 glob 模式时才自动执行，其他命令都要求确认。
3. 自动放行规则先拒绝命令链、管道、重定向、变量展开等 shell 组合字符；只允许一组明确的只读命令，以及 `git status`。`find` 的执行、删除等选项也会被拒绝自动放行。
4. `allow` 只提供模式匹配，不会放宽只读命令限制。例如可在 JSON 配置中写 `"allow": ["ls *", "git status *"]`。
5. 确认提示接受 `y`/`yes` 批准、`n`/`no` 拒绝。空输入根据 `approve_on_enter` 决定：`true` 表示批准，`false` 表示拒绝。
6. 获准命令通过 `subprocess.run(..., shell=True)` 在当前工作目录执行，合并 stdout 和 stderr，超时为 30 秒。输出及退出码组成工具结果；超时则返回超时说明和已产生的部分输出。
7. 工具结果追加到消息历史，随后模型可以读取结果并继续调用工具或作答。

---

## 当前配置示例

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

配置项定义在 `src/config.py:MicroConfig`。命令行目前不提供模型、任务、模式或配置路径选项；通过 JSON 文件设置默认值，并在 REPL 内用 `/mode` 切换模式。

---

## 与旧 `mini` 启动流程的差异

- 命令名是 `micro`，项目名是 `micro-agent`；入口为 `cli:app`。
- `micro` 是独立实现，不导入 `minisweagent`，也不调用 LiteLLM、mini 的 agent/environment 工厂或轨迹保存逻辑。
- 配置是用户级和项目级 JSON 合并；不加载 `.env`，不使用 `MSWEA_*` 环境变量，也没有 `-c/-m/-t/-y` 等旧 CLI 选项。
- 启动后进入交互式 REPL，任务逐轮输入；对话历史在同一进程中保留。
- 模型请求通过 OpenAI Python 客户端访问 Ollama 兼容接口。工具执行由 `MicroAgent` 自行处理，并按 `ask`、`auto`、`yolo` 模式确认。
