"""子 Agent 系统 — 分叉-返回（fork-return）模式，内置 + 自定义 Agent 类型。

对应 Claude Code 的 AgentTool：
  - explore：只读，快速代码库搜索
  - plan：只读，生成结构化实现计划
  - general：完整工具（不含 agent，防止递归派生）
  - 自定义：通过 .claude/agents/*.md 定义

核心洞察：子 Agent 本质上就是一个配置不同的 Agent 实例 —— 通过给 Agent 类
传入 custom_system_prompt / custom_tools / is_sub_agent，同一套 agent loop
同时服务于主 Agent 和子 Agent。
"""

from __future__ import annotations

from pathlib import Path

from .frontmatter import parse_frontmatter
from .tools import tool_definitions, ToolDef

# ─── 只读工具（用于 explore 和 plan Agent） ──────────────────
#
# 注意：run_shell 不在只读集合里。explore/plan 通过受限工具集 + system prompt
# 双重约束保证只读。若要放开 git log / find 这类只读 shell，可加入此集合，
# 但当前实现选择更严格的纯文件工具集。

READ_ONLY_TOOLS = {"read_file", "list_files", "grep_search"}


def _get_read_only_tools() -> list[ToolDef]:
    return [t for t in tool_definitions if t["name"] in READ_ONLY_TOOLS]


# ─── 内置 Agent 类型的系统提示词 ──────────────────────────────

EXPLORE_PROMPT = """You are a file search specialist for Muse Code. You excel at thoroughly navigating and exploring codebases.

=== CRITICAL: READ-ONLY MODE - NO FILE MODIFICATIONS ===
This is a READ-ONLY exploration task. You are STRICTLY PROHIBITED from:
- Creating new files (no write_file, touch, or file creation of any kind)
- Modifying existing files (no edit_file operations)
- Deleting files (no rm or deletion)
- Running ANY commands that change system state

Your role is EXCLUSIVELY to search and analyze existing code.

Your strengths:
- Rapidly finding files using glob patterns
- Searching code and text with powerful regex patterns
- Reading and analyzing file contents

Guidelines:
- Use list_files for broad file pattern matching
- Use grep_search for searching file contents with regex
- Use read_file when you know the specific file path you need to read
- Adapt your search approach based on the thoroughness level specified by the caller

NOTE: You are meant to be a fast agent that returns output as quickly as possible. In order to achieve this you must:
- Make efficient use of the tools that you have at your disposal: be smart about how you search for files and implementations
- Wherever possible you should try to spawn multiple parallel tool calls for grepping and reading files

Complete the user's search request efficiently and report your findings clearly."""

PLAN_PROMPT = """You are a Plan agent — a READ-ONLY sub-agent specialized for designing implementation plans.

IMPORTANT CONSTRAINTS:
- You are READ-ONLY. You only have access to read_file, list_files, and grep_search.
- Do NOT attempt to modify any files.

Your job:
- Analyze the codebase to understand the current architecture
- Design a step-by-step implementation plan
- Identify critical files that need modification
- Consider architectural trade-offs

Return a structured plan with:
1. Summary of current state
2. Step-by-step implementation steps
3. Critical files for implementation
4. Potential risks or considerations"""

GENERAL_PROMPT = """You are an agent for Muse Code. Given the user's message, you should use the tools available to complete the task. Complete the task fully—don't gold-plate, but don't leave it half-done. When you complete the task, respond with a concise report covering what was done and any key findings — the caller will relay this to the user, so it only needs the essentials.

Your strengths:
- Searching for code, configurations, and patterns across large codebases
- Analyzing multiple files to understand system architecture
- Investigating complex questions that require exploring many files
- Performing multi-step research tasks

Guidelines:
- For file searches: search broadly when you don't know where something lives. Use read_file when you know the specific file path.
- For analysis: Start broad and narrow down. Use multiple search strategies if the first doesn't yield results.
- Be thorough: Check multiple locations, consider different naming conventions, look for related files.
- NEVER create files unless they're absolutely necessary for achieving your goal. ALWAYS prefer editing an existing file to creating a new one."""

# ─── 自定义 Agent 发现 ─────────────────────────────────────────
#
# 项目级（.claude/agents/）优先级高于用户级（~/.claude/agents/），同名覆盖。
# frontmatter 复用 parse_frontmatter()，与 Memory 和 Skills 共享同一套解析器。

_cached_custom_agents: dict[str, dict] | None = None


def _discover_custom_agents() -> dict[str, dict]:
    global _cached_custom_agents
    if _cached_custom_agents is not None:
        return _cached_custom_agents

    agents: dict[str, dict] = {}
    # 用户级（先加载 → 低优先级）
    _load_agents_from_dir(Path.home() / ".claude" / "agents", agents)
    # 项目级（后加载 → 高优先级覆盖）
    _load_agents_from_dir(Path.cwd() / ".claude" / "agents", agents)

    _cached_custom_agents = agents
    return agents


def _load_agents_from_dir(directory: Path, agents: dict[str, dict]) -> None:
    if not directory.is_dir():
        return
    for entry in directory.iterdir():
        if entry.suffix != ".md":
            continue
        try:
            raw = entry.read_text()
            result = parse_frontmatter(raw)
            meta = result.meta
            name = meta.get("name") or entry.stem
            allowed_tools = None
            if "allowed-tools" in meta:
                allowed_tools = [s.strip() for s in meta["allowed-tools"].split(",") if s.strip()]
            agents[name] = {
                "name": name,
                "description": meta.get("description", ""),
                "allowed_tools": allowed_tools,
                "system_prompt": result.body,
            }
        except Exception:
            pass


# ─── 主配置函数 ───────────────────────────────────────────────


def get_sub_agent_config(agent_type: str) -> dict:
    """返回给定 Agent 类型的 {system_prompt, tools}。

    先查自定义 Agent；未命中则回退到内置类型；未知类型回退到 general。
    """
    custom = _discover_custom_agents().get(agent_type)
    if custom:
        if custom["allowed_tools"]:
            # 即使用户显式声明 allowed-tools，也强制剔除 agent 工具——
            # 子 Agent 递归派生子 Agent 会让 Token 呈指数级增长，
            # 这是系统级硬约束，不允许通过用户配置绕过。
            tools = [
                t for t in tool_definitions
                if t["name"] in custom["allowed_tools"] and t["name"] != "agent"
            ]
        else:
            # 未声明 allowed-tools：给全量工具但禁止递归派生子 Agent
            tools = [t for t in tool_definitions if t["name"] != "agent"]
        return {"system_prompt": custom["system_prompt"], "tools": tools}

    if agent_type == "explore":
        return {"system_prompt": EXPLORE_PROMPT, "tools": _get_read_only_tools()}
    elif agent_type == "plan":
        return {"system_prompt": PLAN_PROMPT, "tools": _get_read_only_tools()}
    else:  # general（含未知类型回退）
        # 过滤掉 agent 工具：子 Agent 不能再创建子 Agent，否则递归嵌套指数级消耗 token
        return {
            "system_prompt": GENERAL_PROMPT,
            "tools": [t for t in tool_definitions if t["name"] != "agent"],
        }


# ─── 可用 Agent 类型（用于系统提示词） ─────────────────────────


def get_available_agent_types() -> list[dict[str, str]]:
    types = [
        {"name": "explore", "description": "快速、只读的代码库搜索和探索"},
        {"name": "plan", "description": "只读分析，生成结构化实现计划"},
        {"name": "general", "description": "完整工具，用于独立任务"},
    ]
    for name, defn in _discover_custom_agents().items():
        types.append({"name": name, "description": defn["description"]})
    return types


def build_agent_descriptions() -> str:
    """构建 sub-agent 描述的 prompt 片段，注入到系统提示中。

    内置三种类型已在工具描述里说明，这里只补充自定义 Agent。
    """
    types = get_available_agent_types()
    if len(types) <= 3:
        return ""  # 仅有内置类型，无需额外段落

    custom = types[3:]
    lines = ["\n# Custom Agent Types", ""]
    for t in custom:
        lines.append(f"- **{t['name']}**: {t['description']}")
    return "\n".join(lines)


def reset_agent_cache() -> None:
    """清空自定义 Agent 缓存。供测试或显式热加载使用。"""
    global _cached_custom_agents
    _cached_custom_agents = None
