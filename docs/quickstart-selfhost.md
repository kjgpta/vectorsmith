# Self-host (claude.ai custom connector)

Hub: [documentation home](index.md) · [CLI](cli.md) · [Deploy](https://github.com/kjgpta/vectorsmith/blob/main/deploy-templates/README.md).

Streamable HTTP MCP. Endpoint is **`POST /mcp`**. `GET /healthz` returns `{"ok": true}`. Any MCP client can attach the same way.

`--watch` does **not** apply to HTTP (`serve --http` never reloads YAML). Restart the process after edits.

Default `--auth` is `builtin`. Localhost demos must pass `--auth none` explicitly:

```bash
uv run vectorsmith serve examples/qdrant_invoices/tools.invoices.yaml --name invoices \
  --http 127.0.0.1:8080 --auth none
```

`--auth none` is refused off loopback (exit **3**): not `0.0.0.0`, not a public hostname.

For a public URL, `builtin` requires `https://` `--public-url` (exit **2** if missing):

```bash
uv run vectorsmith serve examples/qdrant_invoices/tools.invoices.yaml --name invoices \
  --http 0.0.0.0:8080 --auth builtin --public-url https://vb.example.com
```

The process writes an access secret once to `~/.vectorsmith/access-secret.once` (mode 0600). Builtin OAuth is PKCE S256, DCR, opaque tokens in `~/.vectorsmith/authstate.db` (mode 0600).

```bash
uv run vectorsmith auth rotate-secret
uv run vectorsmith auth revoke
```

Unauthenticated `POST /mcp` returns **401** with:

`WWW-Authenticate: Bearer resource_metadata="<public-url>/.well-known/oauth-protected-resource"`

Also served: `/.well-known/oauth-protected-resource`, `/.well-known/oauth-authorization-server`, `/oauth/authorize`, `/oauth/token`, `/oauth/register`, `/oauth/revoke`.

Add the connector in claude.ai (URL `https://vb.example.com/mcp`). Add Slack/GitHub/etc. as **separate** connectors — see [coexistence.md](coexistence.md).

## JWT (production)

```bash
pip install "vectorsmith[qdrant,auth-jwt,otel]"

vectorsmith serve tools.yaml --http 0.0.0.0:8080 --auth jwt \
  --jwks-url https://auth.example.com/.well-known/jwks.json \
  --jwt-issuer https://auth.example.com --jwt-audience vectorsmith \
  --log-format json --live-embed --shutdown-grace-s 30
```

`GET /healthz` is liveness. `GET /readyz` is **503** if a connection is down, a required embedder fails, or JWKS cannot be fetched. `GET /metrics` when `observability.metrics.enabled`. YAML tenancy / RBAC / audit / rate limits / `profiles.enterprise` apply at start — [enterprise](enterprise.md).

`--auth api_key` reads `--api-keys-file` (`{ "key": { "principal", "claims" } }`). Two replicas sharing builtin OAuth need `--auth-store redis` (`vectorsmith[auth-redis]`).

## MCP protocol negotiation

HTTP clients must initialize with one of `2024-11-05`, `2025-03-26`,
`2025-06-18`, or `2025-11-25`. VectorSmith echoes a supported requested
version. An unsupported or missing `protocolVersion` receives JSON-RPC error
`-32022` whose data lists both the requested value and supported versions.

Stdio hosts use the handshake-only MCP path, so a newer client such as GitHub
Copilot may probe `server/discover` before `initialize` without locking the
connection into an incompatible protocol era.

Container / k8s / Cloud Run / Fly: [deploy-templates/](https://github.com/kjgpta/vectorsmith/blob/main/deploy-templates/README.md) · [Kubernetes](deploy/kubernetes.md).
