# OpenAI Chat Completions 规范笔记

本文概述 OpenAI `POST /v1/chat/completions` 的请求、消息、工具调用和响应结构，并说明与 micro 当前实现的关系。字段和能力可能随模型、API 版本更新；实现时以 [Chat Completions API Reference](https://platform.openai.com/docs/api-reference/chat/create) 为准。

## 请求结构

请求主体是 JSON 对象，核心字段如下：

```json
{
  "model": "gpt-4.1",
  "messages": [
    {"role": "developer", "content": "You are a helpful assistant."},
    {"role": "user", "content": "Hello."}
  ],
  "tools": []
}
```

- `model` 指定模型。
- `messages` 是有序消息数组，包含本轮上下文。
- `tools` 可选，声明模型可请求调用的工具。
- 其他可选参数控制工具选择、生成长度、输出格式、采样、流式响应等。未传字段使用接口或模型默认行为。

认证和服务地址由 HTTP 请求头及 URL 决定，不是 `messages` 中的内容。OpenAI SDK 中 `base_url`、`api_key` 用于设置这些传输信息。

## Message 与 role

消息通常具有 `role` 和 `content`。常见角色：

| Role | 含义 |
|---|---|
| `system` | 提供高优先级行为指令。对于 o1 及之后的模型，官方建议用 `developer` 代替。 |
| `developer` | 应用开发者提供的指令，优先级高于 user 内容。o1 及之后模型以它替代旧的 system 指令。 |
| `user` | 用户输入或提供给模型的上下文。内容可依模型支持文本、图像、音频、文件等。 |
| `assistant` | 模型先前生成的回答或工具调用请求。 |
| `tool` | 工具执行结果；通过 `tool_call_id` 关联 assistant 发出的调用。 |

`messages` 的数组顺序就是本次请求的上下文顺序。应用负责保存并在后续请求中按顺序重发所需历史；接口不会因为收到一条 user 消息就自动读取应用本地的 JSONL 文件。

消息内容可以是字符串，也可以是由内容部分组成的数组。可用内容类型依模型和 endpoint 而异；不能假设所有模型都支持图像、音频或文件输入。

## Tool 定义

自定义 function tool 放在请求顶层 `tools` 数组，不是 `system` 消息或 `tool` 消息：

```json
{
  "type": "function",
  "function": {
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
}
```

`name` 和 `description` 标识、解释工具；`parameters` 用 JSON Schema 描述参数；`strict` 可启用受支持子集上的严格 schema 遵循。应用仍须验证参数并执行授权检查。工具定义只告诉模型有哪些工具可请求，不会自行执行代码。

`tool_choice` 控制模型能否或必须如何选择工具。常见值包括 `auto`、`none`、`required`，也可指定某个函数。可用模式和参数约束取决于请求及模型。

## Tool 调用往返

模型通过 assistant 消息的 `tool_calls` 发出调用：

```json
{
  "role": "assistant",
  "content": null,
  "tool_calls": [
    {
      "id": "call_123",
      "type": "function",
      "function": {
        "name": "bash",
        "arguments": "{\"command\":\"ls\"}"
      }
    }
  ]
}
```

应用解析并验证 arguments，执行工具，然后在后续请求的消息中提供结果：

```json
{"role":"tool","tool_call_id":"call_123","content":"README.md\nsrc/"}
```

`tool_call_id` 必须对应 assistant 调用里的 `id`。一条 assistant 消息可以包含多个调用；若模型返回多个调用，应用应逐一处理并为每个调用回传匹配的 tool 结果，然后继续请求模型。工具调用由模型提出，实际执行由客户端应用负责。

调用参数以 JSON 字符串形式返回。即使提供 JSON Schema，也必须处理无效 JSON、缺少字段、未预期的工具名或后端不遵循 schema 的情况。

## 响应与流式响应

非流式响应主体包含 `choices`；每个 choice 有 assistant `message` 和 `finish_reason`。调用方通常检查 `message.tool_calls` 决定是否执行工具，并按 `finish_reason` 判断模型为何结束。API 错误通过 HTTP/API 错误结构返回。

设置 `stream: true` 后，服务以 Server-Sent Events 逐段返回内容。流式工具调用参数可能分片到多个 chunk，客户端必须根据 choice/index 与工具调用索引逐段拼接后再解析，不能把每个 chunk 当成完整调用。

## 当前 micro 实现

micro 当前用 OpenAI Python SDK 的 `chat.completions.create()`，显式传入 `model`、完整 `messages` 和一个 `bash` function tool。它用 assistant `tool_calls` 的 ID 关联 `role: tool` 的结果，再重新发送更新后的历史。micro 自己将有序消息写入 `.micro/sessions/*.jsonl`；JSONL 是本地持久化格式，不是 OpenAI API 的请求格式。

当前后端是 Ollama 的 OpenAI 兼容 endpoint。兼容声明不保证每个 OpenAI 字段、role、工具调用行为或多模态格式都可用；具体能力由 Ollama 版本、模型和 endpoint 决定。尤其应验证 `developer` role 是否被接受。OpenAI Chat Completions 对 o1 及之后模型定义了 developer role；其他供应商兼容层可能只支持其子集。

## 官方资料

- [Chat Completions API Reference](https://platform.openai.com/docs/api-reference/chat/create)
- [Function calling guide](https://platform.openai.com/docs/guides/function-calling)
- [Conversation messages and roles](https://platform.openai.com/docs/guides/text-generation)
