# Integrations

Hub: [documentation home](../index.md) · [Python API](../python-api.md) · [Getting started](../getting-started.md).

Two ways to use a `tools.yaml`. Pick the one your product supports.

| You are building… | Use | Install |
|---|---|---|
| A **Python agent** (LangChain, LangGraph, OpenAI Agents, Anthropic SDK) | `load_tools` / `connect` in-process | Store extra (`qdrant` / `pgvector` / … — [vector stores](../vector-stores.md)) plus `langchain` / `langgraph` / `openai-agents` / `anthropic` as listed below |
| A **chat / IDE host** (Claude Desktop, Claude Code, Codex, Cursor) | `vectorsmith serve` as an MCP server | Store extra so `vectorsmith` is on `PATH` |
| A **remote / Kubernetes MCP server** | `serve --http` ([self-host](../quickstart-selfhost.md)) | Store extra plus `auth-jwt` / `otel` as needed |

Same YAML either way. Do not import `Engine`. Field-by-field: [tools.yaml](../tools-yaml-reference.md). Extras and public imports: [library surface](../library.md).

--8<-- "docs/includes/demo-video.md"

## MCP hosts

- [Claude Desktop](claude-desktop.md)
- [Claude Code](claude-code.md)
- [OpenAI Codex](openai-codex.md) (CLI, IDE extension, ChatGPT desktop Codex)
- [Cursor](cursor.md)
- [claude.ai custom connector](../quickstart-selfhost.md) (`serve --http`)

Copy-paste configs: [`examples/mcp_hosts/`](https://github.com/kjgpta/vectorsmith/tree/main/examples/mcp_hosts/).

Stdio remains on the handshake protocol even when a newer host probes
`server/discover` before `initialize`, covering the GitHub Copilot CLI
compatibility case. HTTP clients receive JSON-RPC `-32022` with the supported
version list when their initialize version is unavailable. Details:
[CLI protocol behavior](../cli.md#serve).

## Agent frameworks

- [LangChain](langchain.md) — `from vectorsmith import load_tools`
- [LangGraph](langgraph.md) — same tools; `create_react_agent` / `ToolNode`
- [OpenAI Agents SDK](openai-agents.md) — `from vectorsmith.openai_agents import load_tools`
- [Anthropic Messages API](anthropic.md) — `from vectorsmith.anthropic import load_tools`
- [Other frameworks](other-frameworks.md) — LlamaIndex, CrewAI, raw `connect()`

## One-liners

```python
from vectorsmith import load_tools          # LangChain / LangGraph
from vectorsmith.openai_agents import load_tools
from vectorsmith.anthropic import load_tools

from vectorsmith import connect             # await vs.call("search_invoices", {…})
```

```bash
vectorsmith serve tools.invoices.yaml --name invoices
```
