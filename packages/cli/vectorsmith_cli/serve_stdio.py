"""MCP stdio serve loop."""

from __future__ import annotations

import asyncio
import json
import logging
import os
import sys
import uuid
from pathlib import Path
from typing import Any

from mcp import types
from mcp.server import NotificationOptions, Server
from mcp.server.models import InitializationOptions
from mcp.server.runner import serve_loop
from mcp.server.stdio import stdio_server

from vectorsmith_cli.identity import DEFAULT_SERVER_NAME, PRODUCT_NAME
from vectorsmith_cli.observe.logging import configure_logging
from vectorsmith_cli.observe.sinks import build_audit_sink
from vectorsmith_cli.serve_common import (
    dispatch,
    expire_old_drafts,
    mcp_schemas,
    server_instructions,
)
from vectorsmith_cli.serve_router import configure_observability
from vectorsmith_cli.stdio_guard import install as install_stdio_guard
from vectorsmith_cli.validate_cmd import _load_env
from vectorsmith_core.api import (
    CallContext,
    Project,
    load_project,
)
from vectorsmith_core.embed.provider import FastEmbedProvider
from vectorsmith_core.execute.engine import Engine
from vectorsmith_core.security.credentials import build_credential_resolver
from vectorsmith_core.security.hardening import apply_serve_hardening, serve_hardening_errors
from vectorsmith_core.version import ENGINE_VERSION

log = logging.getLogger("vectorsmith.serve")


def _assemble(tools: Path, env: dict[str, str] | None) -> Project:
    project = load_project(tools, env=env)
    errors = [i for i in project.issues if i.severity == "error"]
    if errors:
        for i in errors:
            print(f"{i.code}: {i.message}", file=sys.stderr)
        raise SystemExit(2)
    return project


def _quiet_native_progress() -> None:
    """Stop FastEmbed/HF/tqdm from writing progress bars onto the MCP wire."""
    os.environ.setdefault("HF_HUB_DISABLE_PROGRESS_BARS", "1")
    os.environ.setdefault("TQDM_DISABLE", "1")
    os.environ.setdefault("TOKENIZERS_PARALLELISM", "false")


async def _serve_stdio_loop(
    server: Server[Any],
    read: Any,
    write: Any,
    initialization_options: InitializationOptions,
) -> None:
    """Keep stdio on the handshake protocol even after a modern client probe."""
    async with server.lifespan(server) as lifespan_context:
        await serve_loop(
            server,
            read,
            write,
            lifespan_state=lifespan_context,
            init_options=initialization_options,
        )


def serve_stdio(
    tools: Path,
    *,
    env_file: Path | None = None,
    enable_define: bool = False,
    include_meta: bool = True,
    watch: bool = True,
    name: str = DEFAULT_SERVER_NAME,
    audit_log: Path | None = None,
    audit_sink: str | None = None,
    audit_url: str | None = None,
    log_format: str = "text",
    log_level: str = "info",
) -> None:
    configure_logging(log_format, log_level)
    _quiet_native_progress()
    env = _load_env(env_file)
    project = _assemble(tools, env)
    for msg in serve_hardening_errors(project.tds):
        print(msg, file=sys.stderr)
        raise SystemExit(2)
    enable_define, include_meta = apply_serve_hardening(
        project.tds, enable_define=enable_define, include_meta=include_meta
    )
    drafts_path = tools.parent / "tools.drafts.yaml"
    expire_old_drafts(drafts_path)
    print(
        f"{PRODUCT_NAME} {ENGINE_VERSION} [{name}] — {len(project.tools)} tool(s)",
        file=sys.stderr,
    )
    if watch:
        print("watching tools.yaml (save to reload)", file=sys.stderr)

    async def _run() -> None:
        try:
            embed: FastEmbedProvider | None = FastEmbedProvider()
        except Exception:
            embed = None
        sink = build_audit_sink(
            project.tds.observability.audit,
            log_path=audit_log,
            sink_name=audit_sink,
            url=audit_url,
        )
        resolver = build_credential_resolver(env)
        engine = Engine(
            project,
            credential_resolver=resolver,
            embed_provider=embed,
            audit_sink=sink,
        )
        configure_observability(engine)
        state: dict[str, Any] = {
            "project": project,
            "engine": engine,
            "connection": None,
        }

        async def on_list_tools(_ctx: Any, _params: Any) -> types.ListToolsResult:
            conn = getattr(_ctx, "connection", None)
            if conn is not None:
                state["connection"] = conn
            tools_out = []
            for schema in mcp_schemas(
                state["project"], enable_define=enable_define, include_meta=include_meta
            ):
                tools_out.append(
                    types.Tool(
                        name=schema["name"],
                        description=schema.get("description"),
                        input_schema=schema.get("inputSchema") or {"type": "object"},
                    )
                )
            return types.ListToolsResult(tools=tools_out)

        async def on_call_tool(
            _ctx: Any, params: types.CallToolRequestParams
        ) -> types.CallToolResult:
            conn = getattr(_ctx, "connection", None)
            if conn is not None:
                state["connection"] = conn
            args = dict(params.arguments or {})
            try:
                payload = await dispatch(
                    state["engine"],
                    params.name,
                    args,
                    ctx=CallContext(request_id=str(uuid.uuid4())),
                    enable_define=enable_define,
                    drafts_path=drafts_path,
                    include_meta=include_meta,
                )
                text = json.dumps(payload, default=str)
                return types.CallToolResult(
                    content=[types.TextContent(type="text", text=text)],
                    structured_content=payload,
                )
            except Exception as exc:
                return types.CallToolResult(
                    content=[types.TextContent(type="text", text=str(exc))],
                    is_error=True,
                )

        server = Server(
            name,
            version=ENGINE_VERSION,
            title=PRODUCT_NAME,
            instructions=server_instructions(include_meta=include_meta),
            on_list_tools=on_list_tools,
            on_call_tool=on_call_tool,
        )

        async def _watch() -> None:
            if not watch:
                return
            try:
                from watchfiles import Change, awatch
            except ImportError:
                print("watchfiles missing; save-to-reload disabled", file=sys.stderr)
                return
            names = {tools.name, drafts_path.name}
            try:
                async for changes in awatch(tools.parent):
                    if not any(Path(path).name in names for _kind, path in changes):
                        continue
                    # Ignore transient editor swap files that never become tools.yaml
                    if all(kind is Change.deleted for kind, _path in changes):
                        continue
                    try:
                        fresh = _assemble(tools, env)
                        expire_old_drafts(drafts_path)
                        await state["engine"].aclose()
                        state["project"] = fresh
                        state["engine"] = Engine(
                            fresh,
                            credential_resolver=resolver,
                            embed_provider=embed,
                            audit_sink=sink,
                        )
                        configure_observability(state["engine"])
                        print(
                            f"reloaded tools.yaml — {len(fresh.tools)} tool(s)",
                            file=sys.stderr,
                        )
                        conn = state.get("connection")
                        send = getattr(conn, "send_tool_list_changed", None)
                        if callable(send):
                            await send()
                            print(
                                "sent tools/list_changed "
                                "(Desktop ignores this; use list_available_tools / run_tool)",
                                file=sys.stderr,
                            )
                        else:
                            print(
                                "reload done; list_changed not sent (no session yet)",
                                file=sys.stderr,
                            )
                    except SystemExit:
                        print("reload failed; keeping previous project", file=sys.stderr)
                    except Exception as exc:  # noqa: BLE001
                        print(
                            f"reload failed ({exc}); keeping previous project",
                            file=sys.stderr,
                        )
            except asyncio.CancelledError:
                raise
            except Exception as exc:  # noqa: BLE001
                print(f"watch stopped ({exc})", file=sys.stderr)

        watcher = asyncio.create_task(_watch())
        try:
            async with stdio_server() as (read, write):
                # After the transport claims fd 1, wrap Python stdout so FastEmbed
                # / tqdm / stray prints cannot corrupt JSON-RPC.
                install_stdio_guard()
                await _serve_stdio_loop(
                    server,
                    read,
                    write,
                    server.create_initialization_options(
                        notification_options=NotificationOptions(tools_changed=True)
                    ),
                )
        except Exception:
            log.exception("stdio serve loop crashed")
            raise
        finally:
            watcher.cancel()
            await state["engine"].aclose()

    asyncio.run(_run())
