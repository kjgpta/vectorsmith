# Vector stores

Hub: [documentation home](index.md) · [tools.yaml](tools-yaml-reference.md) · [Python API](python-api.md).

VectorSmith talks to **your** cluster. It does not host a database. These six backends ship in the package; pick the extra that matches `connections.*.backend` in `tools.yaml`.

## What is integrated

| Store | `backend` in YAML | Install extra | Client pulled in |
|---|---|---|---|
| [Qdrant](https://qdrant.tech/) | `qdrant` | `vectorsmith[qdrant]` | `qdrant-client` |
| [PostgreSQL + pgvector](https://github.com/pgvector/pgvector) | `pgvector` | `vectorsmith[pgvector]` | `psycopg` (binary + pool) |
| [Chroma](https://www.trychroma.com/) | `chroma` | `vectorsmith[chroma]` | `chromadb` |
| [Pinecone](https://www.pinecone.io/) | `pinecone` | `vectorsmith[pinecone]` | `pinecone` |
| [Weaviate](https://weaviate.io/) | `weaviate` | `vectorsmith[weaviate]` | `weaviate-client` |
| [Milvus](https://milvus.io/) | `milvus` | `vectorsmith[milvus]` | `pymilvus` |

Every store extra also installs **FastEmbed** (`BAAI/bge-small-en-v1.5` by default) so search can embed queries locally. You do not need a separate embed extra on the published `vectorsmith` package.

```bash
pip install "vectorsmith[qdrant]"     # most common
pip install "vectorsmith[pgvector]"
pip install "vectorsmith[chroma]"
pip install "vectorsmith[pinecone]"
pip install "vectorsmith[weaviate]"
pip install "vectorsmith[milvus]"
```

Install more than one extra if a single `tools.yaml` has mixed `backend`s. The CLI (`serve`, `validate`, `test`) and `connect()` / `load_tools` use the same extras.

There is **no** first-party adapter for other stores (Elasticsearch, Redis, OpenSearch, …). Those are not integrated.

## What each backend can do

Capability gates reject YAML that the adapter cannot run (`validate`, including
`validate --live` for hybrid/sparse). A backend is `stable` only after its advertised
surface passes the live parity, isolation, fault, and supported-version matrix.
`experimental` means the implemented surface is usable but does not yet have that complete
evidence; it does not turn unsupported behavior into a best-effort operation.

The latest live server/client versions, per-backend pass/skip counts, covered
edge cases, and remaining promotion blockers are in
[backend conformance](conformance.md).

<!-- BEGIN GENERATED: backend-capability-matrix -->
| | Qdrant | pgvector | Chroma | Pinecone | Weaviate | Milvus |
|---|---|---|---|---|---|---|
| Dense search | yes | yes | yes | yes | yes | yes |
| Support level | experimental | experimental | experimental | experimental | experimental | experimental |
| Hybrid / sparse | yes | no | no | no | yes | no |
| Nested payload paths | yes | yes | no | no | no | yes |
| `exists` / `is_null` | yes | yes | no | no | no | no |
| `like` | no | yes | no | no | yes | yes |
| `text_match` in filter | yes | no | no | no | yes | no |
| Filtered count | yes | yes | yes | no | yes | yes |
| Scroll | yes | yes | yes | no | yes | yes |
| Guardrail-preserving exact-ID lookup | yes | yes | yes | no | yes | yes |
| Introspection | typed | typed | none | none | typed | typed |
| Server-side embedding | no | no | no | no | yes | no |
<!-- END GENERATED: backend-capability-matrix -->

**Every backend** accepts comparison ops: `eq` `ne` `gt` `gte` `lt` `lte` `in` `nin`.
Qdrant, pgvector, Pinecone, Weaviate, and Milvus also support `keyword[]`
containment through `contains_any` and `contains_all`; Chroma rejects array
filter parameters. Empty containment operands are rejected.

`typed` introspection combines native collection/catalog metadata with sampled
payload fields and labels each field's provenance. `none` means that the store
has no native typed schema contract; Chroma can still report sample-derived
metadata fields, while Pinecone rejects deterministic sampling.

Chroma does not support SQL-style wildcard or substring matching on scalar metadata,
so `like` is rejected during validation. Chroma document bodies are returned in the
reserved `_document` result field; metadata fields, including `content`, remain unchanged.
Its lower-is-better distances are exposed as higher-is-better scores using
`1 / (1 + max(0, distance))`.

Pinecone currently supports dense vector search and namespace isolation. VectorSmith rejects
filter-only lookup/scroll, filtered count, deterministic sampling, and hybrid mode instead of
returning partial or unfiltered results. Use a namespace for hard tenant isolation; metadata
guardrails alone cannot make Pinecone's ID fetch safe.

Weaviate `embedding_mode` may be `client`, `server`, or `auto` (the default).
`auto` uses server-side text embedding only when collection introspection finds
a configured vectorizer; otherwise VectorSmith embeds locally. `server` fails
closed when the target collection is self-provided. Weaviate nested objects can
be stored, but dotted object-property filters are not advertised because the
supported server generation rejects them.

**pgvector table mode** (`mode: table` or `vector_column: null`) is for lookup / count / scroll / pipeline only — no `kind: search` (`VB2016`).

Connection fields: [tools.yaml → connections](tools-yaml-reference.md#connections).

## Tenancy vs payload filters

`static_filters` in YAML are **payload predicates** (e.g. `tenant: acme` on the point/row). The compiler ANDs them on every call; they are not in the MCP schema. That is the VectorSmith isolation layer.

Store-native partitions are a different knob:

| Store | What `target.collection` means | Native tenancy (not `static_filters`) |
|---|---|---|
| Qdrant, Chroma, Milvus, pgvector | Collection / table name | None in the adapter. Use payload `static_filters`. |
| **Pinecone** | **Namespace** on the configured index (`connections.*.host`). Optional `connections.*.namespace` is the connection default. | Isolation by namespace is `collection: that_namespace`, not a metadata filter. Payload `static_filters` still apply **inside** the namespace. |
| **Weaviate** | Collection / class name | `connections.*.tenant` is the Weaviate multi-tenancy tenant on the client. Payload `static_filters` do **not** select that tenant. |

Do not expect `{ path: tenant, op: eq, value: acme }` to switch a Pinecone namespace or a Weaviate tenant. Set the namespace/collection or connection `tenant` in YAML, and keep payload filters for fields stored on the objects.

## Mixing stores

One YAML file can declare several connections with different backends. That is still **one** MCP server (`vectorsmith serve`). Each tool names `target.connection`. Two Claude connectors still mean two YAML files and two `serve --name` processes.

## Not a store extra

These extras are **agent SDKs**, not databases:

| Extra | For |
|---|---|
| `langchain` / `langgraph` | `load_tools` |
| `openai-agents` | `BoundTools.as_openai_agents()` |
| `anthropic` | `BoundTools.as_anthropic()` |

Embed / auth / telemetry extras (`embed-openai`, `embed-cohere`, `auth-jwt`, `auth-redis`, `otel`) are listed on [library surface](library.md). `connect()` only needs the store extra unless you use those features.

## Hosted Qdrant (or any remote cluster)

The dashboard URL (`…/dashboard`) is **not** the API. Put the REST base (no `/dashboard`) in `.env`:

```bash
QDRANT_URL=https://your-cluster.example.com
QDRANT_API_KEY=…
```

```yaml
connections:
  main:
    backend: qdrant
    url: ${QDRANT_URL}
    api_key: ${QDRANT_API_KEY:-}
```

Then `vectorsmith validate tools.yaml --live --env-file .env`. Match `defaults.embedding` to the model and **dims** used when the collection was indexed. Do not commit the live URL or key.
