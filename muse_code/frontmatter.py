"""轻量级 YAML frontmatter 解析与序列化。

只支持 key: value 形式的简单标量，不引入 PyYAML 依赖。
适用于记忆文件、技能文件等 markdown + 元数据场景。

格式：
    ---
    name: 示例名
    type: user
    ---
    正文内容...
"""

from __future__ import annotations

import re
from dataclasses import dataclass


@dataclass
class FrontmatterResult:
    """frontmatter 解析结果。

    - meta: 元数据字典
    - body: 去除头部后的正文
    - has_frontmatter: 是否存在 frontmatter 块
    """
    meta: dict[str, str]
    body: str
    has_frontmatter: bool


_FRONTMATTER_RE = re.compile(
    r"^---\s*\n(.*?)\n---\s*\n?(.*)$",
    re.DOTALL,
)


def parse_frontmatter(content: str) -> FrontmatterResult:
    """从 markdown 字符串中解析出 frontmatter 字典 + 正文。

    无 frontmatter 时返回 has_frontmatter=False，meta={}, body=原内容。
    """
    if not content.startswith("---"):
        return FrontmatterResult(meta={}, body=content, has_frontmatter=False)

    match = _FRONTMATTER_RE.match(content)
    if not match:
        return FrontmatterResult(meta={}, body=content, has_frontmatter=False)

    yaml_block, body = match.group(1), match.group(2)
    meta: dict[str, str] = {}
    for line in yaml_block.split("\n"):
        line = line.strip()
        if not line or line.startswith("#"):
            continue
        if ":" not in line:
            continue
        key, _, val = line.partition(":")
        key = key.strip()
        val = val.strip()
        # 去除引号
        if (val.startswith('"') and val.endswith('"')) or (val.startswith("'") and val.endswith("'")):
            val = val[1:-1]
        meta[key] = val

    return FrontmatterResult(meta=meta, body=body, has_frontmatter=True)


def format_frontmatter(meta: dict[str, str], body: str) -> str:
    """把 meta + body 序列化为带 frontmatter 的 markdown 字符串。

    值中含特殊字符（冒号、引号、换行）时自动加双引号转义。
    """
    lines = ["---"]
    for key, val in meta.items():
        s = str(val)
        needs_quote = (
            ":" in s or "\n" in s or '"' in s or s != s.strip()
            or s.lower() in ("true", "false", "null", "yes", "no")
        )
        if needs_quote:
            escaped = s.replace("\\", "\\\\").replace('"', '\\"').replace("\n", "\\n")
            lines.append(f'{key}: "{escaped}"')
        else:
            lines.append(f"{key}: {s}")
    lines.append("---")
    lines.append("")
    lines.append(body.lstrip("\n"))
    return "\n".join(lines)
