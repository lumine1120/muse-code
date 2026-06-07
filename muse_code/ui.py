from rich.console import Console
from rich.panel import Panel
from rich.prompt import Prompt
from rich.markdown import Markdown

class UI:
    def __init__(self):
        self.console = Console()

    def print_welcome(self):
        self.console.print(Panel.fit(
            "[bold blue]Welcome to Muse Code MVP[/bold blue]\nType 'exit' to quit.",
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
        self.console.print(f"[dim yellow]🛠️  Calling Tool: {tool_name} with {args}[/dim yellow]")
        
    def print_tool_result(self, result: str):
        # Truncate long results for display
        display_result = result if len(result) < 500 else result[:500] + "... [truncated]"
        self.console.print(f"[dim cyan]🔧 Tool Result:[/dim cyan] {display_result}")

    def print_system(self, message: str):
        self.console.print(f"[bold yellow]{message}[/bold yellow]")

    def print_error(self, error: str):
        self.console.print(f"[bold red]! {error}[/bold red]")
