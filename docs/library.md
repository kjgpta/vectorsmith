# Library surface

Hub: [documentation home](index.md). This page is the **inventory** of what ships in `vectorsmith`. Field-by-field YAML is [tools.yaml](tools-yaml-reference.md). Commands are [CLI](cli.md). Call shapes are [Python API](python-api.md).

If a flag, extra, YAML key, HTTP route, or exception is not listed here, it is not a supported public surface.

---

## What you install

```bash
pip install "vectorsmith[<extra>,…]"
```

Published package: **`vectorsmith`** (CLI + `connect` / `load_tools`). Compiler source lives in `packages/core` and is **bundled into that wheel** — there is no second PyPI project.

### Store extras (pick the backends in your YAML)

| Extra | `connections.*.backend` |
|---|---|
| `qdrant` | `qdrant` |
| `pgvector` | `pgvector` |
| `chroma` | `chroma` |
| `pinecone` | `pinecone` |
| `weaviate` | `weaviate` |
| `milvus` | `milvus` |

Each store extra also pulls **FastEmbed**. Details: [vector stores](vector-stores.md).

### Other extras

| Extra | Used for |
|---|---|
| `langchain` / `langgraph` | `from vectorsmith import load_tools` |
| `openai-agents` | `BoundTools.as_openai_agents()` |
| `anthropic` | `BoundTools.as_anthropic()` |
| `embed-openai` | `defaults.embedding.provider: openai` or `azure_openai` |
| `embed-cohere` | `provider: cohere` (embed or rerank) |
| `auth-jwt` | `serve --auth jwt` |
| `auth-redis` | `--auth-store redis` and `security.rate_limit.store: redis` |
| `otel` | OpenTelemetry SDK + OTLP HTTP exporter when `observability.tracing.enabled` |
| `creds-aws` | AWS Secrets Manager credential provider |
| `rerank-local` | Local `cross_encoder` rerank |

---

## Public Python names

Application code imports the runtime from **`vectorsmith`**. Request identity
uses the bundled compiler API's `CallContext`:

| Import | Extra | Role |
|---|---|---|
| `from vectorsmith import connect` | store | `BoundTools` — `call`, `schemas`, adapters |
| `from vectorsmith import load_tools` | `langchain` | LangChain `StructuredTool` list |
| `from vectorsmith.langgraph import load_tools` | `langgraph` | same function |
| `from vectorsmith.openai_agents import load_tools` | `openai-agents` | Agents SDK tools |
| `from vectorsmith.anthropic import load_tools` | `anthropic` | Messages API tools + `execute` |
| `from vectorsmith_core.api import CallContext` | none | Optional authenticated identity for `BoundTools.call(..., ctx=...)` and framework wrappers |

**Do not import `Engine`.** Authoring/CI may use `from vectorsmith_core import load_project`.

Envelope and exceptions: [Python API](python-api.md).

---

## CLI commands

`init` · `validate` · `test` · `serve` · `introspect` · `migrate` ·
`drafts` · `approve` · `auth` · experimental `discover` · experimental `eval`
· experimental `drift`

The lifecycle prototypes require `--experimental` and never auto-promote.
Every flag: [CLI](cli.md).

---

## HTTP routes (`serve --http`)

| Method | Path | When |
|---|---|---|
| `GET` | `/healthz` | Always `{"ok": true}` (liveness) |
| `GET` | `/readyz` | **503** if any connection is down, a required embedder fails (every project with search/pipeline tools, or `--live-embed`), or JWT JWKS cannot be fetched |
| `GET`/`POST` | `/mcp` | MCP. `POST` is the tool path |
| `GET` | `/metrics` | Only if `observability.metrics.enabled` |
| `GET` | `/.well-known/oauth-protected-resource` | Builtin OAuth |
| `GET` | `/.well-known/oauth-authorization-server` | Builtin OAuth |
| `GET`/`POST` | `/oauth/authorize` · `/oauth/token` · `/oauth/register` · `/oauth/revoke` | Builtin OAuth |

Auth: `--auth none` (loopback only) · `builtin` (needs `https` `--public-url`) · `jwt` (JWKS reachability is part of `/readyz`) · `api_key`.

During SIGTERM drain, new `POST /mcp` returns **503** `shutting_down`. Rate limits → **429**. Tool deadline → **504**. RBAC deny → **403**. Auth failure → **401**.

HTTP MCP initialize accepts `2024-11-05`, `2025-03-26`, `2025-06-18`, and
`2025-11-25`. Unsupported or missing protocol versions return JSON-RPC
`-32022` with requested/supported details.

---

## `tools.yaml` map

| Area | Keys | Page |
|---|---|---|
| File | `tds_version`, `connections`, `tools`, `defaults`, `authoring`, `security`, `observability`, `profiles`, `meta` | [YAML](tools-yaml-reference.md#top-level-keys) |
| Store | six backends, `builtin_tools`, `credentials` | [YAML](tools-yaml-reference.md#connections) · [stores](vector-stores.md) |
| Search | `query` (`min_score`, `ef`, `expand`, embedding object) | [YAML](tools-yaml-reference.md#query) · [embed](embedding-providers.md) |
| Guardrails | `static_filters` must/must_not, `security.tenancy`, `security.rbac` | [YAML](tools-yaml-reference.md#static_filters) · [enterprise](enterprise.md) |
| Auth / quotas | `security.auth`, `security.rate_limit` | [YAML](tools-yaml-reference.md#securityauth) · [CLI](cli.md) |
| Output | `fields`, limits, `redact`, `rerank` | [YAML](tools-yaml-reference.md#output) |
| Pipelines | `steps`: retrieve, post_filter, group_by, sort, project | [YAML](tools-yaml-reference.md#pipeline-tools) |
| Ops | `observability.audit` / `tracing` / `metrics` | [observability](observability.md) |
| Enterprise validate | `validate --enterprise`, `--policy-builtin` | [hardening](security-hardening.md) |

---

## Runtime exceptions

All subclass `vectorsmith_core.errors.VectorSmithError` (`code`, `detail`, `retryable`):

| Class | `code` | Typical |
|---|---|---|
| `TDSValidationError` | `tds_invalid` | Load/validate failed (`issues` list) |
| `MissingEnvError` | `missing_env` | Unset `${VAR}` or missing vault path |
| `AuthError` | `auth_error` | HTTP 401 / RBAC 403 |
| `BackendUnreachable` | `backend_unreachable` | Store down |
| `InvalidArgumentsError` | `invalid_arguments` | Schema / unknown tool |
| `SchemaDriftError` | `schema_drift` | Pipeline column mismatch |
| `RateLimited` | `rate_limited` | HTTP 429; `retry_after_s` |
| `QueryTimeout` | `timeout` | `CallContext.deadline_s` exceeded |
| `ExprError` | `expr_error` | Pipeline `post_filter` expr |
| `EmbeddingError` | `embedding_error` | Embed provider failed |
| `InternalError` | `internal` | Unexpected |

Issue codes (`VBxxxx`, `VE00x`, `POL000`): [YAML codes](tools-yaml-reference.md#codes-you-will-actually-hit).

---

## What this library is not

- Not an IdP, API gateway, or hosted SaaS
- Not write tools (no upsert / delete / create-collection)
- Not a second copy of your vector database
- `Engine` is not a public SDK

**0.2.0** is the production HTTP server: JWT, tenancy, RBAC, credential resolvers, audit / OTel / Prometheus, Redis rate limits, and enterprise hardening at `serve` / `connect`.

That status describes the HTTP runtime. Every current vector-store adapter is
still experimental; see [backend conformance](conformance.md).

---

## Examples in this repo

| Path | What |
|---|---|
| `examples/qdrant_invoices/` | Invoice + ticket YAML |
| `examples/enterprise/` | JWT + tenancy + RBAC + audit (`tds_version: "2"`) |
| `examples/mcp_hosts/` | Claude Desktop / Code / Codex / Cursor JSON |
| `examples/langchain_agent/` · `langgraph_agent/` · `openai_agents/` · `anthropic_agent/` | In-process agents |

Deploy: [Kubernetes](deploy/kubernetes.md) · [deploy-templates/](https://github.com/kjgpta/vectorsmith/blob/main/deploy-templates/README.md).
