import asyncio
import time
from typing import Any

import jwt
from mcp import ClientSession
from mcp.client.streamable_http import streamablehttp_client

from app.config import get_settings


def tool_token(analysis_id: str, workspace_id: str, agent: str, lease_owner: str) -> str:
    settings = get_settings()
    return jwt.encode(
        {
            "analysis_id": analysis_id,
            "workspace_id": workspace_id,
            "agent": agent,
            "lease_owner": lease_owner,
            "aud": "release-evidence",
            "exp": int(time.time()) + 300,
        },
        settings.internal_secret.get_secret_value(),
        algorithm="HS256",
    )


async def call_tool_async(token: str, name: str, arguments: dict[str, Any]) -> dict[str, Any]:
    async with streamablehttp_client(
        get_settings().mcp_url,
        headers={"Authorization": f"Bearer {token}"},
        timeout=30,
        sse_read_timeout=45,
    ) as (read, write, _):
        async with ClientSession(read, write) as session:
            await session.initialize()
            result = await session.call_tool(name, arguments)
            if result.isError:
                raise ValueError("MCP tool call failed validation")
            if result.structuredContent is not None:
                return dict(result.structuredContent)
            import json

            return dict(json.loads(result.content[0].text))  # type: ignore[union-attr]


def call_tool(
    token: str, name: str, arguments: dict[str, Any], timeout: float = 20
) -> dict[str, Any]:
    async def bounded() -> dict[str, Any]:
        return await asyncio.wait_for(call_tool_async(token, name, arguments), timeout=timeout)

    return asyncio.run(bounded())


async def discover(token: str) -> list[dict[str, Any]]:
    async with streamablehttp_client(
        get_settings().mcp_url, headers={"Authorization": f"Bearer {token}"}
    ) as (read, write, _):
        async with ClientSession(read, write) as session:
            await session.initialize()
            return [
                {"name": tool.name, "description": tool.description, "parameters": tool.inputSchema}
                for tool in (await session.list_tools()).tools
            ]
