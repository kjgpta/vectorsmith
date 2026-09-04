# Backend support and conformance

Hub: [documentation home](index.md) · Capability matrix: [vector stores](vector-stores.md).

VectorSmith has adapters for Qdrant, pgvector, Chroma, Pinecone, Weaviate, and
Milvus. Every current adapter is classified as **experimental**: its advertised,
read-only surface is usable and tested, but it has not yet passed the complete
fault and supported-version matrix required for a stable designation.

`experimental` does not mean “silently best effort.” Unsupported semantics are
removed from the capability matrix or rejected during validation.

## Latest local evidence

<!-- BEGIN GENERATED: conformance-evidence -->
The latest pinned local run recorded **312 backend test instances**: **183 passed**, **129 capability-gated skips**, and **0 failed**.

| Backend | Server | Client | Passed | Skipped | Failed |
|---|---:|---:|---:|---:|---:|
| Qdrant | 1.13.2 | 1.19.0 | 34 | 18 | 0 |
| pgvector | pgvector/pg16 | 3.3.4 | 34 | 18 | 0 |
| Chroma | 1.5.0 | 1.5.9 | 28 | 24 | 0 |
| Pinecone Local | 2025-01 | 9.1.0 | 20 | 32 | 0 |
| Weaviate | 1.28.5 | 4.23.0 | 34 | 18 | 0 |
| Milvus | 2.5.4 | 3.0.1 | 33 | 19 | 0 |
<!-- END GENERATED: conformance-evidence -->

These numbers describe one reproducible local version set, not every hosted
configuration or SDK/server combination.

## What the shared contract checks

The live suite seeds the same deterministic 1,000-record source dataset into
each backend and compares native results with a backend-independent oracle.
Applicable cases cover:

- health and collection visibility;
- comparison filters and nested `And` / `Or`;
- hidden static-tenant isolation for search, lookup, count, and scroll;
- native record IDs distinct from metadata fields named `id`;
- filtered counts, limits, offsets, projections, score inclusion, and
  exhaustion;
- Unicode, null and missing values, rare filters, large documents, arrays where
  supported, and adversarial reserved metadata keys;
- dense filtered self-recall and higher-is-better `_score` ordering;
- synthesized semantic-search, exact-ID, and count builtins;
- read-only draft behavior and approval validation;
- unsupported semantics failing explicitly;
- cleanup and translation of unexpected SDK failures into VectorSmith errors.

An advertised capability must pass. A test is skipped only when the backend
capability object says the operation is unavailable.

## Backend-specific status

### Qdrant

Dense search, filter-only reads, nested filters, null/existence, text matching,
filtered count, exact-ID lookup with residual tenant filters, projection, score
threshold, HNSW `ef`, array containment, native payload-index introspection,
and seeded dense-plus-BM25 sparse fusion are covered.

Still required for stable status: hosted authentication/timeout fault classes
and successful minimum/newest supported client observations in CI.

### pgvector

Vector mode passes nested JSON filtering, array containment, configured
ID-column handling, null/existence, `like`, filtered counts, offset pagination,
projection, typed catalog introspection, and distance-to-score normalization.
Table mode separately proves lookup, filtered count, pagination, and rejection
of vector search.

Still required: exact versus iterative scan reporting, hosted
network/authentication faults, and more PostgreSQL/pgvector version combinations.

### Chroma

Documents are returned as `_document` without replacing metadata named
`content`; native IDs win over metadata collisions; distances become
higher-is-better scores; filter-only offsets, projection, paginated filtered
count, HTTPS/auth construction, unsupported operators, and cleanup are covered.

Still required: the second intended compatible client/server generation and
the complete connection/authentication/malformed-response fault matrix.

### Pinecone

Dense vector search, namespace scoping, all eight metadata comparison filters,
array containment, projection, and score inclusion are covered with Pinecone
Local.

VectorSmith intentionally does **not** advertise filter-only lookup/scroll,
filtered count, deterministic sampling, hybrid search, nested paths, or
guardrail-preserving exact-ID lookup. Pinecone therefore has the largest number
of capability-gated skips. Use namespaces—not a metadata predicate alone—for a
hard tenant boundary.

### Weaviate

Filters are applied to fetch, near-vector, hybrid, and aggregate calls.
Filter-only pagination, array containment, projection, score metadata, filtered
counts, typed collection introspection, vectorizer-backed server embedding, and
off-event-loop SDK execution are covered.

Null/existence filters are not advertised because they require collection-side
null-state indexing that the current connection contract cannot guarantee.
Nested object filter paths are also not advertised: Weaviate 1.28 rejects dotted
object-property paths even though nested objects can be stored. Native
multi-tenancy and more fault/version combinations remain stability work.

### Milvus

Dense and filter-only reads, nested dynamic JSON, array containment, `like`,
filtered count parsing, typed collection introspection, projections, ID
normalization, metric-aware score direction, and off-event-loop SDK execution
are covered.

Hybrid search and dynamic-field null/existence filters are not advertised.
Additional database/collection-scope, fault, and version coverage is required.

## Support-level rules

The compiler emits:

- `VB2024` as a warning when a connection targets an experimental backend;
- `VB2025` as an error when an enabled builtin cannot preserve exact-ID or
  filtered-count isolation on that backend;
- `VB2026` as a live-validation error when an explicitly indexed backend is
  missing an index for a filter path.

Every public row in the [documented matrix](vector-stores.md) is generated and
snapshot-checked from the runtime capability objects.

No backend should be promoted to stable until its applicable live parity,
tenant-isolation, timeout, authentication, malformed-response, cleanup, and
supported-version cases pass in required CI.

## Running the suite

Install all adapter SDKs and start the pinned local services:

```bash
uv sync --group dev --group conformance --frozen
docker compose up -d
PYTHONPATH=packages/core:packages/cli:. \
  uv run pytest tests/conformance --backend all --tb=short
docker compose down --volumes
```

Run one backend with `--backend qdrant` (or another backend name). The suite
writes `.internal/phase2/conformance-evidence.json` locally with exact versions,
capabilities, results, failures, and timing. That artifact is intentionally not
published.

GitHub Actions exposes non-blocking pinned, minimum-client, and
newest-tested-client jobs for every experimental backend. Those jobs increase
visibility but do not make an experimental backend stable and do not trigger
publishing.
