from __future__ import annotations

import pytest
from mcp.server.runner import ServerRunner
from starlette.testclient import TestClient

from tests.unit.test_http_auth import _app
from vectorsmith_cli.mcp_compat import (
    HANDSHAKE_PROTOCOL_VERSIONS,
    UnsupportedProtocolVersion,
    negotiate_protocol_version,
)

CLIENT_SHAPES = (
    {"name": "claude-desktop", "version": "1"},
    {"name": "cursor", "version": "1"},
    {"name": "codex", "version": "1"},
    {"name": "github-copilot", "version": "1.0.82"},
)


@pytest.mark.parametrize("version", HANDSHAKE_PROTOCOL_VERSIONS[-2:])
@pytest.mark.parametrize("client_info", CLIENT_SHAPES)
def test_stdio_sdk_negotiates_current_and_previous_handshake(
    version: str,
    client_info: dict[str, str],
) -> None:
    request, negotiated = ServerRunner._negotiate_initialize(
        {
            "protocolVersion": version,
            "capabilities": {"roots": {"listChanged": True}},
            "clientInfo": client_info,
        }
    )

    assert request.client_info.name == client_info["name"]
    assert negotiated == version


@pytest.mark.parametrize("version", HANDSHAKE_PROTOCOL_VERSIONS)
def test_http_initialize_echoes_supported_requested_version(
    tmp_path,
    version: str,
) -> None:
    client: TestClient = _app(tmp_path, auth="none")
    response = client.post(
        "/mcp",
        json={
            "jsonrpc": "2.0",
            "id": 1,
            "method": "initialize",
            "params": {
                "protocolVersion": version,
                "capabilities": {},
                "clientInfo": CLIENT_SHAPES[-1],
            },
        },
    )

    assert response.status_code == 200
    assert response.json()["result"]["protocolVersion"] == version


def test_http_initialize_lists_supported_versions_on_failure(tmp_path) -> None:
    client = _app(tmp_path, auth="none")
    response = client.post(
        "/mcp",
        json={
            "jsonrpc": "2.0",
            "id": 1,
            "method": "initialize",
            "params": {
                "protocolVersion": "2099-01-01",
                "capabilities": {},
                "clientInfo": CLIENT_SHAPES[-1],
            },
        },
    )

    error = response.json()["error"]
    assert error["code"] == -32022
    assert error["data"] == {
        "requested": "2099-01-01",
        "supported": list(HANDSHAKE_PROTOCOL_VERSIONS),
    }


def test_local_negotiator_rejects_missing_version() -> None:
    with pytest.raises(UnsupportedProtocolVersion):
        negotiate_protocol_version(None)
