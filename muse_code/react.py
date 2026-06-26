"""ReAct (Reasoning + Acting) 模式 — 显式 Thought/Action/Observation 循环。

适用于推理能力较弱的模型：通过结构化的思考步骤引导模型逐步推理，
而非依赖模型内部的隐式推理能力（tool-loop 模式）。

与 tool-loop 的区别：
  - tool-loop：模型直接输出 tool_calls，推理隐式发生在模型内部（适合 Claude/GPT 等强模型）
  - ReAct：模型先输出 Thought（显式推理），再输出 Action（工具调用），最后接收 Observation（结果）
            整个过程是纯文本交互，不依赖 function calling API
"""

from __future__ import annotations

import json
import re
from typing import Any

# 安全上限：防止单轮对话陷入无限循环
MAX_REACT_STEPS = 30

REACT_SYSTEM_SUFFIX = """

# ReAct Mode Active

You are operating in ReAct (Reasoning + Acting) mode. For each step, you MUST follow this exact format:

Thought: <your reasoning about what to do next>
Action: <tool_name>
Action Input: <JSON object with the tool's parameters>

After each Action, you will receive an Observation containing the tool's result.

When you have gathered enough information to answer the user's request, respond with:
Thought: <your final reasoning>
Final Answer: <your complete answer to the user>

CRITICAL RULES:
- Always start each step with "Thought:" to explain your reasoning before acting
- "Action:" must be exactly one of the available tools listed below
- "Action Input:" must be a valid JSON object
- You can only call ONE tool per step
- When the task is complete, use "Final Answer:" to give your response
- Do NOT output any text outside the Thought/Action/Action Input or Final Answer format

# Available Tools

{tool_descriptions}
"""


def format_tools_for_react(tools: list[dict]) -> str:
    """将工具定义格式化为 ReAct 系统提示中的文本描述。

    把 Anthropic schema 格式的工具定义转换为人类/模型可读的文本列表，
    让不支持的 function calling 的模型也能理解可用工具。
    """
    lines = []
    for t in tools:
        name = t["name"]
        desc = t.get("description", "")
        schema = t.get("input_schema", {})
        props = schema.get("properties", {})
        required = schema.get("required", [])

        if props:
            param_parts = []
            for k, v in props.items():
                ptype = v.get("type", "any")
                pdesc = v.get("description", "")
                req = " (required)" if k in required else ""
                param_parts.append(f'  - "{k}" ({ptype}{req}): {pdesc}')
            params = "\n" + "\n".join(param_parts)
        else:
            params = " (no parameters)"

        lines.append(f"- {name}{params}\n  {desc}")
    return "\n".join(lines)


def parse_react_response(text: str) -> dict[str, Any]:
    """解析 ReAct 响应，返回 action / final / error。

    Returns:
        {"type": "action", "tool": str, "input": dict}
        {"type": "final", "answer": str}
        {"type": "error", "message": str}
    """
    # 优先检查 Final Answer（模型可能同时输出 Action 和 Final Answer）
    final_match = re.search(
        r"Final\s*Answer\s*:?\s*(.*)", text, re.DOTALL | re.IGNORECASE
    )
    if final_match:
        answer = final_match.group(1).strip()
        return {"type": "final", "answer": answer}

    # 提取 Action 和 Action Input。
    # 注意：Action 的正则用负向先行断言排除 "Action Input"，否则会把
    # "Action Input" 里的 "Input" 误当成工具名（弱模型漏写 Action 行时常见）。
    action_match = re.search(r"Action\s*:?\s*(?!Input\b)([A-Za-z_][\w-]*)", text)
    input_match = re.search(
        r"Action\s*Input\s*:?\s*(\{.*?\})", text, re.DOTALL
    )

    if action_match:
        tool_name = action_match.group(1).strip()
        tool_input: dict = {}
        if input_match:
            raw_input = input_match.group(1)
            try:
                tool_input = json.loads(raw_input)
            except json.JSONDecodeError:
                return {
                    "type": "error",
                    "message": (
                        f"Invalid JSON in Action Input: {raw_input}\n"
                        "Please provide valid JSON for Action Input."
                    ),
                }
        return {"type": "action", "tool": tool_name, "input": tool_input}

    return {
        "type": "error",
        "message": (
            "Could not parse your response. Please follow the format exactly:\n"
            "Thought: <your reasoning>\n"
            "Action: <tool_name>\n"
            'Action Input: {"param": "value"}\n\n'
            "Or when done:\n"
            "Thought: <your reasoning>\n"
            "Final Answer: <your answer>"
        ),
    }


def format_observation(result: str, max_len: int = 8000) -> str:
    """将工具结果格式化为 Observation 消息。"""
    if len(result) > max_len:
        result = result[:max_len] + "\n... (truncated)"
    return f"Observation: {result}"
