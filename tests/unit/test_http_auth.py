"""HTTP 401 challenge + healthz."""

from __future__ import annotations

from pathlib import Path

from starlette.testclient import TestClient

from vectorsmith_cli.http.app import build_app, challenge_header
from vectorsmith_cli.http.builtin_oauth.store import AuthStore
from vectorsmith_cli.mcp_compat import LATEST_HANDSHAKE_VERSION
from vectorsmith_core.api import EnvCredentialResolver, load_project
from vectorsmith_core.execute.engine import Engine


def _app(tmp_path: Path, auth: str = "builtin", name: str = "VectorSmith") -> TestClient:
    project = load_project(
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
    engine = Engine(project, credential_resolver=EnvCredentialResolver({}))
    store = AuthStore(tmp_path / "auth.db")
    app = build_app(
        engine=engine,
        enable_define=False,
        auth=auth,
        public_url="https://example.test",
        store=store,
        drafts_path=tmp_path / "tools.drafts.yaml",
        name=name,
    )
    return TestClient(app)


def test_healthz(tmp_path: Path) -> None:
    client = _app(tmp_path, auth="none")
    res = client.get("/healthz")
    assert res.status_code == 200


def test_401_exact_header(tmp_path: Path) -> None:
    client = _app(tmp_path, auth="builtin")
    res = client.post("/mcp", json={"jsonrpc": "2.0", "id": 1, "method": "tools/list"})
    assert res.status_code == 401
    assert res.headers["www-authenticate"] == challenge_header("https://example.test")


def test_initialize_server_info_default(tmp_path: Path) -> None:
    client = _app(tmp_path, auth="none")
    res = client.post(
        "/mcp",
        json={
            "jsonrpc": "2.0",
            "id": 1,
            "method": "initialize",
            "params": {"protocolVersion": LATEST_HANDSHAKE_VERSION},
        },
    )
    assert res.status_code == 200
    info = res.json()["result"]["serverInfo"]
    assert info["name"] == "VectorSmith"
    assert info["title"] == "VectorSmith"


def test_initialize_server_info_user_name(tmp_path: Path) -> None:
    client = _app(tmp_path, auth="none", name="invoices")
    res = client.post(
        "/mcp",
        json={
            "jsonrpc": "2.0",
            "id": 1,
            "method": "initialize",
            "params": {"protocolVersion": LATEST_HANDSHAKE_VERSION},
        },
    )
    info = res.json()["result"]["serverInfo"]
    assert info["name"] == "invoices"
    assert info["title"] == "VectorSmith"


def test_drain_rejects_new_mcp(tmp_path: Path) -> None:
    client = _app(tmp_path, auth="none")
    client.app.state.draining = True
    res = client.post(
        "/mcp",
        json={
            "jsonrpc": "2.0",
            "id": 1,
            "method": "initialize",
            "params": {"protocolVersion": LATEST_HANDSHAKE_VERSION},
        },
    )
    assert res.status_code == 503
    assert res.json()["error"] == "shutting_down"
    assert client.get("/healthz").status_code == 200


def test_write_secret_once_is_0600(tmp_path: Path) -> None:
    store = AuthStore(tmp_path / "auth.db")
    secret = store.rotate_secret()
    dest = store.write_secret_once(secret)
    assert dest.read_text(encoding="utf-8").strip() == secret
    assert dest.stat().st_mode & 0o777 == 0o600
