# LangGraph

Hub: [documentation home](../index.md) · [Python API](../python-api.md) · [LangChain](langchain.md).

LangGraph talks to LangChain tools. Use the same `load_tools` as [LangChain](langchain.md).

```bash
pip install "vectorsmith[qdrant,langgraph]"
```

## `create_react_agent`

```python
from langchain.chat_models import init_chat_model
from langgraph.prebuilt import create_react_agent
from vectorsmith.langgraph import load_tools  # or: from vectorsmith import load_tools

tools = load_tools("tools.invoices.yaml", "tools.tickets.yaml")
try:
    model = init_chat_model("openai:gpt-4.1")
    agent = create_react_agent(model, tools)
    result = await agent.ainvoke({"messages": [{"role": "user", "content": prompt}]})
finally:
    await tools.aclose()
```

Worked sample: [`examples/langgraph_agent/`](https://github.com/kjgpta/vectorsmith/tree/main/examples/langgraph_agent/).

## `StateGraph` + `ToolNode`

```python
from langgraph.prebuilt import ToolNode, tools_condition
from langgraph.graph import StateGraph, MessagesState, START
from vectorsmith import load_tools

vs = load_tools("tools.yaml")
tool_node = ToolNode(vs)

def chatbot(state):
    return {"messages": [model.bind_tools(vs).invoke(state["messages"])]}

graph = StateGraph(MessagesState)
graph.add_node("agent", chatbot)
graph.add_node("tools", tool_node)
graph.add_edge(START, "agent")
graph.add_conditional_edges("agent", tools_condition)
graph.add_edge("tools", "agent")
app = graph.compile()
```

Call `await vs.aclose()` when the process exits.

## Request identity

LangGraph forwards LangChain runnable configuration to tool calls. Supply an
authenticated VectorSmith context when invoking the graph:

```python
from vectorsmith_core.api import CallContext

ctx = CallContext(
    request_id="request-123",
    principal="alice",
    claims={"roles": ["viewer"]},
    tenant_value="acme",
)
result = await app.ainvoke(
    {"messages": [{"role": "user", "content": prompt}]},
    config={"configurable": {"vectorsmith_context": ctx}},
)
```

The embedding application remains the trust boundary for caller-supplied
identity.
