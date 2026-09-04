from __future__ import annotations

import asyncio

import pytest
from mcp.server import NotificationOptions, Server
from mcp.shared.memory import create_client_server_memory_streams
from mcp.shared.message import SessionMessage
from mcp_types import JSONRPCRequest

from vectorsmith_cli.serve_stdio import _serve_stdio_loop


@pytest.mark.asyncio
async def test_modern_discover_probe_does_not_block_stdio_initialize() -> None:
    server: Server[object] = Server("vectorsmith-test")
    options = server.create_initialization_options(
        notification_options=NotificationOptions()
    )

    async with create_client_server_memory_streams() as (
        (client_read, client_write),
        (server_read, server_write),
    ):
        task = asyncio.create_task(
            _serve_stdio_loop(server, server_read, server_write, options)
        )

        await client_write.send(
            SessionMessage(
                JSONRPCRequest(
                    jsonrpc="2.0",
                    id=1,
                    method="server/discover",
                    params={
                        "_meta": {
                            "io.modelcontextprotocol/protocolVersion": "2026-07-28"
                        }
                    },
                )
            )
        )
        probe = (await client_read.receive()).message
        assert probe.error.code == -32601

        await client_write.send(
            SessionMessage(
                JSONRPCRequest(
                    jsonrpc="2.0",
                    id=2,
                    method="initialize",
                    params={
                        "protocolVersion": "2025-11-25",
                        "capabilities": {},
                        "clientInfo": {"name": "github-copilot", "version": "1.0.81"},
                    },
                )
            )
        )
        initialized = (await client_read.receive()).message
        assert initialized.result["protocolVersion"] == "2025-11-25"

        await client_write.aclose()
        await task
