"""Starlette app: /mcp, well-knowns, /oauth, /healthz."""

from __future__ import annotations

import json
from pathlib import Path
from typing import Any

from starlette.applications import Starlette
from starlette.middleware.base import BaseHTTPMiddleware
from starlette.requests import Request
from starlette.responses import JSONResponse, Response
from starlette.routing import Route

from vectorsmith_cli.http.auth.context import call_context_from_request
from vectorsmith_cli.http.auth.resolve import build_auth_provider
from vectorsmith_cli.http.builtin_oauth import server as oauth
from vectorsmith_cli.http.builtin_oauth.store import AuthStore
from vectorsmith_cli.identity import DEFAULT_SERVER_NAME, PRODUCT_NAME
from vectorsmith_cli.mcp_compat import (
    HANDSHAKE_PROTOCOL_VERSIONS,
    UnsupportedProtocolVersion,
    negotiate_protocol_version,
)
from vectorsmith_cli.serve_common import (
    dispatch,
    expire_old_drafts,
    mcp_schemas,
    server_instructions,
)
from vectorsmith_core.errors import AuthError, QueryTimeout, RateLimited
from vectorsmith_core.execute.engine import Engine
from vectorsmith_core.security.tenancy import bind_tenancy
from vectorsmith_core.version import ENGINE_VERSION


def challenge_header(public_url: str) -> str:
    base = public_url.rstrip("/")
    return f'Bearer resource_metadata="{base}/.well-known/oauth-protected-resource"'


class DrainGate(BaseHTTPMiddleware):
    async def dispatch(self, request: Request, call_next):  # type: ignore[override]
        if (
            request.url.path == "/mcp"
            and request.method == "POST"
            and getattr(request.app.state, "draining", False)
        ):
            return JSONResponse({"error": "shutting_down"}, status_code=503)
        return await call_next(request)


def _engine_for(request: Request) -> Engine:
    selected = getattr(request.state, "engine", None)
    if selected is not None:
        return selected  # type: ignore[no-any-return]
    router = getattr(request.app.state, "router", None)
    ctx = getattr(request.state, "call_context", None)
    if router is not None:
        return router.resolve(ctx)  # type: ignore[no-any-return]
    return request.app.state.engine  # type: ignore[no-any-return]


class AuthGate(BaseHTTPMiddleware):
    async def dispatch(self, request: Request, call_next):  # type: ignore[override]
        if request.url.path not in {"/mcp"}:
            return await call_next(request)
        provider = request.app.state.auth_provider
        try:
            ctx = await provider.authenticate(request)
        except AuthError as exc:
            www = request.app.state.www_authenticate
            if request.app.state.auth_mode == "builtin":
                return Response(status_code=401, headers={"WWW-Authenticate": www})
            return JSONResponse(
                {"code": exc.code, "message": exc.detail},
                status_code=401,
                headers={"WWW-Authenticate": www},
            )
        router = getattr(request.app.state, "router", None)
        engine = router.resolve(ctx) if router is not None else request.app.state.engine
        bind_tenancy(
            engine.project.tds.security.tenancy,
            ctx,
            headers=request.headers,
        )
        request.state.call_context = ctx
        request.state.engine = engine
        return await call_next(request)


BearerGate = AuthGate


async def healthz(_request: Request) -> Response:
    return JSONResponse({"ok": True})


async def metrics(_request: Request) -> Response:
    from vectorsmith_core.observe.metrics import render

    return Response(render(), media_type="text/plain; version=0.0.4")


async def readyz(request: Request) -> Response:
    router = getattr(request.app.state, "router", None)
    engine: Engine = request.app.state.engine
    live_embed = bool(getattr(request.app.state, "live_embed", False))
    if router is not None:
        compiled = sum(len(e.project.tools) for e in router.engines.values())
        health = await router.health()
    else:
        compiled = len(engine.project.tools)
        health = await engine.health()
    connections = {
        name: {"ok": st.ok, "detail": st.detail, "latency_ms": st.latency_ms}
        for name, st in health.items()
    }
    conn_ok = all(st.ok for st in health.values()) if health else True
    embed_ok = True
    embed_block: dict[str, Any] | None = None
    if router is not None:
        embed_ok, provider = await router.embed_health(live_embed=live_embed)
        if provider is not None or live_embed:
            embed_block = {"ok": embed_ok, "provider": provider}
    else:
        from vectorsmith_cli.serve_router import project_needs_embed

        if project_needs_embed(engine, live_embed=live_embed):
            embed_ok, provider = await engine.embed_health()
            embed_block = {"ok": embed_ok, "provider": provider}
    auth_ok = True
    auth_block: dict[str, Any] | None = None
    if getattr(request.app.state, "auth_mode", None) == "jwt":
        provider = getattr(request.app.state, "auth_provider", None)
        check = getattr(provider, "health", None)
        if callable(check):
            try:
                auth_ok = bool(await check())
            except Exception:
                auth_ok = False
            auth_block = {"ok": auth_ok, "provider": "jwt"}
    ready = conn_ok and embed_ok and auth_ok
    body: dict[str, Any] = {
        "ready": ready,
        "compiled_tools": compiled,
        "connections": connections,
    }
    if embed_block is not None:
        body["embed"] = embed_block
    if auth_block is not None:
        body["auth"] = auth_block
    return JSONResponse(body, status_code=200 if ready else 503)


def build_app(
    *,
    engine: Engine,
    enable_define: bool,
    include_meta: bool = True,
    auth: str,
    public_url: str,
    store: AuthStore,
    drafts_path: Path,
    name: str = DEFAULT_SERVER_NAME,
    live_embed: bool = False,
    auth_provider: Any | None = None,
    router: Any | None = None,
    metrics_enabled: bool = False,
) -> Starlette:
    expire_old_drafts(drafts_path)
    server_name = name

    async def mcp(request: Request) -> Response:
        if request.method == "GET":
            return JSONResponse({"ok": True})
        body = await request.json()
        method = body.get("method")
        req_id = body.get("id")
        params = body.get("params") or {}
        if method == "initialize":
            try:
                protocol_version = negotiate_protocol_version(params.get("protocolVersion"))
            except UnsupportedProtocolVersion as exc:
                return JSONResponse(
                    {
                        "jsonrpc": "2.0",
                        "id": req_id,
                        "error": {
                            "code": -32022,
                            "message": str(exc),
                            "data": {
                                "requested": exc.requested,
                                "supported": list(HANDSHAKE_PROTOCOL_VERSIONS),
                            },
                        },
                    }
                )
            result: dict[str, Any] = {
                "protocolVersion": protocol_version,
                "capabilities": {"tools": {"listChanged": True}},
                "serverInfo": {
                    "name": server_name,
                    "title": PRODUCT_NAME,
                    "version": ENGINE_VERSION,
                },
                "instructions": server_instructions(include_meta=include_meta),
            }
        elif method == "tools/list":
            selected = _engine_for(request)
            result = {
                "tools": mcp_schemas(
                    selected.project, enable_define=enable_define, include_meta=include_meta
                )
            }
        elif method == "tools/call":
            name = params.get("name")
            args = dict(params.get("arguments") or {})
            selected = _engine_for(request)
            ctx = getattr(request.state, "call_context", None)
            if ctx is None:
                ctx = call_context_from_request(
                    tenancy=selected.project.tds.security.tenancy,
                    headers=request.headers,
                )
            try:
                payload = await dispatch(
                    selected,
                    name,
                    args,
                    ctx=ctx,
                    enable_define=enable_define,
                    drafts_path=drafts_path,
                    include_meta=include_meta,
                )
            except QueryTimeout as exc:
                return JSONResponse(
                    {"error": "timeout", "detail": exc.detail},
                    status_code=504,
                )
            except AuthError as exc:
                return JSONResponse(
                    {
                        "jsonrpc": "2.0",
                        "id": req_id,
                        "error": {
                            "code": -32001,
                            "message": exc.detail,
                            "data": {"code": exc.code},
                        },
                    },
                    status_code=403,
                )
            except RateLimited as exc:
                return JSONResponse(
                    {
                        "error": "rate_limited",
                        "detail": exc.detail,
                        "retry_after_s": exc.retry_after_s,
                    },
                    status_code=429,
                    headers={"Retry-After": str(exc.retry_after_s)},
                )
            result = {
                "content": [{"type": "text", "text": json.dumps(payload, default=str)}],
                "structuredContent": payload,
            }
        elif method == "notifications/initialized":
            return JSONResponse({"jsonrpc": "2.0", "result": {}})
        else:
            return JSONResponse(
                {"jsonrpc": "2.0", "id": req_id, "error": {"code": -32601, "message": method}},
                status_code=400,
            )
        return JSONResponse({"jsonrpc": "2.0", "id": req_id, "result": result})

    async def protected_resource(_request: Request) -> Response:
        return JSONResponse(oauth.well_known(public_url))

    async def as_meta(_request: Request) -> Response:
        return JSONResponse(oauth.as_metadata(public_url))

    routes = [
        Route("/healthz", healthz),
        Route("/readyz", readyz),
        Route("/mcp", mcp, methods=["GET", "POST"]),
        Route("/.well-known/oauth-protected-resource", protected_resource),
        Route("/.well-known/oauth-authorization-server", as_meta),
        Route("/oauth/authorize", oauth.authorize, methods=["GET", "POST"]),
        Route("/oauth/token", oauth.token, methods=["POST"]),
        Route("/oauth/register", oauth.register, methods=["POST"]),
        Route("/oauth/revoke", oauth.revoke, methods=["POST"]),
    ]
    if metrics_enabled:
        routes.append(Route("/metrics", metrics))
    if auth_provider is None:
        cfg = engine.project.tds.security.auth
        auth_provider = build_auth_provider(
            auth,
            store=store,
            auth_cfg=cfg,
            jwt_cfg=cfg.jwt,
            api_key_cfg=cfg.api_key,
        )
    app = Starlette(routes=routes, middleware=[])
    app.add_middleware(AuthGate)
    app.add_middleware(DrainGate)
    app.state.engine = engine
    app.state.router = router
    app.state.draining = False
    app.state.store = store
    app.state.auth_provider = auth_provider
    app.state.auth_mode = auth
    app.state.public_url = public_url
    app.state.live_embed = live_embed
    app.state.www_authenticate = (
        challenge_header(public_url) if auth == "builtin" else "Bearer"
    )
    return app
