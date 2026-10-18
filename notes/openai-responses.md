# OpenAI Responses API 规范笔记

本文概述 OpenAI `POST /v1/responses` 的输入、输出、工具调用和会话延续。Responses API 使用 item 序列，支持文本与多模态内容、工具、后台能力和可选服务端状态。字段和模型支持可能更新；实现时以 [Responses API Reference](https://platform.openai.com/docs/api-reference/responses) 为准。

## 请求结构

典型请求：

```json
{
  "model": "gpt-4.1",
  "instructions": "You are a helpful assistant.",
  "input": [
    {"role": "user", "content": "Hello."}
  ],
  "tools": []
}
```

- `model` 指定模型。
- `input` 接受字符串或输入 item 数组。消息 item 可用 `system`、`developer`、`user`、`assistant` 等 role；输入也可包含图像、音频、文件等特定 item，支持范围随模型而异。
- `instructions` 是系统/开发者层级指令；官方说明它等价于一条 `developer` role 输入。使用 `previous_response_id` 时，前一个 response 的 instructions 不会自动带入，需要在新请求中重新传递。
- `tools` 声明自定义函数或 OpenAI 提供的内置工具。Responses 的工具对象采用该 endpoint 的 schema，不能照搬 Chat Completions 的函数对象形状。

Responses 返回的 `output` 是有序 item 数组，不保证只有一条 assistant 文本消息。常见 item 包括 assistant message、function call、reasoning、拒答或内置工具活动；应按 `type` 解析，而不是只取一个固定的文本字段。

## Input 消息与 role

Responses 的 input message 形式：

```json
{
  "type": "message",
  "role": "user",
  "content": [
    {"type": "input_text", "text": "Summarize this."}
  ]
}
```

简单文本也可使用便捷字符串形式。多模态内容有明确类型，例如 `input_text`、`input_image`、`input_audio`、`input_file`；具体字段和模型能力以 API schema 为准。

`system` 和 `developer` role 都属于高优先级指令；官方规范表示它们优先于 `user` role。`instructions` 字段提供 system/developer 层级指令的便捷入口。不要把 role 仅理解为显示标签，它表示消息来源及指令层级。

## Tool 定义

Responses function tool 在顶层 `tools` 中使用扁平 schema：

```json
{
  "type": "function",
  "name": "bash",
  "description": "Run a shell command in the current project directory.",
  "parameters": {
    "type": "object",
    "properties": {
      "command": {"type": "string"}
    },
    "required": ["command"],
    "additionalProperties": false
  },
  "strict": true
}
```

这与 Chat Completions 常用的 `{ "type":"function", "function": { ... } }` 包装结构不同。Responses 也支持 OpenAI 内置工具和 MCP 等工具类别；可用性由模型和 API 功能决定。

`tool_choice` 可控制工具调用策略，例如 `auto`、`none`、`required` 或强制指定工具。实际选项和约束查阅 Responses API schema。

## Function call 往返

模型在 `output` 中返回 function call item：

```json
{
  "type": "function_call",
  "id": "fc_item_123",
  "call_id": "call_123",
  "name": "bash",
  "arguments": "{\"command\":\"ls\"}"
}
```

应用根据 `name` 和 JSON 字符串 `arguments` 验证并执行工具。之后把结果作为 function call output item 传回：

```json
{
  "type": "function_call_output",
  "call_id": "call_123",
  "output": "README.md\nsrc/"
}
```

结果中的 `call_id` 必须对应模型调用中的 `call_id`。注意，`id` 是 output item 的标识，`call_id` 才是调用和结果之间的关联标识。应用仍负责参数校验、授权、执行和错误处理。

手动管理上下文时，后续请求需把必要的前序 input 和 output items 纳入 `input`，包括 function call 与其输出。不要只保留最终可见文本，否则可能丢失工具往返的结构。

## 会话延续与状态

Responses 可用多种方式延续上下文：

- **手动历史**：客户端自行保存 items，并在下一次请求的 `input` 中发送需要的上下文。
- **`previous_response_id`**：请求引用前一个 response，由服务端关联前序 response。新请求的 instructions 仍需显式提供。
- **Conversation**：可使用 Conversations API 管理持久 conversation，并将其与 response 请求关联。

这些方式的存储位置、生命周期和上下文语义不同。`previous_response_id` 是 response 链接，不等于本地 JSONL；客户端若需要本地可审计记录，仍可独立保存请求和响应 items。

## 流式输出

设置 `stream: true` 时，Responses 通过 SSE 事件流返回。文本、工具调用参数和 response 生命周期都有对应事件。Function call arguments 可先以 delta 事件分片，最终事件提供完整参数；客户端应按 item ID、输出索引和事件顺序组装，待参数完成后再执行。

流中常见事件包括 response 创建、output item 添加、文本 delta、function call arguments delta/done、item 完成、response 完成或失败。使用 SDK 时可消费相应事件对象；原始 HTTP 客户端需按 SSE 协议解析。

## 与 Chat Completions 的主要区别

| 主题 | Chat Completions | Responses |
|---|---|---|
| endpoint | `/v1/chat/completions` | `/v1/responses` |
| 输入 | `messages` 数组 | `input` 字符串或 item 数组，可另传 `instructions` |
| 输出 | `choices[].message` | 有序 `output` items |
| function tool schema | `function` 对象包在 `function` 字段下 | 扁平的 `type`, `name`, `parameters` 等字段 |
| 调用结果 | `role: "tool"` + `tool_call_id` | `function_call_output` item + `call_id` |
| 工具种类 | 以 Chat Completions 支持的工具 schema 为准 | 自定义 function、OpenAI 内置工具、MCP 等类别 |
| 会话方式 | 客户端通常重发完整 message history | 可手动发送 items，也可引用 response/conversation 状态 |

两者都是 OpenAI API，但不能只替换 endpoint；请求字段、消息 item、工具结构、响应解析和上下文延续都需要按对应协议实现。

## 官方资料

- [Responses API Reference](https://platform.openai.com/docs/api-reference/responses)
- [Responses guide](https://platform.openai.com/docs/guides/responses)
- [Function calling guide](https://platform.openai.com/docs/guides/function-calling)
- [Conversation state guide](https://platform.openai.com/docs/guides/conversation-state)
