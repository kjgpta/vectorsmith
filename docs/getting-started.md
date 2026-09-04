# Getting started

Hub: [documentation home](index.md).

This walkthrough uses the invoice example. Copy `.env.example` and set `QDRANT_URL` to your Qdrant cluster (the committed default is `http://localhost:6333`).

You need Python 3.11+ and [uv](https://docs.astral.sh/uv/) (or `pip`).

The walkthrough (problem → YAML → MCP / SDK → Claude):

--8<-- "docs/includes/demo-video-root.md"

## 1. Install from a clone

```bash
git clone https://github.com/kjgpta/vectorsmith.git
cd vectorsmith
uv sync
```

From PyPI, install the extra for **your** store — see the
[available adapters and support levels](vector-stores.md):

```bash
pip install "vectorsmith[qdrant]"      # or pgvector, chroma, pinecone, weaviate, milvus
```

## 2. Look at a `tools.yaml`

Open [`examples/qdrant_invoices/tools.invoices.yaml`](https://github.com/kjgpta/vectorsmith/tree/main/examples/qdrant_invoices/tools.invoices.yaml). You will see:

- A **connection** (`backend: qdrant`, URL as `${QDRANT_URL}`) — six backends ship; see [vector stores](vector-stores.md)
- Tools with **kinds** (`search`, `lookup`, `count`)
- **`static_filters`** the model never sees (`tenant: acme`)
- **Parameters** the model may pass (`client`, `status`, `min_amount`)

Full contract: [tools.yaml reference](tools-yaml-reference.md). Inventory of extras and HTTP routes: [library surface](library.md).

Or generate a starter:

```bash
uv run vectorsmith init ./demo
```

## 3. Validate

The CLI interpolates **only** `--env-file` (not the process environment):

```bash
uv run vectorsmith validate examples/qdrant_invoices/tools.invoices.yaml \
  --env-file examples/qdrant_invoices/.env.example
```

`--live` also pings the store (dims, hybrid/sparse). `--strict` treats warnings
as failure (exit `1`). Errors are exit `2`. All current adapters are
experimental and therefore emit `VB2024`, so strict validation is expected to
remain non-zero until the target backend earns stable status. See
[backend conformance](conformance.md).

## 4. Call one tool without an agent

```bash
uv run vectorsmith test examples/qdrant_invoices/tools.invoices.yaml search_invoices \
  --args '{"query":"Globex invoice","limit":3}' \
  --env-file examples/qdrant_invoices/.env.example
```

You should get JSON with `rows`, `count`, `search_mode`. This is for authoring. Apps use [Python](python-api.md) or [MCP](integrations/README.md), not `test`.

## 5. Pick a door

### A — Claude / Codex / Cursor (MCP)

```bash
uv run vectorsmith serve examples/qdrant_invoices/tools.invoices.yaml --name invoices \
  --env-file examples/qdrant_invoices/.env.example
```

Then paste a config from [`examples/mcp_hosts/`](https://github.com/kjgpta/vectorsmith/tree/main/examples/mcp_hosts/). Host guides: [Claude Desktop](quickstart-desktop.md), [Claude Code](integrations/claude-code.md), [Codex](integrations/openai-codex.md), [Cursor](integrations/cursor.md).

Ask: “Which Globex invoices are overdue?”

### B — Python agent

```bash
pip install "vectorsmith[qdrant,langchain]"
```

```python
from vectorsmith import load_tools
from langchain.agents import create_agent

tools = load_tools(
    "examples/qdrant_invoices/tools.invoices.yaml",
    env_file="examples/qdrant_invoices/.env.example",
)
agent = create_agent("openai:gpt-4.1", tools)
```

Worked apps: [`examples/langchain_agent`](https://github.com/kjgpta/vectorsmith/tree/main/examples/langchain_agent/), [LangGraph](https://github.com/kjgpta/vectorsmith/tree/main/examples/langgraph_agent/), [OpenAI Agents](https://github.com/kjgpta/vectorsmith/tree/main/examples/openai_agents/), [Anthropic](https://github.com/kjgpta/vectorsmith/tree/main/examples/anthropic_agent/). API: [python-api.md](python-api.md).

## 6. Tickets (second connector)

Same cluster, second YAML → second MCP name:

```bash
uv run vectorsmith serve examples/qdrant_invoices/tools.tickets.yaml --name tickets \
  --env-file examples/qdrant_invoices/.env.example
```

Two processes, two Connectors. One Python process can `load_tools` both files.

## Next

- [HTTP / claude.ai](quickstart-selfhost.md) for `serve --http` (JWT, `/readyz`, OTel)
- [Enterprise](enterprise.md) for tenancy, RBAC, credentials, audit
- [FAQ](faq.md) if something fails (Desktop **Server disconnected**, missing `${VAR}`, HTTP auth)
- [CLI reference](cli.md) for every flag
- [Architecture](architecture.md) for what compiles where
