"""记忆系统 — 4 类型文件记忆 + MEMORY.md 索引 + sideQuery 语义召回。

核心设计：
- **基于文件**：每条记忆是一个独立 markdown 文件（YAML frontmatter + 正文），
  好处是任何编辑器都能查看/修改，与 Agent 解耦。
- **项目隔离**：用 sha256(cwd)[:16] 哈希做项目空间，同一目录始终映射到同一记忆库。
- **4 种封闭类型**：user / feedback / project / reference，防止标签膨胀导致召回模糊。
- **双轨加载**：
    1. 索引（MEMORY.md）始终注入 system prompt，让模型知道有什么
    2. 语义召回按需取详细内容，不污染主上下文
- **异步预取**：用户输入瞬间启动记忆召回，与第一次模型调用并行，零额外延迟。
"""

from __future__ import annotations

import asyncio
import hashlib
import json
import re
import time
from datetime import datetime, timezone
from pathlib import Path
from typing import Any, Awaitable, Callable

from .frontmatter import parse_frontmatter, format_frontmatter

# ─── 类型定义 ──────────────────────────────────────────────

# sideQuery 是一个轻量级的"侧通道"模型调用：传入 system + user_message，
# 返回模型的文本响应。不带工具、不进入主对话历史。用于做记忆筛选这种
# 不该污染主对话的辅助任务。
SideQueryFn = Callable[[str, str], Awaitable[str]]

VALID_TYPES = {"user", "feedback", "project", "reference"}

# ─── 容量上限（防御性常量）──────────────────────────────────
# 这些常量都是真实场景中踩坑总结的：曾出现 197KB 内容塞在 200 行内的案例，
# 单维度限制不够，所以加了字节双保险。
MAX_INDEX_LINES = 200
MAX_INDEX_BYTES = 25_000
MAX_MEMORY_FILES = 200
MAX_MEMORY_BYTES_PER_FILE = 4096
MAX_SESSION_MEMORY_BYTES = 60 * 1024  # 单会话累计召回不超过 60KB
MAX_SELECTED_MEMORIES = 5             # sideQuery 单次最多选 5 条
HEADER_SCAN_LINES = 30                # 扫描记忆头部时只读前 30 行


# ─── 数据类 ────────────────────────────────────────────────


class MemoryEntry:
    """完整记忆条目（含正文）。"""
    __slots__ = ("name", "description", "type", "filename", "content")

    def __init__(self, name: str, description: str, type: str, filename: str, content: str):
        self.name = name
        self.description = description
        self.type = type
        self.filename = filename
        self.content = content


class MemoryHeader:
    """轻量记忆头部（不含正文，用于清单展示）。"""
    __slots__ = ("filename", "file_path", "mtime_ms", "description", "type")

    def __init__(self, filename: str, file_path: str, mtime_ms: float,
                 description: str | None, type: str | None):
        self.filename = filename
        self.file_path = file_path
        self.mtime_ms = mtime_ms
        self.description = description
        self.type = type


class RelevantMemory:
    """语义召回返回的相关记忆（含截断后的正文 + 时效头）。"""
    __slots__ = ("path", "content", "mtime_ms", "header")

    def __init__(self, path: str, content: str, mtime_ms: float, header: str):
        self.path = path
        self.content = content
        self.mtime_ms = mtime_ms
        self.header = header


# ─── 路径与命名 ────────────────────────────────────────────


def _project_hash() -> str:
    """同一 cwd 始终映射到同一记忆空间。"""
    return hashlib.sha256(str(Path.cwd()).encode()).hexdigest()[:16]


def get_memory_dir() -> Path:
    """记忆目录：~/.muse/projects/{hash}/memory/"""
    d = Path.home() / ".muse" / "projects" / _project_hash() / "memory"
    d.mkdir(parents=True, exist_ok=True)
    return d


def _get_index_path() -> Path:
    return get_memory_dir() / "MEMORY.md"


def _slugify(text: str) -> str:
    """文件名安全化：小写 + 非字母数字替换为下划线 + 截断 40 字符。"""
    s = re.sub(r"[^a-z0-9]+", "_", text.lower()).strip("_")
    return s[:40] or "memory"


# ─── 增删改查 ───────────────────────────────────────────────


def list_memories() -> list[MemoryEntry]:
    """列出所有记忆，按修改时间倒序。"""
    d = get_memory_dir()
    entries: list[MemoryEntry] = []
    for f in sorted(d.glob("*.md")):
        if f.name == "MEMORY.md":
            continue
        try:
            result = parse_frontmatter(f.read_text())
            meta = result.meta
            if not meta.get("name") or not meta.get("type"):
                continue
            t = meta["type"] if meta["type"] in VALID_TYPES else "project"
            entries.append(MemoryEntry(
                name=meta["name"],
                description=meta.get("description", ""),
                type=t,
                filename=f.name,
                content=result.body,
            ))
        except Exception:
            continue
    entries.sort(key=lambda e: (d / e.filename).stat().st_mtime, reverse=True)
    return entries


def save_memory(name: str, description: str, type: str, content: str) -> str:
    """显式 API：保存一条记忆并自动重建索引。返回文件名。
    
    通常 Agent 通过 write_file 工具直接写文件触发自动索引重建，
    这个函数主要用于 REPL 命令或测试场景。
    """
    if type not in VALID_TYPES:
        type = "project"
    d = get_memory_dir()
    filename = f"{type}_{_slugify(name)}.md"
    text = format_frontmatter(
        {"name": name, "description": description, "type": type},
        content,
    )
    (d / filename).write_text(text)
    update_memory_index()
    return filename


def delete_memory(filename: str) -> bool:
    """删除一条记忆，返回是否成功。"""
    filepath = get_memory_dir() / filename
    if not filepath.exists():
        return False
    filepath.unlink()
    update_memory_index()
    return True


# ─── 索引（MEMORY.md）─────────────────────────────────────


def update_memory_index() -> None:
    """重建 MEMORY.md。每条记忆一行链接，紧凑格式便于注入 prompt。"""
    memories = list_memories()
    lines = ["# Memory Index", ""]
    for m in memories:
        desc = m.description or "(no description)"
        lines.append(f"- **[{m.name}]({m.filename})** ({m.type}) — {desc}")
    _get_index_path().write_text("\n".join(lines))


def load_memory_index() -> str:
    """读取索引文件，做行 + 字节双截断。
    
    双截断的必要性：单看行数有可能放进单行极长的内容（曾踩坑 197KB 在 200 行内），
    单看字节又会从一行中间切断破坏可读性。两个维度都设上限最稳。
    """
    index_path = _get_index_path()
    if not index_path.exists():
        return ""
    content = index_path.read_text()

    # 第一道：按行截断（保持完整条目）
    lines = content.split("\n")
    if len(lines) > MAX_INDEX_LINES:
        content = "\n".join(lines[:MAX_INDEX_LINES]) + "\n\n[... truncated, too many memory entries ...]"

    # 第二道：按字节截断（防御异常长行）
    if len(content.encode()) > MAX_INDEX_BYTES:
        content = content[:MAX_INDEX_BYTES] + "\n\n[... truncated, index too large ...]"

    return content


# ─── 头部扫描（轻量）──────────────────────────────────────


def scan_memory_headers() -> list[MemoryHeader]:
    """轻量扫描所有记忆的头部，不读正文。
    
    用于：sideQuery 召回时把所有记忆的"目录"喂给模型选择。
    只读前 30 行（足够覆盖 frontmatter），避免大文件拖慢扫描。
    """
    d = get_memory_dir()
    headers: list[MemoryHeader] = []
    for f in d.glob("*.md"):
        if f.name == "MEMORY.md":
            continue
        try:
            stat = f.stat()
            raw = f.read_text()
            head = "\n".join(raw.split("\n")[:HEADER_SCAN_LINES])
            result = parse_frontmatter(head)
            meta = result.meta
            t = meta.get("type")
            headers.append(MemoryHeader(
                filename=f.name,
                file_path=str(f),
                mtime_ms=stat.st_mtime * 1000,
                description=meta.get("description"),
                type=t if t in VALID_TYPES else None,
            ))
        except Exception:
            continue
    headers.sort(key=lambda h: h.mtime_ms, reverse=True)
    return headers[:MAX_MEMORY_FILES]


def format_memory_manifest(headers: list[MemoryHeader]) -> str:
    """把头部列表格式化为紧凑清单：每条记忆一行，喂给 sideQuery 选择器。"""
    lines = []
    for h in headers:
        tag = f"[{h.type}] " if h.type else ""
        ts = datetime.fromtimestamp(h.mtime_ms / 1000, tz=timezone.utc).isoformat()
        if h.description:
            lines.append(f"- {tag}{h.filename} ({ts}): {h.description}")
        else:
            lines.append(f"- {tag}{h.filename} ({ts})")
    return "\n".join(lines)


# ─── 记忆时效 / 新鲜度 ────────────────────────────────────


def memory_age(mtime_ms: float) -> str:
    """返回人类可读的时效描述。"""
    days = max(0, int((time.time() * 1000 - mtime_ms) / 86_400_000))
    if days == 0:
        return "today"
    if days == 1:
        return "yesterday"
    return f"{days} days ago"


def memory_freshness_warning(mtime_ms: float) -> str:
    """超过 1 天的记忆附加过期警告。
    
    动机：记忆是时间点观察，描述代码或项目状态的内容会过时。模型不知道这点，
    会把陈旧记忆当事实。明确警告促使模型在引用前验证。
    """
    days = max(0, int((time.time() * 1000 - mtime_ms) / 86_400_000))
    if days <= 1:
        return ""
    return (
        f"This memory is {days} days old. Memories are point-in-time observations, "
        "not live state — descriptions of code behavior may be stale. "
        "Verify against current code before treating as fact."
    )


# ─── sideQuery 语义召回 ───────────────────────────────────


SELECT_MEMORIES_PROMPT = """你正在为 AI 编程助手选择有用的记忆。你将收到用户的查询和可用记忆文件的列表（包含文件名和描述）。

返回一个 JSON 对象，其中 "selected_memories" 数组包含明显有用的记忆文件名（最多 5 个）。仅包含你确信会有帮助的记忆。
- 如果不确定某条记忆是否有用，不要包含它。
- 如果没有记忆明显有用，返回空数组。
- 严格只输出 JSON，不要其他文字。

示例输出：
{"selected_memories": ["user_prefers_concise_output.md", "project_auth_q2.md"]}"""


async def select_relevant_memories(
    query: str,
    side_query: SideQueryFn,  # 一个小模型的client，调用时传入用户查询和记忆清单，返回模型的文本响应
    already_surfaced: set[str],
) -> list[RelevantMemory]:
    """用 sideQuery 让模型按语义选择最相关的记忆，最多 5 条。
    
    比关键词搜索更智能：用户问"我之前说过怎么部署吗"能匹配到"项目部署清单"，
    哪怕字面不重合。代价是一次额外 sideQuery 调用（256 tokens 左右）。
    """
    headers = scan_memory_headers()
    if not headers:
        return []

    # 跳过本会话已展示过的，避免重复打扰
    candidates = [h for h in headers if h.file_path not in already_surfaced]
    if not candidates:
        return []

    manifest = format_memory_manifest(candidates)

    try:
        text = await side_query(
            SELECT_MEMORIES_PROMPT,
            f"Query: {query}\n\nAvailable memories:\n{manifest}",
        )

        # 容错：从可能带说明文字的响应中抽取 JSON
        match = re.search(r"\{[\s\S]*\}", text)
        if not match:
            return []
        parsed = json.loads(match.group(0))
        selected_filenames = set(parsed.get("selected_memories", []))

        selected = [h for h in candidates if h.filename in selected_filenames][:MAX_SELECTED_MEMORIES]

        result: list[RelevantMemory] = []
        for h in selected:
            content = Path(h.file_path).read_text()
            # 单文件 4KB 截断：避免某条记忆过大耗光预算
            if len(content.encode()) > MAX_MEMORY_BYTES_PER_FILE:
                content = content[:MAX_MEMORY_BYTES_PER_FILE] + "\n\n[... truncated, memory file too large ...]"
            freshness = memory_freshness_warning(h.mtime_ms)
            header_text = (
                f"{freshness}\n\nMemory: {h.file_path}:" if freshness
                else f"Memory (saved {memory_age(h.mtime_ms)}): {h.file_path}:"
            )
            result.append(RelevantMemory(
                path=h.file_path, content=content,
                mtime_ms=h.mtime_ms, header=header_text,
            ))
        return result
    except asyncio.CancelledError:
        return []
    except Exception:
        # 召回失败不能影响主对话，吞掉异常即可
        return []


# ─── 异步预取（关键性能优化）─────────────────────────────


class MemoryPrefetch:
    """异步召回任务句柄。
    
    主对话不应等待召回完成。这个句柄让主循环用 settled 非阻塞轮询，
    完成后再消费结果注入到下一次 API 调用前。
    """
    def __init__(self, task: asyncio.Task):
        self.task = task
        self.consumed = False

    @property
    def settled(self) -> bool:
        return self.task.done()


def start_memory_prefetch(
    query: str,
    side_query: SideQueryFn,
    already_surfaced: set[str],
    session_memory_bytes: int,
) -> MemoryPrefetch | None:
    """启动异步记忆召回。返回句柄；不满足触发条件返回 None。
    
    三个门控：
      1. 多词查询才触发（单词太短，sideQuery 选不准）
      2. 会话累计召回 < 60KB（防止整个对话被记忆撑爆）
      3. 必须存在 .md 记忆文件
    """
    if not re.search(r"\s", query.strip()):
        return None
    if session_memory_bytes >= MAX_SESSION_MEMORY_BYTES:
        return None

    d = get_memory_dir()
    has_memories = any(f.suffix == ".md" and f.name != "MEMORY.md" for f in d.iterdir())
    if not has_memories:
        return None

    task = asyncio.create_task(
        select_relevant_memories(query, side_query, already_surfaced)
    )
    return MemoryPrefetch(task)


def format_memories_for_injection(memories: list[RelevantMemory]) -> str:
    """把召回的记忆包装成 <system-reminder> 注入用户消息。
    
    用 system-reminder 而不是 system role：
    - 时序对：召回是用户输入触发的，逻辑上属于"用户上下文增强"
    - 兼容性：OpenAI/Anthropic 都允许在 user 消息里嵌入提示
    - 显眼度：模型对 system-reminder 标签敏感度较高
    """
    parts = [
        f"<system-reminder>\n{m.header}\n\n{m.content}\n</system-reminder>"
        for m in memories
    ]
    return "\n\n".join(parts)


# ─── 系统提示词段落 ──────────────────────────────────────


def build_memory_prompt_section() -> str:
    """构建注入主 system prompt 的"记忆系统说明 + 当前索引"段落。
    
    教模型 3 件事：
      1. 怎么分类（4 种封闭类型）
      2. 怎么操作（write_file 写到 memory_dir，索引自动更新）
      3. 不该记什么（代码、git 历史、可推导信息）
    最后附上当前索引让模型知道现有记忆有哪些。
    """
    index = load_memory_index()
    memory_dir = str(get_memory_dir())

    body = f"""# 记忆系统

你拥有一个持久的、基于文件的记忆系统，位于 `{memory_dir}`。

## 记忆类型（封闭分类，禁止使用其他类型）
- **user**：用户角色、偏好、知识水平
- **feedback**：用户的纠正和肯定（必须包含 Why + How to apply）
- **project**：进行中的工作、目标、截止日期、决策
- **reference**：外部资源指针（URL、工具、仪表盘）

## 如何保存记忆
使用 write_file 工具创建带有 YAML frontmatter 的记忆文件：

```markdown
---
name: 记忆名称
description: 一行描述
type: user|feedback|project|reference
---
记忆内容写在这里。
```

保存路径：`{memory_dir}/{{type}}_{{slugified_name}}.md`
当你写入记忆目录时，MEMORY.md 索引会自动更新——请勿手动维护索引。

## 不应保存的内容
- 代码模式或架构（直接读代码即可）
- Git 历史（用 git log）
- 临时任务细节（任务结束就过时）
- 可从当前项目状态推导的任何信息

## 何时召回
当用户要求记住、回忆，或当前查询与之前的上下文相关时。系统会自动语义召回相关记忆。
"""

    if index:
        body += f"\n## 当前记忆索引\n{index}"
    else:
        body += "\n（尚未保存任何记忆。）"

    return body
