# Chat Completions `tools` 参数

本文记录 `micro` 当前通过 OpenAI 兼容的 Chat Completions API 发送哪些请求内容、如何向模型提供工具，以及模型如何请求工具调用、程序如何回传结果。

## 请求顶层字段

当前在 `src/agent.py` 中调用：

```python
response = self.client.chat.completions.create(
    model=self.config.model,
    messages=self.messages,
    tools=[BASH_TOOL],
)
```

应用显式传入以下字段：

| 字段 | 当前值 | 用途 |
|---|---|---|
| `model` | `self.config.model`，默认 `ornith:9b` | 指定请求使用的模型。 |
| `messages` | `self.messages` | 发送对话的完整消息历史，包括系统指令、用户输入、助手回复、工具调用及工具结果。 |
| `tools` | `[BASH_TOOL]` | 声明可供模型选择的工具及其参数 schema。目前只有 `bash`。 |

`url` 和 `key` 用于初始化 OpenAI SDK 客户端，决定服务地址和认证；它们不是传给 `chat.completions.create()` 的字段。默认 URL 指向本机 Ollama 的 OpenAI 兼容接口。

当前代码没有显式传入 `temperature`、`max_tokens`、`tool_choice`、`response_format` 或 `stream` 等可选参数，也没有启用流式响应。这些行为由 SDK/服务端默认值决定；未设置 `tool_choice` 时由模型自行决定是否调用工具。

## `messages` 对话历史

`messages` 是按顺序排列的消息数组。每次模型请求都发送当前完整历史，而不只是最新输入。常见一次工具调用往返如下：

```json
[
  {
    "role": "system",
    "content": "You are a helpful assistant. Use tools when they help answer the user's request."
  },
  {
    "role": "user",
    "content": "查看当前目录有哪些文件"
  },
  {
    "role": "assistant",
    "content": "",
    "tool_calls": [
      {
        "id": "call_123",
        "type": "function",
        "function": {
          "name": "bash",
          "arguments": "{\"command\": \"ls\"}"
        }
      }
    ]
  },
  {
    "role": "tool",
    "tool_call_id": "call_123",
    "content": "returncode: 0\nREADME.md\nsrc\n"
  },
  {
    "role": "assistant",
    "content": "当前目录包含 README.md 和 src。"
  }
]
```

当前实现使用的 role 和内容：

- `system`：会话第一次调用时加入，内容来自配置的 `system_prompt`。
- `user`：REPL 收到的每条非空文本输入。
- `assistant`：模型生成的文本回答；或带有 `tool_calls` 的工具调用请求。
- `tool`：程序执行工具后追加的结果，通过 `tool_call_id` 关联到对应调用。

用户输入和工具输出目前都是普通文本。代码没有实现图片、音频或其他多模态内容块。

## 工具定义放在哪里

工具定义不是 `messages` 中的 `system`、`user` 或 `tool` 消息，而是请求顶层的 `tools` 参数。当前 `src/agent.py` 在每次模型请求中传入：

```python
response = self.client.chat.completions.create(
    model=self.config.model,
    messages=self.messages,
    tools=[BASH_TOOL],
)
```

`tools` 是工具定义的数组。每个定义采用 function tool 形式：

```json
{
  "type": "function",
  "function": {
    "name": "bash",
    "description": "Run a shell command in the current project directory.",
    "parameters": {
      "type": "object",
      "properties": {
        "command": {
          "type": "string",
          "description": "The shell command to run."
        }
      },
      "required": ["command"]
    }
  }
}
```

其中：

- `type: "function"` 表示这是一个可由模型请求调用的函数工具。
- `function.name` 是模型返回调用时使用的工具名。
- `function.description` 解释工具用途，帮助模型判断何时调用。
- `function.parameters` 是 JSON Schema，描述参数对象、字段类型和必填项。

当前只有 `BASH_TOOL` 一个工具定义。传入 `tools` 表示向模型提供可用工具；它本身不会执行命令。模型服务需要支持兼容的 tool calling 格式。

## 模型怎样发起调用

模型的响应仍是一条 assistant 消息。当模型决定使用工具时，响应带有 `tool_calls`，大致如下：

```json
{
  "role": "assistant",
  "content": "",
  "tool_calls": [
    {
      "id": "call_123",
      "type": "function",
      "function": {
        "name": "bash",
        "arguments": "{\"command\": \"ls\"}"
      }
    }
  ]
}
```

这是 assistant 的工具调用请求，不是 `role: "tool"`。`micro` 将 assistant 消息（包括 `tool_calls`）保存在历史中，再解析函数名与 JSON 参数。当前执行器只接受名称为 `bash` 且 `command` 为非空字符串的调用。

## 工具结果怎样回传

执行器按当前模式（`ask`、`auto` 或 `yolo`）决定是否批准执行。命令运行后，程序将结果作为 tool 消息加入历史，并用 `tool_call_id` 对应原来的调用：

```json
{
  "role": "tool",
  "tool_call_id": "call_123",
  "content": "returncode: 0\nfile1.py\nREADME.md\n"
}
```

之后 `micro` 再把包含 assistant 工具调用和 tool 结果的完整 `messages` 历史连同 `tools` 一起发给模型。模型可以据此继续请求工具，也可以直接回复用户。该循环持续到响应中没有 `tool_calls` 为止。

## Role 与字段速查

| 信息 | 所在位置 | Role |
|---|---|---|
| 工具名称、说明、参数 schema | 请求顶层 `tools` 数组 | 无 message role |
| 模型发起的工具调用 | 响应中的 assistant 消息 `tool_calls` | `assistant` |
| 程序执行后的工具输出 | 后续请求 `messages` 中的 tool 消息 | `tool` |

## 当前实现范围

- 只向模型提供 `bash` 工具。
- 请求未设置 `tool_choice`，由模型决定是否调用工具。
- 工具描述和 schema 硬编码在 `src/agent.py` 的 `BASH_TOOL`，不是从配置文件动态发现。
- 工具定义告知模型工具能力，但实际执行由本地程序控制；模式检查和用户确认仍由 `micro` 执行。
- 不同模型服务对 OpenAI 兼容工具调用的支持可能有差异；需要服务端正确处理 `tools` 参数并返回兼容的 `tool_calls`。
- `chat.completions.create()` 请求当前显式字段只有 `model`、`messages` 和 `tools`；模型服务是否支持这些格式以及默认生成行为由实际后端决定。
