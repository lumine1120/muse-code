# 开发历史记录

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

---
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
│  │  🟡 Layer 2:   snip (同文件去重，保留最近3个)           │   │
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

下面是一个完整的会话演示，展示每层压缩在什么时候触发、对消息数组做了什么。

```
# ── 第 1 轮：读取一个大日志文件 ──

> 帮我分析 /var/log/app.log 的错误
Muse Code
  📖 read_file /var/log/app.log

  [Result too large (82.3 KB, 2500 lines). Full output saved to 
  ~/.muse/tool-results/1712345678-read_file-a1b2c3d4.txt. 
  You can use read_file to see the full result.]

  Preview (first 200 lines):
    1 | 2024-01-01 INFO  Server started
    2 | 2024-01-01 DEBUG Loading config...
  ...（省略中间内容）...
  200 | 2024-01-01 WARN  Connection pool low

Muse Code: 从预览中看到开头有正常启动日志，让我用 grep_search 
  精确定位错误行。
  🔍 grep_search ERROR
  Found 15 matches:
    app.log:234  ERROR  Database timeout
    app.log:567  ERROR  API rate limit exceeded
    ...

Muse Code: 有两个主要错误类型：数据库超时和 API 限流。需要修复...
```

**在此期间消息数组的变化：**

```
# read_file 返回前，Layer 0.5 persist 拦截：
  raw_result = "1 | ... 2500 lines ..."   # 82KB 原始内容
  → persist_large_result 存盘
  → 返回 200 行预览 （~8KB）
  → Layer 0 truncate 检查：8KB < 50K → 不触发
  → 最终放入上下文：8KB 预览文本

# /cost 查看当前状态：
  Token: 12500 in / 800 out
  消息数: 6
  上下文利用率: 11.6%
```

```
# ── 第 5 轮：多次读写后利用率上升 ──

> 把 utils.py 的超时时间改成 10 秒
Muse Code: 好的，让我先确认当前超时值。
  📖 read_file utils.py
  ... （工具结果放回上下文）...

Muse Code
  ✏️ edit_file utils.py
  @@ -42,3 +42,3 @@
  -TIMEOUT = 5
  +TIMEOUT = 10

> /cost
  Token: 62000 in / 3500 out
  消息数: 38
  上下文利用率: 57.4%

# ← 利用率 > 50%，Layer 1 budget 开始生效：
# 旧 tool 消息被截断到 30K 字符，头尾保留。
# 利用率 > 60%，Layer 2 snip 也开始工作：
# 同一个文件读了 5 次，旧 4 次被替换为 [Content snipped]
```

```
# ── 第 8 轮：上下文接近窗口上限 ──

> 帮我看看这个最新的 error log
Muse Code: 上下文窗口即将填满，正在压缩对话...
  # ← Layer 3 auto-compact 触发（利用率 87%）
  # 内部流程：
  #   1. sideQuery → LLM 生成摘要：
  #      "User is debugging a production app with database timeout 
  #       and API rate limit issues. Fixed TIMEOUT in utils.py from 
  #       5s to 10s. Explored connection pool config in pool.py..."
  #   2. 旧消息数组（38 条）→ 新数组：
  #      [system, summary_user, summary_assistant, latest_user]
  #   3. last_input_tokens 重置为 0

对话已压缩 (38 → 4 条消息)

Muse Code: 好的，让我查看最新的错误日志...
  📖 read_file error.log
  ...

> /cost
  Token: 8500 in / 600 out
  消息数: 6
  上下文利用率: 7.9%
```

**消息数组压缩前后对比：**

```
# 压缩前 (38 条):
[system, user "分析日志", assistant "...", tool "1|...", 
 assistant "...", user "修复超时", assistant "...", tool "1|...",
 ... 30 多条 ...
 user "看看最新 error log"]

# 压缩后 (4 条):
[system,
 user "[Previous conversation summary]
      User is debugging... Fixed TIMEOUT in utils.py from 5→10s...",
 assistant "Understood. I have the context... How can I continue helping?",
 user "看看最新 error log"]
```

```
# ── 手动压缩 ──

> /compact
  对话已压缩 (24 → 4 条消息)

# 无论利用率是否达到 85%，/compact 直接强制触发 Layer 3
```

```
# ── Microcompact 场景（空闲 5 分钟后） ──

# 用户去开会了，回来继续：
> 继续刚才的分析，把 pool config 也改了
Muse Code: （Pipeline 检测到 last_api_call_time 超过 5 分钟）
  # ← Layer 2.5 microcompact 触发：
  # 旧 tool 结果 → [Old result cleared]
  # 最近 3 个保留
  
Muse Code
  📖 read_file pool.py
  ...
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

## （7）feat：记忆系统 — 4 类型记忆 + sideQuery 语义召回 + 异步预取

> **一句话概括：** 给 Agent 加一个"会越用越懂你"的持久记忆库——把用户偏好、纠正反馈、项目状态、外部资源等不可推导信息存成本地 markdown 文件，用 sideQuery 做语义召回 + 异步预取，零阻塞地把相关记忆注入对话上下文。

### 背景：为什么需要记忆系统？

会话级 Agent 有个根本痛点——**每次重启都"失忆"**。你已经告诉它三次"不要在末尾总结"，下次启动它还是会总结。如果只是单纯把所有历史塞进 system prompt，token 又会被无关信息撑爆。

记忆系统的本质是：**用文件做长期存储，用语义召回做选择性注入**。下面这些信息适合记下来：

- 用户偏好（"我用 Python，不要写注释"）
- 行为反馈（"上次纠正过你不要乱重构"）
- 项目状态（"Q3 的目标是迁移认证模块"）
- 外部资源（"CI 仪表盘在 ci.example.com"）

而代码、git 历史、可推导的项目结构这些**不要存**——读代码或 `git log` 就能拿到，记下来只会过时漂移。

### 架构设计

```
┌────────────────────────────────────────────────────────────┐
│                     Memory System                           │
│                                                             │
│  ~/.muse/projects/{sha256(cwd)[:16]}/memory/                │
│  ├── MEMORY.md                       ← 索引（注入 system）   │
│  ├── user_prefers_concise.md         ← 偏好                │
│  ├── feedback_no_summary.md          ← 反馈                │
│  ├── project_auth_q3.md              ← 项目                │
│  └── reference_ci_dashboard.md       ← 资源                │
│                                                             │
│  双轨加载策略：                                              │
│                                                             │
│  ┌─────────────────────────────────────┐                    │
│  │ 轨道 1：System Prompt（每会话固定）  │                    │
│  │ MEMORY.md 索引 → 让模型知道有什么    │                    │
│  └─────────────────────────────────────┘                    │
│                                                             │
│  ┌─────────────────────────────────────┐                    │
│  │ 轨道 2：sideQuery 语义召回（按需）   │                    │
│  │ 用户输入 → 异步预取（与首次API并行）  │                    │
│  │   ↓                                  │                    │
│  │ 让小模型从清单选 ≤5 条相关记忆        │                    │
│  │   ↓                                  │                    │
│  │ 包装 <system-reminder> 注入用户消息  │                    │
│  └─────────────────────────────────────┘                    │
└────────────────────────────────────────────────────────────┘
```

### 核心设计点

#### 1. 4 种封闭分类（不允许自由标签）

| 类型 | 记什么 | 何时记 |
|------|--------|--------|
| **user** | 用户身份、偏好、知识背景 | 了解到用户角色或偏好时 |
| **feedback** | 用户的纠正和肯定（必须含 Why + How to apply） | 用户纠正/肯定某个行为时 |
| **project** | 进展、目标、决策、截止日期 | 了解到项目动态时 |
| **reference** | 外部系统的定位（URL、工具、仪表盘） | 了解到外部资源时 |

为什么不允许自由标签？标签膨胀（"important"、"misc"、"tmp"...）会让召回时模糊匹配——4 种封闭类型保证召回精度。

#### 2. 项目隔离（同目录共享，跨目录隔离）

记忆目录：`~/.muse/projects/{sha256(cwd)[:16]}/memory/`

哈希 cwd 的结果做命名空间：
- 同一个项目目录无论何时启动 Agent 都进同一个记忆库
- 切换项目目录自动隔离，不会污染
- 截前 16 字节够用（碰撞概率近乎零），又不至于路径太长

#### 3. 文件 + 索引双层结构

每条记忆是独立 markdown 文件（YAML frontmatter + 正文）：

```markdown
---
name: 不要在末尾总结
description: 用户明确要求省略总结段落
type: feedback
---
**Why:** 用户觉得总结浪费时间，更喜欢直接看 diff。
**How to apply:** 完成任务后直接结束，不要加"以上是..."段落。
```

`MEMORY.md` 是"目录"，每条记忆一行链接：

```markdown
# Memory Index

- **[不要在末尾总结](feedback_no_summary.md)** (feedback) — 用户明确要求省略总结段落
- **[Q3 认证迁移](project_auth_q3.md)** (project) — 8 月底前完成 OAuth 迁移
```

写入触发：`write_file` 检测路径属于 memory_dir 自动重建索引——**模型只管写新记忆，索引零维护成本**。

#### 4. 双截断防御（曾踩过的坑）

`load_memory_index()` 同时做行截断和字节截断：
- **MAX_INDEX_LINES = 200**：正常防护，按完整条目截断
- **MAX_INDEX_BYTES = 25KB**：异常防御，曾踩坑 197KB 内容塞在 200 行内的真实案例

单维度限制不够，两个维度都设上限最稳。

#### 5. sideQuery 语义召回（核心创新）

传统关键词搜索匹配不到"用户问'我之前说过怎么部署吗' → 项目部署清单记忆"这种语义关联。所以引入 **sideQuery**：

```
用户查询  →  把所有记忆的"目录"喂给小模型  →  让模型选 ≤5 条相关记忆
                                                ↓
                                       按需读完整内容注入对话
```

**sideQuery 是个"侧通道"模型调用**：传 system + user_message，返回纯文本。不带工具、不进入主对话历史，专门做记忆筛选这种辅助任务，不污染主上下文。

#### 6. 异步预取（关键性能优化）

如果用户每次输入都要等 sideQuery 选完记忆才能发主请求，每轮多一次 API 往返延迟。所以做**异步预取**：

```
用户按下回车的瞬间：
  ┌──────────────────────────────────────────┐
  │ 主线：用户消息 → 主模型 API（首轮调用）   │
  │ 侧线：sideQuery 异步召回（与主线并行）    │
  └──────────────────────────────────────────┘
                          ↓
                  下一轮主循环开始时
                          ↓
                  非阻塞轮询：settled 了吗？
                  是 → 注入到最后一条 user message
                  否 → 跳过，下一轮再查
```

延迟成本：**0 毫秒**（与主调用并行）。

#### 7. 三个触发门控（防止无意义调用）

```python
def start_memory_prefetch(query, ...):
    if not re.search(r"\s", query.strip()):  # 单词查询不触发
        return None
    if session_memory_bytes >= 60 * 1024:    # 会话累计已超 60KB
        return None
    if no .md files in memory_dir:           # 还没存过任何记忆
        return None
```

单词查询跳过的原因：sideQuery 缺乏上下文做不出准确选择——"bug" 这种词配合所有记忆都"看起来相关"，全选了反而拖累主上下文。

#### 8. 时效警告（防止陈旧记忆当事实）

```python
def memory_freshness_warning(mtime_ms):
    days = (now - mtime_ms) / 86400_000
    if days > 1:
        return f"This memory is {days} days old. Memories are point-in-time observations, "
               "not live state — descriptions of code behavior may be stale."
```

记忆是**时间点观察**，不是实时状态。"上周这个文件这样写"过几天可能就改了。每条召回的旧记忆都附带过期警告，让模型在引用前主动验证。

#### 9. 已展示去重（防打扰）

```python
self._already_surfaced_memories: set[str]  # 本会话已经注入过的记忆路径
```

同一条记忆在一个会话内只展示一次。避免用户问相关问题时反复看到同一条提示。

### 注入格式：`<system-reminder>`

召回的记忆包装成这个标签注入到下一条 user 消息里：

```
<system-reminder>
This memory is 5 days old. Memories are point-in-time observations...

Memory: /Users/.../feedback_no_summary.md:

---
name: 不要在末尾总结
type: feedback
---
**Why:** 用户觉得浪费时间。
**How:** 完成任务直接结束。
</system-reminder>
```

为什么用 user 消息嵌入而不是 system role：
- **时序对**：召回是用户输入触发的，逻辑上属于"用户上下文增强"
- **兼容性**：OpenAI/Anthropic 都允许 user 消息嵌套提示
- **显眼度**：模型对 `<system-reminder>` 标签敏感度较高

### 文件变更

| 文件 | 操作 | 说明 |
|------|------|------|
| `muse_code/frontmatter.py` | **重写** | 实现 YAML frontmatter 解析/序列化（之前是占位空 dict） |
| `muse_code/memory.py` | **重写** | 完整记忆系统（~400 行）：增删改查、索引重建、头部扫描、sideQuery 召回、异步预取 |
| `muse_code/agent.py` | 修改 | 集成预取启动 + 非阻塞消费 + 已展示去重 + sideQuery 构造器（双后端） |
| `muse_code/tools.py` | 修改 | `_auto_update_memory_index` 委托给 memory 模块，单一数据源 |
| `muse_code/__main__.py` | 修改 | 新增 REPL 命令 `/memory` 列出当前所有记忆 |

### 使用示例

下面演示一次完整的"存 → 召回 → 自动生效"流程，展示消息数组在每个步骤的实际状态。

```
# ═══════ 第 1 次会话 ═══════

> 你好，我习惯用 Python 3.12+ 写代码，回复时不要带类型注解，
  也不要写 docstring，直接给代码就行
```

**（1）System Prompt 固定注入**

每次会话 system prompt 都会包含一段记忆系统说明。如果还没存过任何记忆，尾部是空的：

```
# System Prompt 相关片段（部分）:
...
# 记忆系统
你拥有一个持久的、基于文件的记忆系统。...
（尚未保存任何记忆。）
```

**（2）模型识别偏好并保存**

模型在对话中检测到明确偏好后，主动调用 `write_file` 保存：

```
📖 write_file ~/.muse/projects/a1b2.../memory/feedback_no_type_annotations.md
---
name: 不使用类型注解和docstring
description: 用户偏好Pythonic代码，不需要类型注解和docstring
type: feedback
---
用户要求代码中不要添加类型注解和docstring，直接给出干净代码。

**Why:** 用户认为Python的类型系统和docstring影响可读性，
更喜欢简洁直接的代码风格。
**How to apply:** 写Python代码时省略所有类型注解和docstring，
只在用户明确要求时才添加。
---
```

**（3）MEMORY.md 索引自动重建**

写入完成后 `_auto_update_memory_index` 钩子自动触发，重建索引：

```markdown
# Memory Index

- **[不使用类型注解和docstring](feedback_no_type_annotations.md)** (feedback) — 用户偏好...
```

```
> /memory
共 1 条记忆，目录：~/.muse/projects/a1b2.../memory
  [feedback] 不使用类型注解和docstring — 用户偏好Pythonic代码
```

**（4）@include CLAUDE.md 集成**

用户也可以手动引用记忆（新版已支持 @include 指令）——但大多数场景模型会自动处理。以下是侧边对话：

```
> 记住：CI 地址是 https://ci.mycompany.com/dashboard/app

📖 write_file ~/.muse/.../memory/reference_ci_dashboard.md
---
name: CI仪表盘地址
description: 项目CI系统的URL
type: reference
---
https://ci.mycompany.com/dashboard/app
```

**（5）系统提示更新**

写入后下一次 API 调用时系统提示会自动包含新索引：

```
# System Prompt 相关片段:
...
## 当前记忆索引

- **[不使用类型注解和docstring](feedback_no_type_annotations.md)** (feedback) — 用户偏好...
- **[CI仪表盘地址](reference_ci_dashboard.md)** (reference) — 项目CI系统的URL
```

```
# ═══════ 重启程序，第 2 次会话 ═══════

> 帮我写个排序函数
```

**（6）异步预取启动（与主调用并行，零延迟）**

用户按回车的瞬间，两条路径并行启动：

```
┌─ 路径 1（主线）────────────────────┐
│ POST /chat/completions            │
│ messages: [                       │
│   {role:"system", content:"..."}, │
│   {role:"user", content:          │
│     "帮我写个排序函数"}            │
│ ]                                  │
└────────────────────────────────────┘

┌─ 路径 2（sideQuery 侧线）─────────┐
│ POST /chat/completions             │
│ messages: [                        │
│   {role:"system", content:         │
│     "你正在为AI编程助手选择记忆..." │
│   },                               │
│   {role:"user", content:           │
│     "Query: 帮我写个排序函数\n\n"   │
│     "Available memories:\n"        │
│     "- [feedback] feedback_no_..." │
│     "- [reference] reference_ci..."│
│   }                                │
│ ]                                  │
└────────────────────────────────────┘
```

sideQuery 返回结果：

```json
{"selected_memories": ["feedback_no_type_annotations.md"]}
```

**（7）主循环消费预取结果**

下一轮 API 调用前，检查 `memory_prefetch.settled == True`，将召回结果注入：

```
# 注入后的消息数组（最后一条 user 消息被增强）：

messages = [
  {role: "system", content: "你是Muse Code...\n\n## 当前记忆索引\n\n..."},
  {role: "user", content: "帮我写个排序函数\n\n

<system-reminder>
Memory (saved today): ~/.muse/.../feedback_no_type_annotations.md:

---
name: 不使用类型注解和docstring
type: feedback
---
**Why:** 用户认为Python...影响可读性。
**How to apply:** 写Python代码时省略所有类型注解和docstring。
</system-reminder>"},
]
```

**（8）模型看到记忆并遵循偏好**

```
Muse Code
def sort_users(users):
    return sorted(users, key=lambda u: u.name)

# ← 无类型注解、无 docstring，符合用户偏好
```

**（9）时效警告场景**

如果记忆是 5 天前保存的，注入会附带 warning：

```
<system-reminder>
This memory is 5 days old. Memories are point-in-time observations,
not live state — descriptions of code behavior may be stale.
Verify against current code before treating as fact.

Memory: ~/.muse/.../project_auth_q3.md: ...

---
name: Q3认证迁移
type: project
---
8月底前把登录模块从Session迁移到OAuth2
</system-reminder>
```

模型看到警告字眼会意识到"这个信息可能过时了"，在遵循前主动验证。

**（10）预算耗尽自动停止**

当累计召回超过 60KB 后，后续查询不再触发预取：

```
# 假设之前已召回 4 条总计 68KB 的记忆（超额），
# 再次输入 "帮我看看那个登录模块"
# → start_memory_prefetch 检测 session_memory_bytes ≥ 60KB → 返回 None
# → 不会再浪费 API 调用做无效召回
```

**（11）同会话去重**

同一记忆在一个会话里只展示一次。用户多次问相关问题时不会反复看到：

```python
self._already_surfaced_memories = {
    "/Users/../feedback_no_type_annotations.md",  # 已经注入过
    "/Users/../reference_ci_dashboard.md",        # 已经注入过
}
# 下次查询候选会跳过这两条
```

### 与 Claude Code / mini_claude 对比

| 维度 | Claude Code | mini_claude | Muse Code |
|------|------------|-------------|-----------|
| 记忆类型 | 4 种封闭分类 | 4 种封闭分类 | 4 种封闭分类 |
| 项目隔离 | 哈希 cwd | 哈希 cwd | 哈希 cwd |
| 索引机制 | MEMORY.md 自动重建 | MEMORY.md 自动重建 | MEMORY.md 自动重建 |
| 召回方式 | sideQuery + 异步预取 | sideQuery + 异步预取 | sideQuery + 异步预取 |
| 时效警告 | 有 | 有 | 有（中文化） |
| 双截断 | 200 行 + 25KB | 200 行 + 25KB | 200 行 + 25KB |
| 单文件预算 | 4KB | 4KB | 4KB |
| 会话预算 | 60KB | 60KB | 60KB |
| 追加 thinking 召回 | 有 | 无 | 无 |
| 多目录支持 | 有（org-level） | 无 | 无 |

### 设计哲学

1. **基于文件**：记忆 = `.md` 文件。任何编辑器能查、能改、能 git 管理，与 Agent 解耦。
2. **封闭分类**：4 种类型，禁止自由标签——保证召回精度。
3. **只记不可推导**：代码、git 历史、CLAUDE.md 已有的不要存。
4. **双轨加载**：索引固定注入（让模型知道有什么）+ 详情按需召回（不污染上下文）。
5. **零延迟召回**：异步预取与主调用并行，零阻塞。
6. **会话级预算**：60KB 上限防止整个对话被记忆撑爆。

---

## （8）feat：技能系统 — SKILL.md 发现 + 双路径调用 + 占位符模板

> **一句话概括：** 给 Agent 加上"AI Shell 脚本"能力——把可复用的 prompt 模板封装成 `.claude/skills/<name>/SKILL.md`，用户通过 `/<name>` 显式触发，模型也能根据 `when_to_use` 自主调用 `skill` 工具。一次定义，反复使用。

### 背景：为什么需要技能？

每天和 Agent 打交道会发现很多任务"句式相同、参数不同"：

- 提交代码：每次都要"看 diff → 写 commit message → 提交"
- 代码审查：每次都要"读多个文件 → 检查规范 → 输出建议"
- 生成 API 文档：每次都要"扫接口 → 整理参数 → 输出 markdown"

把这些工作流复制粘贴 prompt 不优雅，写成函数又失去自然语言的灵活。**技能 = 自然语言写的、可复用的工作流脚本**。

### 架构设计

```
┌──────────────────────────────────────────────────────────┐
│                    Skills System                          │
│                                                          │
│  发现来源（项目级覆盖用户级）：                            │
│    ~/.claude/skills/<name>/SKILL.md   ← 用户级（低）      │
│    ./.claude/skills/<name>/SKILL.md   ← 项目级（高）      │
│                                                          │
│  ┌──────────────────────────────────────────┐            │
│  │  SKILL.md 格式                             │            │
│  │  ─────────────                             │            │
│  │  ---                                       │            │
│  │  name: commit                              │            │
│  │  description: 创建 git commit              │            │
│  │  when_to_use: 用户要求提交代码时            │            │
│  │  allowed-tools: run_shell, read_file       │            │
│  │  user-invocable: true                      │            │
│  │  context: inline                           │            │
│  │  ---                                       │            │
│  │  请查看当前 git diff...                    │            │
│  │  用户诉求：$ARGUMENTS                       │            │
│  │  技能目录：${CLAUDE_SKILL_DIR}              │            │
│  └──────────────────────────────────────────┘            │
│                                                          │
│  双路径调用：                                              │
│                                                          │
│  ┌─ 路径 1: 用户主动 ──────┐  ┌─ 路径 2: 模型自动 ────┐    │
│  │ /<name> <args>         │  │ skill 工具调用       │    │
│  │  ↓                     │  │  ↓                   │    │
│  │ __main__.py 拦截        │  │ tools.execute_tool   │    │
│  │  ↓                     │  │  ↓                   │    │
│  │ resolve_skill_prompt    │  │ resolve_skill_prompt │    │
│  │  ↓                     │  │  ↓                   │    │
│  │ agent.run(展开后prompt) │  │ 返回 prompt 作为     │    │
│  │                        │  │ tool_result          │    │
│  └────────────────────────┘  └─────────────────────┘     │
└──────────────────────────────────────────────────────────┘
```

### 核心设计点

#### 1. 目录格式（不是单文件）

```
.claude/skills/
├── commit/
│   ├── SKILL.md           ← 必需，frontmatter + prompt 模板
│   └── conventional_commits.md   ← 可选，附带资源文件
├── review/
│   └── SKILL.md
└── api_docs/
    ├── SKILL.md
    └── template.md
```

为什么不用单文件 `commit.md`？技能经常需要附带资源（参考文档、示例数据）。目录格式天然支持，模板里用 `${CLAUDE_SKILL_DIR}/conventional_commits.md` 引用同目录文件即可。

#### 2. 项目级覆盖用户级（用 dict 自然实现）

```python
def discover_skills():
    skills: dict[str, SkillDefinition] = {}
    _load_skills_from_dir(home / ".claude/skills", "user", skills)     # 先加载
    _load_skills_from_dir(cwd / ".claude/skills", "project", skills)   # 后覆盖
    return list(skills.values())
```

不需要写显式优先级判断——后写入的同名 key 自动覆盖。Claude Code 原版有 6 个来源（managed/project/user/plugin/bundled/MCP），我们简化为 2 个：覆盖了个人开发者最常用的"全局技能 + 项目特定技能"。

#### 3. 双路径调用，最终汇合

| 路径 | 触发方式 | 适用场景 |
|------|---------|----------|
| **路径 1：`/<name>`** | 用户在 REPL 显式输入 | 用户已知技能名，想精确触发 |
| **路径 2：`skill` 工具** | 模型基于 `when_to_use` 自主判断 | 用户描述意图（"帮我提交代码"），模型自己识别 |

两条路径都最终调用 `resolve_skill_prompt(skill, args)` 替换占位符——单一数据源，一处修改两处生效。

#### 4. `skill` 是"元工具"（关键设计）

普通工具返回数据（read_file 返回文件内容、grep_search 返回匹配行）。`skill` 工具返回的是**指令**——展开后的 prompt 文本。

```python
# tools.py — execute_tool 处理 skill 工具
if name == "skill":
    result_dict = execute_skill(skill_name, args)
    return result_dict["prompt"]   # 返回 prompt 文本作为 tool_result
```

模型收到这段"工具结果"后，会按文本里的指令在下一轮执行。这种"工具返回 prompt"的设计让技能完全解耦于 Agent 框架——技能作者只写自然语言模板，不用懂工具调用机制。

#### 5. 占位符替换（轻量模板引擎）

模板里支持两个占位符：

| 占位符 | 替换为 | 用途 |
|--------|--------|------|
| `$ARGUMENTS` / `${ARGUMENTS}` | 用户传入参数 | `/commit "fix login"` 时 `fix login` 注入到模板 |
| `${CLAUDE_SKILL_DIR}` | 技能目录绝对路径 | `${CLAUDE_SKILL_DIR}/template.md` 引用同目录资源 |

故意**不实现** `` !`shell` `` 内联执行：教学项目中安全风险大于价值，Claude Code 原版也对 MCP 技能禁用此特性防注入。

#### 6. user-invocable 控制可见性

```yaml
user-invocable: false   # 用户不能 /name 调用，只有模型可自主触发
```

适用场景：内部辅助技能（如 `_validate_diff`），不希望出现在 `/skills` 列表里干扰用户视野，但模型在合适时机仍可通过 `skill` 工具调用。

#### 7. allowed-tools 安全边界

```yaml
allowed-tools: run_shell, read_file
# 或 JSON 数组语法（更严格）
allowed-tools: ["run_shell", "read_file"]
```

技能只能使用白名单内的工具。当前 inline 模式不强制（依赖模型自觉），fork 模式预留了过滤接口——等 subagent 模块完成后即可启用真实隔离。

#### 8. context: inline vs fork

| 模式 | 行为 | 当前实现 |
|------|------|---------|
| **inline**（默认） | 展开 prompt 直接注入主对话 | ✅ 已实现 |
| **fork** | 创建独立子 Agent 执行，只有最终结果回主对话 | 🟡 占位（subagent 模块未实现，退化为 inline） |

fork 模式的价值：代码审查这类需要多次 read_file / grep_search 的技能，工具调用会污染主对话上下文。fork 之后只有 review 结论回到主线，主对话保持干净。等 subagent 模块完工就能无缝启用。

#### 9. System Prompt 自动注入

`build_skill_descriptions()` 把所有技能分两组写入系统提示：

```
# 可用技能

用户可调用技能（用户输入 /<名称> 来调用）：
- **/commit**: 创建一个git提交...
  使用时机：当用户要求提交代码或说"commit"时
- **/review**: 审查当前变更
  使用时机：变更复杂或涉及核心模块时

自动调用技能（在适当时使用 skill 工具）：
- **api_docs**: 生成 API 文档
  使用时机：用户要求文档或讨论接口设计时

要以编程方式调用技能，请使用 `skill` 工具并传入技能名称和可选参数。
```

最后一句关键——告诉模型 "skill 工具" 这个能力存在。没有这句话模型不会主动调用。

#### 10. 模块级缓存（启动时扫描一次）

```python
_cached_skills: list[SkillDefinition] | None = None

def discover_skills():
    if _cached_skills is not None:
        return _cached_skills
    # ... 扫描两个目录 ...
    _cached_skills = list(skills.values())
```

技能内容会话期间几乎不变，每次都扫文件浪费。模块级缓存简单有效，热加载场景调 `reset_skill_cache()` 清空即可。

### 文件变更

| 文件 | 操作 | 说明 |
|------|------|------|
| `muse_code/skills.py` | **重写** | 完整技能系统（~220 行）：SkillDefinition、discover/parse/resolve/execute、build_skill_descriptions、缓存 |
| `muse_code/tools.py` | 修改 | `execute_tool` 处理 `skill` 工具调用，返回展开后的 prompt 文本 |
| `muse_code/agent.py` | 修改 | 工具过滤白名单去掉 `skill`（保留 `agent` 因为仍占位），让 skill 工具暴露给模型 |
| `muse_code/__main__.py` | 修改 | 新增 `/skills` 命令 + `/<skill-name> args` 用户调用路径 |

### 使用示例

下面演示一次完整的"创建 → 用户调用 → 模型自动调用"流程。

```bash
# ── 第 1 步：创建一个 commit 技能 ──
mkdir -p .claude/skills/commit
cat > .claude/skills/commit/SKILL.md <<'EOF'
---
name: commit
description: 创建一个git提交，自动撰写描述性的commit message
when_to_use: 当用户要求提交代码或说"commit"时
allowed-tools: run_shell, read_file
user-invocable: true
---
请查看当前的 git diff 和暂存变更，按 conventional commits 格式
撰写一个清晰简洁的 commit message。

用户的具体诉求：$ARGUMENTS

技能目录：${CLAUDE_SKILL_DIR}
EOF
```

**System Prompt 自动包含技能描述：**

```
# 可用技能

用户可调用技能（用户输入 /<名称> 来调用）：
- **/commit**: 创建一个git提交，自动撰写描述性的commit message
  使用时机：当用户要求提交代码或说"commit"时

要以编程方式调用技能，请使用 `skill` 工具并传入技能名称和可选参数。
```

```
# ── 第 2 步：用户主动调用（路径 1）──
> /commit fix login bug
调用技能: /commit

# 内部流程：
#   1. __main__.py 截获 / 命令
#   2. resolve_skill_prompt(commit, "fix login bug")
#      → "请查看当前的 git diff...
#         用户的具体诉求：fix login bug
#         技能目录：/path/to/.claude/skills/commit"
#   3. 作为 user message 注入主对话
#   4. agent.run(展开后的 prompt)

Muse Code: 我先查看 git 状态。
  🔧 run_shell git diff --staged
  ...
  
Muse Code: 根据 diff，提交消息应该是...
  🔧 run_shell git commit -m "fix(auth): handle expired token..."
  ✓ 提交成功
```

```
# ── 第 3 步：模型自动调用（路径 2）──
> 帮我把这次的改动提交一下
Muse Code: 好的，我使用 commit 技能来生成规范的 commit message。
  🔧 skill {"skill_name": "commit", "args": "提交本次改动"}
  
  # tool_result 内容（即展开后的 prompt）：
  # "请查看当前的 git diff 和暂存变更...
  #  用户的具体诉求：提交本次改动
  #  技能目录：/path/to/.claude/skills/commit"
  
  # 模型在下一轮 API 调用中按这段 prompt 行事：
  🔧 run_shell git diff --staged
  ...
  🔧 run_shell git commit -m "..."
```

**`/skills` 命令查看所有技能：**

```
> /skills
共 1 个技能：
  /commit (project) — 创建一个git提交，自动撰写描述性的commit message
```

### 真实消息流（路径 2 模型自动调用）

```python
# user 输入"帮我把这次的改动提交一下"后的消息数组：

messages = [
  {role: "system", content: "...# 可用技能\n- **/commit**: 创建git提交..."},
  {role: "user", content: "帮我把这次的改动提交一下"},
  
  # 模型决定调用 skill 工具：
  {role: "assistant", content: None, tool_calls: [{
      name: "skill",
      arguments: '{"skill_name":"commit","args":"提交本次改动"}'
  }]},
  
  # 工具结果是展开后的 prompt（不是数据）：
  {role: "tool", tool_call_id: "...", content:
      "请查看当前的 git diff 和暂存变更...\n"
      "用户的具体诉求：提交本次改动\n"
      "技能目录：/path/to/.claude/skills/commit"},
  
  # 模型按上面的 prompt 行事，下一轮调用 run_shell：
  {role: "assistant", content: None, tool_calls: [{
      name: "run_shell", arguments: '{"command":"git diff --staged"}'
  }]},
  ...
]
```

### 与 Claude Code / mini_claude 对比

| 维度 | Claude Code | mini_claude | Muse Code |
|------|------------|-------------|-----------|
| 加载来源 | 6 个（managed/project/user/plugin/bundled/MCP） | 2 个（user/project） | 2 个（user/project） |
| 加载策略 | 启动只读 frontmatter，调用时读全文 | 启动全量加载 | 启动全量加载 + 模块级缓存 |
| Token 预算 | `formatCommandsWithinBudget` 三阶段算法 | 无 | 无 |
| 占位符 | `$ARGUMENTS`、`${CLAUDE_SKILL_DIR}`、`` !`shell` `` | 前两个 | 前两个 |
| 双路径调用 | / + skill 工具 | / + skill 工具 | / + skill 工具 |
| inline / fork | 都支持 | 都支持 | inline 完整、fork 占位 |
| user-invocable | 支持 | 支持 | 支持 |
| allowed-tools | 强制隔离 | inline 不隔离、fork 隔离 | inline 不隔离、fork 占位 |

### 设计哲学

1. **元工具思想**：`skill` 工具返回的是 prompt 不是数据。让技能作者只写自然语言，不用懂工具机制。
2. **双路径单实现**：用户 `/name` 和模型 `skill` 工具最终汇合到 `resolve_skill_prompt`，单一数据源避免漂移。
3. **目录优于文件**：技能可附带资源文件，`${CLAUDE_SKILL_DIR}` 提供可移植引用。
4. **dict 自然覆盖**：用 dict[name] 的后写入覆盖语义实现优先级，比写显式 if-else 优雅。
5. **缓存换性能**：技能会话期间不变，启动时扫描一次足够。
6. **fork 留接口不强求**：subagent 模块还没好，先按 inline 跑；接口语义保留好，模块完工自动升级。

---

## （9）feat：多 Agent 架构 — Sub-Agent fork-return 模式 + 内置/自定义 Agent 类型

> **一句话概括：** 让主 Agent 能派生出独立的子 Agent（explore / plan / general / 自定义）去执行探索、规划、通用任务，子 Agent 在隔离上下文里跑完后只把"结论"返回主 Agent。这是处理复杂任务时最重要的"分而治之"机制，也补齐了技能系统遗留的 fork 占位。

### 背景：为什么需要多 Agent？

单 Agent 干所有事会遇到两个天花板：

- **上下文污染**：一个"分析整个代码库架构"的任务可能要 read_file / grep_search 几十次，这些中间结果全堆在主对话里，挤占窗口又干扰后续推理。
- **缺乏专精**：探索代码需要的是"快、只读、广撒网"，写代码需要的是"全工具、可改文件"。同一套提示词和工具集很难两头讨好。

Sub-Agent 的思路：把一个可独立完成的子任务**分叉**给一个全新的 Agent 实例，它有自己的系统提示词、自己的工具集、自己的消息历史，跑完后只把最终文本结论回传主 Agent。主对话里只留下"派了个活、拿到个结论"，中间几十次工具调用都被隔离掉了。

### 架构设计

```
┌──────────────────────────────────────────────────────────┐
│                   Multi-Agent System                      │
│                                                          │
│  用户请求 → 主 Agent                                       │
│                │                                         │
│                │ agent 工具调用 (type?)                    │
│                ▼                                         │
│        ┌───────┴────────┬─────────────┐                  │
│        ▼                ▼             ▼                   │
│   ┌─────────┐     ┌─────────┐   ┌──────────┐             │
│   │ explore │     │  plan   │   │ general  │             │
│   │ 只读·快 │     │只读·规划│   │ 完整工具 │             │
│   └────┬────┘     └────┬────┘   └────┬─────┘             │
│        │ 独立消息历史 + 独立工具集 + 独立系统提示词         │
│        └────────────────┴─────────────┘                  │
│                         │ 返回文本结论                    │
│                         ▼                                │
│                     主 Agent（token 汇总回父级）          │
│                                                          │
│  自定义 Agent：.claude/agents/*.md（项目级覆盖用户级）     │
└──────────────────────────────────────────────────────────┘
```

### 核心设计点

#### 1. 子 Agent 就是"配置不同的 Agent 实例"（最关键洞察）

没有为子 Agent 新写一套 loop，而是给 `Agent` 类加了三个可选参数：`custom_system_prompt`、`custom_tools`、`is_sub_agent`。同一套 agent loop（含双后端、流式、权限、上下文管理）原封不动地同时服务主 Agent 和子 Agent。`custom_tools` 为 `None` 时回退全量工具，对主 Agent 零侵入。

这避免了"主从两套实现各跑各的、改一处忘一处"的经典陷阱。

#### 2. 三种内置类型，工具集即能力边界

| 类型 | 工具集 | 适用 |
|------|--------|------|
| **explore** | 只读（read_file / list_files / grep_search） | 快速代码库搜索、定位实现 |
| **plan** | 只读 | 分析架构、产出结构化实现计划 |
| **general** | 全量工具（**除 agent**） | 独立的多步任务，可改文件 |

工具集本身就是最硬的能力约束——explore 拿不到 write_file，从根上就改不了文件，再叠加系统提示词的只读声明形成纵深防御。

#### 3. 子 Agent 不能再派生子 Agent（防递归爆炸）

general 的工具集里**显式过滤掉 `agent` 工具**。否则 A 派生 B、B 派生 C 的递归嵌套会指数级消耗 token——每一层都有自己的系统提示词和完整消息历史。实践中 1 层委托已覆盖绝大多数场景，Claude Code 也是同样的硬限制。

#### 4. 输出捕获：buffer 三态

主 Agent 的流式文本要逐字打印给用户看；子 Agent 的文本不能直接打到终端（会和主对话混在一起），得收集起来作为"结论"回传。用一个 `_output_buffer` 字段统一三态：

- `None` = 主 Agent 模式 → 直接打印
- `[]` = 子 Agent 开始收集
- `[...]` = 正在积累

流式回调只管调一个 `_emit_text()`，完全不感知自己在哪个模式下。生命周期边界清晰：`run_once` 开 buffer、loop 往里写、`run_once` 收集并关。比"传 onText 回调到处判断"侵入小得多。

#### 5. agent 工具需要"有状态分发"

普通工具走无状态的 `execute_tool(name, input)`。但 `agent` 工具要访问当前 Agent 实例的状态——model、permission_mode、token 计数器、后端配置（派生子 Agent 时要复用同一后端和密钥）。所以单独走 `_execute_tool_call`，`agent` 分发到实例方法，其余仍走无状态函数。

#### 6. 权限继承：默认 bypass，但 Plan Mode 必须传染

子 Agent 默认 `bypassPermissions`——主 Agent 派活时用户已经授权过了，子 Agent 每个工具再弹一次确认会很烦。**唯一例外**：主 Agent 在 Plan Mode 时，子 Agent 必须继承 `plan` 模式，否则子 Agent 能绕过只读限制去改文件，是个安全漏洞。

#### 7. 容错：子 Agent 出错返回错误字符串，不抛异常

子 Agent 跑挂了返回 `"Sub-agent error: ..."` 字符串而非抛出。父 Agent 的 LLM 看到这段错误信息后可以自行决定重试、换类型还是换策略——而不是整个主对话崩掉。这是 fork-return 模式"容错简单"优势的具体体现。

#### 8. Token 汇总到父级

子 Agent 的 token 用量按"运行后 − 运行前"的增量算出来，回传后通过 `_record_tokens` 累加进父 Agent。这样 `/cost` 看到的是含子 Agent 在内的总账，子 Agent 自己不打印费用（否则造成重复计费的错觉）。

#### 9. 自定义 Agent：`.claude/agents/*.md`

和技能、记忆共用 frontmatter 解析器与"项目级覆盖用户级"的 dict 发现机制：

```markdown
---
name: reviewer
description: Reviews code for bugs and style issues
allowed-tools: read_file, list_files, grep_search
---
You are a code reviewer. Report bugs, style issues, and performance concerns.
```

声明了 `allowed-tools` 就按白名单给工具，没声明就给全量（仍排除 agent）。自定义类型的描述会注入系统提示词的 `# Custom Agent Types` 段落，让模型知道有这么个专家可派。

#### 10. 顺带解锁了技能的 fork 模式

技能系统（#8）里 `context: fork` 一直是占位，因为没有 subagent。现在 subagent 落地，fork 模式具备了真实落地的基础——代码审查这类"多次 read/grep"的技能可以 fork 出去跑，只把结论带回主线，主对话保持干净。

### 文件变更

| 文件 | 操作 | 说明 |
|------|------|------|
| `muse_code/subagent.py` | **重写** | 桩 → 完整实现：内置三类提示词、只读工具集、自定义 Agent 发现、`get_sub_agent_config`、`build_agent_descriptions`、缓存 |
| `muse_code/agent.py` | 修改 | 构造函数加 `custom_tools` / `is_sub_agent`；新增 `_emit_text` / `run_once` / `_execute_agent_tool` / `_execute_tool_call`；两个后端**不再过滤 agent 工具**，按 buffer 状态门控终端输出 |
| `muse_code/ui.py` | 修改 | 新增 `print_sub_agent_start` / `print_sub_agent_end`（magenta `┌─`/`└─` 标记） |

`prompt.py`（已 import `build_agent_descriptions`）和 `permissions.py`（已处理 agent 工具确认 + bypassPermissions）无需改动——前序章节已埋好接口。

### 使用示例

```
# ── 主 Agent 派生一个 explore 子 Agent 去定位实现 ──
> 帮我搞清楚权限检查的核心逻辑在哪、怎么组织的

  🤖 agent  定位权限检查逻辑

  ┌─ Sub-agent [explore]: 定位权限检查逻辑
  （子 Agent 内部跑了多次 grep_search / read_file，
    这些工具调用都在隔离上下文里，不污染主对话）
  └─ Sub-agent [explore] completed

# 主 Agent 拿到子 Agent 的文本结论后，基于结论回答用户：
Muse Code
权限检查集中在 permissions.py 的 PermissionChecker.check()，9 步流水线：
bypass → 规则 → 只读放行 → plan 限制 → ... 危险检测 + 白名单。
入口在 agent.py 的工具执行前，详见 permissions.py:552。
```

```bash
# ── 定义一个自定义 reviewer Agent ──
mkdir -p .claude/agents
cat > .claude/agents/reviewer.md <<'EOF'
---
name: reviewer
description: 审查代码的 bug 与风格问题
allowed-tools: read_file, list_files, grep_search
---
You are a code reviewer. Analyze thoroughly and report bugs,
style inconsistencies, and performance concerns.
EOF

# System Prompt 自动包含：
#   # Custom Agent Types
#   - **reviewer**: 审查代码的 bug 与风格问题
# 之后模型即可 agent(type="reviewer", ...) 派这个专家
```

### 与 Claude Code / mini_claude 对比

| 维度 | Claude Code | mini_claude | Muse Code |
|------|------------|-------------|-----------|
| 协作模式 | Sub-Agent / Coordinator / Swarm | Sub-Agent | Sub-Agent（fork-return） |
| 执行流程 | 5 阶段（fork 进程、缓存共享） | new Agent + runOnce | new Agent + run_once（复用双后端 loop） |
| 工具过滤 | 4 层管道 | 1 个 Set + filter | 工具集即边界 + general 排除 agent |
| Explore 模型 | Haiku（更便宜） | 统一主模型 | 统一主模型 |
| 上下文隔离 | deny-by-default | 天然隔离（独立实例） | 天然隔离（独立实例 + 独立消息历史） |
| Worktree 隔离 | 每个写 Agent 独立 worktree | 无 | 无 |
| 自定义 Agent | `.claude/agents/*.md` | `.claude/agents/*.md` | `.claude/agents/*.md` |
| 递归派生 | 禁止 | 禁止 | 禁止（general 排除 agent） |

### 设计哲学

1. **子 Agent = 配置不同的 Agent 实例**：靠三个可选参数复用整套 loop，拒绝主从两份实现。
2. **工具集即能力边界**：能不能改文件，由拿没拿到 write_file 决定，比提示词约束更硬。
3. **fork-return 优于 Coordinator 作为起点**：无共享状态、控制流确定、容错简单——子 Agent 挂了主 Agent 照常工作。
4. **上下文隔离换主对话整洁**：几十次中间工具调用留在子 Agent 里，主对话只见结论。
5. **权限默认放行但 Plan Mode 传染**：减少打扰，同时堵住只读绕过的安全漏洞。
6. **埋好的接口逐章兑现**：prompt / permissions / 技能 fork 在前几章预留的接口，到这一章一次性兑现。

---

## （10）feat：MCP 集成 — 原始 JSON-RPC over stdio 连接外部工具服务器

> **一句话概括：** 让 Agent 动态加载外部工具——连数据库、Slack、GitHub 等服务，只需在配置文件里声明一个服务器地址，不改一行源码。对 Agent Loop 来说，MCP 工具和内置工具没有任何区别：都是名字 + schema + 执行函数。

### 背景：为什么需要 MCP？

到上一章为止，Agent 的工具是**写死在代码里**的——read_file、grep_search、run_shell 等十来个。但真实场景下用户的需求五花八门：有人要查 Postgres，有人要发 Slack 消息，有人要操作 GitHub Issue。把这些全塞进内置工具既不现实（依赖爆炸）也不优雅（大部分用户用不到）。

MCP（Model Context Protocol）是 Anthropic 发布的开放协议，专门解决这个问题：**工具的提供方（server）和使用方（client）解耦**。任何人都能写一个 MCP server 暴露一组工具，Agent 只要按协议连上去就能用。生态里已经有现成的 filesystem、github、slack、postgres 等官方 server，`npx` 一行就能起。

### 架构设计

```
┌──────────────────────────────────────────────────────────┐
│                      MCP System                           │
│                                                          │
│  配置发现（三处合并，同名后读覆盖）：                       │
│    ~/.claude/settings.json   ← 用户级                    │
│    ./.claude/settings.json   ← 项目级                    │
│    ./.mcp.json               ← 项目根（扁平格式）         │
│                    │                                     │
│                    ▼                                     │
│              ┌───────────┐                               │
│              │ McpManager│                               │
│              └─────┬─────┘                               │
│         spawn 子进程 + stdio                              │
│        ┌───────────┴───────────┐                         │
│        ▼                       ▼                         │
│  ┌───────────┐           ┌───────────┐                   │
│  │ Server A  │           │ Server B  │                   │
│  │(McpConn)  │           │(McpConn)  │                   │
│  └─────┬─────┘           └─────┬─────┘                   │
│   JSON-RPC over stdin/stdout                             │
│        │                       │                         │
│  mcp__A__tool1           mcp__B__tool3                   │
│  mcp__A__tool2                                           │
│        └───────────┬───────────┘                         │
│                    ▼ 透明注入                            │
│               Agent Loop                                 │
│                    │ tool_use: mcp__A__tool1             │
│                    ▼ 按前缀路由                          │
│               McpManager → Server A                      │
└──────────────────────────────────────────────────────────┘
```

核心流程一句话：**spawn 子进程 → JSON-RPC 握手 → 发现工具 → 前缀注册 → 透明路由**。

### 核心设计点

#### 1. JSON-RPC over stdio，不用 HTTP

每个 MCP server 是一个**子进程**，client 通过它的 stdin/stdout 收发换行分隔的 JSON-RPC 消息。为什么不用 HTTP？stdio 的优势是**零配置**：不用管端口、不用服务发现、进程生命周期自动绑定父进程——父进程退出，子进程跟着走，pending 请求自动 reject，不存在连接泄漏。HTTP 方案要处理端口冲突、心跳、进程发现，复杂度高一个量级。stdio 覆盖了 95% 的场景。

#### 2. 不依赖 MCP SDK，手写 ~60 行 JSON-RPC

`@anthropic-ai/sdk` 有现成的 MCP 客户端封装，但我们直接实现原始 JSON-RPC。两个好处：**零依赖**（不增包体积）和**教学价值**（读者能看到协议的完整细节）。整个通信就两种消息：

| 消息类型 | 有无 id | 行为 |
|---------|---------|------|
| **请求（request）** | 有 | 写入 stdin，存入 `pending` 表等响应配对 |
| **通知（notification）** | 无 | 写入 stdin 就结束，发后不管 |

`pending: dict[id → Future]` 用自增 id 关联请求和响应：发送时存入 Future，后台读循环收到带相同 id 的响应就 resolve/reject。

#### 3. 三步标准流程：initialize → tools/list → tools/call

```
initialize（协商协议版本 2024-11-05、交换能力）
   ↓
notifications/initialized（协议强制：告诉 server 客户端就绪）
   ↓
tools/list（发现 server 提供哪些工具）
   ↓
tools/call（实际调用，返回 {content:[{type:"text",text:...}]}）
```

`call_tool` 只提取 `content` 里 `type == "text"` 的部分拼接返回——图片等其他类型暂不处理。

#### 4. 三段式前缀名 `mcp__server__tool`（一名解两题）

filesystem server 的 `read_file` 工具，注册成 `mcp__filesystem__read_file`。这个命名同时解决两个问题：

- **避免冲突**：不同 server 可能有同名工具（两个 server 都有 `read_file`）
- **嵌入路由信息**：从名字直接拆出 server 名，不需要额外映射表

路由时 `split("__")` 取第 2 段作 server 名，`"__".join(parts[2:])` 还原工具名（容错工具名本身含 `__`）。Claude Code 用的是完全相同的命名方案。

#### 5. 懒加载：首次 chat 时才连接

MCP 连接不在构造函数里做，而是**首次 `run()` 时**触发。理由：用户可能只是想问一句"这个函数啥意思"，根本用不到外部工具，没必要付连接的启动成本（npx 起 server 可能要好几秒）。代价是第一次用到时有一次性延迟，但只发生一次。

#### 6. 只在主 Agent 连接，子 Agent 跳过

子 Agent（上一章）不连 MCP——它要么继承受限工具集（explore/plan），要么就是临时任务。`_ensure_mcp_loaded()` 里一个 `is_sub_agent` 判断直接返回，避免每派生一个子 Agent 就重连一遍 server。

#### 7. 容错：失败静默跳过，绝不崩溃

每台 server 独立连接，握手和工具发现各有 **15 秒超时**（npx 首次要下载包，但不能无限等）。某台连不上？打条日志、`close()` 清理、继续连下一台。MCP 整体挂了？Agent 照常用内置工具工作。`_execute_tool_call` 里 MCP 调用出错也包装成字符串返回给模型，而不是抛异常中断主循环。

#### 8. 退出时清理子进程

REPL 退出时调 `disconnect_all()` kill 掉所有 server 子进程，避免僵尸进程。`close()` 同时 reject 所有 pending 请求，让等待中的 `await` 干净地失败。

#### 9. 修正参考实现的一处竞态

mini_claude 的 `_send_request` 是**先写 stdin 再注册 pending future**。如果 server 响应极快（在注册前就返回），读循环会因为 `pending` 里还没有这个 id 而把响应丢弃，请求永久挂起。Muse Code 改成**先注册 future 再写 stdin**，消除这个竞态。

### 文件变更

| 文件 | 操作 | 说明 |
|------|------|------|
| `muse_code/mcp.py` | **新建** | 完整 MCP 客户端（~290 行）：`McpConnection`（子进程 + JSON-RPC 收发握手）、`McpManager`（配置合并、连接生命周期、前缀注册、路由） |
| `muse_code/agent.py` | 修改 | 构造函数加 MCP 状态；`run()` 首次调用懒加载（仅主 Agent）；两后端工具列表追加 MCP 工具；`_execute_tool_call` 按 `mcp__` 前缀路由 |
| `muse_code/__main__.py` | 修改 | REPL 退出时 `disconnect_all()` 清理子进程 |

`permissions.py` 无需改动——MCP 工具不在 `CONCURRENCY_SAFE_TOOLS` 里，总是走串行执行路径（经 `_execute_tool_call` 路由），权限上落到默认放行分支，符合教学范围。

### 配置示例

```json
// .mcp.json（项目根目录）或 ~/.claude/settings.json
{
  "mcpServers": {
    "filesystem": {
      "command": "npx",
      "args": ["@modelcontextprotocol/server-filesystem", "/tmp"]
    },
    "github": {
      "command": "npx",
      "args": ["@modelcontextprotocol/server-github"],
      "env": { "GITHUB_TOKEN": "ghp_xxx" }
    }
  }
}
```

### 使用示例

```
# ── 启动时自动连接配置好的 server ──
$ python -m muse_code
[mcp] Connected to 'filesystem' — 8 tools
[mcp] Connected to 'github' — 26 tools

# ── 模型可直接调用 MCP 工具（与内置工具无异）──
> 看看 /tmp 下有哪些文件

  🛠️ mcp__filesystem__list_directory  {"path": "/tmp"}
  （McpManager 拆出 server="filesystem"、tool="list_directory"，
    转发到对应子进程，返回的 text 内容回到主对话）

Muse Code
/tmp 下有 build/、cache/、test.log 三项。
```

### 与 Claude Code / mini_claude 对比

| 维度 | Claude Code | mini_claude | Muse Code |
|------|------------|-------------|-----------|
| MCP SDK | `@anthropic-ai/sdk` 内置客户端 | 原始 JSON-RPC | 原始 JSON-RPC（无 SDK 依赖） |
| 传输协议 | stdio + SSE | 仅 stdio | 仅 stdio |
| 工具发现 | 动态刷新（server 可通知变更） | 一次性发现 | 一次性发现 |
| 配置来源 | settings.json + .mcp.json + 企业策略 | settings.json + .mcp.json | settings.json + .mcp.json |
| 错误处理 | 重试 + 降级 | 静默跳过 | 静默跳过 + 修正发送竞态 |
| 连接时机 | 首次 chat 懒加载 | 首次 chat 懒加载 | 首次 run 懒加载 |
| 子 Agent | 独立 MCP 连接 | 不连接 | 不连接（is_sub_agent 跳过） |

### 设计哲学

1. **工具即协议，提供方与使用方解耦**：MCP 让工具能在 Agent 之外独立演进，不改源码即可扩展能力。
2. **stdio 优于 HTTP 作为传输**：进程生命周期自动绑定，零端口管理，无连接泄漏。
3. **三段式前缀一名解两题**：命名冲突 + 路由信息一次解决，无需额外映射表。
4. **懒加载换零开销**：用不到 MCP 的快问快答场景一点不付出启动成本。
5. **透明注入**：MCP 工具对 Agent Loop 完全透明，模型不知道也不需要知道工具来自外部进程。
6. **失败不传染**：单台 server 挂掉、超时、出错都被隔离，Agent 永远能用内置工具兜底。

---

## 附录：腾讯 workbuddy 长期记忆系统设计参考

这个记忆系统设计为 muse-code 的记忆模块开发提供了重要参考，特别是在用户画像构建和长期记忆管理方面。

腾讯 workbuddy 的长期记忆系统包含四个核心维度：工作背景、个人背景、当前关注、近期动态。记忆系统会在每天晚上自动生成更新。

### 完整示例：关于你的记忆

**工作背景**
用户是北邮背景的腾讯AI工程师（用户名lumxu），从事LLM微调的产品研发，同时是muse-code（CLI AI编码助手）项目的开发者。当前核心项目为TEN_Turn_Detection v3版本（VAD turn detection），采用LoRA微调（r=16+MLP层，学习率1e-4），分类标签为unfinished/wait/finished三分类，训练策略包含cost-sensitive loss、focal loss、label smoothing。训练集群为Karmada TKE（yunqing-finetuning-north-china），子集群cls-gzqq9xxu，finetuning-vad命名空间，使用run_fast_v2.sh脚本（6卡训练+2卡评估并行）。本地开发环境为macOS，训练集群home目录/data/home/lumxu。Docker镜像turn_detection_train:20260609-v1（23.7GB）。

**个人背景**
用户偏好中文交流，要求大白话式直白解释，简洁、行动导向，附明确命令块。偏好结构化表格输出，常生成架构/评估报告等MD文档。对分类定义和根因敏感，主动纠正助手错误假设，深入质疑设计理由。要求code_history.md关注设计决策和功能（不要实现细节），功能完成后要求commit message。

**当前关注**
muse-code 记忆系统、技能系统开发：参考 mini_claude 构建 CLI AI 编码助手的核心模块，关注设计决策记录。TEN_Turn_Detection v3 训练推进、K8s 训练任务部署、GPU 资源调度。

**近期动态**
- 启动muse-code项目开发：搭建CLI AI编码助手项目框架，参考mini_claude实现。
- 持续推进上下文管理、记忆系统、技能系统模块开发。

### 设计要点

1. **四维记忆结构**：工作背景、个人背景、当前关注、近期动态构成完整的用户画像
2. **自动更新机制**：每天晚上自动生成更新，保持记忆的时效性
3. **结构化存储**：每个维度都有明确的字段定义和更新策略
4. **项目关联**：记忆与具体项目进展紧密关联，便于上下文理解
5. **偏好记录**：详细记录用户的工作习惯和交流偏好，提升交互体验


## （12）feat：新增 ReAct 推理模式，支持弱模型的显式推理链路

**提交:** 待提交 | **新增 1 个文件，修改 2 个文件，共 +280 行**

> **一句话概括：** 在现有 tool-loop 模式（依赖 function calling API）基础上，新增 ReAct（Reasoning + Acting）纯文本推理模式，通过 Thought → Action → Observation → Final Answer 的结构化循环让推理能力较弱的模型也能稳定使用工具，通过 `--react` 参数切换，默认仍为 tool-loop。

### 设计背景

现有 tool-loop 模式依赖模型的 function calling 能力：模型收到用户消息后直接输出 tool_calls，推理过程隐式发生在其内部。Claude/GPT 等强模型对此支持良好，但推理能力较弱的模型（如开源小模型、早期 GLM 等）在 tool-loop 下容易出现幻觉调用、参数错误、过早终止等问题。

ReAct 模式的思路是让思考过程**显式化**：模型先输出 Thought（推理），再输出 Action（工具调用），最后接收 Observation（结果反馈）。这样弱的模型有了结构化引导，每一步都看得到它在想什么。

### 整体架构

```
tool-loop (现有):              ReAct (新增):
                              
  user_msg → model             user_msg → model  
       ↓                            ↓          
  tool_calls (隐式推理)         Thought: "我需要先读文件"
       ↓                            ↓          
  execute → result             Action: read_file  
       ↓                            ↓          
  model → ...                  execute → Observation: "文件内容是..."
                                     ↓          
                               model → (下一轮 Thought/或 Final Answer)
```

两者共用同一套基础设施：权限检查、记忆预取、上下文压缩、MCP 工具、子 Agent、会话持久化。区别仅在于模型交互方式。

### 各模块详解

**[muse_code/react.py](file:///Users/lumine/code/llm/muse-code/muse_code/react.py) - ReAct 核心模块（新文件）**

| 组件 | 职责 |
|------|------|
| `REACT_SYSTEM_SUFFIX` | 追加到 system prompt 的 ReAct 指令模板，教模型输出 Thought/Action/Action Input/Final Answer 格式 |
| `format_tools_for_react(tools)` | 把 Anthropic schema 格式的工具定义转为纯文本描述，让不支持 function calling 的模型也能理解可用工具 |
| `parse_react_response(text)` | 解析模型文本输出，正则提取 Action/Final Answer，返回 `action` / `final` / `error` 三种类型 |
| `format_observation(result)` | 把工具结果包装为 `Observation: ...` 格式（8KB 截断），作为 user 消息注入 |
| `MAX_REACT_STEPS = 30` | 安全上限，防止单轮对话无限循环 |

设计决策：
- ReAct 是纯文本交互，不传 `tools` 参数到 API，不与 function calling 耦合
- `parse_react_response` 优先检查 `Final Answer`（防止模型同时输出 Action 和 Final Answer 时误判）
- Action Input 支持多行 JSON（`re.DOTALL`），但对格式错误（非法 JSON）返回 error 类型让模型修正

**[muse_code/agent.py](file:///Users/lumine/code/llm/muse-code/muse_code/agent.py) - 新增 ReAct 支持**

新增方法和参数：

| 变更 | 说明 |
|------|------|
| `__init__` 新增 `reasoning_mode` 参数 | 默认 `"tool_loop"`，可选 `"react"` |
| `run()` / `run_once()` 分发 | 根据 `reasoning_mode` 分发到 `_chat_react()` 或原有方法 |
| `_build_react_system_prompt()` | 动态构建系统提示（基础 prompt + ReAct 指令 + 当前可用工具描述），在每次 `_chat_react` 调用时重建以包含 MCP 工具 |
| `_chat_react(user_message)` | ReAct 主循环：for 循环多步迭代，每步调用 LLM（纯文本）→ 解析响应 → 如果是 Action 则执行工具 → Observation 注入 → 继续循环 |
| `_call_react_openai_stream()` | OpenAI 流式调用（不传 `tools`），收集文本 + usage |
| `_call_react_anthropic_stream()` | Anthropic 流式调用（不传 `tools`），收集文本 + usage |
| `_execute_agent_tool()` | 子 Agent 继承父 Agent 的 `reasoning_mode` |

关键设计决策：
- **系统提示动态重建**：改为 `run()` 中调用 `_chat_react()` 时重建（而非 `__init__` 中），因为 MCP 工具是懒加载的，`__init__` 时工具列表不完整
- **复用现有消息列表**：ReAct 使用 `self._openai_messages` / `self._anthropic_messages`，会话持久化、auto-compact、记忆注入无须修改
- **Observation → user role**：工具结果以 `Observation: ...` 格式作为 user 消息注入（而非 tool role），这是 ReAct 的核心交互格式
- **for...else 安全上限**：循环达到 `MAX_REACT_STEPS=30` 后打印提示并退出，防止弱模型陷入死循环
- **格式错误处理**：`parse_react_response` 返回 error 时，将修正指引作为 user 消息回传，让模型自行纠正格式

**[muse_code/__main__.py](file:///Users/lumine/code/llm/muse-code/muse_code/__main__.py) - CLI 入口**

| 变更 | 说明 |
|------|------|
| 新增 `--react` 参数 | 布尔标志，启用后 `reasoning_mode="react"` |
| `Agent(... reasoning_mode=...)` | 根据 `args.react` 传入对应模式 |

### 使用方式

```bash
# 默认 tool-loop（不变）
muse "帮我读一下 README.md"

# ReAct 模式
muse --react "帮我读一下 README.md 并总结"
```