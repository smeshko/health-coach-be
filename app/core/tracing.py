"""The Langfuse/OpenTelemetry tracing seam (E12·P1).

The **single home** of all Langfuse/OTel imports, so E9·P1's ``agent_node.py`` stays
Langfuse-free (it consumes only the seam functions here). Every entry point guards on the
one predicate ``is_tracing_enabled`` — when the Langfuse keys are **absent** the seam is a
hard **no-op** (no client, no `InstrumentationSettings`, no OTel registration, no network),
so the briefs run exactly as in E9/E10/E11.

Langfuse v3+ is an OpenTelemetry client: the `Langfuse(...)` client owns an OTel
`TracerProvider` (attaching its OTLP exporter), and PydanticAI's native instrumentation
exports through that provider. So the wiring is: build one `TracerProvider`, hand it to
**both** `Langfuse(tracer_provider=…)` (the exporter) and PydanticAI's
`InstrumentationSettings(tracer_provider=…)` (the spans). Every traced `agent.run` then
emits a span carrying the prompt, the structured output, each retry + its `ModelRetry`
reason, latency, and token usage/cost (TASK-002/TASK-003).

Langfuse + `InstrumentationSettings`/OTel are imported **inside** the functions (guarded), so
importing this module never requires Langfuse on the no-key path, and a partial install
can't break boot. No FastAPI/HTTP import.
"""

from __future__ import annotations

from typing import TYPE_CHECKING, Any

from app.core.settings import Settings, get_settings

if TYPE_CHECKING:  # pragma: no cover - typing only
    from langfuse import Langfuse

# Process singleton, keyed by (public_key, secret_key, host) so the client + its OTel
# TracerProvider are built once per config (and tests with distinct keys stay isolated).
# Each value is a ``(client, tracer_provider)`` tuple.
_CLIENTS: dict[tuple[str, str, str | None], tuple[Any, Any]] = {}


def is_tracing_enabled(settings: Settings | None = None) -> bool:
    """`True` iff both Langfuse keys are present **and non-blank** (host is optional).

    The keys are bare ``str | None`` Settings (no `RequiredStr` strip), so a deployed
    ``LANGFUSE_PUBLIC_KEY=`` empty/whitespace value is *present but unusable* — it reads as
    **disabled** (`.strip()`). The single predicate every other entry point guards on.
    """
    s = settings or get_settings()
    public = (s.langfuse_public_key or "").strip()
    secret = (s.langfuse_secret_key or "").strip()
    return bool(public and secret)


def _client_and_provider(settings: Settings | None = None) -> tuple[Any, Any]:
    """The cached ``(Langfuse client, OTel TracerProvider)``, or ``(None, None)`` when off.

    Builds one `TracerProvider` and hands it to `Langfuse(tracer_provider=…)` so the client
    attaches its exporter to **that** provider — the same provider the instrumentation emits
    spans through (so one trace carries both the parent tags and the model spans). Cached as
    a process singleton keyed by the config.
    """
    s = settings or get_settings()
    if not is_tracing_enabled(s):
        return None, None
    key = (
        (s.langfuse_public_key or "").strip(),
        (s.langfuse_secret_key or "").strip(),
        (s.langfuse_host or None),
    )
    if key not in _CLIENTS:
        from langfuse import Langfuse
        from opentelemetry.sdk.trace import TracerProvider

        provider = TracerProvider()
        client = Langfuse(
            public_key=key[0],
            secret_key=key[1],
            host=key[2],
            tracer_provider=provider,
        )
        _CLIENTS[key] = (client, provider)
    return _CLIENTS[key]


def get_langfuse_client(settings: Settings | None = None) -> "Langfuse | None":
    """The process-cached Langfuse client built from Settings, or ``None`` when off."""
    return _client_and_provider(settings)[0]


def _tracer_provider(settings: Settings | None = None) -> Any:
    """The OTel `TracerProvider` the Langfuse client exports through (or ``None``)."""
    return _client_and_provider(settings)[1]


def reset_tracing_cache() -> None:
    """Clear the client/provider singleton — for test isolation (mirrors `cache_clear`)."""
    _CLIENTS.clear()
