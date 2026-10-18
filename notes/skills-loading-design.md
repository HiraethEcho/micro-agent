# Skills 加载设计

本文记录 micro 的 Skills 发现、暴露、启用和按需注入行为。Skills 不接入 `/system-prompts` 管理流程。

## 发现与覆盖

按以下顺序扫描 Skills 根目录，前面的目录优先级更高：

1. `./.micro/skills/`
2. `./.agents/skills/`
3. `~/.micro/skills/`
4. `~/.agents/skills/`

每个 skill 目录必须使用标准文件名 `SKILL.md`。其 YAML frontmatter 中的 `name` 是 skill 名称，并按 Agent Skills 规范与目录名一致；`description` 也是必填字段。目录扫描只识别 `SKILL.md`。同名时只保留优先级最高的定义，低优先级定义被覆盖。发现结果应保留解析出的名称、title、description 和文件路径。

## 暴露到 system prompt

所有发现的 Skills 默认启用。启用的 skill 只将 metadata 中的 `title`、`description` 和 `SKILL.md` 路径列入 system prompt，不注入正文。System prompt 应说明这些是可选的任务指南：模型根据描述判断是否适用，需要正文时通过可用工具读取所列路径。micro 应在每次请求前按当前启用状态构建目录。

禁用 skill 时，system prompt 完全不包含它的名称、描述和路径。Skills 由 `/skills` 命令管理 enable/disable，不由 `/system-prompts` 处理。底层仍复用 system append 的组装机制，但 Skills 是独立来源类别和管理入口。

## 按需注入正文

`/skill:<name> [additional message]` 按 metadata 的 `name` 查找 skill，把对应 `SKILL.md` 的完整文件内容作为一条新的 `role: user` 消息加入会话；若提供 additional message，则将其追加在正文后。该消息原样持久化在会话 JSONL 中，恢复时作为普通对话历史重放。此命令可用于未启用的 Skill；它不改变该 Skill 的 metadata 暴露状态。

## 会话持久化方向

会话 JSONL 首行保留已有 prompt 来源及会话元数据；Skills 的 enable/disable 状态作为后续 `skill_state` 事件追加，不扩大首行。加载会话时按事件重建 skill 状态，再在每次请求前按优先级重新发现 Skill 并读取启用 Skill 的 metadata，生成 system prompt 目录。`/skill:<name>` 的实际正文注入则作为普通 user 消息按序保存。

同名覆盖发生变化时，以 metadata 名称作为状态键，并将当时胜出的路径记录在会话状态事件中。Enable 状态跟随名称；prompt 目录和正文注入使用当前优先级扫描到的定义。
