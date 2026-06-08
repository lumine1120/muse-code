from rich.console import Console
from rich.panel import Panel
from rich.prompt import Prompt
from rich.markdown import Markdown


# 工具图标映射
_TOOL_ICONS: dict[str, str] = {
    "read_file": "📖",
    "edit_file": "✏️",
    "write_file": "📝",
    "list_files": "📂",
    "grep_search": "🔍",
    "run_shell": "⚡",
    "web_fetch": "🌐",
    "tool_search": "🔎",
    "agent": "🤖",
    "skill": "🎯",
    "enter_plan_mode": "📋",
    "exit_plan_mode": "📋",
}


def _get_tool_icon(name: str) -> str:
    return _TOOL_ICONS.get(name, "🛠️")


def _get_tool_summary(name: str, inp: dict | str) -> str:
    """生成工具调用的简短摘要"""
    if isinstance(inp, str):
        try:
            import json
            inp = json.loads(inp)
        except Exception:
            return inp[:60]

    if name == "read_file":
        path = inp.get("file_path", "")
        return path.split("/")[-1] if path else ""
    if name == "write_file":
        path = inp.get("file_path", "")
        return path.split("/")[-1] if path else ""
    if name == "edit_file":
        path = inp.get("file_path", "")
        old = inp.get("old_string", "")
        preview = old[:30].replace("\n", " ") if old else ""
        return f"{path.split('/')[-1]}: '{preview}...'" if path else ""
    if name == "list_files":
        pattern = inp.get("pattern", "")
        return pattern
    if name == "grep_search":
        pattern = inp.get("pattern", "")
        return pattern
    if name == "run_shell":
        cmd = inp.get("command", "")
        return cmd[:50] if cmd else ""
    if name == "web_fetch":
        url = inp.get("url", "")
        return url[:50] if url else ""
    if name == "tool_search":
        query = inp.get("query", "")
        return query
    return ""


class UI:
    def __init__(self):
        self.console = Console()

    def print_welcome(self):
        self.console.print(Panel.fit(
            "[bold blue]Welcome to Muse Code[/bold blue]\n"
            "输入消息开始对话，输入 exit 退出\n"
            "命令: /clear /cost /compact /plan /whitelist",
            border_style="blue"
        ))

    def get_user_input(self) -> str:
        return Prompt.ask("\n[bold green]You[/bold green]")

    def print_agent_message(self, message: str):
        self.console.print(Panel(
            Markdown(message),
            title="[bold purple]Muse Code[/bold purple]",
            border_style="purple",
            title_align="left"
        ))

    def print_tool_call(self, tool_name: str, args: str):
        icon = _get_tool_icon(tool_name)
        summary = _get_tool_summary(tool_name, args)
        self.console.print(f"\n  [yellow]{icon} {tool_name}[/yellow][dim] {summary}[/dim]")

    def print_tool_result(self, result: str):
        # 截断长结果用于显示
        max_len = 500
        if len(result) > max_len:
            display = result[:max_len] + f"\n  ... ({len(result)} chars total)"
        else:
            display = result
        lines = "\n".join("  " + l for l in display.split("\n"))
        self.console.print(f"[dim]{lines}[/dim]")

    def print_system(self, message: str):
        self.console.print(f"[bold yellow]{message}[/bold yellow]")

    def print_error(self, error: str):
        self.console.print(f"[bold red]! {error}[/bold red]")

    def print_confirmation(self, message: str, danger_level: str | None = None):
        """打印危险操作确认提示"""
        level_color = {
            "critical": "bold red",
            "high": "bold red",
            "medium": "yellow",
            "low": "dim",
        }
        color = level_color.get(danger_level or "", "yellow")
        self.console.print(f"  [{color}]⚠ 需要确认:[/{color}] {message}")

    def print_whitelist_added(self, identifier: str):
        """打印白名单添加提示"""
        preview = identifier[:60] + "..." if len(identifier) > 60 else identifier
        self.console.print(f"  [dim green]✓ 已加入会话白名单: {preview}[/dim green]")
