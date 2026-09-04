# VectorSmith

**Your vector database, forged into tools an agent can actually use.**

Write a `tools.yaml`. VectorSmith compiles it into typed, tenant-guarded tools — then you either import them in Python or serve them over MCP.

[Docs](https://kjgpta.github.io/vectorsmith/) · [GitHub](https://github.com/kjgpta/vectorsmith) · [Changelog](https://github.com/kjgpta/vectorsmith/blob/main/CHANGELOG.md)

```bash
pip install "vectorsmith[qdrant]"
```

<p align="center">
  <a href="../../docs/assets/demo-launch.mp4">
    <img src="../../docs/assets/demo-launch-thumb.png" alt="VectorSmith demo (~50s)" width="720" />
  </a>
</p>

Store extras: `qdrant` · `pgvector` · `chroma` · `pinecone` · `weaviate` · `milvus`.
All adapters currently have experimental support status; see the
[capability matrix](https://kjgpta.github.io/vectorsmith/vector-stores/) and
[live conformance evidence](https://kjgpta.github.io/vectorsmith/conformance/).

## Two doors, one YAML

| You are building… | Install | Call |
|---|---|---|
| A **Python agent** (LangChain, LangGraph, OpenAI Agents, Anthropic SDK) | `pip install "vectorsmith[qdrant,langchain]"` | `from vectorsmith import load_tools` |
| A **chat / IDE host** (Claude Desktop, Claude Code, Codex, Cursor) | `pip install "vectorsmith[qdrant]"` so `vectorsmith` is on `PATH` | `vectorsmith serve tools.yaml --name invoices` |
| A **remote / Kubernetes MCP server** | `pip install "vectorsmith[qdrant,auth-jwt,otel]"` | `vectorsmith serve tools.yaml --http 0.0.0.0:8080 --auth jwt` |

The agent never sees the store URL, the API key, or hidden tenant filters.

```python
from vectorsmith import load_tools, connect

tools = load_tools("tools.invoices.yaml", env_file=".env")
# or
vs = connect("tools.invoices.yaml", env_file=".env")
rows = await vs.call("search_invoices", {"query": "Globex", "limit": 3})
await vs.aclose()
```

Authenticated applications can pass `ctx=CallContext(...)` to `vs.call`.
LangChain/LangGraph, OpenAI Agents, and Anthropic wrappers propagate supported
identity fields; the application remains responsible for authenticating
caller-supplied context.

```json
{
  "mcpServers": {
    "invoices": {
      "command": "vectorsmith",
      "args": ["serve", "/absolute/path/tools.invoices.yaml", "--env-file", "/absolute/path/.env", "--name", "invoices"]
    }
  }
}
```

Host guides: [Claude Desktop](https://kjgpta.github.io/vectorsmith/integrations/claude-desktop/) · [Claude Code](https://kjgpta.github.io/vectorsmith/integrations/claude-code/) · [Codex](https://kjgpta.github.io/vectorsmith/integrations/openai-codex/) · [Cursor](https://kjgpta.github.io/vectorsmith/integrations/cursor/). Production HTTP (JWT, `/readyz`, OTel, Helm): [self-host](https://kjgpta.github.io/vectorsmith/quickstart-selfhost/) · [enterprise](https://kjgpta.github.io/vectorsmith/enterprise/).

## Write a tool, not a prompt

```yaml
tds_version: "1"

connections:
  invoices:
    backend: qdrant
    url: ${QDRANT_URL}
    api_key: ${QDRANT_API_KEY:-}

tools:
  - name: search_invoices
    kind: search
    description: >
      Search invoices by free text and filter by client, status, or amount.
    target: { connection: invoices, collection: invoices }
    query: { param: query, required: false }
    static_filters:
      - { path: tenant, op: eq, value: acme }
    parameters:
      - { name: client, path: client_name, dtype: keyword, op: eq }
      - { name: status, path: status, dtype: keyword, op: in,
          enum: [draft, sent, paid, overdue] }
    output:
      fields: [invoice_id, client_name, status, amount]
```

`tenant: acme` is **not** in the model-facing schema. Full contract: [tools.yaml reference](https://kjgpta.github.io/vectorsmith/tools-yaml-reference/).

Experimental local lifecycle commands are available behind an explicit flag:
`vectorsmith discover`, `vectorsmith eval`, and `vectorsmith drift`. Approval
supports semantic `--dry-run` previews, provenance, and catalog versioning.
These commands never auto-promote a draft.

**0.2.0** is the production HTTP server: JWT / API keys, request tenancy, RBAC, Vault / AWS SM / Kubernetes credentials, audit (file / HTTP / OTLP), OpenTelemetry traces, Prometheus `/metrics`, Redis rate limits, `profiles.enterprise` at `serve` time. Extras: `auth-jwt` · `auth-redis` · `otel` · `creds-aws` · `embed-openai` · `embed-cohere` · `rerank-local`.

That designation applies to the HTTP runtime, not adapter stability. Check the
experimental backend evidence before making a production support claim.

Apache-2.0. *Forge the tools. Keep the store.*
