"""JWT / API key / Redis store / --auth none loopback."""

from __future__ import annotations

import json
import time
from pathlib import Path
from typing import Any

import pytest
from starlette.testclient import TestClient

from vectorsmith_cli.http.app import build_app
from vectorsmith_cli.http.auth.api_key import APIKeyProvider
from vectorsmith_cli.http.auth.jwt import JWTProvider
from vectorsmith_cli.http.auth.store.redis import RedisAuthStore
from vectorsmith_cli.http.builtin_oauth.store import AuthStore
from vectorsmith_cli.mcp_compat import LATEST_HANDSHAKE_VERSION
from vectorsmith_cli.serve_http import localhost_bind
from vectorsmith_core.api import EnvCredentialResolver, load_project
from vectorsmith_core.execute.engine import Engine
from vectorsmith_core.tds.models import APIKeyAuthConfig, JWTAuthConfig


def _project():
    return load_project(
        {
            "tds_version": "1",
            "connections": {"main": {"backend": "qdrant", "url": "http://localhost:6333"}},
            "tools": [
                {
                    "name": "search_invoices",
                    "description": "Search invoices by client status and due date for billing.",
                    "target": {"connection": "main", "collection": "invoices"},
                }
            ],
        },
        env={"QDRANT_URL": "http://localhost:6333"},
    )


def _engine() -> Engine:
    return Engine(_project(), credential_resolver=EnvCredentialResolver({}))


def _client(
    tmp_path: Path,
    *,
    auth: str,
    auth_provider: Any,
    store: Any | None = None,
) -> TestClient:
    app = build_app(
        engine=_engine(),
        enable_define=False,
        auth=auth,
        public_url="https://example.test",
        store=store or AuthStore(tmp_path / "auth.db"),
        drafts_path=tmp_path / "tools.drafts.yaml",
        auth_provider=auth_provider,
    )
    return TestClient(app)


def test_localhost_bind() -> None:
    assert localhost_bind("127.0.0.1:8080")
    assert localhost_bind("localhost:8080")
    assert not localhost_bind("0.0.0.0:8080")
    assert not localhost_bind("example.com:8080")


def test_auth_jwt_interpolates_jwks_url() -> None:
    project = load_project(
        {
            "tds_version": "1",
            "connections": {"main": {"backend": "qdrant", "url": "http://localhost:6333"}},
            "security": {
                "auth": {
                    "mode": "jwt",
                    "jwt": {"jwks_url": "${JWKS_URL}", "issuer": "https://auth.example.com"},
                }
            },
            "tools": [
                {
                    "name": "search_invoices",
                    "description": "Search invoices by client status and due date for billing.",
                    "target": {"connection": "main", "collection": "invoices"},
                }
            ],
        },
        env={
            "QDRANT_URL": "http://localhost:6333",
            "JWKS_URL": "https://auth.example.com/.well-known/jwks.json",
        },
    )
    assert project.tds.security.auth.jwt.jwks_url == (
        "https://auth.example.com/.well-known/jwks.json"
    )


def _rsa_jwt() -> tuple[Any, dict[str, Any]]:
    jwt = pytest.importorskip("jwt")
    pytest.importorskip("cryptography")
    from cryptography.hazmat.primitives.asymmetric import rsa
    from jwt.algorithms import RSAAlgorithm

    key = rsa.generate_private_key(public_exponent=65537, key_size=2048)
    jwk = json.loads(RSAAlgorithm.to_jwk(key.public_key()))
    jwk["kid"] = "k1"
    return key, jwt, {"keys": [jwk]}


def _token(jwt: Any, key: Any, *, exp_offset: int = 60, extra: dict[str, Any] | None = None) -> str:
    payload = {
        "sub": "user-1",
        "tenant_id": "acme",
        "iss": "https://auth.example.com",
        "aud": "vectorsmith",
        "exp": int(time.time()) + exp_offset,
    }
    if extra:
        payload.update(extra)
    return jwt.encode(payload, key, algorithm="RS256", headers={"kid": "k1"})


def test_jwt_rs256_ok(tmp_path: Path) -> None:
    key, jwt, jwks = _rsa_jwt()
    provider = JWTProvider(
        JWTAuthConfig(
            issuer="https://auth.example.com",
            audience="vectorsmith",
            algorithms=["RS256"],
        ),
        jwks=jwks,
    )
    client = _client(tmp_path, auth="jwt", auth_provider=provider)
    token = _token(jwt, key)
    res = client.post(
        "/mcp",
        headers={"Authorization": f"Bearer {token}"},
        json={
            "jsonrpc": "2.0",
            "id": 1,
            "method": "initialize",
            "params": {"protocolVersion": LATEST_HANDSHAKE_VERSION},
        },
    )
    assert res.status_code == 200
    assert res.json()["result"]["serverInfo"]["name"] == "VectorSmith"


def test_jwt_expired_401_no_tools(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> None:
    key, jwt, jwks = _rsa_jwt()
    provider = JWTProvider(
        JWTAuthConfig(issuer="https://auth.example.com", audience="vectorsmith"),
        jwks=jwks,
    )
    called: list[str] = []

    async def boom(*_a: Any, **_k: Any) -> dict[str, Any]:
        called.append("dispatch")
        return {}

    monkeypatch.setattr("vectorsmith_cli.http.app.dispatch", boom)
    client = _client(tmp_path, auth="jwt", auth_provider=provider)
    token = _token(jwt, key, exp_offset=-30)
    res = client.post(
        "/mcp",
        headers={"Authorization": f"Bearer {token}"},
        json={
            "jsonrpc": "2.0",
            "id": 1,
            "method": "tools/call",
            "params": {"name": "search_invoices", "arguments": {}},
        },
    )
    assert res.status_code == 401
    assert res.json()["code"] == "auth_error"
    assert called == []


def test_jwt_invalid_401(tmp_path: Path) -> None:
    _key, _jwt, jwks = _rsa_jwt()
    other, jwt, _ = _rsa_jwt()
    provider = JWTProvider(
        JWTAuthConfig(issuer="https://auth.example.com", audience="vectorsmith"),
        jwks=jwks,
    )
    client = _client(tmp_path, auth="jwt", auth_provider=provider)
    token = _token(jwt, other)
    res = client.post(
        "/mcp",
        headers={"Authorization": f"Bearer {token}"},
        json={"jsonrpc": "2.0", "id": 1, "method": "initialize"},
    )
    assert res.status_code == 401
    assert res.json()["code"] == "auth_error"


@pytest.mark.asyncio
async def test_api_key_populates_principal_and_claims() -> None:
    provider = APIKeyProvider(
        APIKeyAuthConfig(header="Authorization", scheme="Bearer"),
        {"sk-test": {"principal": "svc-billing", "claims": {"tenant_id": "acme"}}},
    )

    class Req:
        headers = {"Authorization": "Bearer sk-test"}

    ctx = await provider.authenticate(Req())  # type: ignore[arg-type]
    assert ctx.principal == "svc-billing"
    assert ctx.claims["tenant_id"] == "acme"


def test_builtin_issued_token_still_works(tmp_path: Path) -> None:
    store = AuthStore(tmp_path / "auth.db")
    tokens = store.issue_tokens()
    app = build_app(
        engine=_engine(),
        enable_define=False,
        auth="builtin",
        public_url="https://example.test",
        store=store,
        drafts_path=tmp_path / "tools.drafts.yaml",
    )
    client = TestClient(app)
    res = client.post(
        "/mcp",
        headers={"Authorization": f"Bearer {tokens['access_token']}"},
        json={"jsonrpc": "2.0", "id": 1, "method": "initialize"},
    )
    assert res.status_code == 200


class _DictRedis:
    def __init__(self, data: dict[str, str]) -> None:
        self.data = data

    def get(self, key: str) -> str | None:
        return self.data.get(key)

    def set(self, key: str, value: str, ex: int | None = None) -> None:
        _ = ex
        self.data[key] = value

    def delete(self, *keys: str) -> None:
        for key in keys:
            self.data.pop(key, None)

    def keys(self, pattern: str) -> list[str]:
        import fnmatch

        return [k for k in self.data if fnmatch.fnmatch(k, pattern)]


def test_redis_store_shared_across_replicas() -> None:
    shared: dict[str, str] = {}
    a = RedisAuthStore(client=_DictRedis(shared))
    b = RedisAuthStore(client=_DictRedis(shared))
    tokens = a.issue_tokens()
    assert b.valid_access(tokens["access_token"])
    assert not a.valid_access("not-a-token")
