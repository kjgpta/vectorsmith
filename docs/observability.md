# Observability

Hub: [documentation home](index.md).

## Audit

`observability.audit` plus `--audit-log` / `--audit-sink` / `--audit-url`. JSONL events include `request_id` (same id as JSON logs and traces). Rows and credentials are never written. Default arg redact: `password`, `token`, `secret`. Single-project and multi-project HTTP `serve` both enable the YAML audit block; multi-project builds one sink per file unless a CLI `--audit-*` flag overrides.

## Tracing

Off by default. Extra: `vectorsmith[otel]` (includes the OTLP HTTP exporter). Set `observability.tracing.enabled: true` and `endpoint` (collector, e.g. `http://otel-collector:4318`). `serve` and `connect` call `configure_tracing` for **single-project and multi-project** HTTP, and for stdio. `exporter: otlp` sends `/v1/traces`; `exporter: console` prints spans.

Spans:

- `vectorsmith.tool.call` — tool, principal, connection, collection
- `vectorsmith.embed` — provider, model, text_count
- `vectorsmith.adapter.search` — backend, collection, limit, mode
- `vectorsmith.pipeline.step` — step_kind

## Metrics

Off by default. When `observability.metrics.enabled`, HTTP serve exposes `GET /metrics`:

```
vectorsmith_tool_calls_total{tool,status}
vectorsmith_tool_latency_seconds_bucket{tool,le}
vectorsmith_tool_latency_seconds_count{tool}
vectorsmith_tool_latency_seconds_sum{tool}
vectorsmith_embed_requests_total{provider}
vectorsmith_adapter_errors_total{backend,code}
vectorsmith_rate_limit_hits_total{tool}
```

Latency uses fixed Prometheus histogram buckets. VectorSmith stores only bucket
counts, total count, and sum per compiler-controlled metric key; it does not
retain one latency sample per call.

HTTP: `GET /healthz` (liveness), `GET /readyz` (503 if a connection, required embedder, or JWT JWKS fetch is down), `GET /metrics` when metrics are enabled. Routes: [library surface](library.md#http-routes-serve-http).

## Logs

```bash
vectorsmith serve tools.yaml --http 127.0.0.1:8080 --auth none \
  --log-format json --log-level info
```

Default is text (dev). JSON fields: `level`, `ts`, `request_id`, `principal`, `tool`, `latency_ms`, `trace_id`, `span_id`, `msg`. `trace_id` / `span_id` come from the current OTel span when tracing is enabled. Credentials and embedding vectors are not logged.

`observability.audit.sink: otlp` posts OTLP HTTP JSON logs to `{url}/v1/logs`. Use `sink: http` for a raw JSONL webhook.
