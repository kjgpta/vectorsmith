# Examples

Docs hub: [docs/README.md](../docs/README.md). YAML contract: [tools.yaml reference](../docs/tools-yaml-reference.md).

How a user authors VectorSmith tools against their own vector database, then uses them in an agent or over MCP.

[![VectorSmith demo (~50s)](../docs/assets/demo-launch-thumb.png)](../docs/assets/demo-launch.mp4)

Copy [`qdrant_invoices/.env.example`](qdrant_invoices/.env.example) to `.env` and set `QDRANT_URL` to your cluster. The committed example is `http://localhost:6333` only.

## `qdrant_invoices`

Two MCP servers (the `mcpServers` key / `--name` is what Claude Connectors show):

| File | MCP name | Role |
|---|---|---|
| [`tools.invoices.yaml`](qdrant_invoices/tools.invoices.yaml) | `invoices` | Invoice search / lookup / count |
| [`tools.tickets.yaml`](qdrant_invoices/tools.tickets.yaml) | `tickets` | Support-ticket search / lookup / count |
| [`qdrant_invoices/.env.example`](qdrant_invoices/.env.example) | | Placeholder `QDRANT_URL` (`localhost`); copy to `.env` |
| [`qdrant_invoices/seed_tickets.py`](qdrant_invoices/seed_tickets.py) | | Create `tickets` and upsert 80 sample rows |
| [`qdrant_invoices/validate_tools.py`](qdrant_invoices/validate_tools.py) | | Compile both files (`load_project` only) |

### CLI

From the repo root:

```bash
uv run vectorsmith validate examples/qdrant_invoices/tools.invoices.yaml \
  --env-file examples/qdrant_invoices/.env.example
uv run vectorsmith validate examples/qdrant_invoices/tools.tickets.yaml \
  --env-file examples/qdrant_invoices/.env.example

uv run vectorsmith test examples/qdrant_invoices/tools.invoices.yaml search_invoices \
  --args '{"query":"Globex invoice","limit":3}' \
  --env-file examples/qdrant_invoices/.env.example

# Two processes — two connector names
uv run vectorsmith serve examples/qdrant_invoices/tools.invoices.yaml --name invoices \
  --env-file examples/qdrant_invoices/.env.example
uv run vectorsmith serve examples/qdrant_invoices/tools.tickets.yaml --name tickets \
  --env-file examples/qdrant_invoices/.env.example
```

`load_project()` (authoring API) interpolates the env map you pass, synthesizes builtins, validates, and compiles. The CLI `validate` / `serve` / `test` commands interpolate **only** `--env-file` (they do not merge the process environment).

### Experimental contract lifecycle

Use live introspection to produce a review-only discovery report:

```bash
uv run vectorsmith discover examples/qdrant_invoices/tools.invoices.yaml \
  --connection invoices --experimental \
  --env-file examples/qdrant_invoices/.env.example \
  --out tools.discovered.drafts.yaml
```

The output is not the active catalog and is separate from
`./tools.drafts.yaml`. After deliberately placing a reviewed proposal into the
normal draft workflow, preview approval without mutation:

```bash
uv run vectorsmith approve TOOL_NAME \
  --file examples/qdrant_invoices/tools.invoices.yaml --dry-run
```

Checked-in scenario and schema files can then be exercised locally:

```bash
uv run vectorsmith eval examples/qdrant_invoices/tools.invoices.yaml \
  scenarios.yaml --experimental --env-file examples/qdrant_invoices/.env.example
uv run vectorsmith drift examples/qdrant_invoices/tools.invoices.yaml \
  schema.json --connection invoices --experimental \
  --env-file examples/qdrant_invoices/.env.example
```

`eval` and `drift` write JSON evidence and return exit `1` on failed scenarios
or detected drift. None of these commands auto-promotes a tool.

## `enterprise`

Reference catalogs: JWT auth defaults, RBAC, audit, `tds_version: "2"`. Claim vs static tenancy are **separate files** so copy-paste does not AND both layers.

| File | Role |
|---|---|
| [`enterprise/tools.yaml`](enterprise/tools.yaml) | Claim tenancy (JWT `tenant_id`) |
| [`enterprise/tools.static.yaml`](enterprise/tools.static.yaml) | Static tenancy (`must` tenant filter) |
| [`enterprise/.env.example`](enterprise/.env.example) | `QDRANT_URL`, `JWKS_URL`, … |

```bash
uv run vectorsmith validate examples/enterprise/tools.yaml \
  --env-file examples/enterprise/.env.example
uv run vectorsmith validate examples/enterprise/tools.yaml --enterprise --strict \
  --env-file examples/enterprise/.env.example
```

`--enterprise` warns **VE007** while the file uses FastEmbed and **VB2024**
while Qdrant remains experimental, so `--strict` is intentionally non-zero.
The same `profiles.enterprise` block refuses `serve` / `connect` if tenancy or
limits fail. Docs: [enterprise](../docs/enterprise.md),
[hardening](../docs/security-hardening.md), [HTTP](../docs/quickstart-selfhost.md).

## Agent frameworks (in-process `load_tools`)

| Directory | Import |
|---|---|
| [`langchain_agent/`](langchain_agent/) | `from vectorsmith import load_tools` + your `@tool`s + optional Slack MCP |
| [`langgraph_agent/`](langgraph_agent/) | `from vectorsmith.langgraph import load_tools` + `create_react_agent` |
| [`openai_agents/`](openai_agents/) | `from vectorsmith.openai_agents import load_tools` + `Agent` / `Runner` |
| [`anthropic_agent/`](anthropic_agent/) | `from vectorsmith.anthropic import load_tools` + Messages API tool loop |

## MCP hosts (Claude, Codex, Cursor)

Copy-paste configs: [`mcp_hosts/`](mcp_hosts/). Full write-ups: [docs/integrations/](../docs/integrations/README.md).

## Alongside other MCP servers

Each VectorSmith `serve` is one `mcpServers` entry. Add filesystem, GitHub, or a second VectorSmith project next to it. Details: [docs/coexistence.md](../docs/coexistence.md).
