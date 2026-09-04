# Python API

Hub: [documentation home](index.md). CLI interpolation is different: [CLI](cli.md).

Application code installs **`vectorsmith`**. Do not import `Engine`.

```bash
pip install "vectorsmith[qdrant]"                 # connect()
pip install "vectorsmith[qdrant,langchain]"       # load_tools (LangChain / LangGraph)
```

Env for these APIs: **`os.environ`**, then `env=`, then `env_file=` (file wins). That is **not** how the CLI works — [CLI](cli.md).

Always `await …aclose()` when finished (closes store clients).

---

## `connect`

```python
from vectorsmith import connect

vs = connect(
    "tools.invoices.yaml",
    "tools.tickets.yaml",
    env_file=".env",           # optional
    env={"QDRANT_URL": "…"},   # optional; overrides os.environ, then env_file overlays
)
```

Returns [`BoundTools`](#boundtools). Compiles each YAML in-process (no `serve` subprocess). Duplicate tool names: last file wins for `call()`. `profiles.enterprise` hardening applies the same refuse rules as `serve` (authoring/meta, tenancy, `limit_max`, allowed backends). `observability.tracing` is configured when any loaded file enables it. Credential providers (`vault` / `aws_sm` / `k8s`) resolve at first use.

---

## `BoundTools`

| Member | Role |
|---|---|
| `names` | Tool names in load order |
| `schemas` | MCP dicts: `name`, `description`, `inputSchema` |
| `as_anthropic()` | `{name, description, input_schema}` for `messages.create` |
| `as_langchain()` | LangChain `Toolset` (`vectorsmith[langchain]`) |
| `as_openai_agents()` | OpenAI Agents `FunctionTool` list (`vectorsmith[openai-agents]`) |
| `await call(name, args, ctx=None)` | Run a tool; optional `CallContext` carries `principal`, `claims`, `tenant_value` / `tenant_filter`, `request_id`, and `deadline_s` |
| `await aclose()` | Close engines |

```python
rows = await vs.call("search_invoices", {"query": "Globex", "limit": 3})
```

For an authenticated in-process request, pass identity explicitly:

```python
from vectorsmith_core.api import CallContext

ctx = CallContext(
    request_id="request-123",
    principal="alice",
    claims={"roles": ["viewer"], "tenant_id": "acme"},
)
rows = await vs.call("search_invoices", {"query": "Globex"}, ctx=ctx)
```

OpenAI Agents propagates a `CallContext` (or identity mapping) from its run context.
LangChain accepts it as
`config={"configurable": {"vectorsmith_context": ctx}}`. Anthropic
`execute(..., ctx=ctx)` accepts it directly.

`CallContext` currently lives in the bundled compiler API at
`vectorsmith_core.api`; application code should not import `Engine` or adapter
internals. Framework mappings may use `vectorsmith_context` or `call_context`
directly, or place `vectorsmith_context` under LangChain/LangGraph
`configurable` or `metadata`. Plain mappings accept `principal`, `claims`,
`roles`, `tenant_value`, `request_id`, and `deadline_s`; `roles` are normalized
into `claims["roles"]` because roles are not a top-level `CallContext` field.

Unknown `name` → `KeyError`.

---

## `load_tools` (LangChain / LangGraph)

```python
from vectorsmith import load_tools
# same function:
from vectorsmith.langchain import load_tools
from vectorsmith.langgraph import load_tools

tools = load_tools("tools.invoices.yaml", env_file=".env")
```

Requires **`langchain-core`** (`vectorsmith[langchain]` or `[langgraph]`). Returns a `Toolset` (a `list` of LangChain `StructuredTool`s) with `aclose()`.

Equivalent: `connect(...).as_langchain()`.

Pass into `create_agent` / `create_react_agent` / `ToolNode`. Mix with your own `@tool`s.

---

## OpenAI Agents SDK

```python
from vectorsmith.openai_agents import load_tools

vs = load_tools("tools.yaml", env_file=".env")
# vs is a list of FunctionTool; splat into Agent(tools=[*vs, ...])
await vs.aclose()
```

Requires `vectorsmith[openai-agents]`. Optional YAML fields are not OpenAI strict-mode schemas; the adapter sets `strict_json_schema=False`.

Equivalent: `connect(...).as_openai_agents()`.

---

## Anthropic Messages API

```python
from vectorsmith.anthropic import load_tools

vs = load_tools("tools.yaml", env_file=".env")
resp = client.messages.create(..., tools=vs.tools, messages=...)
output = await vs.execute(block.name, block.input)  # JSON string
await vs.aclose()
```

Requires `vectorsmith[anthropic]` (or `pip install anthropic` plus `vectorsmith[qdrant]`). `vs.tools` is the list of API dicts; `execute` dispatches `tool_use`.

---

## Return envelope

`call()` / MCP tool results look like:

| Field | Meaning |
|---|---|
| `rows` | Projected records |
| `count` | Length of `rows` |
| `truncated` | Hit `limit` |
| `may_be_incomplete` | Pipeline over-fetch cap; caveat the answer |
| `search_mode` | `dense` · `hybrid` · `none` |
| `warnings` | e.g. `VB4001`–`VB4004`, `VB4020`, `VB4030` |
| `latency_ms` | Engine timing |
| `message` | Human hint (directory resolve alternatives) |
| `exact_search` / `compiled_query` | Present on some results (`compiled_query` when `test --show-plan`) |

---

## Authoring (`vectorsmith_core`)

The compiler module ships **inside** `pip install vectorsmith` (not a second PyPI project). For CI and `validate`-like scripts — **not** for binding schemas onto an LLM:

```python
from vectorsmith_core import load_project

project = load_project("tools.yaml", env={"QDRANT_URL": "http://localhost:6333"})
project.mcp_tool_schemas()
project.issues   # VBxxxx
```

`Engine` is not part of this public surface.

---

## Exceptions

`connect` / `call` raise subclasses of `vectorsmith_core.errors.VectorSmithError`:

| Exception | When |
|---|---|
| `MissingEnvError` | `${VAR}` unset or vault path empty |
| `InvalidArgumentsError` | Unknown tool or schema fail |
| `RateLimited` | Quotas; `retry_after_s` |
| `QueryTimeout` | Exceeded `CallContext.deadline_s` (default 25s; HTTP uses this on `engine.call`) |
| `EmbeddingError` | Embed provider failed |
| `AuthError` | HTTP auth / RBAC (serve path) |
| `BackendUnreachable` | Store health / connect failed |

Full table: [library surface](library.md#runtime-exceptions).

---

## Extras

Store extras (pick one or more): **[vector stores](vector-stores.md)** — `qdrant`, `pgvector`, `chroma`, `pinecone`, `weaviate`, `milvus`. Each extra is the store client plus FastEmbed.

| Extra | What you get |
|---|---|
| `langchain` | `langchain-core` (`load_tools`) |
| `langgraph` | `langchain-core` + `langgraph` |
| `openai-agents` | OpenAI Agents SDK |
| `anthropic` | Anthropic SDK |
| `embed-openai` | OpenAI / Azure embed (+ expand if you use `provider: openai`) |
| `embed-cohere` | Cohere embed / rerank |
| `auth-jwt` | `serve --auth jwt` |
| `auth-redis` | Redis token store and rate-limit store |
| `otel` | OpenTelemetry SDK + OTLP HTTP exporter for `observability.tracing` |
| `creds-aws` | `credentials.provider: aws_sm` |
| `rerank-local` | `rerank.provider: cross_encoder` |

Complete inventory: [library surface](library.md). Guides: [integrations](integrations/README.md). Examples: [examples/](https://github.com/kjgpta/vectorsmith/tree/main/examples/README.md).
