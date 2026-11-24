from contextlib import asynccontextmanager

import httpx
from mcp import ClientSession
from mcp.client.streamable_http import streamable_http_client


@asynccontextmanager
async def connect(url: str, token: str):
    async with (
        httpx.AsyncClient(headers={"Authorization": f"Bearer {token}"}, timeout=30) as http,
        streamable_http_client(url, http_client=http) as (reader, writer, _),
        ClientSession(reader, writer) as session,
    ):
        await session.initialize()
        yield session


async def call(session: ClientSession, name: str, **arguments) -> dict:
    response = await session.call_tool(name, arguments)
    if response.isError:
        raise RuntimeError(response.content[0].text)
    return response.structuredContent
