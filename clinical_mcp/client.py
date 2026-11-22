"""Three real MCP transports with bounded operations and message observation."""
import asyncio
from contextlib import AsyncExitStack
from copy import deepcopy
import json
import os
from pathlib import Path
import sys
import time

import anyio
from mcp import ClientSession, StdioServerParameters
from mcp.client.stdio import stdio_client
from mcp.client.sse import sse_client
from mcp.client.streamable_http import streamable_http_client
import httpx2

ROOT = Path(__file__).resolve().parents[1]
EXTERNAL_URL = "https://pubmed.mcp.claude.com/mcp"


def redact(obj):
    if isinstance(obj, dict):
        return {k: ("[REDACTED]" if any(s in k.casefold() for s in ("token", "authorization", "secret", "api_key")) else redact(v)) for k, v in obj.items()}
    if isinstance(obj, list):
        return [redact(v) for v in obj]
    return obj


class ObservedStream:
    """Transparent SDK message stream; never synthesizes a request from UI input."""
    def __init__(self, stream, direction, history, start):
        self.stream, self.direction, self.history, self.start = stream, direction, history, start

    def __getattr__(self, name):
        return getattr(self.stream, name)

    def record(self, item):
        if isinstance(item, Exception):
            return
        message = item.message.model_dump(by_alias=True, mode="json", exclude_unset=True)
        self.history.append({"direction": self.direction, "elapsed_ms": round((time.monotonic() - self.start) * 1000, 1), "message": redact(deepcopy(message))})
        del self.history[:-80]

    async def send(self, item):
        await self.stream.send(item)
        self.record(item)

    async def receive(self):
        item = await self.stream.receive()
        self.record(item)
        return item

    def __aiter__(self):
        return self

    async def __anext__(self):
        try:
            return await self.receive()
        except anyio.EndOfStream:
            raise StopAsyncIteration

    async def __aenter__(self):
        await self.stream.__aenter__()
        return self

    async def __aexit__(self, *args):
        return await self.stream.__aexit__(*args)


async def exchange(source, tool=None, arguments=None, url=None):
    start, history = time.monotonic(), []
    budget = 12 if source == "external" else 15
    attempts = 2 if source == "sse" else 1
    result = {"ok": False, "source": source, "tool": tool, "history": history}
    try:
        with anyio.fail_after(budget):
            for attempt in range(attempts):
                try:
                    async with AsyncExitStack() as stack:
                        if source == "stdio":
                            streams = await stack.enter_async_context(stdio_client(StdioServerParameters(
                                command=sys.executable, args=["-m", "clinical_mcp.server"], cwd=str(ROOT),
                                env={**os.environ, "PYTHONIOENCODING": "utf-8"})))
                        elif source == "sse":
                            streams = await stack.enter_async_context(sse_client(url or os.getenv("LOCAL_MCP_URL", "http://127.0.0.1:8000/sse"), timeout=3, sse_read_timeout=budget))
                        else:
                            headers = {}
                            if token := os.getenv("EXTERNAL_MCP_TOKEN"):
                                headers["Authorization"] = f"Bearer {token}"
                            http = await stack.enter_async_context(httpx2.AsyncClient(headers=headers, timeout=8))
                            streams = await stack.enter_async_context(streamable_http_client(url or os.getenv("EXTERNAL_MCP_URL", EXTERNAL_URL), http_client=http))
                        async with ClientSession(ObservedStream(streams[0], "received", history, start),
                                                 ObservedStream(streams[1], "sent", history, start), read_timeout_seconds=budget) as session:
                            init = await session.initialize()
                            tools = []
                            params = None
                            while True:
                                page = await session.list_tools(params=params)
                                tools.extend(t.model_dump(by_alias=True, mode="json", exclude_none=True) for t in page.tools)
                                if not page.next_cursor:
                                    break
                                import mcp_types as types
                                params = types.PaginatedRequestParams(cursor=page.next_cursor)
                            result.update(tools=tools, protocol=init.protocol_version)
                            if tool:
                                called = await session.call_tool(tool, arguments or {})
                                result["response"] = called.model_dump(by_alias=True, mode="json", exclude_none=True)
                            result["ok"] = True
                    break
                except Exception:
                    if attempt + 1 == attempts:
                        raise
                    await anyio.sleep(0.25)
    except Exception as exc:
        result["error"] = {"code": "CONNECTION_ERROR", "message": "MCP-сервис недоступен или превышено время ожидания. Проверьте адрес и запуск сервера.", "type": type(exc).__name__}
    result["duration_ms"] = round((time.monotonic() - start) * 1000, 1)
    return result


def run(source, tool=None, arguments=None, url=None):
    return asyncio.run(exchange(source, tool, arguments, url))


def payload(result):
    response = result.get("response", {})
    for content in response.get("content", []):
        if content.get("type") == "text":
            try:
                return json.loads(content["text"])
            except ValueError:
                return {"text": content["text"]}
    return response.get("structuredContent", response)
