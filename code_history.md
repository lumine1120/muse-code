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