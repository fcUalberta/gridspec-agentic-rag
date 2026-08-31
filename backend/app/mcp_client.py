import asyncio
import json

from mcp import ClientSession
from mcp.client.streamable_http import streamable_http_client

from .config import settings


async def call_catalog_tool(name: str, arguments: dict) -> dict:
    async with asyncio.timeout(30):
        async with (
            streamable_http_client(settings.mcp_server_url) as (read_stream, write_stream, _),
            ClientSession(read_stream, write_stream) as session,
        ):
            await session.initialize()
            result = await session.call_tool(name, arguments=arguments)
            if result.isError:
                text = result.content[0].text if result.content else "MCP tool failed"
                raise RuntimeError(text)
            structured = getattr(result, "structuredContent", None) or getattr(
                result, "structured_content", None
            )
            if structured:
                return structured
            for content in result.content:
                if getattr(content, "type", None) == "text":
                    return json.loads(content.text)
    raise RuntimeError(f"MCP tool {name} returned no data")
