"""MCP handshake versions supported by VectorSmith's HTTP compatibility path."""

from __future__ import annotations

HANDSHAKE_PROTOCOL_VERSIONS = (
    "2024-11-05",
    "2025-03-26",
    "2025-06-18",
    "2025-11-25",
)
LATEST_HANDSHAKE_VERSION = HANDSHAKE_PROTOCOL_VERSIONS[-1]


class UnsupportedProtocolVersion(ValueError):
    def __init__(self, requested: object) -> None:
        self.requested = requested
        super().__init__(
            f"unsupported MCP protocol version {requested!r}; "
            f"supported: {', '.join(HANDSHAKE_PROTOCOL_VERSIONS)}"
        )


def negotiate_protocol_version(requested: object) -> str:
    if isinstance(requested, str) and requested in HANDSHAKE_PROTOCOL_VERSIONS:
        return requested
    raise UnsupportedProtocolVersion(requested)
