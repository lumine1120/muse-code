"""权限与安全模块 — 危险命令检测、权限规则系统、统一权限检查、会话级白名单

包含四大子模块:
1. 危险命令检测 (DangerLevel + DangerPattern 增强版)
2. 权限规则系统 (用户级 + 项目级, allow + deny)
3. 会话级白名单 (SessionWhitelist)
4. 统一权限检查器 (UnifiedPermissionChecker)
"""

from __future__ import annotations

import enum
import fnmatch
import json
import os
import re
import time
from dataclasses import dataclass, field
from pathlib import Path
from typing import Optional


# ═══════════════════════════════════════════════════════════════
# 1. 危险命令检测（增强版，带风险等级）
# ═══════════════════════════════════════════════════════════════

class DangerLevel(enum.Enum):
    """危险等级枚举"""
    LOW = "low"          # 潜在风险，一般可自动放行
    MEDIUM = "medium"    # 中等风险，建议确认
    HIGH = "high"        # 高风险，必须确认
    CRITICAL = "critical"  # 极高风险，强烈警告


@dataclass
class DangerPattern:
    """危险命令模式定义"""
    pattern: str          # 编译后的正则表达式模式字符串（compile 后在 __post_init__ 完成）
    level: DangerLevel
    description: str      # 人类可读的描述
    platform: str = "all"  # "all" | "unix" | "windows"

    def __post_init__(self):
        flags = re.IGNORECASE if self.platform == "windows" else 0
        self._compiled = re.compile(self.pattern, flags)

    def search(self, text: str) -> bool:
        return bool(self._compiled.search(text))


# ─── 危险命令模式库 ──────────────────────────

DANGEROUS_PATTERNS: list[DangerPattern] = [
    # ─── CRITICAL: 系统级破坏性操作 ───
    DangerPattern(r"\brm\s+-rf\b", DangerLevel.CRITICAL, "递归强制删除文件/目录"),
    DangerPattern(r"\brm\s+-r\b", DangerLevel.CRITICAL, "递归删除目录"),
    DangerPattern(r"\bdd\s+if=", DangerLevel.CRITICAL, "磁盘写入操作(dd)"),
    DangerPattern(r"\bdd\s+of=", DangerLevel.CRITICAL, "磁盘输出操作(dd)"),
    DangerPattern(r">\s*/dev/(sd|nvme|hd|mmcblk|disk)", DangerLevel.CRITICAL, "直接写入块设备"),
    DangerPattern(r"\bmkfs\b", DangerLevel.CRITICAL, "创建文件系统(格式化)"),
    DangerPattern(r"\bmount\b.*\bremount\b", DangerLevel.CRITICAL, "重新挂载文件系统"),
    DangerPattern(r"\bfsck\b", DangerLevel.CRITICAL, "文件系统检查/修复"),
    DangerPattern(r"format\s+\w:", DangerLevel.CRITICAL, "格式化磁盘(Windows)", platform="windows"),

    # ─── HIGH: 有破坏性但可恢复 ───
    DangerPattern(r"\brm\s", DangerLevel.HIGH, "删除文件"),
    DangerPattern(r"\bgit\s+push\s+.*--force", DangerLevel.HIGH, "Git 强制推送"),
    DangerPattern(r"\bgit\s+reset\s+--hard", DangerLevel.HIGH, "Git 硬重置"),
    DangerPattern(r"\bgit\s+clean\s+-[fidx]", DangerLevel.HIGH, "Git 清理未跟踪文件"),
    DangerPattern(r"\bsudo\b", DangerLevel.HIGH, "使用 sudo 提权"),
    DangerPattern(r"\bchmod\s+777\b", DangerLevel.HIGH, "设置 777 权限"),
    DangerPattern(r"\bchown\b", DangerLevel.HIGH, "更改文件所有者"),
    DangerPattern(r"\bkill\s+-9\b", DangerLevel.HIGH, "强制杀死进程(SIGKILL)"),
    DangerPattern(r"\bkexec\b", DangerLevel.HIGH, "内核执行"),
    DangerPattern(r"\bfdisk\b", DangerLevel.HIGH, "磁盘分区操作"),
    DangerPattern(r"\begister\s+delete\b", DangerLevel.HIGH, "注册表删除(Windows)", platform="windows"),
    DangerPattern(r"\bRemove-Item\s+-Recurse\b", DangerLevel.HIGH, "PowerShell 递归删除", platform="windows"),
    DangerPattern(r"\bStop-Process\s+-Force\b", DangerLevel.HIGH, "PowerShell 强制停止进程", platform="windows"),
    DangerPattern(r"\btaskkill\s+/f\b", DangerLevel.HIGH, "强制结束进程(Windows)", platform="windows"),
    DangerPattern(r"\brmdir\s+/s\b", DangerLevel.HIGH, "递归删除目录(Windows)", platform="windows"),

    # ─── MEDIUM: 可能造成不便 ───
    DangerPattern(r"\bgit\s+checkout\s+\.\b", DangerLevel.MEDIUM, "还原当前目录变更"),
    DangerPattern(r"\bgit\s+rebase\b", DangerLevel.MEDIUM, "Git rebase 操作"),
    DangerPattern(r"\bkill\b", DangerLevel.MEDIUM, "结束进程"),
    DangerPattern(r"\bpkill\b", DangerLevel.MEDIUM, "按名称结束进程"),
    DangerPattern(r"\bshutdown\b", DangerLevel.MEDIUM, "关机"),
    DangerPattern(r"\breboot\b", DangerLevel.MEDIUM, "重启"),
    DangerPattern(r"\bchmod\b", DangerLevel.MEDIUM, "更改文件权限"),
    DangerPattern(r"\bcurl\b.*\|\s*(ba)?sh\b", DangerLevel.MEDIUM, "远程脚本执行(curl|sh)"),
    DangerPattern(r"\bwget\b.*\|\s*(ba)?sh\b", DangerLevel.MEDIUM, "远程脚本执行(wget|sh)"),
    DangerPattern(r"\bpip\s+uninstall\b", DangerLevel.MEDIUM, "pip 卸载包"),
    DangerPattern(r"\bnpm\s+uninstall\b", DangerLevel.MEDIUM, "npm 卸载包"),
    DangerPattern(r"\bdocker\s+rm\b", DangerLevel.MEDIUM, "删除 Docker 容器"),
    DangerPattern(r"\bdocker\s+rmi\b", DangerLevel.MEDIUM, "删除 Docker 镜像"),
    DangerPattern(r"\bdocker\s+prune\b", DangerLevel.MEDIUM, "Docker 清理"),
    DangerPattern(r"\bdocker\s+system\s+prune\b", DangerLevel.MEDIUM, "Docker 系统清理"),
    DangerPattern(r"\beval\s", DangerLevel.MEDIUM, "eval 执行"),
    DangerPattern(r"\bsource\s+/dev/\w+", DangerLevel.MEDIUM, "从设备文件 source"),

    # ─── LOW: 潜在风险，通常不触发确认提示 ───
    DangerPattern(r"\bgrep\s+-r\s+/\b", DangerLevel.LOW, "全系统递归搜索"),
    DangerPattern(r"\bfind\s+/\s+", DangerLevel.LOW, "全系统文件查找"),
    DangerPattern(r"\bnpm\s+publish\b", DangerLevel.LOW, "npm 发布包"),
    DangerPattern(r"\bdocker\s+build\b", DangerLevel.LOW, "Docker 构建"),
]


# 按危险等级排序的常量，用于 max() 比较
LEVEL_ORDER: dict[DangerLevel, int] = {
    DangerLevel.LOW: 1,
    DangerLevel.MEDIUM: 2,
    DangerLevel.HIGH: 3,
    DangerLevel.CRITICAL: 4,
}


def detect_dangerous_commands(command: str) -> list[DangerPattern]:
    """检测命令中的所有危险模式，返回匹配列表。
    
    Args:
        command: 要检查的 shell 命令字符串
    
    Returns:
        匹配的 DangerPattern 列表，按危险等级降序排列
    """
    matches: list[DangerPattern] = []
    for dp in DANGEROUS_PATTERNS:
        if dp.search(command):
            matches.append(dp)
    # 按危险等级降序排列
    matches.sort(key=lambda m: LEVEL_ORDER[m.level], reverse=True)
    return matches


def get_max_danger_level(command: str) -> DangerLevel | None:
    """获取命令的最高危险等级，无危险返回 None"""
    matches = detect_dangerous_commands(command)
    return max(matches, key=lambda m: LEVEL_ORDER[m.level]).level if matches else None


def is_dangerous(command: str, min_level: DangerLevel = DangerLevel.MEDIUM) -> bool:
    """判断命令是否危险（达到指定等级以上）。
    
    Args:
        command: 要检查的命令
        min_level: 最低触发等级，默认 MEDIUM
    """
    level = get_max_danger_level(command)
    if level is None:
        return False
    return LEVEL_ORDER[level] >= LEVEL_ORDER[min_level]


def format_danger_warning(matches: list[DangerPattern]) -> str:
    """格式化危险命令警告信息"""
    lines = ["⚠️  命令包含潜在危险操作:"]
    for m in matches:
        emoji = {DangerLevel.CRITICAL: "🔴", DangerLevel.HIGH: "🟠", 
                 DangerLevel.MEDIUM: "🟡", DangerLevel.LOW: "🟢"}
        lines.append(f"  {emoji.get(m.level, '⚪')} [{m.level.value.upper()}] {m.description}")
    return "\n".join(lines)


# ═══════════════════════════════════════════════════════════════
# 2. 权限规则系统（用户级 + 项目级，allow + deny）
# ═══════════════════════════════════════════════════════════════

def parse_rule(rule: str) -> dict:
    """解析权限规则字符串。
    
    支持格式:
        "tool_name"           → 匹配该工具的所有调用
        "tool_name(pattern)"  → 匹配参数中 pattern 的内容
        "tool_name(path/*)"   → 通配符匹配文件路径
        "tool_name(/abs/path...)" → 前缀匹配
    
    Returns:
        {"tool": str, "pattern": str | None}
    """
    m = re.match(r"^([a-z_]+)\((.+)\)$", rule)
    if m:
        return {"tool": m.group(1), "pattern": m.group(2)}
    return {"tool": rule, "pattern": None}


def matches_rule(rule: dict, tool_name: str, tool_input: dict) -> bool:
    """检查工具调用是否匹配某条权限规则。
    
    Args:
        rule: parse_rule() 返回的规则字典
        tool_name: 工具名称
        tool_input: 工具输入参数字典
    
    Returns:
        True 如果匹配
    """
    if rule["tool"] != tool_name:
        return False

    # 无 pattern = 匹配该工具的所有调用
    if rule["pattern"] is None:
        return True

    # 提取要匹配的值
    value = ""
    if tool_name == "run_shell":
        value = tool_input.get("command", "")
    elif "file_path" in tool_input:
        value = tool_input["file_path"]
    elif "path" in tool_input:
        value = tool_input["path"]
    else:
        return True  # 其他工具类型，有 pattern 即匹配

    pattern = rule["pattern"]

    # 支持 fnmatch 通配符匹配 (路径类)
    if "*" in pattern or "?" in pattern or "[" in pattern:
        return fnmatch.fnmatch(value, pattern)

    # 前缀匹配 (以 ... 结尾)
    if pattern.endswith("..."):
        return value.startswith(pattern[:-3])

    # 精确匹配
    return value == pattern


# ─── 规则集加载与缓存 ──────────────────────

@dataclass
class PermissionRules:
    """权限规则集合，区分来源: 用户级 vs 项目级，allow vs deny"""
    allow_user: list[dict] = field(default_factory=list)
    deny_user: list[dict] = field(default_factory=list)
    allow_project: list[dict] = field(default_factory=list)
    deny_project: list[dict] = field(default_factory=list)

    def is_empty(self) -> bool:
        return not any([self.allow_user, self.deny_user,
                        self.allow_project, self.deny_project])

    def check(self, tool_name: str, tool_input: dict) -> str | None:
        """按优先级检查规则: deny(用户级) > deny(项目级) > allow(用户级) > allow(项目级)
        
        Returns:
            "deny" | "allow" | None
        """
        # Deny 优先 — 用户级 deny 优先级最高
        for rule in self.deny_user:
            if matches_rule(rule, tool_name, tool_input):
                return "deny"
        for rule in self.deny_project:
            if matches_rule(rule, tool_name, tool_input):
                return "deny"

        # 然后 allow
        for rule in self.allow_user:
            if matches_rule(rule, tool_name, tool_input):
                return "allow"
        for rule in self.allow_project:
            if matches_rule(rule, tool_name, tool_input):
                return "allow"

        return None


def _load_settings_json(file_path: Path) -> dict | None:
    """安全加载 JSON 设置文件"""
    if not file_path.exists():
        return None
    try:
        return json.loads(file_path.read_text())
    except (json.JSONDecodeError, OSError):
        return None


# 全局缓存，调用 reset_permission_cache() 清除
_cached_rules: PermissionRules | None = None


def load_permission_rules(
    user_config_path: Path | None = None,
    project_config_path: Path | None = None,
) -> PermissionRules:
    """加载权限规则（带缓存）。
    
    加载顺序: 用户级 ~/.muse/settings.json → 项目级 .muse/settings.json
    
    settings.json 格式:
    {
        "permissions": {
            "allow": ["read_file", "write_file(/abs/path/*)", "run_shell(npm test)"],
            "deny": ["run_shell(rm *)", "write_file(/etc/*)"]
        }
    }
    """
    global _cached_rules
    if _cached_rules is not None:
        return _cached_rules

    if user_config_path is None:
        user_config_path = Path.home() / ".muse" / "settings.json"
    if project_config_path is None:
        project_config_path = Path.cwd() / ".muse" / "settings.json"

    rules = PermissionRules()

    for config_path, is_user in [(user_config_path, True), (project_config_path, False)]:
        settings = _load_settings_json(config_path)
        if not settings or "permissions" not in settings:
            continue

        perms = settings["permissions"]
        target_allow = rules.allow_user if is_user else rules.allow_project
        target_deny = rules.deny_user if is_user else rules.deny_project

        for r in perms.get("allow", []):
            target_allow.append(parse_rule(r))
        for r in perms.get("deny", []):
            target_deny.append(parse_rule(r))

    _cached_rules = rules
    return _cached_rules


def reset_permission_cache() -> None:
    """清除权限规则缓存"""
    global _cached_rules
    _cached_rules = None


# ═══════════════════════════════════════════════════════════════
# 3. 会话级白名单
# ═══════════════════════════════════════════════════════════════

@dataclass
class WhitelistEntry:
    """白名单条目"""
    tool_name: str
    identifier: str           # 文件路径 或 命令字符串
    created_at: float = field(default_factory=time.time)
    source: str = "session"   # "session" | "user" | "project"

    def age_seconds(self) -> float:
        return time.time() - self.created_at


class SessionWhitelist:
    """会话级权限白名单。
    
    记录当前会话中用户已确认过安全的操作（路径/命令），
    避免对同一操作重复询问。
    
    层级:
    - session: 当前会话中手动确认的
    - user:    用户级预设（从 ~/.muse/settings.json 加载）
    - project: 项目级预设（从 .muse/settings.json 加载）
    
    支持父目录匹配: 如果 /home/user/project 在白名单，
    则 /home/user/project/sub/file.py 也视为在白名单。
    """

    def __init__(self):
        # tool_name → identifier → WhitelistEntry
        self._entries: dict[str, dict[str, WhitelistEntry]] = {}

    # ── 增删查 ──────────────────────────────

    def add(self, tool_name: str, identifier: str, source: str = "session") -> WhitelistEntry:
        """添加白名单条目，返回创建的条目
        
        自动规范化:
        - 文件路径去除尾部斜杠
        - 保持原始字符串不变
        """
        # 规范化路径标识符: 去除尾部斜杠
        normalized = identifier.rstrip("/") if tool_name in ("write_file", "edit_file", "read_file", "list_files") else identifier
        entry = WhitelistEntry(tool_name=tool_name, identifier=normalized, source=source)
        self._entries.setdefault(tool_name, {})[normalized] = entry
        return entry

    def remove(self, tool_name: str, identifier: str) -> bool:
        """移除白名单条目，返回是否成功"""
        if tool_name in self._entries:
            return self._entries[tool_name].pop(identifier, None) is not None
        return False

    def contains(self, tool_name: str, identifier: str) -> bool:
        """检查是否在白名单中（含父目录匹配）"""
        if tool_name not in self._entries:
            return False

        # 规范化标识符
        normalized = identifier.rstrip("/")

        # 精确匹配
        if normalized in self._entries[tool_name]:
            return True

        # 父目录匹配（仅文件操作工具）
        return self._check_parent_dirs(tool_name, normalized)

    def _check_parent_dirs(self, tool_name: str, identifier: str) -> bool:
        """检查是否有父目录在白名单中"""
        try:
            path = Path(identifier)
            for parent in path.parents:
                parent_str = str(parent)
                if parent_str in self._entries.get(tool_name, {}):
                    return True
        except Exception:
            pass
        return False

    # ── 批量操作 ────────────────────────────

    def clear_session(self) -> None:
        """清除当前会话确认的条目（保留用户级和项目级预设）"""
        for tn in list(self._entries.keys()):
            self._entries[tn] = {
                k: v for k, v in self._entries[tn].items()
                if v.source != "session"
            }
            if not self._entries[tn]:
                del self._entries[tn]

    def clear_all(self) -> None:
        """清空所有白名单条目"""
        self._entries.clear()

    # ── 查询 ────────────────────────────────

    def is_empty(self) -> bool:
        return len(self._entries) == 0

    def count(self) -> int:
        """总条目数"""
        return sum(len(entries) for entries in self._entries.values())

    def get_entries_for_tool(self, tool_name: str) -> dict[str, WhitelistEntry]:
        """获取某个工具的所有白名单条目"""
        return dict(self._entries.get(tool_name, {}))

    def get_summary(self) -> dict:
        """获取白名单摘要 {工具名: [标识符列表]}"""
        return {
            tn: list(entries.keys())
            for tn, entries in self._entries.items()
        }

    # ── 序列化 ──────────────────────────────

    def to_dict(self) -> dict:
        """序列化为字典"""
        result: dict = {}
        for tn, entries in self._entries.items():
            result[tn] = {
                ident: {
                    "identifier": e.identifier,
                    "source": e.source,
                    "created_at": e.created_at,
                }
                for ident, e in entries.items()
            }
        return result

    @classmethod
    def from_dict(cls, data: dict) -> "SessionWhitelist":
        """从字典反序列化"""
        instance = cls()
        for tn, entries in data.items():
            for ident, info in entries.items():
                instance.add(tn, ident, source=info.get("source", "session"))
        return instance


# ═══════════════════════════════════════════════════════════════
# 4. 统一权限检查器
# ═══════════════════════════════════════════════════════════════

# 工具分类常量
READ_TOOLS = frozenset({"read_file", "list_files", "grep_search", "web_fetch"})
EDIT_TOOLS = frozenset({"write_file", "edit_file"})
MODE_TOOLS = frozenset({"enter_plan_mode", "exit_plan_mode"})


@dataclass
class PermissionResult:
    """权限检查结果"""
    action: str          # "allow" | "deny" | "confirm"
    message: str = ""    # 人类可读消息
    danger_level: str | None = None        # DangerLevel.value
    danger_descriptions: list[str] | None = None  # 危险操作描述列表
    whitelist_identifier: str = ""          # 用于白名单的标识符


class PermissionChecker:
    """统一权限检查器。
    
    整合了所有权限检查逻辑:
    1. bypassPermissions 模式 → 直接放行
    2. 权限规则 (deny 优先, 用户级 > 项目级)
    3. 只读工具 → 放行
    4. plan 模式 → 限制编辑和 shell
    5. 模式切换工具 → 放行
    6. acceptEdits 模式 → 自动允许编辑
    7. 危险操作检测 → 确认 或 白名单 或 dontAsk 拒绝
    8. 默认放行
    
    使用示例:
        checker = PermissionChecker(mode="default")
        result = checker.check("run_shell", {"command": "rm -rf /"})
        if result.action == "confirm":
            # 让用户确认
            pass
        elif result.action == "deny":
            # 拒绝
            pass
        else:
            # 允许
            pass
    """

    def __init__(
        self,
        mode: str = "default",
        user_config_path: Path | None = None,
        project_config_path: Path | None = None,
    ):
        self.mode = mode
        self.rules = load_permission_rules(user_config_path, project_config_path)
        self.whitelist = SessionWhitelist()
        self.plan_file_path: str | None = None

        # 统计计数器
        self.stats = {"denied": 0, "confirmed": 0, "auto_allowed": 0}

    # ── 模式切换 ─────────────────────────────

    def set_mode(self, mode: str) -> None:
        """更改权限模式"""
        self.mode = mode

    def set_plan_file(self, path: str | None) -> None:
        """设置计划模式文件路径"""
        self.plan_file_path = path

    # ── 核心检查方法 ────────────────────────

    def check(self, tool_name: str, tool_input: dict) -> PermissionResult:
        """统一的权限检查入口。
        
        Args:
            tool_name: 工具名称
            tool_input: 工具输入参数字典
        
        Returns:
            PermissionResult(action=...)
        """
        # 1. bypassPermissions: 上帝模式，全部放行
        if self.mode == "bypassPermissions":
            self.stats["auto_allowed"] += 1
            return PermissionResult(action="allow")

        # 2. 权限规则检查 (deny 优先)
        rule_result = self.rules.check(tool_name, tool_input)
        if rule_result == "deny":
            self.stats["denied"] += 1
            return PermissionResult(
                action="deny",
                message=f"权限规则禁止: {tool_name}",
            )
        if rule_result == "allow":
            self.stats["auto_allowed"] += 1
            return PermissionResult(action="allow")

        # 3. 只读工具 → 直接放行
        if tool_name in READ_TOOLS:
            self.stats["auto_allowed"] += 1
            return PermissionResult(action="allow")

        # 4. plan 模式: 只能操作计划文件
        if self.mode == "plan":
            if tool_name in EDIT_TOOLS:
                file_path = tool_input.get("file_path", "")
                if self.plan_file_path and file_path == self.plan_file_path:
                    return PermissionResult(action="allow")
                return PermissionResult(
                    action="deny",
                    message=f"计划模式禁止编辑: {tool_name}",
                )
            if tool_name == "run_shell":
                return PermissionResult(
                    action="deny",
                    message="计划模式禁止执行 Shell 命令",
                )

        # 5. 模式切换工具 → 直接放行
        if tool_name in MODE_TOOLS:
            return PermissionResult(action="allow")

        # 6. acceptEdits 模式: 自动允许编辑
        if self.mode == "acceptEdits" and tool_name in EDIT_TOOLS:
            self.stats["auto_allowed"] += 1
            return PermissionResult(action="allow")

        # 7. 危险操作检测 + 白名单
        confirm = self._needs_confirmation(tool_name, tool_input)
        if confirm is not None:
            # 检查会话白名单
            if self.whitelist.contains(tool_name, confirm.whitelist_identifier):
                self.stats["auto_allowed"] += 1
                return PermissionResult(action="allow")

            # dontAsk 模式: 自动拒绝
            if self.mode == "dontAsk":
                self.stats["denied"] += 1
                return PermissionResult(
                    action="deny",
                    message=f"dontAsk 模式拒绝: {confirm.message}",
                    danger_level=confirm.danger_level,
                    danger_descriptions=confirm.danger_descriptions,
                )

            # 需要用户确认
            return confirm

        # 8. 默认放行
        self.stats["auto_allowed"] += 1
        return PermissionResult(action="allow")

    def _needs_confirmation(self, tool_name: str, tool_input: dict) -> PermissionResult | None:
        """检查是否需要用户确认。返回 PermissionResult 或 None（不需要确认）。"""
        whitelist_id = ""

        if tool_name in EDIT_TOOLS:
            file_path = tool_input.get("file_path", "")
            if not file_path:
                return PermissionResult(action="confirm", message=f"{tool_name}: (无文件路径)")
            whitelist_id = file_path

            if not Path(file_path).exists():
                return PermissionResult(
                    action="confirm",
                    message=f"创建新文件: {file_path}",
                    whitelist_identifier=whitelist_id,
                )
            return PermissionResult(
                action="confirm",
                message=f"修改文件: {file_path}",
                whitelist_identifier=whitelist_id,
            )

        if tool_name == "run_shell":
            command = tool_input.get("command", "")
            if not command:
                return PermissionResult(action="confirm", message=f"run_shell: (空命令)")
            whitelist_id = command

            dangers = detect_dangerous_commands(command)
            if dangers:
                max_level = max(dangers, key=lambda d: LEVEL_ORDER[d.level]).level
                return PermissionResult(
                    action="confirm",
                    message=command,
                    danger_level=max_level.value,
                    danger_descriptions=[d.description for d in dangers],
                    whitelist_identifier=whitelist_id,
                )

            # 非危险 Shell 命令也需要确认
            return PermissionResult(
                action="confirm",
                message=command,
                whitelist_identifier=whitelist_id,
            )

        if tool_name == "agent":
            return PermissionResult(
                action="confirm",
                message=f"启动子代理: {tool_input.get('description', '')}",
                whitelist_identifier=tool_input.get("description", ""),
            )

        return None

    # ── 确认/拒绝操作 ────────────────────────

    def confirm(self, tool_name: str, identifier: str, source: str = "session") -> None:
        """用户确认操作，加入白名单"""
        self.whitelist.add(tool_name, identifier, source)
        self.stats["confirmed"] += 1

    def deny(self) -> None:
        """记录一次拒绝"""
        self.stats["denied"] += 1

    # ── 重置 ─────────────────────────────────

    def reset(self) -> None:
        """重置统计和会话白名单"""
        self.stats = {"denied": 0, "confirmed": 0, "auto_allowed": 0}
        self.whitelist.clear_session()


# ═══════════════════════════════════════════════════════════════
# 向后兼容 API（供 tools.py 和 agent.py 迁移使用）
# ═══════════════════════════════════════════════════════════════

# 全局检查器实例（方便旧代码使用）
_default_checker: PermissionChecker | None = None


def get_checker() -> PermissionChecker:
    """获取或创建默认的全局权限检查器"""
    global _default_checker
    if _default_checker is None:
        _default_checker = PermissionChecker()
    return _default_checker


def check_permission(
    tool_name: str,
    inp: dict,
    mode: str = "default",
    plan_file_path: str | None = None,
) -> dict:
    """向后兼容的 check_permission 函数。
    
    与旧版 API 签名一致，返回 {"action": "allow"|"deny"|"confirm", "message": ...}
    """
    checker = get_checker()

    # 同步模式设置（如果调用方传入不同 mode）
    if checker.mode != mode:
        checker.set_mode(mode)
    if plan_file_path is not None:
        checker.plan_file_path = plan_file_path

    result = checker.check(tool_name, inp)
    out = {"action": result.action}
    if result.message:
        out["message"] = result.message
    if result.danger_level:
        out["danger_level"] = result.danger_level
    if result.danger_descriptions:
        out["danger_description"] = result.danger_descriptions
    return out
