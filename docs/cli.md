# CLI reference

Hub: [documentation home](index.md). Inventory of extras / routes: [library surface](library.md). Python env rules differ: [python-api.md](python-api.md).

```bash
vectorsmith --help
vectorsmith COMMAND --help
```

All commands that read YAML take a path to a TDS file. Secrets: **`--env-file` only** — the process environment is not merged. Use `${VAR:-default}` in YAML if you have no file. Python APIs merge `os.environ`; see [python-api.md](python-api.md).

Default MCP instance name is `VectorSmith` (`--name`). Product title is always `VectorSmith`.

---

## `init`

```bash
vectorsmith init [DIRECTORY]
vectorsmith init ./demo --print-desktop-config --name invoices
```

Writes `tools.yaml` and `.env.example` if they do not exist. `--print-desktop-config` prints a Claude Desktop JSON block (includes a sample `filesystem` server) to stdout.

---

## `validate`

```bash
vectorsmith validate TOOLS.yaml [--live] [--live-embed] [--json] [--strict] [--env-file FILE]
vectorsmith validate TOOLS.yaml --enterprise --strict
vectorsmith validate TOOLS.yaml --policy-builtin enterprise,pci,soc2
```

Compile, interpolate, synthesize built-ins, collect `VBxxxx` / `VE00x` / policy issues. No MCP server.

| Flag | Meaning |
|---|---|
| `--live` | Ping the store (health, embedding dim vs collection, sparse / hybrid, payload-path drift) |
| `--live-embed` | Also smoke-test the embedding provider (implies `--live`) |
| `--json` | Issues as JSON on stdout |
| `--strict` | Warnings → exit `1` |
| `--env-file` | Keys used for `${VAR}` under `connections` and embedding `config` |
| `--enterprise` / `--profile enterprise` | Production-safe preset (`VE001`–`VE007`) |
| `--policy FILE.rego` | Run `opa eval` with the compiled TDS as input JSON (`POL000` if `opa` is missing; each `deny` is `POL001`) |
| `--policy-builtin` | Comma list: `enterprise`, `pci`, `soc2` |

Exit: `0` ok · `1` warnings with `--strict` · `2` errors.

Every current adapter is experimental, so a catalog containing a backend
connection emits `VB2024`; `--strict` intentionally turns that warning into
exit `1`. Use ordinary validation while evaluating an adapter, and treat
strict validation as an unmet stability gate rather than suppressing the
warning. See [backend conformance](conformance.md).

---

## `test`

```bash
vectorsmith test TOOLS.yaml TOOL_NAME [--args JSON] [--show-plan] [--env-file FILE]
```

Run one compiled tool. Authoring smoke-test — not the app API.

| Flag | Meaning |
|---|---|
| `--args` | JSON object (default `{}`) |
| `--show-plan` | Print MCP schema + plan kind/collection/mode on stderr; `debug` on the call |

Exit: `0` ok · `2` unknown tool / validation errors · `3` live call failed.

Stdout is the result envelope (truncated to 20k characters).

---

## `serve`

```bash
vectorsmith serve TOOLS.yaml [OPTIONS]
vectorsmith serve projects/internal.yaml projects/external.yaml \
  --route-by-claim product --default-project internal --http 0.0.0.0:8080 --auth jwt
```

### Stdio (Claude Desktop, Claude Code, Codex, Cursor)

Default when `--http` is omitted. The host **spawns** this process.

| Flag | Default | Meaning |
|---|---|---|
| `--name` | `VectorSmith` | MCP `serverInfo.name` — match the `mcpServers` / `mcp_servers` key |
| `--env-file` | | Interpolation map |
| `--watch` / `--no-watch` | `--watch` | Reload YAML (and `tools.drafts.yaml`) on save. Recompiles plans; Desktop still freezes the named list |
| `--enable-define` | off | Advertise `describe_collection` / `define_tool` (or set `authoring.define_tool: true` in YAML) |
| `--meta-tools` / `--no-meta-tools` | `--meta-tools` | Advertise `list_available_tools` / `run_tool`. Off = compiled tools only |

Default: compiled tools **plus** `list_available_tools` and `run_tool`. Those two exist because Claude Desktop freezes `tools/list` at connect. `run_tool` is **not** a schema bypass — inner args go through the named tool’s jsonschema and `static_filters` / request tenancy still AND. They are not advertised by `load_tools`. Use `--no-meta-tools` to hide them.

`--watch` reloads and recompiles; it does not make Desktop refresh the Connectors UI. Details: [FAQ](faq.md).

Drafts are written to **`./tools.drafts.yaml` (process cwd)**. Set `cwd` in the host config.

Stdio uses MCP's handshake protocol even if a client first probes
`server/discover` with a newer per-request protocol envelope. Supported
initialize versions are `2024-11-05`, `2025-03-26`, `2025-06-18`, and
`2025-11-25`; this avoids the discover-before-initialize failure seen in newer
GitHub Copilot CLI clients.

### HTTP (claude.ai, remote MCP)

```bash
vectorsmith serve tools.yaml --http 127.0.0.1:8080 --auth none --name invoices
vectorsmith serve tools.yaml --http 0.0.0.0:8080 --auth builtin --public-url https://example.com
vectorsmith serve tools.yaml --http 0.0.0.0:8080 --auth jwt \
  --jwt-issuer https://auth.example.com --jwt-audience vectorsmith \
  --jwks-url https://auth.example.com/.well-known/jwks.json
```

| Flag | Default | Meaning |
|---|---|---|
| `--http HOST:PORT` | | Streamable HTTP. MCP is `POST /mcp` |
| `--auth` | `builtin` | `none` (loopback only), `builtin`, `jwt`, or `api_key` |
| `--public-url` | required for `builtin` | Must be `https://…` |
| `--jwt-issuer` / `--jwt-audience` / `--jwks-url` | | JWT mode (or `security.auth.jwt` in YAML). Extra: `vectorsmith[auth-jwt]` |
| `--api-keys-file` | | JSON `{ "key": { "principal", "claims" } }` for `--auth api_key` |
| `--auth-store` / `--redis-url` | `sqlite` | Builtin OAuth token store. `redis` needs `vectorsmith[auth-redis]` |
| `--audit-log` / `--audit-sink` / `--audit-url` | | JSONL audit events (file is mode 0600). Override per-YAML `observability.audit` |
| `--route-by-claim` / `--default-project` | | Multi-YAML routing (HTTP). Tool names must be unique across files |
| `--shutdown-grace-s` | `30` | Drain in-flight MCP calls on SIGTERM; new `/mcp` POSTs get 503 |
| `--log-format` / `--log-level` | `text` / `info` | `json` adds `request_id` / `principal` / `tool` / `latency_ms` / `trace_id` / `span_id` |
| `--live-embed` | off | Include embed-provider health on `GET /readyz` even when the YAML has no search tools |

`--watch` is **ignored** on HTTP. Restart after YAML edits. `--meta-tools` / `--no-meta-tools` and `--enable-define` apply the same as stdio.

The CLI uses MCP SDK `>=2,<3`. HTTP `initialize` accepts handshake versions
`2024-11-05`, `2025-03-26`, `2025-06-18`, and `2025-11-25`, echoing the
requested supported version. A missing or unsupported version returns
JSON-RPC error `-32022` with `data.requested` and `data.supported`; it is not
silently upgraded.

`GET /healthz` → `{"ok": true}` (liveness). `GET /readyz` → 503 if any connection is down, a required embedder fails (every loaded project with search/pipeline tools, or `--live-embed`), or `--auth jwt` cannot fetch JWKS. `GET /metrics` when `observability.metrics.enabled`. `profiles.enterprise` and `validate --enterprise` rules refuse start (same as `connect`). `builtin` OAuth: PKCE, DCR, tokens in `~/.vectorsmith/authstate.db` (mode 0600). First start writes the access secret once to `~/.vectorsmith/access-secret.once` (mode 0600) — it is not printed.

Exit: `2` if `builtin` lacks `https` `--public-url`, or jwt/api_key is missing JWKS/keys · `3` if `--auth none` is not loopback.

Details: [HTTP quickstart](quickstart-selfhost.md).

---

## `introspect`

```bash
vectorsmith introspect TOOLS.yaml --connection NAME [--out schema.json] \
  [--collections a,b] [--redact-examples] [--audit] [--env-file FILE]
```

Metadata-only export (field names / types — not a row dump). `--audit` prints JSON instead of writing `--out`. `--connection` is required.

Exit `3` on live failure.

---

## `discover` (experimental)

```bash
vectorsmith discover TOOLS.yaml --connection NAME --experimental \
  [--collections invoices,tickets] [--out tools.discovered.drafts.yaml] \
  [--env-file FILE]
```

Runs metadata-only introspection, detects likely tenant fields, chooses only
operators advertised by that backend, and proposes at most eight schema-backed
parameters per collection. The output contains pending draft records,
provenance, validator issues, and tenant-field candidates.

It does not edit `tools.yaml` or silently approve anything. Without
`--experimental`, exits `2`; live/validation failure exits `3`. The default
`tools.discovered.drafts.yaml` is a discovery report, not the
`./tools.drafts.yaml` consumed by `vectorsmith approve`.

---

## `eval` (experimental)

```bash
vectorsmith eval TOOLS.yaml scenarios.yaml --experimental \
  [--out vectorsmith-eval.json] [--env-file FILE]
```

Runs each checked-in call through the same `connect` / execution path used by
applications. A scenario can assert the selected tool and exact arguments plus
row invariants:

```yaml
scenarios:
  - name: overdue invoices stay in tenant
    request: Show overdue invoices
    call:
      tool: search_invoices
      arguments: { status: [overdue] }
    expected_tool: search_invoices
    expected_arguments: { status: [overdue] }
    expect:
      min_rows: 1
      max_rows: 20
      row_field_equals: { tenant: acme }
      forbidden_field_values: { tenant: [other] }
      min_score: 0.5
```

Supported row checks are `exact_rows`, `min_rows`, `max_rows`,
`row_field_equals`, `forbidden_field_values`, and `min_score`. The JSON report
records each call, arguments, row count, failures, and aggregate pass/fail
counts. Exit `1` means one or more scenarios failed; `2` means usage/format
error.

---

## `drift` (experimental)

```bash
vectorsmith drift TOOLS.yaml schema.json --connection NAME --experimental \
  [--out vectorsmith-drift.json] [--env-file FILE]
```

Compares a checked-in metadata-only schema export with fresh introspection and
reports fields that were added, removed, or changed type. The output recommends
review and rerunning evals, but never edits or promotes the catalog.

Exit `1` means drift was found; `0` means no drift; missing
`--experimental` exits `2`.

---

## `drafts` / `approve`

```bash
vectorsmith drafts list
vectorsmith drafts reject NAME
vectorsmith approve NAME [--file tools.yaml] [--approver USER] [--dry-run]
```

Reads `./tools.drafts.yaml` in the current working directory. Cap **10** pending; pending drafts **30 days** old expire on serve.

`approve` revalidates the draft before promotion, prints a semantic summary of
its kind, target, parameters, guardrails, provenance, and catalog-version
change, then preserves existing YAML comments/formatting while appending it.
Approval increments `meta.tool_catalog_version` and records the approver,
timestamp, hash, and resulting version on the draft.

`--dry-run` prints exactly that summary without changing the active catalog or
draft status. `--approver` defaults to `$USER`, then `local-user`.

`approve` interpolates the target YAML with an **empty** env map. Use
`${VAR:-default}` in that file or interpolation fails. `--file` defaults to
`tools.yaml`.

---

## `migrate`

```bash
vectorsmith migrate TOOLS.yaml --from 1 --to 2 --dry-run
vectorsmith migrate TOOLS.yaml --from 1 --to 2 --write
```

`--dry-run` prints a unified diff and does not write. `--write` rewrites the file (`tds_version: "2"`, list `static_filters` → `{must: …}`).

---

## `auth`

```bash
vectorsmith auth rotate-secret
vectorsmith auth revoke
```

Builtin HTTP OAuth admin. `rotate-secret` writes a new secret once to `~/.vectorsmith/access-secret.once` (mode 0600). `revoke` drops stored tokens.

---

## Exit codes (summary)

| Code | Typical |
|---|---|
| `0` | Success |
| `1` | `validate --strict` warnings, failed `eval` scenarios, or detected `drift` |
| `2` | Validation / usage / missing draft / `builtin` missing `https` URL |
| `3` | Live `test` / `introspect` / `discover` failure; `--auth none` off localhost |
