from __future__ import annotations

import asyncio
import json
import os
import re
from dataclasses import dataclass
from typing import Any

from ..schemas import McpServer, ToolCallRecord
from .workbench_store import workbench_store


MAX_TOOL_RESULT_BYTES = 12 * 1024
MCP_PROTOCOL_VERSION = "2024-11-05"


@dataclass(frozen=True)
class ToolSpec:
    schema_name: str
    kind: str
    display_name: str
    server_id: str | None
    schema: dict[str, Any]


def _truncate_text(text: str, limit: int = MAX_TOOL_RESULT_BYTES) -> str:
    encoded = text.encode("utf-8")
    if len(encoded) <= limit:
        return text
    return encoded[:limit].decode("utf-8", errors="ignore") + "\n...[工具结果已截断]"


def _sanitize_tool_name(name: str) -> str:
    safe = re.sub(r"[^a-zA-Z0-9_]", "_", name).strip("_")
    return safe[:48] or "tool"


def mcp_schema_name(server_id: str, tool_name: str) -> str:
    return f"mcp_{server_id[:8].replace('-', '_')}_{_sanitize_tool_name(tool_name)}"


def build_tool_specs(user_id: str, mcp_server_ids: list[str] | None = None) -> list[ToolSpec]:
    specs: list[ToolSpec] = []

    selected = set(mcp_server_ids or [])
    for server in workbench_store.list_mcp_servers(user_id, include_disabled=False):
        if selected and server.id not in selected:
            continue
        for tool in workbench_store.list_mcp_tools(user_id, server.id):
            schema_name = mcp_schema_name(server.id, tool.name)
            specs.append(
                ToolSpec(
                    schema_name=schema_name,
                    kind="mcp",
                    display_name=f"{server.name} / {tool.name}",
                    server_id=server.id,
                    schema={
                        "type": "function",
                        "function": {
                            "name": schema_name,
                            "description": tool.description or f"MCP tool {tool.name} from {server.name}.",
                            "parameters": tool.input_schema or {"type": "object", "properties": {}},
                        },
                    },
                )
            )
    return specs


class McpStdioClient:
    def __init__(self, server: McpServer, timeout: float = 20.0) -> None:
        self.server = server
        self.timeout = timeout
        self.process: asyncio.subprocess.Process | None = None
        self._next_id = 1

    async def __aenter__(self) -> "McpStdioClient":
        env = os.environ.copy()
        env.update(self.server.env)
        self.process = await asyncio.create_subprocess_exec(
            self.server.command,
            *self.server.args,
            stdin=asyncio.subprocess.PIPE,
            stdout=asyncio.subprocess.PIPE,
            stderr=asyncio.subprocess.PIPE,
            env=env,
        )
        await self.request(
            "initialize",
            {
                "protocolVersion": MCP_PROTOCOL_VERSION,
                "capabilities": {},
                "clientInfo": {"name": "standard-ai-workbench", "version": "1.0.0"},
            },
        )
        await self.notify("notifications/initialized", {})
        return self

    async def __aexit__(self, exc_type: object, exc: object, tb: object) -> None:
        if not self.process:
            return
        if self.process.returncode is None:
            self.process.terminate()
            try:
                await asyncio.wait_for(self.process.wait(), timeout=2)
            except asyncio.TimeoutError:
                self.process.kill()
                await self.process.wait()

    async def notify(self, method: str, params: dict[str, Any]) -> None:
        await self._write({"jsonrpc": "2.0", "method": method, "params": params})

    async def request(self, method: str, params: dict[str, Any] | None = None) -> dict[str, Any]:
        request_id = self._next_id
        self._next_id += 1
        await self._write({"jsonrpc": "2.0", "id": request_id, "method": method, "params": params or {}})
        while True:
            message = await asyncio.wait_for(self._read(), timeout=self.timeout)
            if message.get("id") != request_id:
                continue
            if "error" in message:
                raise RuntimeError(json.dumps(message["error"], ensure_ascii=False))
            return message.get("result") or {}

    async def _write(self, payload: dict[str, Any]) -> None:
        if not self.process or not self.process.stdin:
            raise RuntimeError("MCP server 未启动。")
        body = json.dumps(payload, ensure_ascii=False).encode("utf-8")
        header = f"Content-Length: {len(body)}\r\n\r\n".encode("ascii")
        self.process.stdin.write(header + body)
        await self.process.stdin.drain()

    async def _read(self) -> dict[str, Any]:
        if not self.process or not self.process.stdout:
            raise RuntimeError("MCP server 未启动。")
        header = b""
        while b"\r\n\r\n" not in header:
            chunk = await self.process.stdout.read(1)
            if not chunk:
                raise RuntimeError("MCP server 已退出。")
            header += chunk
        header_text = header.decode("ascii", errors="ignore")
        length = 0
        for line in header_text.split("\r\n"):
            if line.lower().startswith("content-length:"):
                length = int(line.split(":", 1)[1].strip())
                break
        if length <= 0:
            raise RuntimeError("MCP server 返回无效消息。")
        body = await self.process.stdout.readexactly(length)
        return json.loads(body.decode("utf-8"))


async def refresh_mcp_tools(user_id: str, server_id: str) -> list[dict[str, Any]]:
    server = workbench_store.get_mcp_server(user_id, server_id, masked=False)
    async with McpStdioClient(server) as client:
        result = await client.request("tools/list")
    tools = result.get("tools", [])
    if not isinstance(tools, list):
        raise RuntimeError("MCP server tools/list 返回格式无效。")
    workbench_store.replace_mcp_tools(user_id, server_id, tools)
    return tools


async def run_mcp_tool(user_id: str, server_id: str, schema_name: str, arguments: dict[str, Any]) -> str:
    server = workbench_store.get_mcp_server(user_id, server_id, masked=False)
    real_tool_name = None
    for tool in workbench_store.list_mcp_tools(user_id, server_id):
        if mcp_schema_name(server_id, tool.name) == schema_name:
            real_tool_name = tool.name
            break
    if not real_tool_name:
        raise KeyError(schema_name)
    async with McpStdioClient(server) as client:
        result = await client.request("tools/call", {"name": real_tool_name, "arguments": arguments})
    return _truncate_text(json.dumps(result, ensure_ascii=False, indent=2))


async def execute_tool_call(user_id: str, record: ToolCallRecord) -> str:
    if record.tool_kind == "mcp" and record.server_id:
        return await run_mcp_tool(user_id, record.server_id, record.tool_name, record.arguments)
    raise ValueError(f"不支持的工具调用：{record.tool_kind}")
