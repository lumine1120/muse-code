import asyncio
import json
import os
import time
from typing import Any, Callable, Awaitable

import anthropic
import openai

from .ui import UI
from .tools import (
    execute_tool,
    check_permission,
    CONCURRENCY_SAFE_TOOLS,
    get_active_tool_definitions
)
from .prompt import SYSTEM_PROMPT

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
    def __init__(self, ui: UI):
        self.ui = ui
        self.permission_mode = "default"
        self._aborted = False
        
        backend = os.getenv("MUSE_BACKEND", "openai").lower()
        self.use_openai = (backend != "anthropic")

        # Read-before-edit state matching
        self._read_file_state: dict[str, float] = {}

        if self.use_openai:
            api_key = os.getenv("OPENAI_API_KEY", "sk-da55231cfba049438b776410797e5032")
            base_url = os.getenv("OPENAI_BASE_URL", "https://api.deepseek.com")
            self.model = os.getenv("OPENAI_MODEL", "deepseek-v4-flash")
            self._openai_client = openai.AsyncOpenAI(api_key=api_key, base_url=base_url)
            self._anthropic_client = None
            self._openai_messages = [{"role": "system", "content": SYSTEM_PROMPT}]
        else:
            api_key = os.getenv("ANTHROPIC_API_KEY")
            self.model = os.getenv("ANTHROPIC_MODEL", "claude-3-5-sonnet-20241022")
            self._anthropic_client = anthropic.AsyncAnthropic(api_key=api_key)
            self._openai_client = None
            self._anthropic_messages = []
            self._system_prompt = SYSTEM_PROMPT

    def abort(self) -> None:
        self._aborted = True

    async def run(self, user_message: str) -> None:
        self._aborted = False
        if self.use_openai:
            await self._chat_openai(user_message)
        else:
            await self._chat_anthropic(user_message)

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
                    perm = check_permission(block["name"], block["input"], self.permission_mode)
                    if perm["action"] == "allow":
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

                # 没有预执行的话，现在执行
                perm = check_permission(tu.name, inp, self.permission_mode)
                if perm["action"] == "deny":
                    self.ui.print_error(f"Denied: {perm.get('message', '')}")
                    tool_results.append({"type": "tool_result", "tool_use_id": tu.id, "content": f"Action denied: {perm.get('message', '')}"})
                    continue

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

                perm = check_permission(fn_name, inp, self.permission_mode)
                if perm["action"] == "deny":
                    self.ui.print_error(f"Denied: {perm.get('message', '')}")
                    oai_checked.append({"tc": tc, "fn": fn_name, "inp": inp, "allowed": False, "result": f"Action denied: {perm.get('message', '')}"})
                    continue
                
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
