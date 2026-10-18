# Compare with Pi

## tools

Pi 1.3.0 的 `read`、`bash`、`edit`、`write`、`grep`、`find`、`ls` 工具定义，并展示它们在 OpenAI Chat Completions 与 Responses API 中的函数工具格式。

Pi 默认启用 `read`、`bash`、`edit`、`write`。`grep`、`find`、`ls` 是 Pi 内置工具，但默认不启用。OpenAI API 只接收工具声明并返回工具调用。

参数 schema 保留可选属性。示例使用 `strict: false`，避免严格模式对可选参数提出额外 schema 限制。`additionalProperties` 未列出，和 Pi 暴露的 schema 一致。

| 项目     | Chat Completions                          | Responses API                               |
| -------- | ----------------------------------------- | ------------------------------------------- |
| 工具定义 | `{"type":"function","function":{...}}`    | `{"type":"function","name":"...",...}`      |
| 模型调用 | assistant 消息中的 `tool_calls[]`         | `output[]` 中的 `function_call` item        |
| 参数     | `function.arguments`，JSON 字符串         | `arguments`，JSON 字符串                    |
| 调用 ID  | `tool_calls[].id`                         | `function_call.call_id`                     |
| 工具结果 | `role: "tool"`、`tool_call_id`、`content` | `function_call_output`、`call_id`、`output` |

两种协议只改变 API 的工具声明和往返消息结构。工具名称与参数 schema 可以保持一致。API 不会替 Pi 执行这些本地工具；调用方必须验证参数、执行工具，并回传结果。

### Chat Completions

请求使用 `tools[].function` 包装函数定义。模型以 assistant 消息的 `tool_calls` 返回调用；应用执行后，以 `role: "tool"` 和对应的 `tool_call_id` 回传结果。

```json
{
  "model": "<model>",
  "messages": [{ "role": "user", "content": "<user prompt>" }],
  "tools": [
    {
      "type": "function",
      "function": {
        "name": "read",
        "description": "Read the contents of a file. Supports text files and images (jpg, png, gif, webp, bmp). Images are sent as attachments. For text files, output is truncated to 2000 lines or 50KB (whichever is hit first). Use offset/limit for large files. When you need the full file, continue with offset until complete.",
        "parameters": {
          "type": "object",
          "properties": {
            "path": {
              "type": "string",
              "description": "Path to the file to read (relative or absolute)"
            },
            "offset": {
              "type": "number",
              "description": "Line number to start reading from (1-indexed)"
            },
            "limit": {
              "type": "number",
              "description": "Maximum number of lines to read"
            }
          },
          "required": ["path"]
        },
        "strict": false
      }
    },
    {
      "type": "function",
      "function": {
        "name": "bash",
        "description": "Execute a bash command in the current working directory. Returns stdout and stderr. Output is truncated to last 2000 lines or 50KB (whichever is hit first). If truncated, full output is saved to a temp file. Optionally provide a timeout in seconds.",
        "parameters": {
          "type": "object",
          "properties": {
            "command": {
              "type": "string",
              "description": "Shell command to execute"
            },
            "timeout": {
              "type": "number",
              "description": "Timeout in seconds (optional, no default timeout)"
            }
          },
          "required": ["command"]
        },
        "strict": false
      }
    },
    {
      "type": "function",
      "function": {
        "name": "edit",
        "description": "Edit a single file using exact text replacement. Every edits[].oldText must match a unique, non-overlapping region of the original file. If two changes affect the same block or nearby lines, merge them into one edit instead of emitting overlapping edits. Do not include large unchanged regions just to connect distant changes.",
        "parameters": {
          "type": "object",
          "properties": {
            "path": {
              "type": "string",
              "description": "Path to the file to edit (relative or absolute)"
            },
            "edits": {
              "type": "array",
              "description": "One or more targeted replacements. Each edit is matched against the original file, not incrementally. Do not include overlapping or nested edits. If two changes touch the same block or nearby lines, merge them into one edit instead.",
              "items": {
                "type": "object",
                "properties": {
                  "oldText": {
                    "type": "string",
                    "description": "Exact text for one targeted replacement. It must be unique in the original file and must not overlap with any other edits[].oldText in the same call."
                  },
                  "newText": {
                    "type": "string",
                    "description": "Replacement text for this targeted edit."
                  }
                },
                "required": ["oldText", "newText"]
              }
            }
          },
          "required": ["path", "edits"]
        },
        "strict": false
      }
    },
    {
      "type": "function",
      "function": {
        "name": "write",
        "description": "Write content to a file. Creates the file if it doesn't exist. Automatically creates parent directories.",
        "parameters": {
          "type": "object",
          "properties": {
            "path": {
              "type": "string",
              "description": "Path to the file to write (relative or absolute)"
            },
            "content": {
              "type": "string",
              "description": "Content to write to the file"
            }
          },
          "required": ["path", "content"]
        },
        "strict": false
      }
    },
    {
      "type": "function",
      "function": {
        "name": "grep",
        "description": "Search file contents for a pattern. Returns matching lines with file paths and line numbers. Respects .gitignore. Output is truncated to 100 matches or 50KB (whichever is hit first). Long lines are truncated to 500 chars.",
        "parameters": {
          "type": "object",
          "properties": {
            "pattern": {
              "type": "string",
              "description": "Search pattern (regex or literal string)"
            },
            "path": {
              "type": "string",
              "description": "Directory or file to search (default: current directory)"
            },
            "glob": {
              "type": "string",
              "description": "Filter files by glob pattern, e.g. '*.ts' or '**/*.spec.ts'"
            },
            "ignoreCase": {
              "type": "boolean",
              "description": "Case-insensitive search (default: false)"
            },
            "literal": {
              "type": "boolean",
              "description": "Treat pattern as literal string instead of regex (default: false)"
            },
            "context": {
              "type": "number",
              "description": "Number of lines to show before and after each match (default: 0)"
            },
            "limit": {
              "type": "number",
              "description": "Maximum number of matches to return (default: 100)"
            }
          },
          "required": ["pattern"]
        },
        "strict": false
      }
    },
    {
      "type": "function",
      "function": {
        "name": "find",
        "description": "Search for files by glob pattern. Returns matching file paths relative to the search directory. Respects .gitignore. Output is truncated to 1000 results or 50KB (whichever is hit first).",
        "parameters": {
          "type": "object",
          "properties": {
            "pattern": {
              "type": "string",
              "description": "Glob pattern to match files, e.g. '*.ts', '**/*.json', or 'src/**/*.spec.ts'"
            },
            "path": {
              "type": "string",
              "description": "Directory to search in (default: current directory)"
            },
            "limit": {
              "type": "number",
              "description": "Maximum number of results (default: 1000)"
            }
          },
          "required": ["pattern"]
        },
        "strict": false
      }
    },
    {
      "type": "function",
      "function": {
        "name": "ls",
        "description": "List directory contents. Returns entries sorted alphabetically, with '/' suffix for directories. Includes dotfiles. Output is truncated to 500 entries or 50KB (whichever is hit first).",
        "parameters": {
          "type": "object",
          "properties": {
            "path": {
              "type": "string",
              "description": "Directory to list (default: current directory)"
            },
            "limit": {
              "type": "number",
              "description": "Maximum number of entries to return (default: 500)"
            }
          }
        },
        "strict": false
      }
    }
  ]
}
```

工具调用往返示例：

```json
{
  "role": "assistant",
  "content": null,
  "tool_calls": [
    {
      "id": "call_123",
      "type": "function",
      "function": {
        "name": "read",
        "arguments": "{\"path\":\"README.md\",\"offset\":1,\"limit\":40}"
      }
    }
  ]
}
```

应用执行 `read` 后，在后续请求的 `messages` 中追加结果：

```json
{ "role": "tool", "tool_call_id": "call_123", "content": "<tool output>" }
```

### Responses API

Responses API 使用扁平的 function tool 定义：`type`、`name`、`description`、`parameters` 和 `strict` 位于同一对象。模型在 `output` 中返回 `function_call` item；应用执行后，以 `function_call_output` item 回传结果，并用 `call_id` 关联调用。

请求的 `tools` 数组使用与 Chat Completions 相同的参数 schema，只改变函数定义的外层结构：

```json
{
  "model": "<model>",
  "input": [{ "role": "user", "content": "<user prompt>" }],
  "tools": [
    {
      "type": "function",
      "name": "read",
      "description": "Read the contents of a file. Supports text files and images (jpg, png, gif, webp, bmp). Images are sent as attachments. For text files, output is truncated to 2000 lines or 50KB (whichever is hit first). Use offset/limit for large files. When you need the full file, continue with offset until complete.",
      "parameters": {
        "type": "object",
        "properties": {
          "path": {
            "type": "string",
            "description": "Path to the file to read (relative or absolute)"
          },
          "offset": {
            "type": "number",
            "description": "Line number to start reading from (1-indexed)"
          },
          "limit": {
            "type": "number",
            "description": "Maximum number of lines to read"
          }
        },
        "required": ["path"]
      },
      "strict": false
    },
    {
      "type": "function",
      "name": "bash",
      "description": "Execute a bash command in the current working directory. Returns stdout and stderr. Output is truncated to last 2000 lines or 50KB (whichever is hit first). If truncated, full output is saved to a temp file. Optionally provide a timeout in seconds.",
      "parameters": {
        "type": "object",
        "properties": {
          "command": {
            "type": "string",
            "description": "Shell command to execute"
          },
          "timeout": {
            "type": "number",
            "description": "Timeout in seconds (optional, no default timeout)"
          }
        },
        "required": ["command"]
      },
      "strict": false
    },
    {
      "type": "function",
      "name": "edit",
      "description": "Edit a single file using exact text replacement. Every edits[].oldText must match a unique, non-overlapping region of the original file. If two changes affect the same block or nearby lines, merge them into one edit instead of emitting overlapping edits. Do not include large unchanged regions just to connect distant changes.",
      "parameters": {
        "type": "object",
        "properties": {
          "path": {
            "type": "string",
            "description": "Path to the file to edit (relative or absolute)"
          },
          "edits": {
            "type": "array",
            "description": "One or more targeted replacements. Each edit is matched against the original file, not incrementally. Do not include overlapping or nested edits. If two changes touch the same block or nearby lines, merge them into one edit instead.",
            "items": {
              "type": "object",
              "properties": {
                "oldText": {
                  "type": "string",
                  "description": "Exact text for one targeted replacement. It must be unique in the original file and must not overlap with any other edits[].oldText in the same call."
                },
                "newText": {
                  "type": "string",
                  "description": "Replacement text for this targeted edit."
                }
              },
              "required": ["oldText", "newText"]
            }
          }
        },
        "required": ["path", "edits"]
      },
      "strict": false
    },
    {
      "type": "function",
      "name": "write",
      "description": "Write content to a file. Creates the file if it doesn't exist. Automatically creates parent directories.",
      "parameters": {
        "type": "object",
        "properties": {
          "path": {
            "type": "string",
            "description": "Path to the file to write (relative or absolute)"
          },
          "content": {
            "type": "string",
            "description": "Content to write to the file"
          }
        },
        "required": ["path", "content"]
      },
      "strict": false
    },
    {
      "type": "function",
      "name": "grep",
      "description": "Search file contents for a pattern. Returns matching lines with file paths and line numbers. Respects .gitignore. Output is truncated to 100 matches or 50KB (whichever is hit first). Long lines are truncated to 500 chars.",
      "parameters": {
        "type": "object",
        "properties": {
          "pattern": {
            "type": "string",
            "description": "Search pattern (regex or literal string)"
          },
          "path": {
            "type": "string",
            "description": "Directory or file to search (default: current directory)"
          },
          "glob": {
            "type": "string",
            "description": "Filter files by glob pattern, e.g. '*.ts' or '**/*.spec.ts'"
          },
          "ignoreCase": {
            "type": "boolean",
            "description": "Case-insensitive search (default: false)"
          },
          "literal": {
            "type": "boolean",
            "description": "Treat pattern as literal string instead of regex (default: false)"
          },
          "context": {
            "type": "number",
            "description": "Number of lines to show before and after each match (default: 0)"
          },
          "limit": {
            "type": "number",
            "description": "Maximum number of matches to return (default: 100)"
          }
        },
        "required": ["pattern"]
      },
      "strict": false
    },
    {
      "type": "function",
      "name": "find",
      "description": "Search for files by glob pattern. Returns matching file paths relative to the search directory. Respects .gitignore. Output is truncated to 1000 results or 50KB (whichever is hit first).",
      "parameters": {
        "type": "object",
        "properties": {
          "pattern": {
            "type": "string",
            "description": "Glob pattern to match files, e.g. '*.ts', '**/*.json', or 'src/**/*.spec.ts'"
          },
          "path": {
            "type": "string",
            "description": "Directory to search in (default: current directory)"
          },
          "limit": {
            "type": "number",
            "description": "Maximum number of results (default: 1000)"
          }
        },
        "required": ["pattern"]
      },
      "strict": false
    },
    {
      "type": "function",
      "name": "ls",
      "description": "List directory contents. Returns entries sorted alphabetically, with '/' suffix for directories. Includes dotfiles. Output is truncated to 500 entries or 50KB (whichever is hit first).",
      "parameters": {
        "type": "object",
        "properties": {
          "path": {
            "type": "string",
            "description": "Directory to list (default: current directory)"
          },
          "limit": {
            "type": "number",
            "description": "Maximum number of entries to return (default: 500)"
          }
        }
      },
      "strict": false
    }
  ]
}
```

Function call 和结果示例：

```json
{
  "type": "function_call",
  "call_id": "call_123",
  "name": "read",
  "arguments": "{\"path\":\"README.md\",\"offset\":1,\"limit\":40}"
}
```

应用执行调用后，把结果作为后续 `input` 中的 item 发送：

```json
{
  "type": "function_call_output",
  "call_id": "call_123",
  "output": "<tool output>"
}
```

## 4. 工具的实际实现

Pi 的源码项目使用 TypeScript。安装包通过 `tsc` 编译，再打包成 JavaScript；因此，运行时执行的是 JavaScript bundle，不是直接执行 TypeScript。当前安装包的工具定义和执行器位于 `dist/bundle/chunks/chunk-66G7ITPS.js`。

| Pi 工具 | 实际执行方式 |
|---|---|
| `read` | 使用 Node.js 文件 API 读取文本文件；支持读取部分图片。 |
| `edit` | 使用 Node.js 文件 API 读取文件，按精确文本匹配替换，再写回文件；不调用 `sed`。 |
| `write` | 使用 Node.js 文件 API 创建目录并写入文件。 |
| `ls` | 使用 Node.js 文件 API 读取目录，并排序目录项。 |
| `grep` | 使用 `rg`（ripgrep）搜索文件内容。Pi 会解析或准备 `rg`；不可用时工具会报错。 |
| `find` | 使用 `fd` 按 glob 模式查找文件。Pi 会解析或准备 `fd`；不可用时工具会报错。 |
| `bash` | 在工作目录启动 shell 执行命令，并收集标准输出和标准错误。 |

`grep` 工具不是 `grep` 命令的简单别名，`find` 工具也不是 Linux 的 `find` 命令。它们有自己的参数 schema 和结果处理逻辑，底层分别使用 `rg` 和 `fd`。

`bash` 可以调用 `sed`、Linux `find`、`grep`、`rg`、`fd` 等系统命令。命令能否运行取决于当前环境是否安装该命令，以及 shell 的 `PATH` 是否能找到它。`bash` 工具本身由 Pi 启动 shell 执行命令，不会为每种命令单独提供工具 schema。

## 5. 参考位置

- Pi CLI 文档：`docs/cli.md`，列出内置工具及默认启用工具。
- Pi 本机实现：`dist/bundle/chunks/chunk-66G7ITPS.js`，包含工具参数 schema 与执行器。
- Pi 本机 `package.json`：`build:unbundled` 调用 `tsc`，`build` 再打包构建产物。
- 项目协议笔记：`notes/openai-chat-completions.md`、`notes/openai-responses.md`。
