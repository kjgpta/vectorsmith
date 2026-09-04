# VectorSmith

**Your vector database, forged into tools an agent can actually use.**

Write a `tools.yaml`. VectorSmith compiles it into typed, tenant-guarded tools — then you either import them in Python or serve them over MCP (stdio or production HTTP).

```bash
pip install "vectorsmith[qdrant]"
```

[Get started](getting-started.md){ .md-button .md-button--primary }
[tools.yaml reference](tools-yaml-reference.md){ .md-button }

--8<-- "docs/includes/demo-video-root.md"

---

## Two doors, one YAML

| You are building… | Use |
|---|---|
| A **Python agent** (LangChain, LangGraph, OpenAI Agents, Anthropic SDK) | [`load_tools` / `connect`](python-api.md) |
| A **chat / IDE host** (Claude Desktop, Claude Code, Codex, Cursor) | [`vectorsmith serve`](cli.md) (MCP stdio) |
| A **remote / Kubernetes MCP server** (claude.ai, gateways) | [`serve --http`](quickstart-selfhost.md) with JWT / probes / OTel |

Same file either way. The agent never sees the store URL, the API key, or hidden tenant filters.

---

## Find a page

### Tutorials

| | |
|---|---|
| [Getting started](getting-started.md) | Install, write YAML, prove a tool works |
| [Claude Desktop](quickstart-desktop.md) | Connectors, sandbox, `--watch` |
| [HTTP / claude.ai](quickstart-selfhost.md) | `serve --http`, OAuth, `/mcp` |

### How-to

| | |
|---|---|
| [Use in an agent](use-in-agents.md) | `load_tools` vs `serve` |
| [Integrations](integrations/README.md) | Claude, Codex, Cursor, LangChain, LangGraph, Agents SDK, Anthropic |
| [Next to other MCP servers](coexistence.md) | Slack, GitHub, filesystem, vendor MCP |
| [Deploy templates](https://github.com/kjgpta/vectorsmith/blob/main/deploy-templates/README.md) | Docker, Kubernetes, Cloud Run, Fly |

### Reference

| | |
|---|---|
| [Vector stores](vector-stores.md) | Qdrant, pgvector, Chroma, Pinecone, Weaviate, Milvus |
| [Backend conformance](conformance.md) | Live version matrix, tested contracts, skips, and stability blockers |
| [tools.yaml](tools-yaml-reference.md) | Every field, operators, pipelines, `VBxxxx` |
| [Library surface](library.md) | Extras, HTTP routes, exceptions, public imports |
| [CLI](cli.md) | Runtime, validation, approval, and experimental discover/eval/drift commands |
| [Enterprise](enterprise.md) | JWT, tenancy, RBAC, credentials, audit, rate limits |
| [Security hardening](security-hardening.md) | `--enterprise` checklist |
| [Embedding providers](embedding-providers.md) | FastEmbed, OpenAI, Azure, Cohere, HTTP |
| [Observability](observability.md) | Audit, traces, metrics, JSON logs |
| [Kubernetes](deploy/kubernetes.md) | Helm, probes, Redis auth store |
| [Python API](python-api.md) | `connect`, `load_tools`, extras, return envelope |

### Explanation

| | |
|---|---|
| [How it is put together](architecture.md) | Compile pipeline, two doors, what stays private |
| [FAQ](faq.md) | Desktop disconnects, env interpolation, HTTP auth, hybrids |
| [Repository map](repository.md) | What each top-level path is for |

Examples in the repo: [invoice + ticket YAML, enterprise JWT catalog, agent apps, MCP host configs](https://github.com/kjgpta/vectorsmith/tree/main/examples).

---

## Install extras

```bash
pip install "vectorsmith[qdrant]"              # CLI + connect()
pip install "vectorsmith[qdrant,langchain]"    # + load_tools for LangChain / LangGraph
pip install "vectorsmith[qdrant,langgraph]"
pip install "vectorsmith[qdrant,openai-agents]"
pip install "vectorsmith[qdrant,anthropic]"
```

Store extras: see [vector stores](vector-stores.md) (`qdrant` · `pgvector` · `chroma` · `pinecone` · `weaviate` · `milvus`).

Also: `embed-openai` · `embed-cohere` · `auth-jwt` · `auth-redis` · `otel` · `creds-aws` · `rerank-local`. Full list: [library surface](library.md).

---

## Status

**0.2.0** — production HTTP MCP server. Read-only tools from YAML. `serve --http` applies tenancy, RBAC, credential resolvers, audit, tracing, metrics, rate limits, and `profiles.enterprise` at process start. Application code uses `from vectorsmith import load_tools` or `connect` — do not import `Engine`.

**Unreleased Phase 2 foundation** — all six adapters are explicitly
experimental. The generated conformance report records current applicable
passes, capability-gated skips, failures, and exact client/server versions. It
also adds MCP compatibility, Python identity context, bounded metrics, semantic
approval, and opt-in local `discover`, `eval`, and `drift` prototypes. See
[backend conformance](conformance.md) and the [changelog](changelog.md).

Source: [github.com/kjgpta/vectorsmith](https://github.com/kjgpta/vectorsmith).
