"""MCP（Model Context Protocol）集成 — 连接基于 stdio 的外部工具服务器。

核心思路：spawn 子进程 → JSON-RPC 握手 → 发现工具 → 前缀注册 → 透明路由。
对 Agent Loop 来说，MCP 工具和内置工具没有区别——都是名字 + schema + 执行函数。

用原始 JSON-RPC over stdio 实现，无任何 MCP SDK 依赖。

配置从三处读取并合并（同名后读覆盖先读）：
  1. ~/.claude/settings.json（用户级）
  2. ./.claude/settings.json（项目级）
  3. ./.mcp.json（项目根目录，Claude Code 约定）

格式：
  { "mcpServers": { "name": { "command": "...", "args": [...], "env": {...} } } }

每个 MCP 工具以 "mcp__serverName__toolName" 三段式前缀暴露：
同时解决命名冲突（不同服务器可能有同名工具）和路由（从名字即可知道转发到哪台服务器）。
"""

from __future__ import annotations

import asyncio
import json
import os
import subprocess
from pathlib import Path
from typing import Any


# ─── 单个 MCP 连接（每个服务器一个） ────────────────────────


class McpConnection:
    """管理单个 MCP 服务器子进程和 JSON-RPC 通信。

    三个关键状态：
      _process —— 子进程句柄
      _pending —— 请求-响应关联表（id → Future），用自增 id 配对
      _reader_task —— 后台按行解析 stdout 的协程
    """

    def __init__(
        self,
        server_name: str,
        command: str,
        args: list[str] | None = None,
        env: dict[str, str] | None = None,
    ):
        self.server_name = server_name
        self.command = command
        self.args = args or []
        self.env = env or {}
        self._process: asyncio.subprocess.Process | None = None
        self._next_id = 1
        self._pending: dict[int, asyncio.Future] = {}
        self._reader_task: asyncio.Task | None = None

    async def connect(self) -> None:
        """启动服务器进程，stdin/stdout 作为双向 JSON-RPC 通道。"""
        merged_env = {**os.environ, **self.env}
        self._process = await asyncio.create_subprocess_exec(
            self.command, *self.args,
            stdin=subprocess.PIPE,
            stdout=subprocess.PIPE,
            stderr=subprocess.PIPE,
            env=merged_env,
        )
        # 后台启动 stdout 行读取循环
        self._reader_task = asyncio.create_task(self._read_loop())

    async def _read_loop(self) -> None:
        """从 stdout 读取换行分隔的 JSON-RPC 消息，按 id 配对到 pending future。"""
        assert self._process and self._process.stdout
        while True:
            line = await self._process.stdout.readline()
            if not line:
                break  # 进程关闭了 stdout
            try:
                msg = json.loads(line)
            except json.JSONDecodeError:
                continue  # 忽略非 JSON 行（服务器日志等）
            msg_id = msg.get("id")
            if msg_id is not None and msg_id in self._pending:
                fut = self._pending.pop(msg_id)
                if fut.done():
                    continue
                if "error" in msg:
                    e = msg["error"]
                    fut.set_exception(
                        RuntimeError(f"MCP error {e.get('code')}: {e.get('message')}")
                    )
                else:
                    fut.set_result(msg.get("result"))

    async def _send_request(self, method: str, params: dict | None = None) -> Any:
        """发送 JSON-RPC 请求并等待响应。"""
        if not self._process or not self._process.stdin:
            raise RuntimeError(f"MCP server '{self.server_name}' is not connected")
        req_id = self._next_id
        self._next_id += 1
        # 先注册 future 再写 stdin —— 否则极快的响应可能在注册前就到达而被丢弃
        loop = asyncio.get_event_loop()
        fut: asyncio.Future = loop.create_future()
        self._pending[req_id] = fut
        msg = json.dumps({"jsonrpc": "2.0", "id": req_id, "method": method, "params": params or {}})
        self._process.stdin.write((msg + "\n").encode())
        await self._process.stdin.drain()
        return await fut

    def _send_notification(self, method: str, params: dict | None = None) -> None:
        """发送 JSON-RPC 通知（无 id，发后不管）。"""
        if not self._process or not self._process.stdin:
            return
        msg = json.dumps({"jsonrpc": "2.0", "method": method, "params": params or {}})
        self._process.stdin.write((msg + "\n").encode())

    async def initialize(self) -> None:
        """MCP 初始化握手：协商版本 → 发 initialized 通知确认就绪。"""
        await self._send_request("initialize", {
            "protocolVersion": "2024-11-05",
            "capabilities": {},
            "clientInfo": {"name": "muse-code", "version": "1.0.0"},
        })
        # 协议要求 initialize 之后必须发此通知，告诉服务器客户端准备就绪
        self._send_notification("notifications/initialized")

    async def list_tools(self) -> list[dict]:
        """发现服务器提供的工具。"""
        result = await self._send_request("tools/list")
        if not result or not isinstance(result.get("tools"), list):
            return []
        return [
            {
                "name": t["name"],
                "description": t.get("description", ""),
                "inputSchema": t.get("inputSchema"),
                "serverName": self.server_name,
            }
            for t in result["tools"]
        ]

    async def call_tool(self, name: str, args: dict) -> str:
        """调用工具，返回拼接后的文本结果。

        MCP 返回 {content: [{type: "text", text: "..."}]} 格式，
        只提取 text 类型内容——图片等其他类型暂不处理。
        """
        result = await self._send_request("tools/call", {"name": name, "arguments": args})
        if isinstance(result, dict) and isinstance(result.get("content"), list):
            return "\n".join(
                c["text"] for c in result["content"]
                if c.get("type") == "text" and "text" in c
            )
        return json.dumps(result)

    def close(self) -> None:
        """终止服务器进程，拒绝所有待处理请求。"""
        if self._reader_task:
            self._reader_task.cancel()
            self._reader_task = None
        if self._process:
            try:
                self._process.kill()
            except ProcessLookupError:
                pass
            self._process = None
        for fut in self._pending.values():
            if not fut.done():
                fut.set_exception(RuntimeError(f"MCP server '{self.server_name}' closed"))
        self._pending.clear()


# ─── MCP 管理器 ─────────────────────────────────────────────


class McpManager:
    """管理所有 MCP 服务器连接的生命周期，对外提供统一接口。

    调用 load_and_connect() 一次（幂等），然后用 get_tool_definitions()
    把工具暴露给 Agent，用 call_tool() 路由调用。
    """

    def __init__(self):
        self._connections: dict[str, McpConnection] = {}
        self._tools: list[dict] = []
        self._connected = False

    async def load_and_connect(self) -> None:
        """读取配置，连接所有已配置的 MCP 服务器，发现工具。

        每台服务器独立连接，一个失败不影响其他（静默跳过）。
        握手和工具发现各有 15 秒超时——npx 首次启动需下载包，但不能无限等。
        """
        if self._connected:
            return  # 幂等：多次调用只连一次
        self._connected = True

        configs = self._load_configs()
        if not configs:
            return

        timeout = 15.0

        for name, cfg in configs.items():
            conn = McpConnection(name, cfg["command"], cfg.get("args"), cfg.get("env"))
            try:
                await conn.connect()
                await asyncio.wait_for(conn.initialize(), timeout=timeout)
                server_tools = await asyncio.wait_for(conn.list_tools(), timeout=timeout)
                self._connections[name] = conn
                self._tools.extend(server_tools)
                print(f"[mcp] Connected to '{name}' — {len(server_tools)} tools", flush=True)
            except Exception as e:
                print(f"[mcp] Failed to connect to '{name}': {e}", flush=True)
                conn.close()  # 失败连接立即清理，不影响其他服务器

    def get_tool_definitions(self) -> list[dict]:
        """返回 Anthropic API 格式的工具定义，带 mcp__ 三段式前缀。

        filesystem 服务器的 read_file 工具 → mcp__filesystem__read_file。
        格式直接符合 API tool 规范，可直接拼到工具列表里。
        """
        return [
            {
                "name": f"mcp__{t['serverName']}__{t['name']}",
                "description": t.get("description") or f"MCP tool {t['name']} from {t['serverName']}",
                "input_schema": t.get("inputSchema") or {"type": "object", "properties": {}},
            }
            for t in self._tools
        ]

    def is_mcp_tool(self, name: str) -> bool:
        """工具名是否为 MCP 前缀工具。"""
        return name.startswith("mcp__")

    async def call_tool(self, prefixed_name: str, args: dict) -> str:
        """把带前缀的工具调用路由到对应服务器。"""
        parts = prefixed_name.split("__")
        if len(parts) < 3:
            raise ValueError(f"Invalid MCP tool name: {prefixed_name}")
        server_name = parts[1]
        tool_name = "__".join(parts[2:])  # 工具名本身可能含 __
        conn = self._connections.get(server_name)
        if not conn:
            raise RuntimeError(f"MCP server '{server_name}' not connected")
        return await conn.call_tool(tool_name, args)

    async def disconnect_all(self) -> None:
        """断开所有连接（退出时清理）。"""
        for conn in self._connections.values():
            conn.close()
        self._connections.clear()
        self._tools.clear()
        self._connected = False

    # ─── 配置加载 ──────────────────────────────────────────

    def _load_configs(self) -> dict[str, dict]:
        merged: dict[str, dict] = {}
        # 1. 用户级 → 2. 项目级 → 3. .mcp.json，依次合并，同名后读覆盖先读
        self._merge_config_file(Path.home() / ".claude" / "settings.json", merged)
        self._merge_config_file(Path.cwd() / ".claude" / "settings.json", merged)
        self._merge_config_file(Path.cwd() / ".mcp.json", merged)
        return merged

    def _merge_config_file(self, path: Path, target: dict[str, dict]) -> None:
        if not path.exists():
            return
        try:
            raw = json.loads(path.read_text())
            # 兼容两种格式：settings.json 的 mcpServers 嵌套 / .mcp.json 的扁平映射
            servers = raw.get("mcpServers", raw) if isinstance(raw, dict) else {}
            for name, config in servers.items():
                if isinstance(config, dict) and "command" in config:
                    target[name] = config
        except Exception:
            pass  # 静默跳过格式错误的配置文件
