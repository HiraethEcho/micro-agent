# `uv run mini` 启动流程

本文追踪一条命令从 uv 到 agent 循环的完整调用顺序。

```bash
uv run mini -c mini.yaml -m ollama/qwen3.5:0.8b -t "list files" -y
```

所有行号对应当前 checkout（`minisweagent.__version__ == 2.4.6`）。

---

## 总览

```
uv → .venv/bin/mini → minisweagent/__init__.py（读 .env）
   → run/mini.py:main()（合并 config）
   → LitellmModel + LocalEnvironment + InteractiveAgent
   → default.py:run() ⇄ step() ⇄ litellm.completion / subprocess.Popen
   → 每步 save() trajectory
```

---

## 第一段：uv 层（Python 未启动）

1. uv 读 `pyproject.toml`，识别根项目 `mini-swe-agent`。
2. 找 `.venv`。没有就按 `requires-python = ">=3.10"` 选解释器新建。
3. 同步环境：安装项目本体（默认 editable）、`dependencies`、`[dependency-groups] dev`。
   dev 组默认包含，这就是 `pytest`、`datasets` 会被装上的原因。跳过用 `--no-dev`。
4. 在 `.venv/bin/` 找 `mini`。该文件由 `pyproject.toml` 生成：

   ```toml
   [project.scripts]
   mini = "minisweagent.run.mini:app"
   ```

5. 调用 `minisweagent.run.mini:app`。`app` 是 Typer 实例。只有一个 `@app.command`，
   因此被当作默认命令直接执行。

---

## 第二段：包导入的副作用

`src/minisweagent/__init__.py` 在导入时立即执行四件事：

1. 打印版本横幅。`MSWEA_SILENT_STARTUP` 可关闭。
2. `src/minisweagent/__init__.py:26` 计算 `global_config_dir`，来自
   `platformdirs.user_config_dir("mini-swe-agent")` → `~/.config/mini-swe-agent`。
   `MSWEA_GLOBAL_CONFIG_DIR` 可覆盖。
3. `src/minisweagent/__init__.py:27` 执行 `mkdir(parents=True, exist_ok=True)`。
4. `src/minisweagent/__init__.py:36` 执行 `dotenv.load_dotenv(global_config_file)`，
   读取 `~/.config/mini-swe-agent/.env`。注意 `load_dotenv` 默认不覆盖已存在的环境变量，
   因此 shell 里 export 的值优先级高于 `.env`。

---

## 第三段：CLI 入口 `run/mini.py:main()`

1. `src/minisweagent/run/mini.py:68` 调用 `configure_if_first_time()`。
   若 `.env` 里没有 `MSWEA_CONFIGURED`，运行交互式 `setup()` 向导。

2. 逐个解析 `-c` 的 spec，走 `minisweagent/config/__init__.py:get_config_from_spec()`：
   - 字符串含 `=` → 按 `key=value` 解析成嵌套 dict（key 用 `.` 分层）
   - 否则走 `get_config_path()`，依次查找：给定路径 → `$MSWEA_CONFIG_DIR` → 内置
     `config/` → `config/extra/` → `config/benchmarks/`，然后读 yaml

3. 追加一份由命令行选项构成的 dict。映射关系：

   | 选项 | config 位置 |
   |---|---|
   | `-m/--model` | `model.model_name` |
   | `--model-class` | `model.model_class` |
   | `-c/--config` | 整体配置来源 |
   | `-t/--task` | `run.task` |
   | `-y/--yolo` | `agent.mode = "yolo"` |
   | `-l/--cost-limit` | `agent.cost_limit` |
   | `-o/--output` | `agent.output_path` |
   | `--exit-immediately` | `agent.confirm_exit = False` |
   | `--agent-class` | `agent.agent_class` |
   | `--environment-class` | `environment.environment_class` |

4. `src/minisweagent/run/mini.py:92` 调用 `recursive_merge(*configs)` 合成一份 config。
   后写的覆盖先写的。

5. `src/minisweagent/run/mini.py:96` 取任务。`run.task` 为空就调 `_multiline_prompt()`
   让用户手输。

6. `src/minisweagent/run/mini.py:99` → `minisweagent/models/__init__.py:45` 的 `get_model()`：
   - `get_model_name()`（`:65`）按序查找：config 里的 `model_name` → 环境变量
     `MSWEA_MODEL_NAME` → 都没有则 `raise ValueError`
   - `get_model_class()`（`:92`）优先用 `model_class`，否则默认 `LitellmModel`
   - 实例化为 `LitellmModel(**config)`，内部用 `LitellmModelConfig` 做 pydantic 校验

7. `src/minisweagent/run/mini.py:100` → `environments/__init__.py:30` 的 `get_environment()`，
   `default_type="local"` → `LocalEnvironment`。

8. `src/minisweagent/run/mini.py:101` → `agents/__init__.py:25` 的 `get_agent()`，
   `default_type="interactive"` → `InteractiveAgent`。它会 `config.pop("agent_class")`，
   然后把剩余 config 作为 kwargs 传给构造函数。

9. `src/minisweagent/run/mini.py:102` 调用 `agent.run(run_task)`。

---

## 第四段：agent 循环

### 4.1 `run()` — `agents/default.py:88`

1. 写入两条种子消息：
   - `role="system"`，渲染 `config.system_template`
   - `role="user"`，渲染 `config.instance_template`

   渲染用 Jinja2 的 `StrictUndefined`（`:67`）。模板引用不存在的变量会直接报错，
   不是静默渲染成空串。

2. 进入 `while True`，每轮 `step()`（`:126`），即 `execute_actions(query())`。

### 4.2 `query()` — `agents/default.py:130`

3. 检查三个限额，超限则抛异常退出：
   - `step_limit` → `LimitsExceeded`
   - `cost_limit` → `LimitsExceeded`
   - `wall_time_limit_seconds` → `TimeExceeded`

   值为 0 表示不限制。

4. `n_calls += 1`。

5. `model.query(messages)` → `models/litellm_model.py:81`：
   - `_prepare_messages_for_api()`（`:76`）：剥掉 `extra` 键、Anthropic thinking 块重排、
     按需插入 cache control
   - `retry()` 包裹整个调用。重试策略在 `models/utils/retry.py:9`，次数取
     `MSWEA_MODEL_RETRY_STOP_AFTER_ATTEMPT`，默认 10。`abort_exceptions` 里的异常
     直接放弃重试
   - `_query()`（`:64`）调用 `litellm.completion(model=..., messages=...,
     tools=[BASH_TOOL], **model_kwargs)`。`BASH_TOOL` 定义在
     `models/utils/actions_toolcall.py:11`。这是唯一真正发起网络请求的地方
   - `_calculate_cost()`（`:108`）调用 `litellm.cost_calculator.completion_cost()`。
     计算失败且 `cost_tracking != "ignore_errors"` → `raise RuntimeError`
   - `GLOBAL_MODEL_STATS.add(cost)`（`models/__init__.py:13`）检查
     `MSWEA_GLOBAL_COST_LIMIT` 与 `MSWEA_GLOBAL_CALL_LIMIT`
   - `_parse_actions()`（`:128`）从 `message.tool_calls` 提取动作，走
     `parse_toolcall_actions()`（`actions_toolcall.py:30`）。不是恰好一个合法的
     bash 工具调用 → 抛 `FormatError`
   - 返回的消息带 `extra.actions`、`extra.cost`、`extra.response`、`extra.timestamp`

6. 回到 `agents/default.py:150` 累加 cost，`add_messages(message)`。

### 4.3 `execute_actions()` — `agents/interactive.py:123`

`InteractiveAgent` 覆盖了 `DefaultAgent:154` 的版本，多出确认环节。

7. `_ask_confirmation_or_interrupt()`：`confirm` 模式下，命令不匹配
   `whitelist_actions` 里任何正则就停下来问用户。`-y` 把 mode 设成 `yolo`，
   跳过这一步。`human` 模式下改为用户直接输入命令。

8. 逐个 `env.execute(action)` → `environments/local.py:24`：
   - `_run()`（`:72`）用
     `subprocess.Popen(command, shell=True, cwd=..., env=..., timeout=30,
     start_new_session=True)`
   - 超时用 `os.killpg` 杀整个进程组，避免留下孤儿进程
   - `stderr` 合并进 `stdout`
   - `env` 是 `os.environ | self.config.env`，`.env` 里的键覆盖系统环境

9. `_check_finished()`（`:45`）：输出首行等于
   `COMPLETE_TASK_AND_SUBMIT_FINAL_OUTPUT` 且 returncode 为 0 → 抛 `Submitted`，
   任务结束。

10. `format_observation_messages()` 把输出渲染成 tool result 消息追加进消息列表。

### 4.4 收尾

11. `run()` 的 `finally` 块（`agents/default.py:121`）每轮都调一次 `self.save()`。
    trajectory 每一步都落盘，默认写到
    `~/.config/mini-swe-agent/last_mini_run.traj.json`（`run/mini.py:23`）。

12. 最后一条消息 `role == "exit"` 时跳出循环。

13. 连续 3 次 `FormatError`（`max_consecutive_format_errors`）→ 追加一条
    `RepeatedFormatError` 退出循环。

---

## 退出状态

| `exit_status` | 触发位置 |
|---|---|
| `Submitted` | 模型发出提交命令，`LocalEnvironment._check_finished()` |
| `LimitsExceeded` | `step_limit` 或 `cost_limit` 用尽 |
| `TimeExceeded` | `wall_time_limit_seconds` 用尽 |
| `RepeatedFormatError` | 连续格式错误达到上限 |
| `UserInterruption` | 用户拒绝执行或按 Ctrl-C |
| `UserNewTask` | 用户追加了新任务 |

---

## 使用注意

1. `-c` 一旦使用，默认配置不再自动加载。所以 `-c mini.yaml` 必须显式写出来。
2. 本地模型常缺成本信息。用 `MSWEA_COST_TRACKING=ignore_errors` 跳过，否则
   `_calculate_cost()` 会抛 `RuntimeError`。
3. `mini_textbased.yaml` 内部没有 `model_class` 字段。要用正则解析而非原生 tool
   calling 时，必须额外传 `--model-class litellm_textbased`。
   `tests/test_fire.py:77` 是正确写法，`docs/advanced/v2_migration.md` 少了这个参数。
4. `uv.lock` 已被 `.gitignore` 忽略。`uv sync` 生成它不会弄脏 git 状态。
5. 沙箱或代理环境下，`HTTP_PROXY` / `HTTPS_PROXY` 指向不可用的代理会让
   `uv pip install` 连不上 PyPI。装依赖时用
   `env -u HTTP_PROXY -u HTTPS_PROXY uv pip install -e .`。
