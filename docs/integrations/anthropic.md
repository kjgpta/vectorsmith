# Anthropic Messages API

Hub: [documentation home](../index.md) · [Python API](../python-api.md). For **Claude Desktop** or **Claude Code**, those apps spawn `serve` — [Desktop](claude-desktop.md), [Claude Code](claude-code.md).

In-process Python.

```bash
pip install "vectorsmith[qdrant,anthropic]"
```

```python
import anthropic
from vectorsmith.anthropic import load_tools

vs = load_tools("tools.invoices.yaml", "tools.tickets.yaml")
client = anthropic.Anthropic()
messages = [{"role": "user", "content": "Which Globex invoices are overdue?"}]
try:
    resp = client.messages.create(
        model="claude-sonnet-4-20250514",
        max_tokens=2048,
        tools=vs.tools,
        messages=messages,
    )
    if resp.stop_reason == "tool_use":
        results = []
        for block in resp.content:
            if block.type == "tool_use":
                output = await vs.execute(block.name, block.input)
                results.append(
                    {"type": "tool_result", "tool_use_id": block.id, "content": output}
                )
        messages.append({"role": "assistant", "content": resp.content})
        messages.append({"role": "user", "content": results})
        resp = client.messages.create(
            model="claude-sonnet-4-20250514",
            max_tokens=2048,
            tools=vs.tools,
            messages=messages,
        )
finally:
    await vs.aclose()
```

`vs.tools` is the list of `{name, description, input_schema}` dicts. `vs.execute` runs the compiled YAML tool.

For authenticated request-scoped tenancy, pass an explicit context:

```python
from vectorsmith_core.api import CallContext

ctx = CallContext(
    request_id="request-123",
    principal="alice",
    claims={"roles": ["viewer"]},
    tenant_value="acme",
)
output = await vs.execute(block.name, block.input, ctx=ctx)
```

The application—not the model-provided tool input—must establish this identity.

Worked sample (full loop): [`examples/anthropic_agent/`](https://github.com/kjgpta/vectorsmith/tree/main/examples/anthropic_agent/).
