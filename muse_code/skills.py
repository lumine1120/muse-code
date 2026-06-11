"""技能系统 — 发现、解析和执行 .claude/skills/<name>/SKILL.md

技能 = "AI Shell 脚本"：把一段 prompt 模板封装成可复用模块。
用户定义一次（写一个 SKILL.md），可以通过两条路径反复触发：

  路径 1（用户主动）：在 REPL 输入 `/<skill_name> <args>`
  路径 2（模型自动）：模型根据 when_to_use 判断后调用 `skill` 工具

两条路径最终汇合到同一个 `resolve_skill_prompt` —— 把模板里的
`$ARGUMENTS` 和 `${CLAUDE_SKILL_DIR}` 替换好后作为指令给模型执行。

发现规则：
  - 用户级（低优先级）：~/.claude/skills/<name>/SKILL.md
  - 项目级（高优先级）：./.claude/skills/<name>/SKILL.md  ← 同名覆盖用户级

支持两种 context 模式：
  - inline（默认）：把展开后的 prompt 注入当前对话
  - fork（占位）：创建独立子 Agent 执行（本项目 subagent 模块仍是占位，
                  当前 fork 行为退化为 inline；保留字段语义不变，
                  等 subagent 实现完成后无缝升级）
"""

from __future__ import annotations

import json
import re
from dataclasses import dataclass
from pathlib import Path

from .frontmatter import parse_frontmatter

# ─── 类型 ──────────────────────────────────────────────────


@dataclass
class SkillDefinition:
    """单个 SKILL.md 解析后的技能定义。"""
    name: str
    description: str
    when_to_use: str | None = None
    allowed_tools: list[str] | None = None
    user_invocable: bool = True
    context: str = "inline"           # "inline" | "fork"
    prompt_template: str = ""         # frontmatter 之后的正文模板
    source: str = "project"           # "project" | "user"
    skill_dir: str = ""               # 技能所在目录的绝对路径


# ─── 发现 ──────────────────────────────────────────────────

# 模块级缓存：技能内容在会话中很少变化，启动时扫描一次即可。
# 测试或热加载场景调 reset_skill_cache() 清空。
_cached_skills: list[SkillDefinition] | None = None


def discover_skills() -> list[SkillDefinition]:
    """扫描两个来源加载所有技能，按"项目级覆盖用户级"合并。

    用 dict[name] = skill 自然实现优先级：先 user 后 project，
    同名 key 被后者覆盖；最终 dict.values() 即可得到去重列表。
    """
    global _cached_skills
    if _cached_skills is not None:
        return _cached_skills

    skills: dict[str, SkillDefinition] = {}

    # 用户级（先加载 → 低优先级）
    _load_skills_from_dir(Path.home() / ".claude" / "skills", "user", skills)
    # 项目级（后加载 → 高优先级覆盖）
    _load_skills_from_dir(Path.cwd() / ".claude" / "skills", "project", skills)

    _cached_skills = list(skills.values())
    return _cached_skills


def _load_skills_from_dir(
    base_dir: Path, source: str, skills: dict[str, SkillDefinition],
) -> None:
    """扫描 base_dir 下每个子目录的 SKILL.md，解析后塞进 skills 字典。"""
    if not base_dir.is_dir():
        return
    for entry in base_dir.iterdir():
        if not entry.is_dir():
            continue
        skill_file = entry / "SKILL.md"
        if not skill_file.exists():
            continue
        skill = _parse_skill_file(skill_file, source, str(entry))
        if skill:
            skills[skill.name] = skill


def _parse_skill_file(
    file_path: Path, source: str, skill_dir: str,
) -> SkillDefinition | None:
    """解析单个 SKILL.md：frontmatter 当元数据，正文当 prompt 模板。"""
    try:
        raw = file_path.read_text()
        result = parse_frontmatter(raw)
        meta = result.meta

        # 兼容：name 缺省时用目录名
        name = meta.get("name") or file_path.parent.name or "unknown"

        # 字符串 "false" 才禁用，其他都视为允许用户调用
        user_invocable = meta.get("user-invocable", "true") != "false"

        # 只有显式声明 fork 才走 fork，其他默认 inline
        context = "fork" if meta.get("context") == "fork" else "inline"

        # allowed-tools 同时支持 JSON 数组语法和逗号分隔语法
        allowed_tools: list[str] | None = None
        if "allowed-tools" in meta:
            raw_tools = meta["allowed-tools"]
            if raw_tools.strip().startswith("["):
                try:
                    allowed_tools = json.loads(raw_tools)
                except Exception:
                    allowed_tools = [s.strip() for s in raw_tools.strip("[]").split(",")]
            else:
                allowed_tools = [s.strip() for s in raw_tools.split(",") if s.strip()]

        return SkillDefinition(
            name=name,
            description=meta.get("description", ""),
            when_to_use=meta.get("when_to_use") or meta.get("when-to-use"),
            allowed_tools=allowed_tools,
            user_invocable=user_invocable,
            context=context,
            prompt_template=result.body,
            source=source,
            skill_dir=skill_dir,
        )
    except Exception:
        return None


# ─── 解析 ─────────────────────────────────────────────────


def get_skill_by_name(name: str) -> SkillDefinition | None:
    """按名称查找技能。线性扫描，技能数量通常 < 100，无需建索引。"""
    for s in discover_skills():
        if s.name == name:
            return s
    return None


def resolve_skill_prompt(skill: SkillDefinition, args: str) -> str:
    """把 prompt 模板里的占位符替换成实参。

    支持的占位符：
      $ARGUMENTS / ${ARGUMENTS}  → 用户传入的参数字符串
      ${CLAUDE_SKILL_DIR}        → 技能目录绝对路径（让 prompt 引用同目录的资源文件）

    注意：故意不实现 `` !`shell` `` 内联执行——那是 Claude Code 的特性，
    教学项目中安全收益不值得增加复杂度。
    """
    prompt = skill.prompt_template
    prompt = re.sub(r"\$ARGUMENTS|\$\{ARGUMENTS\}", args, prompt)
    prompt = prompt.replace("${CLAUDE_SKILL_DIR}", skill.skill_dir)
    return prompt


def execute_skill(skill_name: str, args: str) -> dict | None:
    """两条调用路径都汇聚到这里：返回展开后的 prompt + 元数据。

    返回 None 表示技能不存在。返回 dict 包含：
      - prompt：替换占位符后的指令文本
      - allowed_tools：可选的工具白名单
      - context：inline / fork
      - skill：原始 SkillDefinition（fork 模式下子代理需要它）
    """
    skill = get_skill_by_name(skill_name)
    if not skill:
        return None
    return {
        "prompt": resolve_skill_prompt(skill, args),
        "allowed_tools": skill.allowed_tools,
        "context": skill.context,
        "skill": skill,
    }


# ─── 系统提示词段落 ────────────────────────────────────────


def build_skill_descriptions() -> str:
    """生成注入主 system prompt 的"可用技能"段落。

    分两组展示：
      1. 用户可调用：列出 /name 形式 + when_to_use（用户和模型都看）
      2. 仅模型自动：列出 name + when_to_use（用户不能直接 /调用）

    末尾告诉模型可以通过 skill 工具显式调用——这一句很关键，
    没有它模型不知道有这个工具能用。
    """
    skills = discover_skills()
    if not skills:
        return ""

    lines = ["# 可用技能", ""]
    invocable = [s for s in skills if s.user_invocable]
    auto_only = [s for s in skills if not s.user_invocable]

    if invocable:
        lines.append("用户可调用技能（用户输入 /<名称> 来调用）：")
        for s in invocable:
            lines.append(f"- **/{s.name}**: {s.description}")
            if s.when_to_use:
                lines.append(f"  使用时机：{s.when_to_use}")
        lines.append("")

    if auto_only:
        lines.append("自动调用技能（在适当时使用 skill 工具）：")
        for s in auto_only:
            lines.append(f"- **{s.name}**: {s.description}")
            if s.when_to_use:
                lines.append(f"  使用时机：{s.when_to_use}")
        lines.append("")

    lines.append("要以编程方式调用技能，请使用 `skill` 工具并传入技能名称和可选参数。")
    return "\n".join(lines)


def reset_skill_cache() -> None:
    """清空缓存。供测试或显式热加载使用。"""
    global _cached_skills
    _cached_skills = None
