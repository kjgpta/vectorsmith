# Changelog

Format: [Keep a Changelog](https://keepachangelog.com/en/1.1.0/).
Versioning: [SemVer](https://semver.org/).

## [Unreleased]

### Fixed

- Experimental client-boundary CI now isolates each backend SDK instead of allowing
  unrelated stores to create transitive dependency conflicts.
- The Qdrant extra includes FastEmbed for its BM25 sparse hybrid path, and Weaviate's
  minimum client is 4.16.9 because older releases fail boolean-filter serialization
  with current protobuf.

## [0.2.1] — 2026-09-04

### Added

- Experimental local contract-lifecycle commands, all gated by `--experimental`:
  - `vectorsmith discover` introspects selected collections, recommends only operators
    supported by the target backend, identifies likely tenant fields, and writes pending
    schema-backed drafts without modifying the active catalog;
  - `vectorsmith eval` runs checked-in tool-call scenarios through the normal execution
    engine and records tool/argument mismatches, row-count invariants, required and forbidden
    field values, score thresholds, and execution failures in a JSON report;
  - `vectorsmith drift` compares a checked-in metadata-only schema report with live
    introspection and reports added, removed, and type-changed fields without promoting
    changes.
- Approval previews and provenance: `vectorsmith approve --dry-run` prints the proposed
  read-only tool, target, parameters, guardrails, catalog-version change, and provenance
  without mutating either file. Successful approval records the approver, timestamp, draft
  hash, and catalog version, increments `meta.tool_catalog_version`, and uses round-trip YAML
  editing to preserve existing comments and formatting.
- Optional Python `CallContext` propagation through `BoundTools.call()`, including principal,
  claims, roles, tenant identity, deadline, and request ID where supported by LangChain /
  LangGraph, OpenAI Agents, and Anthropic wrappers. Existing calls without a context remain
  backward compatible.
- Explicit backend `support_level` and guardrail-preserving `id_lookup` capability metadata.
  All current backend integrations remain `experimental` pending their complete fault and
  supported-version matrices.
- Compiler warning `VB2024` for experimental backend connections and error `VB2025` when a
  synthesized exact-ID or filtered-count builtin cannot preserve the backend's advertised
  isolation contract.
- A deterministic six-backend conformance suite over 1,000 generated records, covering
  universal and capability-gated adapter behavior, synthesized builtins, draft safety,
  hidden-tenant isolation, Filter IR parity, exact IDs, counts, pagination, projection,
  score direction, Unicode, null/missing values, large documents, reserved metadata,
  cleanup, and foreign-exception translation.
- A backend-independent oracle for filter evaluation, deterministic vector ranking,
  pagination, and projection, plus a local evidence artifact containing client/server
  versions, capability snapshots, per-backend pass/skip/failure counts, and timing.
- Visible, non-blocking CI conformance jobs for Qdrant, pgvector, Chroma, Pinecone Local,
  Weaviate, and Milvus. Experimental backend failures remain diagnostic and do not publish
  or trigger releases.
- Direct live capability proofs for nested paths, array containment, typed introspection,
  Qdrant dense/BM25 sparse fusion, Weaviate server-side embedding, Pinecone comparison
  filters, and pgvector table mode, with per-capability evidence in the local artifact.
- Reproducible minimum, pinned, and newest-tested backend client boundaries plus CI jobs
  that exercise each boundary against the pinned server generation.
- Live index validation error `VB2026` for filter paths missing an explicit native index on
  backends that require one.

### Changed

- MCP is constrained to `mcp>=2,<3`. HTTP initialization now negotiates the requested
  handshake version across `2024-11-05`, `2025-03-26`, `2025-06-18`, and `2025-11-25`;
  unsupported or missing versions return JSON-RPC error `-32022` with the requested and
  supported versions.
- Stdio MCP serving uses the handshake-only loop so a modern `server/discover` probe cannot
  lock the connection into the 2026 protocol era and reject a subsequent legacy
  `initialize` request. This covers the GitHub Copilot CLI discover-before-initialize
  sequence while preserving normal Claude, Cursor, Codex, and older-client handshakes.
- Latency metrics use fixed Prometheus histogram buckets with `_bucket`, `_count`, and `_sum`
  output instead of retaining every observed latency sample indefinitely.
- Synchronous Pinecone, Weaviate, and Milvus SDK operations run through `asyncio.to_thread`
  so adapter calls do not block the async runtime; close operations now release SDK clients
  and local controller/index resources deterministically.
- Every documented vector-store matrix row is generated and checked against runtime
  capabilities. Pinecone no
  longer advertises hybrid search, filtered count, scrolling, or guardrail-preserving
  exact-ID lookup; Milvus no longer advertises hybrid or null/existence filters; Weaviate no
  longer advertises null/existence filters unless that collection-level indexing contract
  can be guaranteed.
- Local backend infrastructure pins compatible server versions, uses Chroma 1.5.0, exposes
  Weaviate gRPC, and pins Pinecone Local by image digest for reproducible conformance runs.
- The Chroma optional dependency constrains NumPy to `<2` for compatibility with supported
  Chroma client generations and now requires a schema-compatible Chroma 1.5 client.
- Weaviate connections accept `embedding_mode: auto | client | server`; `auto` selects a
  collection vectorizer only when native introspection proves it is available.

### Fixed

- Chroma results now include document bodies in the reserved `_document` field without
  overwriting metadata, normalize distances to higher-is-better `_score` values, and honor
  exact record IDs, filter-only offsets, projections, paginated filtered counts, HTTPS,
  bearer authentication, and client cleanup.
- Chroma no longer advertises unsupported SQL-style `like` filters; validation reports
  `VB2004` instead of silently compiling wildcard patterns as equality.
- Qdrant exact-ID extraction preserves residual tenant filters, treats conflicting IDs as
  impossible, prevents payload `_id` values from replacing native IDs, implements native
  existence and text-match filters, rejects unsupported vector offsets before SDK access,
  paginates filter-only reads, and translates unexpected SDK failures consistently.
- Qdrant hybrid search now generates BM25 sparse vectors locally, queries a named sparse
  vector, honors HNSW `ef`, and is covered by a seeded live ranking contract.
- pgvector now composes nested JSON paths and configured ID columns safely, implements
  `exists`, `is_null`, and `like` explicitly instead of silently broadening unsupported
  predicates to `TRUE`, applies filter parameters in the correct order, honors offsets and
  projections, strips embedding internals, and converts lower-is-better distance into a
  higher-is-better `_score`.
- Pinecone now rejects unsupported filter-only lookup/scroll, filtered count, deterministic
  sample, and nested-filter semantics instead of returning partial or misleading results.
  Dense results honor projection and score flags.
- Weaviate applies compiled filters to fetch, near-vector, hybrid, and aggregate operations;
  filter-only reads honor limit, offset, and projection, and vector/hybrid results expose
  available score metadata. Server-vectorized collections use `near_text` without invoking
  a client embedder. Nested object filters are rejected because the supported server rejects
  dotted object-property paths.
- Milvus correctly parses filtered `count(*)` responses, supports filter-only reads, removes
  native ID aliases from projected rows, normalizes score direction according to the
  collection metric, rejects vector offsets, and fails explicitly for unsupported filter
  operators.
- Qdrant, pgvector, Pinecone, Weaviate, and Milvus implement exact `contains_any` and
  `contains_all` array-filter contracts; nested paths are proved for Qdrant, pgvector, and
  Milvus. Static-filter capability checks now match user parameter checks.
- Adapter health, collection listing, search, count, and sample paths translate unexpected
  third-party SDK exceptions to VectorSmith backend errors instead of leaking foreign
  exception types.
- Disabling OpenTelemetry tracing now shuts down its batch provider, preventing exporter
  threads from surviving process teardown.
- Reranking recognizes Chroma's reserved `_document` field as source text before falling
  back to metadata fields such as `content`, `body`, or `title`.
- Structurally invalid pending drafts now retain a fully valid inert placeholder tool while
  reporting the original validation issues, instead of constructing a partially invalid
  model.

### Security

- Shared live and builtin conformance cases prove hidden static-tenant filters remain attached
  to search, exact-ID lookup, count, and scroll paths. Builtins that cannot preserve those
  constraints are rejected during validation rather than exposed with weaker semantics.
- Recursive inline-secret linting now inspects values only beneath credential-bearing keys
  such as `api_key`, `auth_token`, `token`, `password`, and `dsn`, avoiding false positives
  from unrelated URLs and ordinary configuration text while retaining nested credential
  detection.
- Security guidance now distinguishes desktop/stdio static tenancy, authenticated HTTP
  claim/header tenancy, and caller-supplied Python in-process identity; these profiles are
  documented as separate trust models rather than interchangeable guarantees.

## [0.2.0] — 2026-08-23

Production HTTP MCP server. Every `security.*`, `observability.*`, credential, rerank, and `profiles.enterprise` knob that 0.1.3 *declared* is now applied at `serve` and `connect` — not only at `validate`. Same YAML still compiles to in-process `load_tools`.

### Added

- Credential resolvers at runtime: `vault` (`VAULT_ADDR` / `VAULT_TOKEN`), `aws_sm` (`vectorsmith[creds-aws]`), and in-cluster `k8s` Secrets. Missing config is **VB4040**–**VB4042**. Extra `vectorsmith[creds-aws]`.
- OTLP span export from `observability.tracing.endpoint` / `exporter: otlp` (`vectorsmith[otel]` now includes the OTLP HTTP exporter). `exporter: console` still prints spans.
- Local `rerank.provider: cross_encoder` (`vectorsmith[rerank-local]`). Encoder instances are cached; `predict` runs in `asyncio.to_thread`. Missing extra is **VB4032**; runtime failure keeps vector order (**VB4031**).
- `profiles.enterprise` hardening at `serve`, `connect`, and `load_tools` (same refuse rules as `validate --enterprise`: authoring/meta off, tenancy required, `limit_max`, allowed backends).
- `validate --policy FILE.rego` runs `opa eval` with the compiled TDS as input JSON. Each Rego `deny` is **POL001**; missing `opa` is **POL000**.
- `GET /readyz` fetches JWKS when `--auth jwt` (503 if the IdP is unreachable).
- JSON logs include OTel `trace_id` / `span_id` when tracing is on (same `request_id` as audit).
- Audit `sink: otlp` posts OTLP HTTP JSON logs to `{url}/v1/logs` (collector). `sink: http` remains a raw JSONL webhook.
- Claim vs static enterprise examples (`examples/enterprise/tools.yaml` and `tools.static.yaml`) so copy-paste does not AND both tenancy layers.
- TDS v2 schema `$comment` documents the shared structure with v1 (`migrate` still only sets `tds_version`, seeds `meta`, and rewrites bare `static_filters` lists).

### Changed

- HTTP `serve` configures tracing, metrics, and audit for a **single** YAML as well as multi-project.
- Multi-project `serve` unions enterprise flags and observability across every file (strictest authoring/meta; tracing/metrics if any project enables them) and builds each engine’s audit sink from that YAML unless `--audit-*` is set.
- Multi-project `GET /readyz` checks embed health on every project that has search/pipeline tools (or `--live-embed`), not only the default.
- Redis rate limits use `redis.asyncio` (or `asyncio.to_thread` for a sync test client). Extra `vectorsmith[auth-redis]`.
- Helm chart / image tag **0.2.0**. Docs cover the production HTTP surface: JWT, tenancy, RBAC, credentials, probes, OTel, extras.

### Fixed

- Multi-project HTTP `serve` reads auth from `engine.project` (no `NameError` on `project`).
- `rerank.provider: cross_encoder` no longer silently falls through to the HTTP provider.
- `connect` / `load_tools` apply `profiles.enterprise` (they previously skipped serve-time hardening).

### Security

- Enterprise hardening refuses a non-compliant process at start, not only in CI `validate`.
- `/readyz` is the production gate: every connection, required embedder(s), and JWT JWKS. `GET /healthz` stays liveness-only (200).

## [0.1.3] — 2026-08-22

### Added

- Pluggable embedding providers: `fastembed` (default), `openai`, `azure_openai`, `http`, `cohere`. String `defaults.embedding` still works.
- `${VAR}` interpolation and secret lint under `defaults.embedding.config` / `query.embedding.config`.
- Extras `vectorsmith[embed-openai]` and `vectorsmith[embed-cohere]`. **VB2019** if the extra is missing.
- `validate --live-embed` smoke-tests the embedder. HTTP `GET /readyz` checks provider health when `serve --http --live-embed`.
- `static_filters` object form: `must` / `must_not` (bare list still means `must` only).
- `query.min_score` and `query.ef` (Qdrant `score_threshold` / HNSW `ef`; post-filter as a safety net).
- Request-scoped tenancy: `security.tenancy` (`claim` / `header`) ANDs a payload filter from caller identity. **VB4010** / **VB4011** / **VB4012**.
- HTTP auth providers: `--auth jwt` (JWKS / RS256) and `--auth api_key`, plus `--auth-store redis` for shared builtin OAuth tokens. Extras `vectorsmith[auth-jwt]` and `vectorsmith[auth-redis]`. `--auth none` is still loopback-only (exit 3).
- Tool-level RBAC: `security.rbac` (`roles`, `deny_tools`). Applied on `run_tool`. **VB4013** / **VB4014**.
- Audit log: `observability.audit` and `--audit-log` / `--audit-sink`. JSONL events; redacted args; sink failures do not block the call.
- Rate limits: `security.rate_limit` (off by default). Per-principal / per-tool / embed windows; Redis-shareable. HTTP **429** with `retry_after_s`.
- Parameter `resolve.kind: directory` (fuzzy / cached). **VB4020** / **VB4021**.
- `output.redact` (`omit` / `hash` / `mask` / `pattern`) and `output.max_field_length`. Applied before the result (and audit) is returned.
- Credential backends: `connections.*.credentials.provider` (`env` / `vault` / `aws_sm` / `k8s`). Missing secret still surfaces as `MissingEnvError`.
- `GET /readyz` checks every connection and embed health when search tools exist (or `--live-embed`). **503** if any fail. `GET /healthz` stays 200.
- Optional OpenTelemetry spans and Prometheus `GET /metrics`. Extra `vectorsmith[otel]`. Off by default.
- `validate --enterprise` / `--profile enterprise` (`VE001`–`VE007`) and `--policy` / `--policy-builtin` (`pci`, `soc2`, `enterprise`).
- Multi-project `serve`: extra YAML args, `--route-by-claim`, `--default-project`. Duplicate tool names fail at startup.
- Optional `query.expand` (N+1 embeds, merge by best score; failure **VB4030**) and `tool.rerank` (`retrieve_k` then reorder; failure **VB4031`). Both off by default.
- Helm chart, Docker image, and compose stack under `deploy-templates/` (readyz probes, Redis auth store, graceful drain).
- `vectorsmith migrate --from 1 --to 2` (`--dry-run` / `--write`). `tds_version: "2"` + `meta`. v1 still loads with **VB0002**.
- Request `deadline_s` → `QueryTimeout`. `--shutdown-grace-s` drains HTTP; new `POST /mcp` is **503** while draining.
- `--log-format json --log-level info`. Default text logs unchanged. JSON includes `request_id` (same as audit).
- Docs inventory page (`docs/library.md`): extras, HTTP routes, exceptions, public imports. YAML reference covers credentials, expand, resolve, redact, profiles, and remaining `VBxxxx` codes.

## [0.1.2] — 2026-08-20

### Added

- `vectorsmith serve --no-meta-tools` omits `list_available_tools` / `run_tool` (compiled tools only). Default remains on for Claude Desktop’s frozen `tools/list`.
- `validate --live` embedding fingerprint: **VB2017** (collection dim ≠ known embedder, error), **VB2018** (unknown model id, warning).
- `validate --live` payload-path drift: **VB4004** (YAML path not seen on sampled/native fields, warning).
- Qdrant search can request a payload include-list when the tool has `output.fields`; Milvus `search` uses `output_fields` the same way.

### Changed

- Compiler honors `defaults.embedding` on the execution plan. Per-tool `query.embedding` still wins.
- `run_tool` description states that inner arguments are re-validated against the named tool’s compiled schema and that `static_filters` still apply. `additionalProperties` on the MCP envelope is not a typing bypass.

### Fixed

- Documented Pinecone `collection` = index namespace and Weaviate connection `tenant` vs payload `static_filters`, so those are not mistaken for the same isolation layer.

## [0.1.1] — 2026-08-19

### Changed

- PyPI long description is the package README (install, two doors, YAML sketch, store extras).
- Builtin HTTP OAuth writes the one-time access secret to `~/.vectorsmith/access-secret.once` (mode 0600) instead of printing it.

### Fixed

- Secret-lint corpus no longer uses a Stripe `whsec_` sample that GitHub secret scanning treated as a live key.

## [0.1.0] — 2026-08-19

First public release.

### Added

- `tools.yaml` (TDS v1): connections, user tools, opt-in built-ins, pipelines.
- Adapters: Qdrant, pgvector (vector + table), Chroma, Pinecone, Weaviate, Milvus.
- CLI: `init`, `validate`, `serve` (stdio + HTTP/OAuth), `test`, `introspect`, `drafts`, `approve`, `auth`.
- In-process API: `load_tools` (LangChain / LangGraph), `connect`, OpenAI Agents and Anthropic adapters.
- MCP host docs and examples: Claude Desktop, Claude Code, Codex, Cursor.
- Agent examples: LangChain, LangGraph, OpenAI Agents SDK, Anthropic Messages API.
