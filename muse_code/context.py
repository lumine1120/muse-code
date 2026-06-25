"""上下文管理模块 — 6 层分级压缩管道

防止对话历史超出 LLM 上下文窗口：
  Layer 0:   truncate_result — >50K chars 硬截断，保留头尾（在 tools.py）
  Layer 0.5: persist_large_result — >30KB 工具结果写入磁盘，保留 200 行预览
  Layer 1:   budget_trim — 动态缩减工具结果（50%/70% 双阈值）
  Layer 2:   snip — 替换过时的工具结果（同文件去重，保留最近 3 个）
  Layer 2.5: microcompact — 缓存冷启动激进清理（5 分钟空闲触发）
  Layer 3:   auto_compact — 全量摘要压缩（85% 窗口利用率触发）

触发时机:
  - 工具执行后 → Layer 0 + Layer 0.5（执行即触发）
  - API 调用前  → Layer 1 + Layer 2 + Layer 2.5（零 API 成本）
  - 轮次边界   → Layer 3 (auto_compact)
  - 手动 /compact → 强制 Layer 3

Token 统计: 用 API 返回的 usage 锚点 + 4 chars ≈ 1 token 粗估
"""

from __future__ import annotations

import hashlib
import time
from pathlib import Path
from typing import Any

# ─── 持久化配置 ────────────────────────────────────
PERSIST_THRESHOLD_BYTES = 30 * 1024  # 30 KB
PERSIST_PREVIEW_LINES = 200
PERSIST_DIR = Path.home() / ".muse" / "tool-results"

# ─── Budget 配置 ───────────────────────────────────
BUDGET_THRESHOLD_1 = 0.50  # 50% 窗口利用率 → 30K 预算
BUDGET_THRESHOLD_2 = 0.70  # 70% 窗口利用率 → 15K 预算
BUDGET_CHARS_1 = 30000
BUDGET_CHARS_2 = 15000

# ─── Snip 配置 ─────────────────────────────────────
SNIP_UTILIZATION_THRESHOLD = 0.60
SNIP_KEEP_RECENT = 3
SNIPPABLE_TOOLS = {"read_file", "grep_search", "list_files", "run_shell"}
SNIP_PLACEHOLDER = "[Content snipped - re-read if needed]"

# ─── Microcompact 配置 ─────────────────────────────
MICROCOMPACT_IDLE_S = 5 * 60  # 5 分钟空闲触发
MICROCOMPACT_CLEARED = "[Old result cleared]"

# ─── Auto-compact 配置 ─────────────────────────────
COMPACT_UTILIZATION_THRESHOLD = 0.85
COMPACT_RESERVED_TOKENS = 20000  # 预留给新一轮输入/输出

# ─── Context Collapse 配置（Layer 4 读时投影）─────────
# 参考 Claude Code：不修改原始消息，只在 API 调用时深拷贝 + 压缩副本。
# 触发条件：利用率 >= 90%（比 Budget Trim 的 50% 阈值更激进）
COLLAPSE_UTILIZATION_THRESHOLD = 0.90
COLLAPSE_BUDGET_CHARS = 8000  # Collapse 模式下的单工具结果预算（比 BUDGET_CHARS_2 的 15K 更激进）
COLLAPSE_KEEP_RECENT = 2     # Collapse 保留最近 2 个同文件结果（比 SNIP_KEEP_RECENT 的 3 更少）

# ─── 上下文窗口（按模型）────────────────────────────
DEFAULT_CONTEXT_WINDOW = 128_000
CONTEXT_WINDOWS: dict[str, int] = {
    # GLM 系列
    "GLM-4.7-Flash": 128_000,
    "GLM-4.5": 128_000,
    "GLM-4-Plus": 128_000,
    # Claude 系列
    "claude-3-5-sonnet-20241022": 200_000,
    "claude-3-opus-20240229": 200_000,
    "claude-3-sonnet-20240229": 200_000,
    "claude-3-haiku-20240307": 200_000,
    # GPT 系列
    "gpt-4": 128_000,
    "gpt-4-turbo": 128_000,
    "gpt-4o": 128_000,
    "gpt-4o-mini": 128_000,
    "gpt-3.5-turbo": 16_384,
    # DeepSeek
    "deepseek-chat": 128_000,
    "deepseek-coder": 128_000,
}


def get_context_window(model: str) -> int:
    """根据模型名获取上下文窗口大小 (tokens)"""
    # 精确匹配
    if model in CONTEXT_WINDOWS:
        return CONTEXT_WINDOWS[model]
    # 前缀匹配（处理模型版本号）
    for prefix, window in CONTEXT_WINDOWS.items():
        if model.startswith(prefix):
            return window
    return DEFAULT_CONTEXT_WINDOW


def get_effective_window(model: str) -> int:
    """有效窗口 = 模型上下文窗口 - 预留空间"""
    return max(get_context_window(model) - COMPACT_RESERVED_TOKENS, 10000)


# ═══════════════════════════════════════════════════════════════
# Token 统计
# ═══════════════════════════════════════════════════════════════


class TokenCounter:
    """追踪 Token 使用量。
    
    用 API 返回的 usage 做锚点，新增消息用 4 chars ≈ 1 token 粗估。
    """

    def __init__(self):
        self.total_input_tokens = 0
        self.total_output_tokens = 0
        self.last_input_tokens = 0  # 最近一次 API 调用的输入 token 数
        self.last_output_tokens = 0
        self.last_api_call_time: float | None = None
        # 估算：在未收到 API 返回的 usage 之前，用字符数粗估
        self._estimated_messages_chars = 0
        self._estimated_since_last_anchor = 0

    def record_usage(self, input_tokens: int, output_tokens: int) -> None:
        """用 API 返回的 usage 更新锚点"""
        self.total_input_tokens += input_tokens
        self.total_output_tokens += output_tokens
        self.last_input_tokens = input_tokens
        self.last_output_tokens = output_tokens
        self.last_api_call_time = time.time()
        # 重置粗估算计数
        self._estimated_messages_chars = 0
        self._estimated_since_last_anchor = 0

    def add_estimated_message(self, text: str) -> None:
        """添加一条消息的粗估算（4 chars ≈ 1 token）"""
        self._estimated_messages_chars += len(text)
        self._estimated_since_last_anchor += len(text)

    def estimate_current_input(self) -> int:
        """估算当前上下文的 token 数
        
        用最近一次 API usage 作为锚点 + 此后新增消息的粗估
        """
        est_new_tokens = self._estimated_since_last_anchor // 4
        return self.last_input_tokens + est_new_tokens

    def utilization(self, model: str) -> float:
        """返回上下文利用率（0 到 1）"""
        window = get_context_window(model)
        if window <= 0:
            return 0.0
        return min(self.estimate_current_input() / window, 1.0)

    def effective_utilization(self, model: str) -> float:
        """返回有效窗口利用率（扣除预留空间）"""
        effective = get_effective_window(model)
        if effective <= 0:
            return 0.0
        return min(self.estimate_current_input() / effective, 1.0)


# ═══════════════════════════════════════════════════════════════
# Layer 0.5: 大结果持久化
# ═══════════════════════════════════════════════════════════════


def persist_large_result(tool_name: str, result: str) -> str:
    """超过 30KB 的工具结果写入磁盘，返回预览。
    
    在上下文保留 200 行预览 + 持久化文件路径，
    模型后续可用 read_file 读取完整内容。
    """
    if len(result.encode("utf-8", errors="replace")) <= PERSIST_THRESHOLD_BYTES:
        return result

    PERSIST_DIR.mkdir(parents=True, exist_ok=True)

    # 生成唯一文件名：时间戳 + 工具名 + 内容哈希
    content_hash = hashlib.sha256(result.encode("utf-8", errors="replace")).hexdigest()[:12]
    filename = f"{int(time.time() * 1000)}-{tool_name}-{content_hash}.txt"
    filepath = PERSIST_DIR / filename

    try:
        filepath.write_text(result, encoding="utf-8", errors="replace")
    except Exception:
        return result  # 写磁盘失败时原样返回

    lines = result.split("\n")
    preview = "\n".join(lines[:PERSIST_PREVIEW_LINES])
    size_kb = len(result.encode("utf-8", errors="replace")) / 1024

    return (
        f"[Result too large ({size_kb:.1f} KB, {len(lines)} lines). "
        f"Full output saved to {filepath}. "
        f"You can use read_file to see the full result.]\n\n"
        f"Preview (first {PERSIST_PREVIEW_LINES} lines):\n{preview}"
    )


# ═══════════════════════════════════════════════════════════════
# Layer 1: Budget — 动态缩减工具结果
# ═══════════════════════════════════════════════════════════════


def budget_trim_text(text: str, budget: int) -> str:
    """按预算截断文本，保留头尾。

    当文本超过 budget 字符时，保留开头和结尾各约 (budget-80)//2 个字符，
    中间替换为截断提示信息（80 字符）。这样模型至少能看到文本的开头和结尾，
    保留关键的上下文信息（开头通常是命令输出摘要，结尾通常是最新内容）。

    Args:
        text: 原始文本内容
        budget: 截断后的目标字符数上限

    Returns:
        如果原文本未超预算，原样返回；否则返回 "头部 + 截断提示 + 尾部" 的拼接文本
    """
    if len(text) <= budget:
        return text
    # 计算首尾各保留的字符数：(总预算 - 截断提示字符) / 2
    keep_each = (budget - 80) // 2
    return (
        text[:keep_each]
        # 截断提示，告知被裁减了多少字符
        + f"\n\n[... budgeted: {len(text) - keep_each * 2} chars truncated ...]\n\n"
        + text[-keep_each:]
    )


def apply_budget_openai(
    messages: list[dict[str, Any]],
    utilization: float,
) -> None:
    """对 OpenAI 格式消息应用 Budget 截断"""
    if utilization < BUDGET_THRESHOLD_1:
        return
    budget = BUDGET_CHARS_2 if utilization > BUDGET_THRESHOLD_2 else BUDGET_CHARS_1

    for msg in messages:
        if msg.get("role") != "tool":
            continue
        content = msg.get("content", "")
        if isinstance(content, str) and len(content) > budget:
            msg["content"] = budget_trim_text(content, budget)


def apply_budget_anthropic(
    messages: list[dict[str, Any]],
    utilization: float,
) -> None:
    """对 Anthropic 格式消息应用 Budget 截断"""
    if utilization < BUDGET_THRESHOLD_1:
        return
    budget = BUDGET_CHARS_2 if utilization > BUDGET_THRESHOLD_2 else BUDGET_CHARS_1

    for msg in messages:
        if msg.get("role") != "user":
            continue
        content = msg.get("content")
        if not isinstance(content, list):
            continue
        for block in content:
            if isinstance(block, dict) and block.get("type") == "tool_result":
                text = block.get("content", "")
                if isinstance(text, str) and len(text) > budget:
                    block["content"] = budget_trim_text(text, budget)


# ═══════════════════════════════════════════════════════════════
# Layer 2: Snip — 替换过时的工具结果
# ═══════════════════════════════════════════════════════════════


def _extract_file_path(result_text: str) -> str | None:
    """尝试从工具结果文本中提取文件路径。

    当前为存根实现，始终返回 None。后续可扩展为解析 read_file 结果的
    首行（如 "File: /path/to/file.go"）来提取精确路径，从而实现更精准的
    按文件路径去重（同一文件的多次读取视为同一 key）。
    """
    # read_file 结果的第一行通常是带行号的文件内容
    # 简单策略：看内容的前 100 个字符中是否有明显路径
    lines = result_text.split("\n", 1)
    if not lines:
        return None
    return None  # 存根实现：不尝试提取路径，用内容哈希做去重


def _make_tool_key(tool_name: str, result_text: str) -> str:
    """为工具结果生成去重键（dedup key）。

    去重键决定了哪些工具结果被视为"重复"：
    - read_file：用结果前 500 字符做 SHA256 哈希（前 16 位），
      意味着读取同一文件（内容前 500 字符相同）的结果共享一个 key。
      前 500 字符通常包含文件路径声明和文件开头代码，足以区分不同文件。
    - 其他工具（grep_search / list_files / run_shell）：
      用完整结果文本的 SHA256 哈希（前 16 位）作为 key，
      意味着完全相同的输出才被视为重复。

    Returns:
        格式为 "tool_name:16位哈希" 的去重键，如 "read_file:a1b2c3d4e5f6g7h8"
    """
    # 对 read_file，保留最近几个不同文件的读取
    if tool_name == "read_file":
        # 用内容前 500 字符做粗略去重——足以区分不同文件
        content_hash = hashlib.sha256(
            result_text[:500].encode("utf-8", errors="replace")
        ).hexdigest()[:16]
        return f"read_file:{content_hash}"
    # 其他工具：只有完全相同的输出才算重复
    return f"{tool_name}:{hashlib.sha256(result_text.encode('utf-8', errors='replace')).hexdigest()[:16]}"


def apply_snip_openai(
    messages: list[dict[str, Any]],
    utilization: float,
) -> None:
    """对 OpenAI 格式消息应用 Snip 去重（Layer 2）。

    核心思路：同一去重键的工具结果，只保留最近的 N 个，更早的替换为占位符。

    去重键生成规则（见 _make_tool_key）：
    - read_file：结果前 500 字符的 SHA256 哈希 → 不同文件自然分到不同 key
    - 其他工具：完整结果文本的 SHA256 哈希 → 完全相同的输出才算重复

    当前局限：未通过 tool_call_id 反查实际的工具名，
    所有 tool 消息统一使用 tool_name="unknown" 生成 key。
    这意味着去重键为 "unknown:{full_content_hash}"，
    即：任何工具产生两次相同输出也会被去重，不仅限于同类工具之间。

    流程：
    1. 从后往前遍历消息，收集每个去重键对应的 tool 消息索引列表
    2. 对每个去重键，只保留最近 SNIP_KEEP_RECENT（默认 3）个
    3. 将其余更早的 tool 消息 content 替换为 SNIP_PLACEHOLDER

    触发条件：窗口利用率 >= SNIP_UTILIZATION_THRESHOLD（默认 60%）
    """
    if utilization < SNIP_UTILIZATION_THRESHOLD:
        return

    # 收集最近的工具结果（从后往前），同一去重键只保留最近 KEEP_RECENT 个
    # key 格式: "unknown:{sha256_full_content[:16]}"
    tool_occurrences: dict[str, list[int]] = {}  # key → [index, ...]

    for i in range(len(messages) - 1, -1, -1):
        msg = messages[i]
        if msg.get("role") != "tool":
            continue
        content = msg.get("content", "")
        if not isinstance(content, str):
            continue
        # 注意：当前未通过 tool_call_id 反查实际工具名，
        # 统一用 "unknown" 作为 tool_name
        # 可通过解析 msg["tool_call_id"] 在前面的 assistant 消息中查找对应工具名来改进
        key = _make_tool_key("unknown", content)
        if key not in tool_occurrences:
            tool_occurrences[key] = []
        tool_occurrences[key].append(i)

    # 对每个去重键，只保留最近 SNIP_KEEP_RECENT 个（indices 从后往前，越靠前越新）
    for key, indices in tool_occurrences.items():
        if len(indices) <= SNIP_KEEP_RECENT:
            continue
        # indices 是按从后往前收集的（index 越大越新），
        # indices[0] 是最新的，indices[SNIP_KEEP_RECENT:] 是更早的 → 需要 snip
        for idx in indices[SNIP_KEEP_RECENT:]:
            messages[idx]["content"] = SNIP_PLACEHOLDER


def apply_snip_anthropic(
    messages: list[dict[str, Any]],
    utilization: float,
) -> None:
    """对 Anthropic 格式消息应用 Snip 去重（Layer 2）。

    与 OpenAI 版本逻辑相同，但消息结构不同：
    Anthropic 的 tool_result 嵌套在 user 消息的 content 数组块中，
    而非独立的 tool 角色消息。

    去重键生成规则同 _make_tool_key（当前使用 tool_name="unknown"）。
    每个去重键只保留最近 SNIP_KEEP_RECENT（默认 3）个 tool_result 块，
    更早的替换为 SNIP_PLACEHOLDER。

    触发条件：窗口利用率 >= SNIP_UTILIZATION_THRESHOLD（默认 60%）
    """
    if utilization < SNIP_UTILIZATION_THRESHOLD:
        return

    # 收集所有 tool_result 块位置：(消息索引, 块索引, 去重键)
    tool_locations: list[tuple[int, int, str]] = []  # (msg_idx, block_idx, key)

    for mi, msg in enumerate(messages):
        if msg.get("role") != "user":
            continue
        content = msg.get("content")
        if not isinstance(content, list):
            continue
        for bi, block in enumerate(content):
            if isinstance(block, dict) and block.get("type") == "tool_result":
                text = block.get("content", "")
                # 截取前 200 字符用于 deup key 生成，减少哈希计算开销
                key = _make_tool_key("tool", str(text)[:200])
                tool_locations.append((mi, bi, key))

    # 按去重键分组，每组只保留最近 SNIP_KEEP_RECENT 个
    grouped: dict[str, list[tuple[int, int]]] = {}
    for mi, bi, key in tool_locations:
        if key not in grouped:
            grouped[key] = []
        grouped[key].append((mi, bi))

    for key, locations in grouped.items():
        if len(locations) <= SNIP_KEEP_RECENT:
            continue
        # locations 是从前往后排列的，倒数 SNIP_KEEP_RECENT 个保留（最新），其余 snip
        for mi, bi in locations[:-SNIP_KEEP_RECENT]:
            block = messages[mi]["content"][bi]
            if isinstance(block, dict):
                block["content"] = SNIP_PLACEHOLDER


# ═══════════════════════════════════════════════════════════════
# Layer 2.5: Microcompact — 缓存冷启动时激进清理
# ═══════════════════════════════════════════════════════════════


def apply_microcompact_openai(
    messages: list[dict[str, Any]],
    last_api_call_time: float | None,
) -> None:
    """对 OpenAI 格式消息应用 Microcompact。
    
    当空闲超过 5 分钟时，prompt cache 大概率已过期，
    此时激进清理旧工具结果没有缓存失效成本。
    除最近 3 个外，所有 tool 消息替换为 "[Old result cleared]"。
    """
    if not last_api_call_time:
        return
    if (time.time() - last_api_call_time) < MICROCOMPACT_IDLE_S:
        return

    # 收集所有未被 snip/清理过的 tool 消息索引
    tool_indices: list[int] = []
    for i, msg in enumerate(messages):
        if msg.get("role") != "tool":
            continue
        content = msg.get("content", "")
        if not isinstance(content, str):
            continue
        if content in (SNIP_PLACEHOLDER, MICROCOMPACT_CLEARED):
            continue
        tool_indices.append(i)

    # 只保留最近 KEEP_RECENT 个，其余全清
    clear_count = len(tool_indices) - SNIP_KEEP_RECENT
    for idx in tool_indices[:max(0, clear_count)]:
        messages[idx]["content"] = MICROCOMPACT_CLEARED


def apply_microcompact_anthropic(
    messages: list[dict[str, Any]],
    last_api_call_time: float | None,
) -> None:
    """对 Anthropic 格式消息应用 Microcompact。"""
    if not last_api_call_time:
        return
    if (time.time() - last_api_call_time) < MICROCOMPACT_IDLE_S:
        return

    # 收集所有未被 snip/清理过的 tool_result 块位置
    tool_locations: list[tuple[int, int]] = []
    for mi, msg in enumerate(messages):
        if msg.get("role") != "user":
            continue
        content = msg.get("content")
        if not isinstance(content, list):
            continue
        for bi, block in enumerate(content):
            if isinstance(block, dict) and block.get("type") == "tool_result":
                text = block.get("content", "")
                if text not in (SNIP_PLACEHOLDER, MICROCOMPACT_CLEARED):
                    tool_locations.append((mi, bi))

    # 只保留最近 KEEP_RECENT 个
    clear_count = len(tool_locations) - SNIP_KEEP_RECENT
    for mi, bi in tool_locations[:max(0, clear_count)]:
        block = messages[mi]["content"][bi]
        if isinstance(block, dict):
            block["content"] = MICROCOMPACT_CLEARED


# ═══════════════════════════════════════════════════════════════
# Layer 3: Auto-compact — 全量摘要压缩
# ═══════════════════════════════════════════════════════════════

COMPACT_SYSTEM_PROMPT = """You are a conversation summarizer. You MUST NOT call any tools — only return text.

Output your summary in this exact XML structure:

<analysis>
(Brief reasoning about what to include — this section will be discarded)
</analysis>
<summary>
1. Primary Request and Intent: What the user asked for
2. Key Technical Concepts: Technologies, patterns, and architecture involved
3. Files and Code Sections: File paths read or modified, with key code snippets
4. Errors and fixes: Errors encountered and how they were resolved
5. Problem Solving: Decisions made and approaches tried
6. All user messages: Enumerate EVERY user message in order, one per line — do not summarize, list each one
7. Pending Tasks: What remains to be done
8. Current Work: Be specific — exact file names, function names, and current progress
9. Optional Next Step: What should be done next
</summary>

CRITICAL: Do NOT call any tools. Do NOT ask questions. Only return the summary text."""

COMPACT_USER_PROMPT = (
    "Summarize the conversation so far using the 9-part structure above. "
    "Enumerate ALL user messages (item 6) — do not paraphrase, list each one. "
    "For Current Work (item 8), be specific about exact file paths and function names."
)

COMPACT_ASSISTANT_RESPONSE = (
    "Understood. I have the context from our previous conversation. "
    "How can I continue helping?"
)

# ─── 压缩后文件恢复配置 ─────────────────────────────────
# 参考 Claude Code：压缩后按最近活跃度恢复关键文件，
# 让 Agent 接续工作时不用重新读取已知文件。
POST_COMPACT_MAX_FILES = 5           # 最多恢复 5 个文件
POST_COMPACT_MAX_CHARS_PER_FILE = 5000  # 每个文件最多 ~5K token（≈20K chars 粗估取 5K）
POST_COMPACT_MAX_TOTAL_CHARS = 50000    # 总额不超过 ~50K token


def restore_recent_files(
    read_file_state: dict[str, float],
    max_files: int = POST_COMPACT_MAX_FILES,
    max_chars_per_file: int = POST_COMPACT_MAX_CHARS_PER_FILE,
    max_total_chars: int = POST_COMPACT_MAX_TOTAL_CHARS,
) -> str:
    """压缩后恢复最近活跃的文件内容。

    从 _read_file_state（{abs_path: mtime}）中按 mtime 降序取最近 N 个文件，
    读取内容并截断，返回一段格式化的"已恢复文件"文本。
    如果读取失败或无文件，返回空字符串。
    """
    if not read_file_state:
        return ""

    # 按 mtime 降序排序（最近修改的优先）
    sorted_paths = sorted(
        read_file_state.items(),
        key=lambda x: x[1],
        reverse=True,
    )

    parts: list[str] = []
    total_chars = 0

    for abs_path, _mtime in sorted_paths[:max_files]:
        try:
            from pathlib import Path
            p = Path(abs_path)
            if not p.is_file():
                continue
            content = p.read_text(errors="replace")
            if not content:
                continue

            # 截断单个文件
            if len(content) > max_chars_per_file:
                content = content[:max_chars_per_file] + "\n... (truncated)"

            entry = f"--- {abs_path} ---\n{content}"
            entry_len = len(entry)

            # 检查总额
            if total_chars + entry_len > max_total_chars:
                remaining = max_total_chars - total_chars
                if remaining < 200:
                    break
                entry = entry[:remaining] + "\n... (budget reached)"
                entry_len = len(entry)

            parts.append(entry)
            total_chars += entry_len

            if total_chars >= max_total_chars:
                break
        except Exception:
            continue

    if not parts:
        return ""

    return "[Recently read files restored after compact]\n\n" + "\n\n".join(parts)


# ═══════════════════════════════════════════════════════════════
# Layer 4: Context Collapse — 读时投影，不破坏原始消息
# ═══════════════════════════════════════════════════════════════


def apply_context_collapse_openai(
    messages: list[dict[str, Any]],
    utilization: float,
) -> None:
    """对 OpenAI 格式消息副本应用更激进的压缩（Context Collapse 模式）。

    与 Budget Trim/Snip 的区别：本函数在**已深拷贝的副本**上操作，
    原始消息不受影响。触发条件是利用率 >= 90%。

    激进策略：
    - 工具结果预算降到 COLLAPSE_BUDGET_CHARS（8K，比 BUDGET_CHARS_2 的 15K 更小）
    - 同文件去重保留最近 COLLAPSE_KEEP_RECENT 个（2 个，比 Snip 的 3 个更少）
    """
    # 更激进的 budget trim
    for msg in messages:
        if msg.get("role") != "tool":
            continue
        content = msg.get("content", "")
        if isinstance(content, str) and len(content) > COLLAPSE_BUDGET_CHARS:
            msg["content"] = budget_trim_text(content, COLLAPSE_BUDGET_CHARS)

    # 更激进的 snip：只保留最近 COLLAPSE_KEEP_RECENT 个
    tool_occurrences: dict[str, list[int]] = {}
    for i in range(len(messages) - 1, -1, -1):
        msg = messages[i]
        if msg.get("role") != "tool":
            continue
        content = msg.get("content", "")
        if not isinstance(content, str):
            continue
        if content in (SNIP_PLACEHOLDER, MICROCOMPACT_CLEARED):
            continue
        key = _make_tool_key("unknown", content)
        if key not in tool_occurrences:
            tool_occurrences[key] = []
        tool_occurrences[key].append(i)

    for key, indices in tool_occurrences.items():
        if len(indices) <= COLLAPSE_KEEP_RECENT:
            continue
        for idx in indices[COLLAPSE_KEEP_RECENT:]:
            messages[idx]["content"] = SNIP_PLACEHOLDER


def apply_context_collapse_anthropic(
    messages: list[dict[str, Any]],
    utilization: float,
) -> None:
    """对 Anthropic 格式消息副本应用更激进的压缩（Context Collapse 模式）。"""
    # 更激进的 budget trim
    for msg in messages:
        if msg.get("role") != "user":
            continue
        content = msg.get("content")
        if not isinstance(content, list):
            continue
        for block in content:
            if isinstance(block, dict) and block.get("type") == "tool_result":
                text = block.get("content", "")
                if isinstance(text, str) and len(text) > COLLAPSE_BUDGET_CHARS:
                    block["content"] = budget_trim_text(text, COLLAPSE_BUDGET_CHARS)

    # 更激进的 snip
    tool_locations: list[tuple[int, int, str]] = []
    for mi, msg in enumerate(messages):
        if msg.get("role") != "user":
            continue
        content = msg.get("content")
        if not isinstance(content, list):
            continue
        for bi, block in enumerate(content):
            if isinstance(block, dict) and block.get("type") == "tool_result":
                text = block.get("content", "")
                if text in (SNIP_PLACEHOLDER, MICROCOMPACT_CLEARED):
                    continue
                key = _make_tool_key("tool", str(text)[:200])
                tool_locations.append((mi, bi, key))

    grouped: dict[str, list[tuple[int, int]]] = {}
    for mi, bi, key in tool_locations:
        if key not in grouped:
            grouped[key] = []
        grouped[key].append((mi, bi))

    for key, locations in grouped.items():
        if len(locations) <= COLLAPSE_KEEP_RECENT:
            continue
        for mi, bi in locations[:-COLLAPSE_KEEP_RECENT]:
            block = messages[mi]["content"][bi]
            if isinstance(block, dict):
                block["content"] = SNIP_PLACEHOLDER


async def compact_openai(
    messages: list[dict[str, Any]],
    client: Any,
    model: str,
    read_file_state: dict[str, float] | None = None,
) -> list[dict[str, Any]]:
    """压缩 OpenAI 格式对话历史。
    
    保留 system message，用 LLM 生成 9 部分结构化摘要替换历史，
    压缩后按最近活跃度恢复关键文件。返回新的消息列表。
    """
    if len(messages) < 5:
        return messages

    system_msg = messages[0]  # 保留 system prompt
    last_msg = messages[-1]   # 可能是最新的 user 消息

    # 生成摘要
    try:
        summary_resp = await client.chat.completions.create(
            model=model,
            max_tokens=4096,  # 9 部分结构化摘要需要更大空间
            messages=[
                {"role": "system", "content": COMPACT_SYSTEM_PROMPT},
                *messages[1:-1],
                {"role": "user", "content": COMPACT_USER_PROMPT},
            ],
        )
        summary_text = (
            summary_resp.choices[0].message.content
            or "No summary available."
        )
    except Exception:
        # 摘要生成失败，使用简单截断作为后备
        return _simple_truncate_openai(messages)

    # 重建消息数组
    new_messages: list[dict[str, Any]] = [
        system_msg,
        {"role": "user", "content": f"[Previous conversation summary]\n{summary_text}"},
        {"role": "assistant", "content": COMPACT_ASSISTANT_RESPONSE},
    ]

    # 文件恢复：压缩后按最近活跃度恢复关键文件
    if read_file_state:
        restored = restore_recent_files(read_file_state)
        if restored:
            new_messages.append({"role": "user", "content": restored})
            new_messages.append({"role": "assistant", "content": "Understood. I have the restored file context. Continuing..."})

    # 只把最后一条 user 消息追回（不追 tool 消息）
    if last_msg.get("role") == "user":
        new_messages.append(last_msg)

    return new_messages


async def compact_anthropic(
    messages: list[dict[str, Any]],
    client: Any,
    model: str,
    system_prompt: str,
    read_file_state: dict[str, float] | None = None,
) -> list[dict[str, Any]]:
    """压缩 Anthropic 格式对话历史。
    
    生成 9 部分结构化摘要替换历史，压缩后恢复关键文件。
    """
    if len(messages) < 4:
        return messages

    last_msg = messages[-1]

    # 生成摘要
    try:
        summary_resp = await client.messages.create(
            model=model,
            max_tokens=4096,
            system=COMPACT_SYSTEM_PROMPT,
            messages=[
                *messages[:-1],
                {"role": "user", "content": COMPACT_USER_PROMPT},
            ],
        )
        summary_text = (
            summary_resp.content[0].text
            if summary_resp.content and summary_resp.content[0].type == "text"
            else "No summary available."
        )
    except Exception:
        return _simple_truncate_anthropic(messages)

    # 重建消息数组
    new_messages: list[dict[str, Any]] = [
        {"role": "user", "content": f"[Previous conversation summary]\n{summary_text}"},
        {"role": "assistant", "content": COMPACT_ASSISTANT_RESPONSE},
    ]

    # 文件恢复
    if read_file_state:
        restored = restore_recent_files(read_file_state)
        if restored:
            new_messages.append({"role": "user", "content": restored})
            new_messages.append({"role": "assistant", "content": "Understood. I have the restored file context. Continuing..."})

    # 只把最后一条 user 消息追回
    if last_msg.get("role") == "user":
        new_messages.append(last_msg)

    return new_messages


def _simple_truncate_openai(messages: list[dict[str, Any]]) -> list[dict[str, Any]]:
    """简单的截断式压缩（后备方案）"""
    if len(messages) <= 5:
        return messages
    system = messages[0]
    last_user = messages[-1] if messages[-1].get("role") == "user" else None

    truncated: list[dict[str, Any]] = [system]
    if last_user and last_user != system:
        truncated.append(messages[-3])  # 保留倒数第 3 条
        truncated.append(messages[-2])  # 保留倒数第 2 条
        truncated.append(last_user)
    else:
        truncated.extend(messages[-4:])
    return truncated


def _simple_truncate_anthropic(messages: list[dict[str, Any]]) -> list[dict[str, Any]]:
    """简单的截断式压缩（后备方案）"""
    if len(messages) <= 4:
        return messages
    last_user = messages[-1] if messages[-1].get("role") == "user" else None

    truncated = list(messages[-3:])
    if last_user and truncated[-1] != last_user:
        truncated.append(last_user)
    return truncated


# ═══════════════════════════════════════════════════════════════
# ContextManager — 统一上下文管理入口
# ═══════════════════════════════════════════════════════════════


class ContextManager:
    """统一上下文管理器，封装 4 层压缩管道 + Token 统计。

    用法:
        ctx = ContextManager("GLM-4.7-Flash")
        
        # 每次 API 调用前执行管道
        ctx.run_pre_call_pipeline(messages, use_openai=True)
        
        # 工具执行后持久化大结果
        result = ctx.persist_if_large("read_file", raw_result)
        
        # API 调用后更新 token 统计
        ctx.counter.record_usage(input_tokens, output_tokens)
        
        # 轮次边界检查是否需要 auto-compact
        if ctx.should_auto_compact():
            messages = await ctx.do_compact(...)
    """

    def __init__(self, model: str):
        self.model = model
        self.counter = TokenCounter()
        self._compact_failure_count = 0 # 记录连续压缩失败次数
        self._max_compact_failures = 3  # 熔断器

    @property
    def context_window(self) -> int:
        return get_context_window(self.model)

    @property
    def effective_window(self) -> int:
        return get_effective_window(self.model)

    # ─── Layer 0.5 ─────────────────────────────────

    @staticmethod
    def persist_if_large(tool_name: str, result: str) -> str:
        """持久化超大工具结果（Layer 0.5）"""
        return persist_large_result(tool_name, result)

    # ─── Layer 1+2+2.5+4 (pre-call pipeline) ─────────

    def run_pre_call_pipeline(
        self,
        messages: list[dict[str, Any]],
        use_openai: bool,
    ) -> list[dict[str, Any]]:
        """每次 API 调用前执行压缩管道，返回应传给 API 的消息列表。

        Context Collapse 设计（参考 Claude Code L4）：
        - 低利用率（<50%）：零拷贝，直接返回原始 messages
        - 中利用率（50%-90%）：深拷贝 → Budget → Snip → Microcompact，返回副本
        - 高利用率（>=90%）：深拷贝 → Budget → Snip → Microcompact → Context Collapse，返回副本

        原始 messages 永不被修改，只有 Auto-Compact（Layer 3）才是破坏性操作。
        """
        utilization = self.counter.effective_utilization(self.model)

        # 低利用率：不需要压缩，直接返回原始消息（零拷贝）
        if utilization < BUDGET_THRESHOLD_1:
            return messages

        # Context Collapse：深拷贝后在副本上压缩，不破坏原始消息
        import copy
        collapsed = copy.deepcopy(messages)

        if use_openai:
            apply_budget_openai(collapsed, utilization)
            apply_snip_openai(collapsed, utilization)
            apply_microcompact_openai(collapsed, self.counter.last_api_call_time)
            # Layer 4: 高利用率时应用更激进的压缩
            if utilization >= COLLAPSE_UTILIZATION_THRESHOLD:
                apply_context_collapse_openai(collapsed, utilization)
        else:
            apply_budget_anthropic(collapsed, utilization)
            apply_snip_anthropic(collapsed, utilization)
            apply_microcompact_anthropic(collapsed, self.counter.last_api_call_time)
            if utilization >= COLLAPSE_UTILIZATION_THRESHOLD:
                apply_context_collapse_anthropic(collapsed, utilization)

        return collapsed

    # ─── Layer 3 (turn boundary) ──────────────────

    def should_auto_compact(self) -> bool:
        """判断是否应该触发自动压缩"""
        if self._compact_failure_count >= self._max_compact_failures:
            return False  # 熔断
        return self.counter.effective_utilization(self.model) >= COMPACT_UTILIZATION_THRESHOLD

    async def do_compact_openai(
        self,
        messages: list[dict[str, Any]],
        client: Any,
        read_file_state: dict[str, float] | None = None,
    ) -> list[dict[str, Any]]:
        """执行 OpenAI 后端的全量压缩（含文件恢复）"""
        try:
            result = await compact_openai(messages, client, self.model, read_file_state)
            self.counter.last_input_tokens = 0
            self._compact_failure_count = 0
            return result
        except Exception:
            self._compact_failure_count += 1
            return _simple_truncate_openai(messages)

    async def do_compact_anthropic(
        self,
        messages: list[dict[str, Any]],
        client: Any,
        system_prompt: str,
        read_file_state: dict[str, float] | None = None,
    ) -> list[dict[str, Any]]:
        """执行 Anthropic 后端的全量压缩（含文件恢复）"""
        try:
            result = await compact_anthropic(messages, client, self.model, system_prompt, read_file_state)
            self.counter.last_input_tokens = 0
            self._compact_failure_count = 0
            return result
        except Exception:
            self._compact_failure_count += 1
            return _simple_truncate_anthropic(messages)
