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