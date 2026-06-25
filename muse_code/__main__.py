import sys
import os
import signal
import argparse
import asyncio

from .ui import UI
from .agent import Agent
from .session import load_session, get_latest_session_id


def parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser(prog="muse", add_help=False)
    parser.add_argument("prompt", nargs="*")
    parser.add_argument("--yolo", "-y", action="store_true",
                        help="跳过所有确认，自动执行")
    parser.add_argument("--plan", action="store_true",
                        help="计划模式（只读，不修改文件）")
    parser.add_argument("--accept-edits", action="store_true",
                        help="自动接受文件编辑")
    parser.add_argument("--dont-ask", action="store_true",
                        help="尽量不向用户提问")
    parser.add_argument("--thinking", action="store_true",
                        help="启用扩展思考模式")
    parser.add_argument("--react", action="store_true",
                        help="启用 ReAct 模式（显式 Thought/Action/Observation，适合推理能力较弱的模型）")
    parser.add_argument("--model", "-m", default=None,
                        help="指定模型名称")
    parser.add_argument("--api-base", default=None,
                        help="自定义 API 基地址")
    parser.add_argument("--resume", action="store_true",
                        help="恢复上一次会话")
    parser.add_argument("--max-cost", type=float, default=None,
                        help="最大费用限制（USD）")
    parser.add_argument("--max-turns", type=int, default=None,
                        help="最大对话轮次")
    parser.add_argument("--sub-agent-timeout", type=float, default=30.0,
                        help="子 Agent 同步等待超时秒数，超时后转后台运行（默认 30）")
    parser.add_argument("--help", "-h", action="store_true",
                        help="显示帮助信息")
    return parser.parse_args()


def _resolve_permission_mode(args: argparse.Namespace) -> str:
    """将命令行参数映射为权限模式"""
    if args.yolo:
        return "bypassPermissions"
    if args.plan:
        return "plan"
    if args.accept_edits:
        return "acceptEdits"
    if args.dont_ask:
        return "dontAsk"
    return "default"


def main() -> None:
    args = parse_args()

    if args.help:
        print(
            "Muse Code — 轻量级编程助手 CLI\n\n"
            "用法: muse [选项] [提示词]\n\n"
            "默认后端: 智谱AI (GLM-4.7-Flash 免费模型)，无需环境变量即可使用。\n"
            "设置 OPENAI_API_KEY + OPENAI_BASE_URL 或 ANTHROPIC_API_KEY 可切换后端。\n\n"
            "选项:\n"
            "  --yolo, -y        跳过所有确认，自动执行\n"
            "  --plan             计划模式（只读）\n"
            "  --accept-edits     自动接受文件编辑\n"
            "  --dont-ask         尽量不向用户提问\n"
            "  --thinking         启用扩展思考模式\n"
            "  --react            ReAct 模式（显式推理，适合弱模型）\n"
            "  --model, -m MODEL  指定模型名称\n"
            "  --api-base URL     自定义 API 基地址\n"
            "  --resume           恢复上一次会话\n"
            "  --max-cost USD     最大费用限制\n"
            "  --max-turns N      最大对话轮次\n"
            "  --sub-agent-timeout SECONDS  子Agent超时转后台（默认30）\n"
            "  --help, -h         显示帮助信息\n"
        )
        sys.exit(0)

    permission_mode = _resolve_permission_mode(args)
    model = args.model or os.environ.get("MUSE_MODEL")

    # 解析 API Key 和后端
    # 默认使用 OpenAI 兼容后端（内置智谱AI免费凭据）
    resolved_api_key: str | None = None
    resolved_use_openai = True

    if os.environ.get("ANTHROPIC_API_KEY"):
        resolved_api_key = os.environ["ANTHROPIC_API_KEY"]
        resolved_use_openai = False
    elif os.environ.get("OPENAI_API_KEY"):
        resolved_api_key = os.environ["OPENAI_API_KEY"]

    if not resolved_api_key:
        # 使用内置默认凭据（智谱AI免费模型 GLM-4.7-Flash），无需环境变量即可运行
        pass

    # 如果通过 --api-base 指定，强制使用 OpenAI 后端
    if args.api_base:
        os.environ["OPENAI_BASE_URL"] = args.api_base
        resolved_use_openai = True

    # 设置后端环境变量
    os.environ["MUSE_BACKEND"] = "openai" if resolved_use_openai else "anthropic"

    ui = UI()
    agent = Agent(
        ui=ui,
        permission_mode=permission_mode,
        model=model,
        thinking=args.thinking,
        max_cost_usd=args.max_cost,
        max_turns=args.max_turns,
        api_key=resolved_api_key,
        api_base=args.api_base if resolved_use_openai else None,
        anthropic_base_url=args.api_base if not resolved_use_openai else None,
        reasoning_mode="react" if args.react else "tool_loop",
    )
    agent.sub_agent_timeout = args.sub_agent_timeout

    # 恢复会话
    if args.resume:
        session_id = get_latest_session_id()
        if session_id:
            session = load_session(session_id)
            if session:
                agent.restore_session(session)
                ui.print_system(f"已恢复会话: {session_id}")
        else:
            ui.print_system("没有找到可恢复的会话")

    # 单次提示词模式 vs 交互模式
    prompt = " ".join(args.prompt) if args.prompt else None
    if prompt:
        async def _run_once() -> None:
            try:
                await agent.run(prompt)
            finally:
                # 退出前清理 MCP 子进程，避免孤儿进程
                await agent._mcp_manager.disconnect_all()
        asyncio.run(_run_once())
    else:
        asyncio.run(run_repl(agent))


async def run_repl(agent: Agent) -> None:
    """交互式 REPL 循环"""
    ui = agent.ui
    sigint_count = 0

    def handle_sigint(sig, frame):
        nonlocal sigint_count
        if agent._aborted is False:
            agent.abort()
            print("\n  (已中断)")
            sigint_count = 0
            _print_prompt()
        else:
            sigint_count += 1
            if sigint_count >= 2:
                print("\n再见！\n")
                sys.exit(0)
            print("\n  再按一次 Ctrl+C 退出")
            _print_prompt()

    def _print_prompt():
        ui.console.print("\n[bold green]You[/bold green]", end=" ")

    signal.signal(signal.SIGINT, handle_sigint)
    ui.print_welcome()

    while True:
        _print_prompt()
        try:
            line = input()
        except (EOFError, KeyboardInterrupt):
            print("\n再见！\n")
            break

        inp = line.strip()
        sigint_count = 0

        if not inp:
            continue
        if inp in ("exit", "quit"):
            print("\n再见！\n")
            break

        # REPL 命令
        if inp == "/clear":
            agent.clear_history()
            continue
        if inp == "/whitelist":
            agent.show_whitelist()
            continue
        if inp == "/cost":
            agent.show_cost()
            continue
        if inp == "/compact":
            await agent.compact()
            continue
        if inp == "/plan":
            agent.toggle_plan_mode()
            continue
        if inp == "/memory":
            from .memory import list_memories, get_memory_dir
            memories = list_memories()
            if not memories:
                ui.print_system(
                    f"尚未保存任何记忆。记忆目录：{get_memory_dir()}"
                )
            else:
                lines = [f"共 {len(memories)} 条记忆，目录：{get_memory_dir()}"]
                for m in memories:
                    desc = m.description or "(no description)"
                    lines.append(f"  [{m.type}] {m.name} — {desc}")
                ui.print_system("\n".join(lines))
            continue
        if inp == "/skills":
            from .skills import discover_skills
            skills = discover_skills()
            if not skills:
                ui.print_system(
                    "未找到任何技能。在 .claude/skills/<name>/SKILL.md 创建技能后即可使用。"
                )
            else:
                lines = [f"共 {len(skills)} 个技能："]
                for s in skills:
                    tag = f"/{s.name}" if s.user_invocable else s.name
                    desc = s.description or "(no description)"
                    lines.append(f"  {tag} ({s.source}) — {desc}")
                ui.print_system("\n".join(lines))
            continue

        # 用户主动触发技能：/<skill-name> [args]
        # 注意要放在所有内置 / 命令之后，避免误吞 /clear、/cost 等
        if inp.startswith("/") and len(inp) > 1:
            from .skills import get_skill_by_name, resolve_skill_prompt
            space_idx = inp.find(" ")
            cmd_name = inp[1:space_idx] if space_idx > 0 else inp[1:]
            cmd_args = inp[space_idx + 1:] if space_idx > 0 else ""
            skill = get_skill_by_name(cmd_name)
            if skill and skill.user_invocable:
                ui.print_system(f"调用技能: /{skill.name}")
                expanded = resolve_skill_prompt(skill, cmd_args)
                # 将展开后的 prompt 作为 user message 注入主对话（inline 模式）。
                # fork 模式需要 subagent 模块支持，当前退化为 inline。
                try:
                    await agent.run(expanded)
                except Exception as e:
                    if "abort" not in str(e).lower():
                        ui.print_error(str(e))
                continue
            # 未匹配到技能时继续往下走，让用户得到"未知命令"反馈
            ui.print_error(f"未知命令或技能：{inp}")
            continue

        try:
            await agent.run(inp)
        except Exception as e:
            if "abort" not in str(e).lower():
                ui.print_error(str(e))

    # 退出 REPL：清理 MCP 子进程，避免僵尸进程
    await agent._mcp_manager.disconnect_all()


if __name__ == "__main__":
    main()
