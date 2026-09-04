from __future__ import annotations

from vectorsmith_core.observe import metrics


def test_latency_memory_is_bounded_by_fixed_histogram_state() -> None:
    metrics.reset()
    metrics.configure_metrics(True)

    for index in range(100_000):
        metrics.observe_latency("search_docs", (index % 20_000) / 1_000)

    snapshot = metrics.snapshot()["latency"]["search_docs"]
    assert snapshot["count"] == 100_000
    assert len(snapshot["buckets"]) == 12
    assert snapshot["buckets"][-1] == 100_000
    assert not any(isinstance(value, list) for value in snapshot.values())


def test_latency_render_uses_prometheus_histogram_shape() -> None:
    metrics.reset()
    metrics.configure_metrics(True)
    metrics.observe_latency("search_docs", 0.02)
    output = metrics.render()

    assert "# TYPE vectorsmith_tool_latency_seconds histogram" in output
    assert 'vectorsmith_tool_latency_seconds_bucket{tool="search_docs",le="0.025"} 1' in output
    assert 'vectorsmith_tool_latency_seconds_bucket{tool="search_docs",le="+Inf"} 1' in output
    assert 'vectorsmith_tool_latency_seconds_count{tool="search_docs"} 1' in output
