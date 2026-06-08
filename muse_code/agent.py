import asyncio
import json
import os
import time
from datetime import datetime, timezone
from pathlib import Path
from typing import Any, Callable, Awaitable

import anthropic
import openai

from .ui import UI
from .tools import (
    execute_tool,
    CONCURRENCY_SAFE_TOOLS,
    get_active_tool_definitions,
)
from .permissions import (
    PermissionChecker,
    PermissionResult,
    format_danger_warning,
    detect_dangerous_commands,
    SessionWhitelist,
)
from .prompt import build_system_prompt
from .session import save_session, new_session_id

def _is_retryable(error: Exception) -> bool:
    status = getattr(error, "status_code", None) or getattr(error, "status", None)
    if status in (429, 503, 529):
        return True
    msg = str(error)
    if "overloaded" in msg or "ECONNRESET" in msg or "ETIMEDOUT" in msg:
        return True
    return False

async def _with_retry(fn, max_retries: int = 3):
    for attempt in range(max_retries + 1):
        try:
            return await fn()
        except Exception as error:
            if attempt >= max_retries or not _is_retryable(error):
                raise
            delay = min(1000 * (2 ** attempt), 30000) / 1000
            await asyncio.sleep(delay)

def _to_openai_tools(tools: list[dict]) -> list[dict]:
    return [
        {
            "type": "function",
            "function": {
                "name": t["name"],
                "description": t["description"],
                "parameters": t.get("input_schema", {"type": "object", "properties": {}}),
            },
        }
        for t in tools
    ]


class Agent:
    def __init__(
        self,
        ui: UI,
        permission_mode: str = "default",
        model: str | None = None,
        thinking: bool = False,
        max_cost_usd: float | None = None,
        max_turns: int | None = None,
        api_key: str | None = None,
        api_base: str | None = None,
        anthropic_base_url: str | None = None,
        custom_system_prompt: str | None = None,
        confirm_fn: Callable[[str], Awaitable[bool]] | None = None,
    ):
        self.ui = ui
        self.permission_mode = permission_mode
        self.thinking = thinking
        self.max_cost_usd = max_cost_usd
        self.max_turns = max_turns
        self._aborted = False
        self._base_system_prompt = custom_system_prompt or build_system_prompt()
        self.confirm_fn = confirm_fn  # 外部确认回调

        # 会话追踪
        self._session_id = new_session_id()
        self._session_start = datetime.now(timezone.utc).isoformat()
        self._turn_count = 0
        self._cost_usd = 0.0
        self._total_input_tokens = 0
        self._total_output_tokens = 0

        # ─── 权限与安全 ────────────────────────
        # 会话白名单: 记录本次会话中用户已确认过的操作，避免重复询问
        self._confirmed_paths: set[str] = set()
        # 统一权限检查器
        self._permission_checker = PermissionChecker(mode=permission_mode)

        # 自动判断后端
        backend = os.getenv("MUSE_BACKEND", "openai").lower()
        self.use_openai = (backend != "anthropic")

        # Read-before-edit state matching
        self._read_file_state: dict[str, float] = {}

        if self.use_openai:
            # 默认使用智谱AI免费模型，开箱即用，无需配置环境变量
            resolved_key = api_key or os.getenv("OPENAI_API_KEY", "906aad8906cd4d21accfd202ecfec9a7.FItpB5LP18zYE8Th")
            resolved_base = api_base or os.getenv("OPENAI_BASE_URL", "https://open.bigmodel.cn/api/paas/v4/")
            self.model = model or os.getenv("OPENAI_MODEL", "GLM-4.7-Flash")
            self._openai_client = openai.AsyncOpenAI(api_key=resolved_key, base_url=resolved_base)
            self._anthropic_client = None
            self._openai_messages = [{"role": "system", "content": self._base_system_prompt}]
        else:
            resolved_key = api_key or os.getenv("ANTHROPIC_API_KEY")
            self.model = model or os.getenv("ANTHROPIC_MODEL", "claude-3-5-sonnet-20241022")
            kwargs: dict[str, Any] = {}
            if api_key:
                kwargs["api_key"] = api_key
            if anthropic_base_url:
                kwargs["base_url"] = anthropic_base_url
            self._anthropic_client = anthropic.AsyncAnthropic(**kwargs)
            self._openai_client = None
            self._anthropic_messages = []
            self._system_prompt = self._base_system_prompt

        # 计划模式状态
        self._pre_plan_mode: str | None = None
        self._plan_file_path: str | None = None

    def abort(self) -> None:
        self._aborted = True

    def restore_session(self, session: dict[str, Any]) -> None:
        """从保存的会话数据恢复消息历史和白名单"""
        meta = session.get("metadata", {})
        self._session_id = meta.get("id", self._session_id)
        self._session_start = meta.get("startTime", self._session_start)
        self._cost_usd = meta.get("costUsd", 0.0)
        self._turn_count = meta.get("turnCount", 0)

        if self.use_openai:
            self._openai_messages = session.get("openaiMessages", self._openai_messages)
        else:
            self._anthropic_messages = session.get("anthropicMessages", self._anthropic_messages)

        # 恢复白名单
        whitelist_data = session.get("whitelist")
        if whitelist_data:
            from .permissions import SessionWhitelist
            self._permission_checker.whitelist = SessionWhitelist.from_dict(whitelist_data)
        paths = session.get("confirmedPaths", [])
        if paths:
            self._confirmed_paths = set(paths)

    def clear_history(self) -> None:
        """清空对话历史，保留系统提示"""
        if self.use_openai:
            self._openai_messages = [{"role": "system", "content": self._base_system_prompt}]
        else:
            self._anthropic_messages = []
        self._turn_count = 0
        self.ui.print_system("对话历史已清空")

    def show_cost(self) -> None:
        """显示当前会话的用量统计"""
        cost = self._get_current_cost_usd()
        budget_info = f" / ${self.max_cost_usd} 预算" if self.max_cost_usd else ""
        turn_info = f" | 轮次: {self._turn_count}/{self.max_turns}" if self.max_turns else ""
        msg_count = len(self._openai_messages) if self.use_openai else len(self._anthropic_messages)
        self.ui.print_system(
            f"Token: {self._total_input_tokens} in / {self._total_output_tokens} out\n"
            f"消息数: {msg_count}\n"
            f"预估费用: ${cost:.4f}{budget_info}{turn_info}"
        )

    def show_whitelist(self) -> None:
        """显示当前会话的白名单"""
        summary = self._permission_checker.whitelist.get_summary()
        confirmed = self._confirmed_paths
        if not summary and not confirmed:
            self.ui.print_system("会话白名单为空")
            return

        lines = ["会话白名单:"]
        if confirmed:
            lines.append(f"  已确认路径 ({len(confirmed)}):")
            for path in sorted(confirmed):
                lines.append(f"    • {path}")
        if summary:
            for tool, entries in summary.items():
                lines.append(f"  {tool} ({len(entries)}):")
                for entry in sorted(entries):
                    lines.append(f"    • {entry}")
        self.ui.print_system("\n".join(lines))

    def _get_current_cost_usd(self) -> float:
        """估算当前费用（基于 token 用量）"""
        return (self._total_input_tokens / 1_000_000) * 3 + (self._total_output_tokens / 1_000_000) * 15

    def _check_budget(self) -> dict:
        """检查是否超出预算或轮次限制"""
        if self.max_cost_usd is not None and self._get_current_cost_usd() >= self.max_cost_usd:
            return {"exceeded": True, "reason": f"费用已达上限 (${self._get_current_cost_usd():.4f} >= ${self.max_cost_usd})"}
        if self.max_turns is not None and self._turn_count >= self.max_turns:
            return {"exceeded": True, "reason": f"轮次已达上限 ({self._turn_count} >= {self.max_turns})"}
        return {"exceeded": False}

    async def compact(self) -> None:
        """压缩对话历史：保留系统提示 + 最近 4 条消息"""
        if self.use_openai:
            if len(self._openai_messages) > 5:
                system = self._openai_messages[0]
                self._openai_messages = [system] + self._openai_messages[-4:]
                self.ui.print_system("对话已压缩")
            else:
                self.ui.print_system("对话较短，无需压缩")
        else:
            if len(self._anthropic_messages) > 4:
                self._anthropic_messages = self._anthropic_messages[-4:]
                self.ui.print_system("对话已压缩")
            else:
                self.ui.print_system("对话较短，无需压缩")

    def toggle_plan_mode(self) -> str:
        """切换计划模式（只读），返回当前权限模式"""
        if self.permission_mode == "plan":
            # 退出计划模式，恢复之前的权限模式
            self.permission_mode = self._pre_plan_mode or "default"
            self._permission_checker.set_mode(self.permission_mode)
            self._permission_checker.set_plan_file(None)
            self._pre_plan_mode = None
            self._plan_file_path = None
            self._system_prompt = self._base_system_prompt
            if self.use_openai and self._openai_messages:
                self._openai_messages[0]["content"] = self._system_prompt
            self.ui.print_system(f"已退出计划模式 → {self.permission_mode} 模式")
            return self.permission_mode
        else:
            # 进入计划模式，保存当前权限模式
            self._pre_plan_mode = self.permission_mode
            self.permission_mode = "plan"
            self._permission_checker.set_mode("plan")
            self._plan_file_path = self._generate_plan_file_path()
            self._permission_checker.set_plan_file(self._plan_file_path)
            self._system_prompt = self._base_system_prompt + self._build_plan_mode_prompt()
            if self.use_openai and self._openai_messages:
                self._openai_messages[0]["content"] = self._system_prompt
            self.ui.print_system(f"已进入计划模式。计划文件: {self._plan_file_path}")
            return "plan"

    def _generate_plan_file_path(self) -> str:
        """生成计划文件路径"""
        d = Path.home() / ".muse" / "plans"
        d.mkdir(parents=True, exist_ok=True)
        return str(d / f"plan-{self._session_id}.md")

    def _build_plan_mode_prompt(self) -> str:
        """构建计划模式的附加系统提示"""
        return f"""

# Plan Mode Active

Plan mode is active. You MUST NOT make any edits (except the plan file below), run non-readonly tools, or make any changes to the system.

## Plan File: {self._plan_file_path}
Write your plan incrementally to this file using write_file or edit_file. This is the ONLY file you are allowed to edit.

## Workflow
1. **Explore**: Read code to understand the task. Use read_file, list_files, grep_search.
2. **Design**: Design your implementation approach. Use the agent tool with type="plan" if the task is complex.
3. **Write Plan**: Write a structured plan to the plan file including:
   - **Context**: Why this change is needed
   - **Steps**: Implementation steps with critical file paths
   - **Verification**: How to test the changes
4. **Exit**: Call exit_plan_mode when your plan is ready for user review.

IMPORTANT: When your plan is complete, you MUST call exit_plan_mode. Do NOT ask the user to approve — exit_plan_mode handles that."""

    def _auto_save(self) -> None:
        """自动保存会话到磁盘（含白名单）"""
        data: dict[str, Any] = {
            "metadata": {
                "id": self._session_id,
                "model": self.model,
                "cwd": os.getcwd(),
                "startTime": self._session_start,
                "turnCount": self._turn_count,
                "costUsd": self._cost_usd,
            },
            # 持久化白名单
            "whitelist": self._permission_checker.whitelist.to_dict(),
            "confirmedPaths": list(self._confirmed_paths),
        }
        if self.use_openai:
            data["openaiMessages"] = self._openai_messages
        else:
            data["anthropicMessages"] = self._anthropic_messages
        save_session(self._session_id, data)

    async def run(self, user_message: str) -> None:
        self._aborted = False
        self._turn_count += 1

        # 检查预算和轮次限制
        budget = self._check_budget()
        if budget["exceeded"]:
            self.ui.print_system(budget["reason"])
            return

        try:
            if self.use_openai:
                await self._chat_openai(user_message)
            else:
                await self._chat_anthropic(user_message)
        finally:
            self._auto_save()

    # ─── Anthropic backend ───────────────────────────────────────

    async def _chat_anthropic(self, user_message: str) -> None:
        # 1. 把用户消息加入上下文
        self._anthropic_messages.append({"role": "user", "content": user_message})

        while True:
            if self._aborted:
                break

            # 2. 准备预执行字典
            early_executions: dict[str, asyncio.Task] = {}

            # 3. 定义回调：当流式响应收到一个完整的工具调用时，立即预执行安全工具
            def _on_tool_block(block: dict):
                if block["name"] in CONCURRENCY_SAFE_TOOLS:
                    perm = self._permission_checker.check(block["name"], block["input"])
                    if perm.action == "allow":
                        task = asyncio.create_task(execute_tool(block["name"], block["input"], self._read_file_state))
                        early_executions[block["id"]] = task

            # 4. 调用流式 API！
            response = await self._call_anthropic_stream(on_tool_block_complete=_on_tool_block)

            # 5. 从完整响应里提取所有工具调用
            tool_uses = [b for b in response.content if b.type == "tool_use"]

            # 6. 把模型的完整响应加入上下文
            self._anthropic_messages.append({
                "role": "assistant",
                "content": [self._block_to_dict(b) for b in response.content],
            })

            # 7. 没有工具调用的话，就结束本轮对话
            if not tool_uses:
                break

            # 8. 有工具调用！逐个执行
            tool_results: list[dict] = []
            for tu in tool_uses:
                if self._aborted:
                    break
                inp = dict(tu.input) if hasattr(tu.input, 'items') else tu.input
                self.ui.print_tool_call(tu.name, json.dumps(inp))

                # 先用预执行的结果（如果有的话）
                early_task = early_executions.get(tu.id)
                if early_task:
                    res = await early_task
                    self.ui.print_tool_result(res)
                    tool_results.append({"type": "tool_result", "tool_use_id": tu.id, "content": res})
                    continue

                # 没有预执行的话，现在进行权限检查
                perm = self._permission_checker.check(tu.name, inp)
                if perm.action == "deny":
                    self.ui.print_error(f"Denied: {perm.message}")
                    tool_results.append({"type": "tool_result", "tool_use_id": tu.id, "content": f"Action denied: {perm.message}"})
                    continue

                if perm.action == "confirm":
                    # 检查会话白名单
                    whitelist_id = perm.whitelist_identifier or perm.message
                    if whitelist_id not in self._confirmed_paths:
                        confirmed = await self._confirm_dangerous(tu.name, perm)
                        if not confirmed:
                            self._permission_checker.deny()
                            tool_results.append({"type": "tool_result", "tool_use_id": tu.id, "content": f"User denied: {perm.message}"})
                            continue
                        self._confirmed_paths.add(whitelist_id)
                        self._permission_checker.confirm(tu.name, whitelist_id)

                res = await execute_tool(tu.name, inp, self._read_file_state)
                self.ui.print_tool_result(res)
                tool_results.append({"type": "tool_result", "tool_use_id": tu.id, "content": res})

            # 9. 把工具执行结果加入上下文，继续循环（模型会根据结果继续输出）
            if tool_results:
                self._anthropic_messages.append({"role": "user", "content": tool_results})


    @staticmethod
    def _block_to_dict(block) -> dict:
        if block.type == "text":
            return {"type": "text", "text": block.text}
        if block.type == "tool_use":
            return {"type": "tool_use", "id": block.id, "name": block.name, "input": dict(block.input) if hasattr(block.input, 'items') else block.input}
        return {"type": block.type}

    async def _call_anthropic_stream(self, on_tool_block_complete=None):
        async def _do():
            active_tools = get_active_tool_definitions()
            
            # 过滤掉未实现的 MVP 工具，防止 API 错误
            filtered_tools = [t for t in active_tools if t["name"] not in ("agent", "skill")]

            create_params: dict[str, Any] = {
                "model": self.model,
                "max_tokens": 4096,
                "system": self._system_prompt,
                "tools": filtered_tools,
                "messages": self._anthropic_messages,
            }

            first_text = True
            tool_blocks_by_index: dict[int, dict] = {}
            full_text = ""

            async with self._anthropic_client.messages.stream(**create_params) as stream:
                async for event in stream:
                    if not hasattr(event, 'type'): continue

                    # (1) content_block_start: 内容块开始
                    if event.type == "content_block_start":
                        cb = getattr(event, 'content_block', None)
                        if cb and getattr(cb, 'type', None) == "tool_use":
                            # 如果是工具调用块，先存下来，后面要拼接参数
                            tool_blocks_by_index[event.index] = {
                                "id": cb.id, "name": cb.name, "input_json": "",
                            }

                    # (2) content_block_delta: 内容块增量（核心！）
                    elif event.type == "content_block_delta":
                        delta = event.delta
                        if hasattr(delta, 'text'):
                            # 是文本！直接打印到终端（用户马上就能看到回答）
                            if first_text:
                                self.ui.console.print("\n[bold purple]Muse Code[/bold purple]")
                                first_text = False
                            self.ui.console.print(delta.text, end="")  # end="" 不换行，逐字输出
                            full_text += delta.text
                        elif hasattr(delta, 'partial_json'):
                            # 是工具调用的参数 JSON，还没传完，先拼起来
                            tb = tool_blocks_by_index.get(event.index)
                            if tb:
                                tb["input_json"] += delta.partial_json

                    # (3) content_block_stop: 内容块结束
                    elif event.type == "content_block_stop":
                        tb = tool_blocks_by_index.pop(event.index, None)
                        if tb and on_tool_block_complete:
                            # 工具调用的参数收全了！解析 JSON，触发回调
                            try:
                                parsed = json.loads(tb["input_json"] or "{}")
                            except Exception:
                                parsed = {}
                            on_tool_block_complete({
                                "type": "tool_use", "id": tb["id"],
                                "name": tb["name"], "input": parsed,
                            })

                if not first_text:
                    self.ui.console.print()
                return await stream.get_final_message()
        return await _with_retry(_do)


    # ─── OpenAI-compatible backend ───────────────────────────────

    async def _chat_openai(self, user_message: str) -> None:
        # 1. 用户消息加入上下文
        self._openai_messages.append({"role": "user", "content": user_message})

        while True:
            if self._aborted:
                break

            # 2. 调用流式 API
            response = await self._call_openai_stream()

            # 3. 解析响应
            choice = response.get("choices", [{}])[0] if response.get("choices") else {}
            message = choice.get("message", {})

            # 4. 把模型的完整响应加入上下文
            self._openai_messages.append(message)

            # 5. 没有工具调用的话，结束
            tool_calls = message.get("tool_calls")
            if not tool_calls:
                break

            # ========== Phase 1: 先检查所有工具的权限 ==========
            oai_checked: list[dict] = []
            for tc in tool_calls:
                if self._aborted:
                    break
                if tc.get("type") != "function":
                    continue
                fn_name = tc["function"]["name"]
                try:
                    inp = json.loads(tc["function"]["arguments"])
                except Exception:
                    inp = {}

                self.ui.print_tool_call(fn_name, json.dumps(inp))

                perm = self._permission_checker.check(fn_name, inp)
                if perm.action == "deny":
                    self.ui.print_error(f"Denied: {perm.message}")
                    oai_checked.append({"tc": tc, "fn": fn_name, "inp": inp, "allowed": False, "result": f"Action denied: {perm.message}"})
                    continue

                if perm.action == "confirm":
                    # 检查会话白名单
                    whitelist_id = perm.whitelist_identifier or perm.message
                    if whitelist_id not in self._confirmed_paths:
                        confirmed = await self._confirm_dangerous(fn_name, perm)
                        if not confirmed:
                            self._permission_checker.deny()
                            oai_checked.append({"tc": tc, "fn": fn_name, "inp": inp, "allowed": False, "result": f"User denied: {perm.message}"})
                            continue
                        self._confirmed_paths.add(whitelist_id)
                        self._permission_checker.confirm(fn_name, whitelist_id)
                
                oai_checked.append({"tc": tc, "fn": fn_name, "inp": inp, "allowed": True})

            # ========== Phase 2: 分批执行 ==========
            oai_batches: list[dict] = []
            for ct in oai_checked:
                safe = ct["allowed"] and ct["fn"] in CONCURRENCY_SAFE_TOOLS
                if safe and oai_batches and oai_batches[-1]["concurrent"]:
                    # 前面的也是安全工具，和前面的合并成一个并发批次
                    oai_batches[-1]["items"].append(ct)
                else:
                    # 新开一个批次
                    oai_batches.append({"concurrent": safe, "items": [ct]})

            for batch in oai_batches:
                if self._aborted:
                    break

                if batch["concurrent"]:
                    # ========== 安全工具：并发执行 ==========
                    async def _run_oai_safe(ct_item: dict) -> tuple[dict, str]:
                        res = await execute_tool(ct_item["fn"], ct_item["inp"], self._read_file_state)
                        self.ui.print_tool_result(res)
                        return ct_item, res

                    results = await asyncio.gather(*[_run_oai_safe(ct) for ct in batch["items"]])
                    for ct_item, res in results:
                        self._openai_messages.append({"role": "tool", "tool_call_id": ct_item["tc"]["id"], "content": res})
                else:
                    # ========== 非安全工具：串行执行 ==========
                    for ct in batch["items"]:
                        if not ct["allowed"]:
                            self._openai_messages.append({"role": "tool", "tool_call_id": ct["tc"]["id"], "content": ct["result"]})
                            continue
                        res = await execute_tool(ct["fn"], ct["inp"], self._read_file_state)
                        self.ui.print_tool_result(res)
                        self._openai_messages.append({"role": "tool", "tool_call_id": ct["tc"]["id"], "content": res})


    # ─── 危险命令确认 ──────────────────────────────────────

    async def _confirm_dangerous(self, tool_name: str, perm: PermissionResult) -> bool:
        """向用户确认危险操作，返回 True 表示用户同意。
        
        显示危险等级、描述信息，然后等待用户确认。
        支持外部 confirm_fn 回调或内置交互式确认。
        """
        danger_level = perm.danger_level
        descriptions = perm.danger_descriptions or []

        # 显示警告信息
        if danger_level and descriptions:
            self.ui.console.print(format_danger_warning(
                detect_dangerous_commands(perm.message)
            ))
        self.ui.print_confirmation(perm.message, danger_level)

        # 优先使用外部回调（如测试或 GUIsd
        if self.confirm_fn:
            return await self.confirm_fn(perm.message)

        # 内置交互式确认
        try:
            prompt = "  Allow? (y/n/always): "
            answer = input(prompt).strip().lower()
            if answer == "always":
                # 加入会话白名单
                if perm.whitelist_identifier:
                    self._confirmed_paths.add(perm.whitelist_identifier)
                    self.ui.print_whitelist_added(perm.whitelist_identifier)
                return True
            if answer.startswith("y"):
                return True
            return False
        except (EOFError, KeyboardInterrupt):
            return False

    async def _call_openai_stream(self) -> dict:
        async def _do():
            # 先准备工具列表，过滤掉没实现的
            active_tools = get_active_tool_definitions()
            filtered_tools = [t for t in active_tools if t["name"] not in ("agent", "skill")]
            
            # 调用 OpenAI API，开启流式
            stream = await self._openai_client.chat.completions.create(
                model=self.model,
                tools=_to_openai_tools(filtered_tools),
                messages=self._openai_messages,
                stream=True  # 关键！开启流式
            )

            # 初始化变量
            content = ""
            first_text = True
            tool_calls: dict[int, dict] = {}  # 按索引存储工具调用
            finish_reason = ""
            # 循环处理每个流式 chunk
            async for chunk in stream:
                if not chunk.choices:
                    continue
                delta = chunk.choices[0].delta

                # (1) 文本内容来了！直接打印
                if delta and delta.content:
                    if first_text:
                        self.ui.console.print("\n[bold purple]Muse Code[/bold purple]")
                        first_text = False
                    self.ui.console.print(delta.content, end="")  # end="" 逐字输出
                    content += delta.content

                # (2) 工具调用内容来了！拼起来
                if delta and delta.tool_calls:
                    for tc in delta.tool_calls:
                        existing = tool_calls.get(tc.index)
                        if existing:
                            # 这个工具调用已经存在，只需要追加参数
                            if tc.function and tc.function.arguments:
                                existing["arguments"] += tc.function.arguments
                        else:
                            # 新的工具调用，初始化
                            tool_calls[tc.index] = {
                                "id": tc.id or "",
                                "name": (tc.function.name if tc.function else "") or "",
                                "arguments": (tc.function.arguments if tc.function else "") or "",
                            }
                # (3) 收到 finish_reason，记录下来
                if chunk.choices[0].finish_reason:
                    finish_reason = chunk.choices[0].finish_reason
            # 流式结束，换行
            if not first_text:
                self.ui.console.print()
            # 组装完整的响应对象
            assembled = None
            if tool_calls:
                assembled = [
                    {"id": tc["id"], "type": "function", "function": {"name": tc["name"], "arguments": tc["arguments"]}}
                    for _, tc in sorted(tool_calls.items())
                ]

            return {
                "choices": [{
                    "message": {
                        "role": "assistant",
                        "content": content or None,
                        "tool_calls": assembled,
                    },
                    "finish_reason": finish_reason or "stop",
                }]
            }

        return await _with_retry(_do)
