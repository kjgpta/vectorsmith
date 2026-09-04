# FAQ

Hub: [documentation home](index.md) · [Getting started](getting-started.md) · [CLI](cli.md).

## Install and run

### Which vector stores are supported?

Six: **Qdrant, pgvector, Chroma, Pinecone, Weaviate, Milvus**. All
currently have **experimental** support status: their advertised read-only
capabilities are tested, but the full fault and version matrix required for
stable status is incomplete. Install `vectorsmith[<backend>]`. There is no
extra for Elasticsearch, Redis, or OpenSearch. Details:
[vector stores](vector-stores.md) and
[backend conformance](conformance.md).

### `vectorsmith: command not found`

Install so the CLI is on `PATH`: `pip install "vectorsmith[qdrant]"` (or `uv sync` in this repo, then `uv run vectorsmith …`). Claude Desktop often cannot see a venv under `~/Downloads` — [Desktop](quickstart-desktop.md).

### Validation says a variable is missing, but it is in my shell

The CLI interpolates **only** `--env-file`. Exporting `QDRANT_URL` in the terminal does nothing unless that key is in the file (or the YAML uses `${QDRANT_URL:-default}`).

`load_tools` / `connect` **do** read `os.environ`.

Host JSON `env: { "QDRANT_URL": "…" }` is **not** used for `${VAR}` in YAML. Keep using `--env-file`.

### Desktop shows **Server disconnected**

The MCP process cannot start. Common cause: sandboxed `~/Downloads` venv (`PermissionError` on `pyvenv.cfg`). Install under `~/Claude` or `~/Documents`, or set `command` to that venv’s absolute `vectorsmith` binary.

If a GitHub Copilot CLI client reports that the connection is serving the
2026 protocol and rejects a `2025-11-25` initialize handshake, upgrade to a
VectorSmith build containing the Phase 2 MCP fix. Stdio now remains in the
handshake protocol when Copilot probes `server/discover` before `initialize`.

### Claude never sees a tool I just added to YAML

Desktop freezes the named list at connect. Stdio `--watch` **recompiles** the process (new YAML → new plans and schemas). Desktop still ignores `notifications/tools/list_changed`, so the Connectors UI stays stale until reconnect. Default `serve` advertises `list_available_tools` then `run_tool` so new names stay reachable without reconnecting. HTTP `serve` does not watch — restart the process.

Use `--no-meta-tools` if you do not want those two dispatchers; then a reconnect (or a host that honors `tools/list_changed`) is required after YAML edits.

### Is `run_tool` a way around enums and tenant filters?

No. `run_tool` exists because Claude Desktop freezes `tools/list`. It is MCP-only (`load_tools` / `connect` never advertise it). Calling it runs the **same** `engine.call` path as a named tool: jsonschema on that tool’s compiled `inputSchema` (types, enums, limits), then hidden `static_filters` and request tenancy AND-merged into the store filter. The envelope field `arguments` allows extra keys at the MCP layer; they are still validated against the inner schema. Disable with `--no-meta-tools`.

### `serve --http` exits 2 or 3

| Exit | Cause |
|---|---|
| `3` | `--auth none` on a non-loopback bind (`0.0.0.0`, a hostname) |
| `2` | `--auth builtin` (the default) without `https://` `--public-url` |

Local: `--http 127.0.0.1:8080 --auth none`. Public: `--auth builtin --public-url https://…`, or `--auth jwt` / `--auth api_key`.

---

## YAML and tools

### Is this the same as official Qdrant / Pinecone MCP?

No. Vendor servers are cluster admin (often including writes). VectorSmith is **read-only**, tenant-scoped tools you declared. You can run both — [coexistence](coexistence.md).

### Why isn’t `tenant` in the tool schema?

`static_filters` are applied on every call and are not advertised. Put org isolation there so the model cannot skip it. That is a payload field, not Pinecone namespace or Weaviate `connections.*.tenant` — [vector stores](vector-stores.md#tenancy-vs-payload-filters).

For **request-scoped** isolation (each caller is a different tenant), set
`security.tenancy.mode` to `claim` or `header`. The engine ANDs that filter
from the JWT claim or `X-Tenant-Id` header. That path is never in the MCP
schema. Stdio has no authenticated caller identity, so use static tenancy and
separate processes there. Python `connect` / `load_tools` can receive a
caller-supplied `CallContext`; the embedding application must construct it from
an authenticated request.

### Which embedding model actually runs?

`query.embedding` on the tool if set, otherwise `defaults.embedding` (string or `{provider, model, dims}`). Default is FastEmbed `fastembed/BAAI/bge-small-en-v1.5`. OpenAI / Azure / Cohere / HTTP need the matching extra and usually an explicit `dims`. `validate --live` errors **VB2017** on dim mismatch, warns **VB2018** if the model is unknown without `dims`, and errors **VB2019** if the provider extra is missing.

### How do I point YAML at a hosted Qdrant (TrueFoundry, Cloud, …)?

Use the **REST API base**, not the `/dashboard` UI URL. Put it in `.env` as `QDRANT_URL` (plus `QDRANT_API_KEY` if the cluster requires it). Match embedding `dims` to the collection. See [vector stores → hosted Qdrant](vector-stores.md#hosted-qdrant-or-any-remote-cluster).

### `VB0002` on every old file

`tds_version: "1"` still loads. `vectorsmith migrate tools.yaml --from 1 --to 2 --dry-run` shows the rewrite. `--strict` treats the deprecation as failure.

### Hybrid search fails (`VB2012` / `VB2013`)

Needs a backend that currently advertises hybrid (**Qdrant or Weaviate**) and
sparse vectors on the collection. Confirm with `validate --live`. Chroma,
pgvector, Pinecone, and Milvus do not currently advertise hybrid.

### Name collision `VB2010` / `search_invoices`

Built-in `semantic_search` on connection `invoices` synthesizes `search_invoices`. Turn the built-in off or rename the connection. The invoice example omits built-ins for this reason.

### Two collections, one Claude connector or two?

One YAML with two `connections` = **one** `serve` = one connector. Two YAML files and two `serve --name` processes = two connectors (this repo: `invoices` and `tickets`).

---

## Python

### `from vectorsmith import load_tools` fails with missing `langchain_core`

Install `vectorsmith[langchain]` (or `[langgraph]`). For no LangChain: `from vectorsmith import connect`.

### Do I call `Engine`?

No. Use `connect` / `load_tools` or `vectorsmith serve`.

### Slack / GitHub next to VectorSmith in LangChain?

Keep them as MCP clients (`langchain-mcp-adapters`). VectorSmith tools stay in-process `load_tools` — [LangChain](integrations/langchain.md).

---

## Authoring

### Where is `tools.drafts.yaml`?

The process **cwd**. Set `cwd` in Desktop/Codex. Cap 10 pending; 30-day expiry.

### `approve` fails missing env

`approve` interpolates with an empty env map. Use `${VAR:-default}` in the YAML you approve into.

Use `approve NAME --dry-run` to inspect the semantic summary, catalog-version
increment, and provenance without changing either file. Successful approval
preserves existing YAML comments and formatting.

---

### Which pip extras exist?

Stores, agent SDKs, `embed-openai` / `embed-cohere`, `auth-jwt` / `auth-redis`, `otel`, `creds-aws`, `rerank-local`. Inventory: [library surface](library.md).

### Is HTTP `serve` production-ready?

The HTTP transport, authentication, probes, observability, and hardening
surface shipped in **0.2.0**. That is separate from backend stability: all six
adapters currently remain experimental and emit `VB2024`. Use `--auth jwt` or
`api_key` on a public bind, `GET /readyz` as the readiness probe, and
`--log-format json`. Keep `validate --enterprise --strict` in CI as an honest
gate; it remains non-zero until the selected backend earns stable status.
Chart: [Kubernetes](deploy/kubernetes.md). `--auth none` remains loopback-only.

## Still stuck

Repro with `validate --json` and a redacted `tools.yaml`. Security issues: [SECURITY.md](https://github.com/kjgpta/vectorsmith/blob/main/SECURITY.md), not a public GitHub issue.
