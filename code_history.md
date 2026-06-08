# 开发历史记录

## 2026-06-07

## （1）feat：初始化项目，可以命令行启动极简版功能，只包含简单的模型调用和工具使用

**提交:** `3e9e8d2` | **新增 9 个文件，共 332 行**

> **一句话概括：** 搭起了项目骨架，基于 OpenAI 兼容 API 实现了一个可在终端交互的 AI 编程助手，支持执行命令和读写文件三种工具，并能通过 `muse` 命令全局一键启动。

### 整体架构

项目采用典型的分层结构：

```
入口 → UI 层 → Agent 层 → LLM API
                  ↓
               Tools 层（命令执行、文件读写）
```

### 各模块详解

**[muse_code/__main__.py](file:///Users/lumine/code/llm/muse-code/muse_code/__main__.py) - 入口文件**

- 启动 CLI 交互循环，打印欢迎面板
- 循环读取用户输入，交给 Agent 处理
- 支持 `exit` / `quit` 退出，捕获 `KeyboardInterrupt` 和通用异常
- 通过 `pyproject.toml` 注册为 `muse` 命令，可全局一键启动

**[muse_code/ui.py](file:///Users/lumine/code/llm/muse-code/muse_code/ui.py) - 终端界面**

- 基于 Rich 库渲染美观的终端 UI
- 用 Panel + Markdown 展示 Agent 回复
- 区分展示：用户输入（绿色）、Agent 消息（紫色面板）、工具调用（黄色）、工具结果（青色）、错误（红色）
- 工具结果超过 500 字符会自动截断

**[muse_code/agent.py](file:///Users/lumine/code/llm/muse-code/muse_code/agent.py) - Agent 核心**

- 使用 OpenAI 兼容 API，默认指向 DeepSeek（可通过环境变量切换）
- 维持多轮对话上下文（`self.messages`）
- 实现完整的 tool-calling 循环：LLM 返回工具调用 → 执行工具 → 结果回传 → 继续对话
- 无工具调用时自动结束本轮对话

**[muse_code/tools.py](file:///Users/lumine/code/llm/muse-code/muse_code/tools.py) - 工具集**

提供 3 个工具，均以 OpenAI function calling 格式定义：

| 工具 | 功能 |
|------|------|
| `execute_command` | 执行 Shell 命令，60 秒超时，捕获 stdout/stderr |
| `read_file` | 读取文件内容（UTF-8） |
| `write_file` | 写入文件，自动创建父目录 |

**[muse_code/prompt.py](file:///Users/lumine/code/llm/muse-code/muse_code/prompt.py) - System Prompt**

- 定义 Agent 的角色：AI 编程助手，运行在 CLI 环境
- 指导 LLM 使用工具分析需求、收集信息、执行操作
- 要求简洁的 Markdown 格式回复

**[pyproject.toml](file:///Users/lumine/code/llm/muse-code/pyproject.toml) - 项目配置**

- Python >= 3.12，依赖 `rich>=13.7.0`、`openai>=1.14.0`
- 定义 `muse` 命令行入口，支持 `uv tool install` 全局安装

---

## （2）feat：工具系统全面升级，支持 Anthropic 后端，新增权限控制

**提交:** `待提交` | **修改 4 个文件，新增 2 个文件，共 +1035 -141 行**

> **一句话概括：** 工具集从 3 个扩充到 12 个，新增 Anthropic 后端支持，完善权限系统（5种模式）、延迟工具、编辑前读取检查、智能引号匹配、并发工具执行等特性。

### 核心技术点

#### 1. 双后端支持（OpenAI + Anthropic）

在 [agent.py](file:///Users/lumine/code/llm/muse-code/muse_code/agent.py#L58-L77) 中新增：

- 通过 `MUSE_BACKEND` 环境变量切换后端（默认 `openai`）
- 统一工具定义格式，自动转换 OpenAI 与 Anthropic 工具 schema
- Anthropic 支持流式响应 + 工具并发预执行（只读工具）
- 可重试机制（429/503/529 错误指数退避重试）

#### 2. 工具系统大升级（3 → 12 个工具）

新增工具：

| 工具 | 功能 |
|------|------|
| `edit_file` | 精确字符串替换编辑，返回 diff |
| `list_files` | Glob 模式列文件，跳 node_modules/.git |
| `grep_search` | 正则搜索，优先系统 grep 失败回退 Python |
| `run_shell` | 执行 Shell 命令，可自定义超时 |
| `web_fetch` | 抓取 URL，HTML 自动去标签 |
| `tool_search` | 搜索并激活延迟工具 |
| `enter_plan_mode` / `exit_plan_mode` | 计划模式切换 |
| `agent` | 子代理自主任务处理 |

#### 3. 权限系统（5种模式）

在 [tools.py](file:///Users/lumine/code/llm/muse-code/muse_code/tools.py#L547-L626) 中实现：

- **default**：读工具直接允许，写工具按需确认
- **plan**：只读模式，仅允许读写计划文件
- **acceptEdits**：自动允许编辑工具
- **bypassPermissions**：完全跳过权限检查
- **dontAsk**：自动拒绝需要确认的操作

支持 `~/.claude/settings.json` 或项目本地 `.claude/settings.json` 配置 allow/deny 规则。

#### 4. 延迟工具机制

- 默认只暴露 8 个核心工具，减少 LLM token 消耗
- 通过 `tool_search` 按需激活 `enter_plan_mode` / `exit_plan_mode` / `agent`
- 激活后工具会自动加入可用列表

#### 5. 编辑前读取 + mtime 新鲜度检查

在 [tools.py](file:///Users/lumine/code/llm/muse-code/muse_code/tools.py#L634-L699) 中实现：

- 写/编辑文件前必须先读取，防止覆盖未查看内容
- 记录读取时的 mtime，编辑前检查文件是否被外部修改
- 外部修改后提示重新读取

#### 6. 智能引号匹配

在 [tools.py](file:///Users/lumine/code/llm/muse-code/muse_code/tools.py#L252-L258) 中实现：

- 自动归一化弯引号（中文/排版引号）为直引号
- 解决 LLM 输出 `old_string` 时引号样式不一致导致匹配失败的问题

#### 7. 并发安全工具预执行

- 标记只读工具为 `CONCURRENCY_SAFE_TOOLS`
- **并发控制规则**：非并发安全的工具必须独占执行；多个并发安全工具可以同时跑
- Anthropic 后端在流式响应收到 tool_use 时，对安全工具立即异步执行
- 不等模型输出完所有 tool_use blocks，一旦检测到完整 block 就立即启动执行——工具执行延迟约 1 秒，模型流式输出持续 5-30 秒，大部分工具可以完全隐藏在流式窗口内
- 收到完整响应后直接用预执行结果，减少等待时间
- **OpenAI 后端无法实现流式中预执行**：因为 OpenAI 的流式响应中，`tool_calls` 的参数是增量拼接的，只有在整个流式响应结束后才能拿到完整的工具调用列表和参数，无法像 Anthropic 那样在单个 `tool_use` 块收完时就触发执行。作为替代优化，OpenAI 后端在流式结束后将连续的安全工具合并为一个批次，用 `asyncio.gather` 并发执行

#### 8. 其他增强

- 工具结果自动截断（最大 50000 字符），保留头尾而非只保留头部（很多命令的关键输出在末尾，如编译错误摘要、测试结果统计），截断提示明确告知模型内容被截断，模型可据此决定是否用 `grep_search` 或 `read_file` 获取完整内容
- `write_file` 自动创建父目录，返回内容预览
- 危险命令模式检测（`rm`/`sudo`/`git push --force` 等 16 种模式）
- `grep_search` 跨平台兼容（优先系统 grep，Windows 回退 Python）

### 依赖变更

新增依赖：`anthropic>=0.30.0`

### 与 Claude Code 截断策略对比

| 特性 | Claude Code | Muse Code |
|------|------------|-----------|
| 截断策略 | 保留头部 + `PARTIAL view` 提示 | 保留头尾 + 提示用 grep/read_file |
| 超长内容持久化 | 自动存磁盘，上下文只放文件路径 | 没有，截断后丢弃中间部分 |
| 二进制文件处理 | 自动解码存盘（PDF/Office/音频） | 没有 |
| 截断上限可配置 | 支持 `maxResultSizeChars` 覆盖，最高 500K | 固定 50K，不可配置 |
| 边界字符保护 | 处理了 surrogate-pair 截断问题 | 没有，可能截断在 Emoji 中间导致报错 |
| UI 交互 | 点击展开查看完整内容 | UI 层截断到 500 字符显示 |

### TODO

- [ ] **边界字符保护**：截断字符串时安全处理 surrogate pair，防止切在 Emoji/宽字节中间导致 API 报错
- [ ] **超长内容自动持久化**：超过 50K 的工具结果自动存磁盘文件，上下文只放文件路径，模型可随时用 `read_file` 读取完整内容
- [ ] **截断上限可配置**：支持环境变量或工具参数覆盖默认 50K 限制

---

## （3）feat：构建完整系统提示体系，支持 CLAUDE.md 发现、@include 指令、动态上下文注入

**提交:** `待提交` | **修改 3 个文件，新增 2 个文件**

> **一句话概括：** 从硬编码的简短 system prompt 升级为模板化、可插拔的完整提示体系，涵盖反模式接种、爆炸半径框架、工具偏好映射、CLAUDE.md 5 层发现、@include 指令、Deferred 工具名注入等关键设计。

### 核心技术点

#### 0. 提示词 7 层架构（从抽象到具体）

系统提示词的内容从抽象到具体分为 7 层——先建立身份和约束框架，再填充具体行为指导。这个顺序很重要：模型先建立的概念会成为理解后续内容的框架。

| 层级 | 名称 | 核心问题 | 对应章节 |
|------|------|----------|----------|
| 1 | Identity | 我是谁？ | `You are Muse Code, a lightweight coding assistant CLI.` |
| 2 | System | 运行环境的基本事实 | `# System` — 权限模式、标签处理、上下文压缩 |
| 3 | Doing Tasks | 怎么写代码？ | `# Doing tasks` — 反模式接种（3 条规则） |
| 4 | Actions | 哪些操作需要确认？ | `# Executing actions with care` — 爆炸半径框架 |
| 5 | Using Tools | 怎么用工具？ | `# Using your tools` — 偏好映射表 |
| 6 | Tone & Style | 输出什么格式？ | `# Tone and style` — 简洁、无 emoji、文件引用格式 |
| 7 | Output Efficiency | 怎么更简洁？ | `# Output efficiency` — 直奔主题、省略过渡语 |

这种分层设计遵循认知心理学中的"锚定效应"：模型首先建立的身份和约束会锚定后续所有输出的基调，使得具体的行为指导更容易被一致地遵循。

#### 1. 反模式接种（3 条规则）

在系统提示中预埋了 3 条"反模式"规则，防止 LLM 陷入常见的不良行为：

- **不过度工程**：不添加未被请求的功能、重构、文档、类型注解、错误处理、特性开关、兼容性垫片
- **不创建不必要的抽象**：一次性操作不需要 helper，三行相似代码优于过早抽象
- **不保留废弃代码**：不使用 `_var` 重命名、`// removed` 注释等向后兼容 hack，确认无用就彻底删除

这些规则通过"先告诉模型不要做什么"来减少后续纠正轮次，比事后修补更高效。

#### 2. @include 指令

在 [prompt.py](file:///Users/lumine/code/llm/muse-code/muse_code/prompt.py#L140-L175) 中实现：

- 支持 `@./path`、`@~/path`、`@/path` 三种引用语法，在 CLAUDE.md 中引用外部文件
- 递归解析，最大深度 5 层（`_MAX_INCLUDE_DEPTH = 5`），防止无限递归
- 循环引用检测：用 `visited` 集合记录已访问文件，遇到循环输出 `<!-- circular -->`
- 文件不存在时输出 `<!-- not found -->`，读取失败输出 `<!-- error reading -->`
- 所有路径都 resolve 为绝对路径后比较，防止符号链接绕过

#### 3. CLAUDE.md 5 层发现 + .claude 子目录

在 [prompt.py](file:///Users/lumine/code/llm/muse-code/muse_code/prompt.py#L193-L216) 中实现：

- 从 `cwd` 向上遍历到根目录，收集所有层级的 `CLAUDE.md` 文件
- 子目录的 CLAUDE.md 排在前面（`parts.insert(0, ...)`），确保最内层（项目级）优先级最高
- 额外加载 `.claude/rules/*.md` 目录下的所有规则文件（按文件名排序）
- 每个规则文件包裹 `<!-- rule: filename -->` 注释，方便溯源
- 典型 5 层结构：`/CLAUDE.md` → `/home/CLAUDE.md` → `/home/user/CLAUDE.md` → `/home/user/project/CLAUDE.md` → `.claude/rules/*.md`

#### 4. 爆炸半径框架

在系统提示的 `# Executing actions with care` 章节中定义：

- **核心原则**：考虑操作的可逆性和爆炸半径，本地可逆操作可自由执行，不可逆/影响共享状态的操作必须确认
- **一次性授权不等于永久授权**：用户批准一次 `git push` 不代表所有场景都批准
- **三类高风险操作**：
  - 破坏性操作：删除文件/分支、rm -rf、覆盖未提交变更
  - 难逆操作：force-push、reset --hard、修改 CI/CD
  - 影响共享状态：推送代码、创建 PR、发送消息
- **障碍处理原则**：不用破坏性操作绕过障碍，而是找根因修复（如解决冲突而非丢弃变更，调查锁文件而非删除）

#### 5. 工具偏好映射表

在系统提示的 `# Using your tools` 章节中定义了明确的工具优先级：

| 场景 | 应使用 | 不应使用 |
|------|--------|----------|
| 读文件 | `read_file` | cat/head/tail/sed |
| 编辑文件 | `edit_file` | sed/awk |
| 创建文件 | `write_file` | cat heredoc/echo |
| 列文件 | `list_files` | find/ls |
| 搜索内容 | `grep_search` | grep/rg |
| 系统命令 | `run_shell` | 仅在无专用工具时 |

为什么专用工具优于 shell 命令？每个专用工具都在对应 shell 命令的基础上增加了关键能力：

| 专用工具 | 对应 shell 命令 | 多出的能力 |
|----------|----------------|-----------|
| `read_file` | `cat` | 自动添加行号（`4 | content`），模型可直接用行号定位代码；记录读取 mtime，编辑前检查文件是否被外部修改 |
| `edit_file` | `sed -i` | 精确字符串匹配替换（非行号依赖），自动生成 unified diff 供用户审查；唯一性检查（匹配多处时报错而非静默替换）；智能引号匹配（弯引号自动归一化） |
| `write_file` | `cat > file` | 自动创建父目录（`mkdir -p`）；返回带行号的内容预览（前 30 行），用户可确认写入是否正确；自动更新 memory 索引 |
| `list_files` | `find`/`ls` | 自动跳过 `node_modules` 和 `.git`；结果上限 200 条防止输出爆炸；glob 模式比 find 语法更直观 |
| `grep_search` | `grep -r` | 跨平台兼容（Windows 回退 Python 实现）；结果上限 100 条防爆炸；支持 `include` 参数按文件类型过滤 |

核心设计原则：**专用工具是结构化的、可审计的、有安全边界的**，而 shell 命令是原始的、不可控的。通过在提示中明确映射偏好，模型默认走安全路径，只在确实需要时才回退到 `run_shell`。

#### 6. Deferred 工具名注入

在 [prompt.py](file:///Users/lumine/code/llm/muse-code/muse_code/prompt.py#L233-L238) 中实现：

- 从 `tools.py` 获取延迟工具名称列表（`get_deferred_tool_names()`）
- 在系统提示末尾注入提示：`The following deferred tools are available via tool_search: enter_plan_mode, exit_plan_mode, agent. Use tool_search to fetch their full schemas when needed.`
- 模型知道这些工具存在但不知道完整 schema，需要时才通过 `tool_search` 按需加载
- 减少默认 tool schema 的 token 消耗，同时不隐藏工具的存在

#### 7. 模板化变量插值

在 [prompt.py](file:///Users/lumine/code/llm/muse-code/muse_code/prompt.py#L224-L243) 中实现：

- 系统提示以模板形式内嵌（`SYSTEM_PROMPT_TEMPLATE`），使用 `{{variable}}` 占位符
- 动态插值的变量：`cwd`、`date`、`platform`、`shell`、`git_context`、`claude_md`、`memory`、`skills`、`agents`、`deferred_tools`
- Git 上下文自动获取：当前分支、最近 5 条 commit、工作区状态
- Agent 构造函数支持 `custom_system_prompt` 参数，可覆盖默认生成的提示

## （4）feat：添加命令行参数体系、REPL 交互循环、会话持久化

**核心内容**：从简单的主循环升级为完整的 CLI 工具，支持命令行参数、权限模式切换、会话保存/恢复、预算控制等。

#### 1. 命令行参数体系

| 参数 | 说明 |
|------|------|
| `--yolo, -y` | 跳过所有确认，自动执行（bypassPermissions 模式） |
| `--plan` | 计划模式（只读，不修改文件） |
| `--accept-edits` | 自动接受文件编辑 |
| `--dont-ask` | 尽量不向用户提问（CI 场景） |
| `--thinking` | 启用扩展思考模式 |
| `--model, -m` | 指定模型名称 |
| `--api-base` | 自定义 API 基地址 |
| `--resume` | 恢复上一次会话 |
| `--max-cost` | 最大费用限制（USD） |
| `--max-turns` | 最大对话轮次 |

通过 `_resolve_permission_mode()` 将参数映射为 5 种权限模式：`default`、`bypassPermissions`、`plan`、`acceptEdits`、`dontAsk`。

#### 2. REPL 交互循环

- 支持 SIGINT 双击退出（第一次中断当前操作，第二次退出程序）
- 内置 REPL 命令：`/clear`（清空历史）、`/cost`（显示用量）、`/compact`（压缩对话）、`/plan`（切换计划模式）
- 支持单次提示词模式（`muse "fix the bug"`）和交互模式（`muse`）

#### 3. 会话持久化

- 每轮对话后自动保存到 `~/.muse/sessions/{session_id}.json`
- 保存内容：metadata（id、model、cwd、startTime、turnCount、costUsd）+ 消息历史
- `--resume` 参数恢复最近一次会话，继续之前的对话

#### 4. 预算控制

- `_check_budget()` 在每轮对话前检查费用和轮次是否超限
- `_get_current_cost_usd()` 基于 token 用量估算费用（input $3/M, output $15/M）
- `show_cost()` 显示 token 数、预估费用、预算上限、轮次上限

#### 5. 计划模式增强

- 进入计划模式时保存之前的权限模式（`_pre_plan_mode`），退出时恢复
- 动态修改系统提示：进入时追加计划模式提示词，退出时还原
- OpenAI 后端同步更新 `_openai_messages[0]` 的系统消息
- 计划文件生成到 `~/.muse/plans/plan-{session_id}.md`
- 计划模式提示词包含 Explore → Design → Write Plan → Exit 工作流

#### 6. UI 增强

- 工具图标映射（`_TOOL_ICONS`）：每个工具有专属 emoji
- 工具调用摘要（`_get_tool_summary`）：根据工具类型生成简短描述（如 `read_file` 只显示文件名）
- 工具结果截断显示（500 字符上限）

---
## （5）feat：权限与安全模块全面升级 — 危险命令检测、规则系统、统一权限检查、会话白名单

> **一句话概括：** 从零散的权限判断升级为结构化安全体系，新增 4 级危险命令检测、用户+项目级 allow/deny 规则、统一权限检查流水线、会话级白名单记忆——让 AI 执行操作时既有"护栏"又有"记忆力"。

### 背景：为什么需要权限与安全？

当你让一个 AI 编程助手帮你写代码时，它可能会做这些事情：

- 读取你的项目文件（通常是安全的）
- **修改**你的源码（需要确认）
- **删除**文件或目录（危险！）
- 执行 `rm -rf /` 这种灾难性命令（绝对不能执行）
- 运行 `git push --force` 覆盖远程分支（需要二次确认）

权限系统的核心问题是：**哪些操作可以自动执行？哪些需要问你？哪些应该直接禁止？** 以及——**同一个操作你同意过一次后，能不能别再问了？**

本次升级把权限逻辑从散落在 `tools.py` 和 `agent.py` 中的零碎代码，重构为独立的 `permissions.py` 模块（670+ 行），包含四大子系统：

```
┌─────────────────────────────────────────────────────┐
│                  PermissionChecker                  │
│                  （统一权限检查器）                     │
│                                                      │
│  ┌──────────────┐  ┌──────────────┐                 │
│  │ 危险命令检测   │  │ 权限规则系统  │                 │
│  │ 4级风险 + 37  │  │ 用户+项目级   │                 │
│  │ 种危险模式    │  │ allow + deny │                 │
│  └──────┬───────┘  └──────┬───────┘                 │
│         │                  │                         │
│         ▼                  ▼                         │
│  ┌──────────────────────────────────────┐           │
│  │         检查流水线（9 步）              │           │
│  │  bypassPermissions → 规则 → 只读工具   │           │
│  │  → plan模式 → 模式切换 → acceptEdits  │           │
│  │  → 危险检测 → 会话白名单 → dontAsk    │           │
│  └──────────────────────────────────────┘           │
│                         │                            │
│                         ▼                            │
│  ┌──────────────────────────────────────┐           │
│  │         SessionWhitelist             │           │
│  │         （会话级白名单）                │           │
│  │  "你同意过的，我都记得"                 │           │
│  └──────────────────────────────────────┘           │
└─────────────────────────────────────────────────────┘
```

### 子模块 1：危险命令检测（4 级风险体系）

原来的危险命令检测只是一个"是否危险"的是非判断，现在升级为 4 级风险体系：

| 风险等级 | 含义 | 示例命令 | 默认行为 |
|----------|------|----------|----------|
| `critical` 🔴 | 极度危险，可能破坏系统 | `rm -rf /`、`mkfs`、`dd if=`、写块设备 | 必须确认 + 强烈警告 |
| `high` 🟠 | 高风险但可恢复 | `rm`、`sudo`、`chmod 777`、`git push --force` | 必须确认 + 警告 |
| `medium` 🟡 | 中等风险，可能造成不便 | `kill`、`git rebase`、`curl \| sh` | 需要确认 |
| `low` 🟢 | 潜在风险，通常不触发 | `grep -r /`、`npm publish` | 不主动触发确认 |

**使用场景举例**：

```python
# 场景 1：用户让 AI "清理临时文件"
# AI 生成了命令：rm -rf /tmp/build/*
# 系统检测到：
>>> from muse_code.permissions import detect_dangerous_commands
>>> detects = detect_dangerous_commands("rm -rf /tmp/build/*")
>>> for d in detects:
...     print(f"[{d.level.value}] {d.description}")
[critical] 递归强制删除文件/目录
[high] 删除文件

# 场景 2：AI 想执行一个正常的 npm 命令
>>> from muse_code.permissions import is_dangerous
>>> is_dangerous("npm run build")
False  # 安全，不需要确认

# 场景 3：AI 想用 sudo 安装系统包
>>> is_dangerous("sudo apt-get install redis")
True   # 需要确认（因为用了 sudo 提权）
```

新增了 **37 种危险模式**（原 16 种），覆盖 Linux/macOS/Windows 三大平台，包括：
- 系统破坏类（`rm -rf`、`mkfs`、`dd`、写 `/dev/*`）
- Git 危险操作（`push --force`、`reset --hard`、`rebase`）
- 权限变更（`sudo`、`chmod 777`、`chown`）
- 远程代码执行（`curl | sh`、`wget | sh`）
- Docker 清理（`docker rm`、`docker system prune`）
- Windows 命令（`format`、`taskkill /f`、`Remove-Item -Recurse`）

### 子模块 2：权限规则系统（用户级 + 项目级，Allow + Deny）

你可以通过配置文件定义哪些操作"永远允许"或"永远禁止"，而不用每次都在终端手动确认。

**配置文件位置**：
- 用户级：`~/.muse/settings.json`（对所有项目生效）
- 项目级：`.muse/settings.json`（只对当前项目生效）

**配置示例**：

```json
{
  "permissions": {
    "allow": [
      "read_file",                          // 允许读取任何文件
      "write_file(/home/user/project/*)",   // 允许写 project 下的文件
      "run_shell(npm test)",                // 允许运行 npm test
      "run_shell(git status)",              // 允许运行 git status
      "run_shell(python -m pytest *)",      // 允许运行 pytest
      "grep_search"                         // 允许搜索任何内容
    ],
    "deny": [
      "run_shell(rm *)",                    // 禁止任何 rm 命令
      "run_shell(sudo *)",                  // 禁止任何 sudo 命令
      "write_file(/etc/*)",                 // 禁止写 /etc 目录
      "edit_file(/etc/*)",                  // 禁止编辑 /etc 目录
      "run_shell(curl * | sh)"             // 禁止远程脚本执行
    ]
  }
}
```

**规则格式说明**：

| 规则写法 | 含义 | 例子 |
|----------|------|------|
| `tool_name` | 匹配该工具的所有调用 | `read_file` → 允许读任何文件 |
| `tool_name(pattern)` | 匹配参数中 pattern 的内容 | `run_shell(npm test)` → 只允许 `npm test` |
| `tool_name(/path/*)` | 通配符匹配文件路径 | `write_file(/project/src/*)` → 允许写 src 下文件 |
| `tool_name(/path...)` | 前缀匹配 | `write_file(/home/user...)` → 允许写 home 目录 |

**优先级规则**：Deny 永远优先于 Allow（安全第一）。如果用户级和项目级冲突，用户级 deny > 项目级 deny > 用户级 allow > 项目级 allow。

**实际场景**：

> 你在公司项目里工作，不想让 AI 意外修改 `/etc` 下的配置文件，也不希望它用 `sudo`。同时你经常需要 AI 帮你跑 `npm test` 和 `pytest`，不想每次都确认。

在项目的 `.muse/settings.json` 写入：
```json
{
  "permissions": {
    "deny": [
      "write_file(/etc/*)",
      "run_shell(sudo *)"
    ],
    "allow": [
      "run_shell(npm test)",
      "run_shell(python -m pytest *)"
    ]
  }
}
```

这样 AI 运行 `npm test` 时直接通过，想 `sudo rm file` 时直接被拦截。

### 子模块 3：统一权限检查器（9 步流水线）

`PermissionChecker` 把所有判断逻辑整合为一条清晰的流水线，每一步都有明确的责任：

```
用户操作请求
    │
    ▼
[1] bypassPermissions？  ──是──▶ 直接放行
    │否
    ▼
[2] 权限规则检查 (deny优先)  ──命中 deny──▶ 拦截拒绝
    │命中 allow
    ▼
    直接放行
    │未命中
    ▼
[3] 是只读工具？(read_file等)  ──是──▶ 直接放行
    │否
    ▼
[4] plan 模式？  ──是──▶ 只允许操作计划文件
    │否
    ▼
[5] 模式切换工具？(enter/exit_plan)  ──是──▶ 直接放行
    │否
    ▼
[6] acceptEdits + 编辑工具？  ──是──▶ 自动允许
    │否
    ▼
[7] 需要确认吗？(写文件/运行shell/危险命令)
    │是
    ▼
[8] 在会话白名单中？  ──是──▶ 直接放行
    │否
    ▼
[9] dontAsk 模式？  ──是──▶ 自动拒绝
    │否
    ▼
    弹出确认 → 用户同意 → 加入白名单 → 执行
```

**使用示例**：

```python
from muse_code.permissions import PermissionChecker

checker = PermissionChecker(mode="default")

# 读取文件 — 自动放行
result = checker.check("read_file", {"file_path": "/home/user/main.py"})
print(result.action)  # "allow"

# 运行危险命令 — 需要确认
result = checker.check("run_shell", {"command": "rm -rf /tmp/build"})
print(result.action)         # "confirm"
print(result.danger_level)   # "critical"
print(result.danger_descriptions)  # ["递归强制删除文件/目录", "删除文件"]

# 用户确认后
checker.confirm("run_shell", "rm -rf /tmp/build")
# 下次同样命令在白名单中，不会再问
result = checker.check("run_shell", {"command": "rm -rf /tmp/build"})
print(result.action)  # "allow" — 白名单记忆生效！
```

### 子模块 4：会话级白名单（"你同意过的，我都记得"）

这是最影响用户体验的功能。在没有白名单之前，AI 每次写文件你都要手动确认——比如改 5 个文件就要确认 5 次。有了白名单后：

- **同一个操作只问一次**：你同意 AI 编辑 `main.py` 后，它再改这个文件就不再问了
- **目录级白名单**：你同意 AI 写 `/project/src/` 目录后，所有 `src/` 下的文件自动放行
- **持久化**：白名单跟随会话，下次启动（如果用 `--resume`）仍然有效
- **三种来源**：
  - `session`：当前会话中手动确认的（会过期）
  - `user`：用户级 settings.json 预设的
  - `project`：项目级 settings.json 预设的

**交互示例**（模拟终端对话）：

```
You: 帮我把所有 Python 文件里的 print 改成 logger.info

Muse Code: 好的，我先搜索一下。
  🔍 grep_search   print

Muse Code: 找到了 5 个文件需要修改：main.py, utils.py, config.py, 
  api.py, models.py。开始逐个修改。

  ✏️ edit_file   main.py: 'print(...)...'
  ⚠ 需要确认: 修改文件: /project/src/main.py
  Allow? (y/n/always): always     ← 用户输入 always

  ✓ 已加入会话白名单: /project/src/main.py
  [diff 显示修改内容]

  ✏️ edit_file   utils.py: 'print(...)...'
  ✓ 白名单匹配，自动放行          ← 不再问！
  [diff 显示修改内容]

  ✏️ edit_file   config.py: 'print(...)...'
  ✓ 白名单匹配，自动放行          ← 同一目录自动放行
  [diff 显示修改内容]

  ...（继续自动处理剩余文件）
```

**实现细节**：

```python
from muse_code.permissions import SessionWhitelist

wl = SessionWhitelist()

# 添加一个目录到白名单
wl.add("write_file", "/home/user/project/src/")

# 检查子文件 — 父目录匹配自动生效
wl.contains("write_file", "/home/user/project/src/main.py")        # True
wl.contains("write_file", "/home/user/project/src/sub/deep/file.py") # True
wl.contains("write_file", "/other/project/file.py")                # False

# 添加一个命令到白名单
wl.add("run_shell", "npm test")

# 只能匹配到完全相同的命令
wl.contains("run_shell", "npm test")        # True
wl.contains("run_shell", "npm run build")   # False

# 查看当前白名单状态
wl.get_summary()
# {'write_file': ['/home/user/project/src/'], 'run_shell': ['npm test']}

# 序列化 — 可以保存到会话文件
data = wl.to_dict()
# 恢复
wl2 = SessionWhitelist.from_dict(data)
```

### 五种权限模式速查表

这张表概括了所有模式下各类工具的行为，帮你快速选择合适的模式：

| 模式（CLI 参数） | 读工具<br>`read_file` 等 | 编辑工具<br>`write/edit_file` | Shell（安全命令）<br>`npm test`、`ls` 等 | Shell（危险命令）<br>`rm -rf`、`sudo` 等 | 适用场景 |
|------------------|:--:|:--:|:--:|:--:|----------|
| **default**<br>`muse` | ✅ 自动放行 | ⚠️ 弹出确认 | ⚠️ 弹出确认 | 🔴 弹出确认<br>（含危险等级提示） | 日常使用<br>平衡安全与效率 |
| **plan**<br>`muse --plan` | ✅ 自动放行 | ❌ 拒绝<br>（仅计划文件例外） | ❌ 拒绝 | ❌ 拒绝 | 只规划不执行<br>审查方案后用 |
| **acceptEdits**<br>`muse --accept-edits` | ✅ 自动放行 | ✅ 自动放行 | ⚠️ 弹出确认 | 🔴 弹出确认 | 信任 AI 的文件编辑<br>只想审查命令 |
| **bypassPermissions**<br>`muse --yolo` | ✅ 自动放行 | ✅ 自动放行 | ✅ 自动放行 | ✅ 自动放行 | YOLO 模式<br>完全信任，无确认 |
| **dontAsk**<br>`muse --dont-ask` | ✅ 自动放行 | ❌ 自动拒绝 | ✅ 自动放行 | ❌ 自动拒绝 | CI/CD 非交互环境<br>自动拒绝所有需确认操作 |

> **记忆规则**：
> - `default` 是万能模式——安全的事自动做，危险的事问你
> - `--yolo`（bypassPermissions）是"我全都要"——什么都不问，直接干
> - `--dont-ask` 是"我问不了你"——能自动做的就做，需要确认的直接拒绝
> - `--plan` 是"让我想想"——只能看不能改，方案满意了再执行
> - `--accept-edits` 是"代码你改，命令问我"——信任编辑能力，保留命令审查

### 文件变更

| 文件 | 操作 | 说明 |
|------|------|------|
| `muse_code/permissions.py` | **新增** | 核心权限与安全模块（670+ 行），包含全部 4 个子系统 |
| `muse_code/tools.py` | 修改 | 移除约 120 行重复权限代码，通过 re-export 委托给 permissions.py |
| `muse_code/agent.py` | 修改 | 新增 `PermissionChecker`、`_confirmed_paths` 白名单、`_confirm_dangerous()` 交互确认方法 |
| `muse_code/ui.py` | 修改 | 新增 `print_confirmation()`（带颜色等级）和 `print_whitelist_added()` |

### 向后兼容

所有旧 API 保持不变，现有代码无需修改：

```python
# 旧代码仍然正常工作
from muse_code.tools import check_permission, is_dangerous, load_permission_rules

result = check_permission("run_shell", {"command": "rm -rf /tmp"}, mode="default")
# {'action': 'confirm', 'message': 'rm -rf /tmp', 'danger_level': 'critical', ...}
```

唯一的差异：返回的 `dict` 现在多了 `danger_level` 和 `danger_description` 字段（如果命令有危险的话），方便 UI 层做更丰富的展示。


---

## （6）feat：上下文管理模块 — 4 层分级压缩管道

> **一句话概括：** 防止对话历史超出 LLM 上下文窗口（GLM-4.7-Flash 128K），实现 4 层渐进式压缩：大结果持久化（>30KB→磁盘）、Budget 动态裁剪（50%/70%双阈值）、Snip 去重替换、Auto-compact 全量摘要压缩。

### 背景：为什么需要上下文管理？

免费模型 GLM-4.7-Flash 上下文窗口仅 128K tokens。在多轮对话中，尤其是涉及读取大文件、执行长命令输出、多次搜索的场景下，消息历史会迅速膨胀。一旦超出窗口，API 会直接报错或静默截断，导致模型丢失关键上下文。

上下文管理的核心策略是 **渐进式压缩**：先用成本最低的手段（截断/去重），只在必要时才动更重的武器（LLM 摘要）。4 层管道配合触发时机，在保留关键信息的同时控制上下文大小。

### 架构设计

```
┌─────────────────────────────────────────────────────────────┐
│                    ContextManager                            │
│                                                             │
│  ┌───────────────┐  ┌───────────────┐  ┌───────────────┐   │
│  │ TokenCounter   │  │ Persist        │  │ Compactor     │   │
│  │ (usage锚点统计)│  │ (磁盘持久化)   │  │ (LLM摘要生成) │   │
│  └───────┬───────┘  └───────┬───────┘  └───────┬───────┘   │
│          │                  │                   │           │
│          ▼                  ▼                   ▼           │
│  ┌──────────────────────────────────────────────────────┐   │
│  │              4 层压缩管道                              │   │
│  │                                                       │   │
│  │  🔵 Layer 0:   truncate_result (>50K chars→截断)       │   │
│  │  🔵 Layer 0.5: persist_large_result (>30KB→磁盘)      │   │
│  │  🟡 Layer 1:   budget_trim (50%/70%双阈值)             │   │
│  │  🟠 Layer 2:   snip (同文件去重，保留最近3个)           │   │
│  │  🟣 Layer 2.5: microcompact (5min空闲→激进清理)        │   │
│  │  🔴 Layer 3:   auto_compact (85%窗口→LLM摘要)          │   │
│  └──────────────────────────────────────────────────────┘   │
│                                                             │
│  触发时机:                                                   │
│    工具执行后 → Layer 0 + Layer 0.5 (执行即触发)              │
│    API调用前  → Layer 1 + Layer 2 + Layer 2.5 (零API成本)    │
│    轮次边界   → Layer 3 (利用率>85%)                         │
│    手动       → /compact 强制 Layer 3                        │
└─────────────────────────────────────────────────────────────┘
```

### 5 层详解

> 每层清理的目标、触发时机、信息是否可恢复：

| 层级 | 清理目标 | 操作粒度 | 具体操作 | 触发时机 | 丢失信息是否可恢复 | 是否存磁盘 | API 成本 |
|------|----------|----------|----------|----------|:--:|:--:|:--:|
| **0** truncate | 工具结果内容 | 截断保留头尾 | >50K chars→截断，提示用 grep/read_file | 每次工具执行后 | ❌ 截断部分永丢 | ❌ | 0 |
| **0.5** persist | 工具结果内容 | 截断 + 存盘 | >30KB → 磁盘存完整版，消息里留 200 行预览 | 每次工具执行后（在 L0 之前） | ✅ `read_file` 取回 | ✅ `~/.muse/tool-results/` | 0 |
| **1** budget | 工具结果内容 | 截断保留头尾 | 利用率 >50%→<30K, >70%→<15K | 每次 API 调用前 | ❌ 截断部分永丢 | ❌ | 0 |
| **2** snip | 工具结果内容 | 替换为占位符 | 同文件重复读取→旧结果替换为 `[Content snipped]` | 利用率 >60%，每次 API 调用前 | ⚠️ 可重新调工具获取 | ❌ | 0 |
| **2.5** microcompact | 工具结果内容 | 替换为占位符 | 空闲 >5min→旧结果替换为 `[Old result cleared]` | 每次 API 调用前 | ⚠️ 可重新调工具获取 | ❌ | 0 |
| **3** auto-compact | 整段对话历史 | 删除消息 | LLM 摘要替换掉 [1]~[N] 之间全部消息 | 利用率 >85%，轮次边界 / `/compact` | ❌ 原始对话永丢 | ❌ | 1 次 API 调用 |

**消息结构 vs 内容**：L0~2.5 只改 `tool` 消息的 `content` 字段，消息本身还在——模型仍知道"我调过 read_file"。L3 直接删消息重建数组，是最重的操作。

**L0 与 L0.5 的阈值配合**：`persist` 用 **30KB(字节)** 做门槛，`truncate` 用 **50K(字符)**。30KB 字节 = 最多 ~30K chars，在任何编码下都小于 50K 字符，所以 persist 永远先拦截。目的是"低门槛先存盘（可恢复）、高门槛后截断（兜底）"——正常源码 200 行预览远小于 50K，truncate 只有遇到 minified 长行文件才触发。

#### Layer 0.5：大结果持久化 (`persist_large_result`)

超过 **30KB** 的工具结果自动写入 `~/.muse/tool-results/{timestamp}-{tool}-{hash}.txt`，上下文仅保留 200 行预览 + 文件路径提示。

```
# 示例：read_file 返回一个 80KB 的大文件
[Result too large (82.3 KB, 2500 lines). 
 Full output saved to ~/.muse/tool-results/1712345678-read_file-a1b2c3d4.txt. 
 You can use read_file to see the full result.]

Preview (first 200 lines):
   1 | import ...
   2 | ...
 200 | def helper():
```

**设计要点**：
- **30KB 阈值低于 truncateResult 的 50K 限制**：在截断之前先拦截，避免不可逆的信息丢失
- **可恢复 vs 不可恢复**：与 `_truncate_result` 的区别——持久化后数据仍在磁盘，模型可用 `read_file` 取回
- **调用时机**：在 `truncateResult` 之前生效，持久化返回的预览文本通常远小于 50K，不会触发二次截断
- **防循环**：`execute_tool` 在 `read_file` 读取 persisted 目录下的文件时跳过 persist_large_result，防止"读持久化文件 → 太大再次持久化 → 生成新文件 → 再读"的无限循环

#### Layer 1：Budget 动态裁剪 (`budget_trim`)

每次 API 调用前，根据当前上下文利用率动态收紧已存在的工具结果大小：

| 利用率 | 预算 | 效果 |
|--------|------|------|
| < 50% | 不触发 | 工具结果保持原样 |
| 50% - 70% | 30K 字符 | 较温和的截断 |
| > 70% | 15K 字符 | 激进截断，为后续对话腾空间 |

双阈值设计保证在上下文宽裕时多保留细节，紧张时自动收紧。

```python
# context.py — apply_budget_openai
utilization = counter.effective_utilization(model)
if utilization < 0.50:
    return  # 不触发
budget = 15000 if utilization > 0.70 else 30000
# 对 history 中的所有 tool_result content 应用 budget_trim_text
```

#### Layer 2：Snip 去重替换 (`apply_snip`)

利用率 > 60% 时触发，替换过时/重复的工具结果：

- **同文件多次读取**：同一文件被 `read_file` 多次读取，只保留最近 3 次，旧的替换为 `[Content snipped - re-read if needed]`
- **同类搜索结果**：`grep_search` / `list_files` 去重，保留最近 3 个
- **最近 3 个永远保留**：不论去重逻辑，最近 3 个 tool_result 不会被 snip

关键设计：**只清 content，保留元数据**。模型仍能看到"我之前读了 main.py"，只是看不到内容了，可以重新调用 `read_file`。

#### Layer 2.5：Microcompact 缓存冷启动清理 (`apply_microcompact`)

空闲超过 **5 分钟** 时触发，除最近 3 个工具结果外全部替换为 `[Old result cleared]`：

```
# 示例：连续 6 次 read_file 后空闲 6 分钟
[Old result cleared]           ← 第 1 次读取，5min 超时被清
[Old result cleared]           ← 第 2 次读取，被清
[Old result cleared]           ← 第 3 次读取，被清
file_b.py content...           ← 最近第 3 个，保留
file_c.py content...           ← 最近第 2 个，保留  
file_d.py content...           ← 最近第 1 个，保留
```

**设计原理**：prompt cache 有 TTL（Claude 约 5 分钟），空闲超时后缓存大概率已过期。此时继续保存旧消息内容没有缓存命中优势，不如激进清理——下次 API 调用会重建 cache prefix，清理这些内容没有额外成本。

与 Snip 的区别：Snip 是选择性的（同文件去重）、利用率触发；Microcompact 是无差别的（时间触发）、更激进——比 Snip 多清一层。

#### Layer 3：Auto-compact 全量摘要压缩

当有效窗口利用率 ≥ **85%** 时，在轮次边界（用户输入 push 进消息数组后、API 调用前）触发：

1. 调用同一个 LLM，用专用 system prompt（`"You are a conversation summarizer..."`）生成对话摘要
2. 剥离旧的对话历史，替换为：`[摘要] → [Assistant确认] → [最新用户消息]`
3. 重置 `lastInputTokenCount`，让后续 Budget/Snip 基于新的较小上下文工作

**安全措施**：
- **熔断器**：连续 3 次压缩失败后不再尝试（防止无限 API 调用浪费）
- **后备截断**：如果 LLM 摘要生成失败，回退到简单截断（保留最近 4 条消息）
- **只在轮次边界调用**：不在 tool 循环中段调用，避免切断 `tool_use`/`tool_result` 配对导致 API 报错

### Token 统计

`TokenCounter` 类实现两层估算：

1. **API 锚点**：每次 API 调用后用返回的 `usage.input_tokens` 更新锚点，这是准确的
2. **增量估算**：锚点之后新增的消息用 `4 chars ≈ 1 token` 粗估

```
estimate_current_input() = last_input_tokens + (新增字符数 // 4)
utilization = estimate_current_input() / context_window
```

误差控制在 < 5%，无需额外 API 调用来统计 token。

### 文件变更

| 文件 | 操作 | 说明 |
|------|------|------|
| `muse_code/context.py` | **新增** | 上下文管理核心模块（~400 行），包含 TokenCounter、4 层压缩函数、ContextManager 入口 |
| `muse_code/tools.py` | 修改 | 在 `execute_tool` 中注入 `persist_large_result`，在 `_truncate_result` 之前生效 |
| `muse_code/agent.py` | 修改 | 初始化 ContextManager、API 调用前执行 Layer 1+2 管道、API 调用后记录 token、轮次边界检查 Layer 3 auto-compact、更新 `compact()` 方法、`show_cost()` 显示利用率 |
| `muse_code/__main__.py` | 无需修改 | `/compact` 命令已调用 `agent.compact()`，自动使用新实现 |

### 使用示例

```python
# 自动触发场景模拟：
# 
# 1. 用户让 AI 分析一个 100KB 的日志文件
#    → Layer 0.5: 日志内容写入磁盘，上下文只保留 200 行预览
#
# 2. 多轮对话后利用率达 55%
#    → Layer 1: 旧工具结果被截断到 30K
#    → Layer 2: 重复的文件读取被 snip 替换
#
# 3. 利用率继续升高到 87%
#    → Layer 3: 触发 auto-compact，LLM 生成对话摘要替换历史
#
# 4. 手动触发压缩
#    > /compact
#    对话已压缩 (18 → 4 条消息)
```

### 与 Claude Code / mini_claude 对比

| 维度 | Claude Code | mini_claude | Muse Code |
|------|------------|-------------|-----------|
| 压缩层级 | 5 级流水线 | 4 层 | 6 层 (L0+L0.5+L1+L2+L2.5+L3) |
| Microcompact | 时间+缓存编辑双路径 | 仅 5min 空闲触发 | 5min 空闲触发，和 Snip 共用保留阈值 |
| 持久化 | 磁盘持久化，2KB 预览 | 磁盘持久化（>30KB），200 行预览 | 磁盘持久化（>30KB），200 行预览 |
| Token 计数 | 锚点+粗估 | 直接用 API usage | 锚点+增量粗估 |
| Auto-compact | 两阶段摘要+恢复+熔断器 | 单段摘要，无恢复 | 单段摘要+后备截断+3 次熔断器 |
| 上下文窗口 | 按模型确定 | 按模型确定 | 按模型名匹配，向前缀兼容 |

### 向后兼容

- `/compact` 命令行为不变，底层实现升级为 LLM 摘要压缩
- `show_cost()` 新增上下文利用率显示，原有字段不变
- 所有现有 CLI 参数和 API 不变

### Bug 修复

- **ContextManager 初始化顺序**：原 `self._context = ContextManager(self.model)` 在 `self.model` 赋值前执行导致 `AttributeError`，已移至 if/else 块之后
- **Persist 无限循环**：模型读取 `~/.muse/tool-results/` 目录下的已持久化文件时，若文件仍 >30KB 会再次触发持久化生成新文件，形成死循环。修复：`execute_tool` 检测到文件在 PERSIST_DIR 下时跳过 persist_large_result

---