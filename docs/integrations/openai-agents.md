# OpenAI Agents SDK

Hub: [documentation home](../index.md) · [Python API](../python-api.md). For the **Codex CLI / IDE** (MCP host), see [OpenAI Codex](openai-codex.md).

In-process Python.

```bash
pip install "vectorsmith[qdrant,openai-agents]"
```

```python
from agents import Agent, Runner, function_tool
from vectorsmith.openai_agents import load_tools

@function_tool
def get_current_user() -> dict:
    """Signed-in support agent."""
    return {"email": "agent@example.com"}

vs = load_tools("tools.invoices.yaml", "tools.tickets.yaml")
try:
    agent = Agent(
        name="Support",
        instructions="Use invoice and ticket tools before answering.",
        tools=[get_current_user, *vs],
    )
    result = await Runner.run(agent, "Which Globex invoices are overdue?")
    print(result.final_output)
finally:
    await vs.aclose()
```

Equivalent: `connect("tools.yaml").as_openai_agents()`.

Optional fields in `tools.yaml` are not OpenAI strict-mode schemas; the adapter sets `strict_json_schema=False`.

VectorSmith inspects the OpenAI Agents run context for a `CallContext` or an
identity mapping containing `principal`, `claims` / `roles`, `tenant_value`,
`request_id`, and `deadline_s`. The application must populate that context from
an authenticated request; absent identity remains backward compatible but
cannot satisfy claim-based tenancy.

Worked sample: [`examples/openai_agents/`](https://github.com/kjgpta/vectorsmith/tree/main/examples/openai_agents/).
