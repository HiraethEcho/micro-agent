# 功能

## session management

use jsonl to store session data

## json mode

use this as a cli, give json output to stdout, and read json input from stdin. So that can be used by other tools

## 注入

### system_prompt

有默认 system prompt
配置文件里有 system prompt来覆盖默认
加上 system_prompt_apend 的接口，可以在会话中动态修改最终发送给模型的 role: system 的部分
例如用 `/system_prompt_apend "你是一个有趣的聊天机器人"` 来在会话中追加 system prompt
或者后续有其他动态注入方式

### AGENTS.md

读取项目 AGENTS.md

### Skills

渐进式披露

### tools

自定义添加 tools
