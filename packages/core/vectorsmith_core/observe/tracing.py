"""Optional tracing. Disabled by default — start_span is a no-op singleton."""

from __future__ import annotations

from contextlib import suppress
from typing import Any, Literal

_enabled = False
_service = "vectorsmith"
_endpoint = "http://localhost:4318"
_exporter = "otlp"
_recorded: list[tuple[str, dict[str, Any]]] = []
_stack: list[str] = []
_otel_provider: Any = None


class _Noop:
    __slots__ = ()

    def __enter__(self) -> _Noop:
        return self

    def __exit__(self, *args: object) -> Literal[False]:
        return False

    def set_attribute(self, *_a: object, **_k: object) -> None:
        return None


_NOOP = _Noop()


class _MemSpan:
    def __init__(self, name: str, attrs: dict[str, Any]) -> None:
        self.name = name
        self.attrs = attrs
        self._otel: Any = None

    def __enter__(self) -> _MemSpan:
        _stack.append(self.name)
        _recorded.append((self.name, dict(self.attrs)))
        self._otel = _start_otel(self.name, self.attrs)
        return self

    def __exit__(self, *args: object) -> Literal[False]:
        if _stack and _stack[-1] == self.name:
            _stack.pop()
        if self._otel is not None:
            with suppress(Exception):
                self._otel.__exit__(*args)
        return False

    def set_attribute(self, key: str, value: Any) -> None:
        self.attrs[key] = value


def configure_tracing(
    enabled: bool = False,
    *,
    service_name: str = "vectorsmith",
    endpoint: str | None = None,
    exporter: str | None = None,
) -> None:
    global _enabled, _service, _endpoint, _exporter, _otel_provider
    if not enabled and _otel_provider is not None:
        with suppress(Exception):
            _otel_provider.shutdown()
        _otel_provider = None
    _enabled = bool(enabled)
    _service = service_name
    if endpoint:
        _endpoint = endpoint
    if exporter:
        _exporter = exporter
    if _enabled:
        _try_otel()


def _span_exporter() -> Any:
    if _exporter == "console":
        from opentelemetry.sdk.trace.export import ConsoleSpanExporter

        return ConsoleSpanExporter()
    try:
        from opentelemetry.exporter.otlp.proto.http.trace_exporter import OTLPSpanExporter

        url = _endpoint.rstrip("/")
        if not url.endswith("/v1/traces"):
            url = f"{url}/v1/traces"
        return OTLPSpanExporter(endpoint=url)
    except Exception:
        from opentelemetry.sdk.trace.export import ConsoleSpanExporter

        return ConsoleSpanExporter()


def _try_otel() -> None:
    global _otel_provider
    if _otel_provider is not None:
        return
    try:
        from opentelemetry import trace
        from opentelemetry.sdk.resources import Resource
        from opentelemetry.sdk.trace import TracerProvider
        from opentelemetry.sdk.trace.export import BatchSpanProcessor

        resource = Resource.create({"service.name": _service})
        provider = TracerProvider(resource=resource)
        provider.add_span_processor(BatchSpanProcessor(_span_exporter()))
        trace.set_tracer_provider(provider)
        if trace.get_tracer_provider() is provider:
            _otel_provider = provider
        else:
            provider.shutdown()
    except Exception:
        return


def current_trace_context() -> dict[str, str]:
    """OTel ``trace_id`` / ``span_id`` for the current span, if any."""
    try:
        from opentelemetry import trace

        span = trace.get_current_span()
        ctx = span.get_span_context()
        if ctx is not None and getattr(ctx, "is_valid", False):
            return {
                "trace_id": format(int(ctx.trace_id), "032x"),
                "span_id": format(int(ctx.span_id), "016x"),
            }
    except Exception:
        return {}
    return {}


def _start_otel(name: str, attrs: dict[str, Any]) -> Any:
    try:
        from opentelemetry import trace

        tracer = trace.get_tracer("vectorsmith")
        span_cm = tracer.start_as_current_span(name)
        span = span_cm.__enter__()
        for key, val in attrs.items():
            if val is not None:
                span.set_attribute(key, val)
        return span_cm
    except Exception:
        return None


def start_span(name: str, **attrs: Any) -> Any:
    if not _enabled:
        return _NOOP
    return _MemSpan(name, attrs)


def recorded_spans() -> list[tuple[str, dict[str, Any]]]:
    return list(_recorded)


def reset_spans() -> None:
    _recorded.clear()
    _stack.clear()
