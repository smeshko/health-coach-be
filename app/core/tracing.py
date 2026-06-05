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

import contextlib
from collections.abc import Iterator
from typing import TYPE_CHECKING, Any

from app.core.settings import Settings, get_settings

if TYPE_CHECKING:  # pragma: no cover - typing only
    from langfuse import Langfuse

# Process singleton, keyed by ``public_key`` — matching Langfuse's OWN
# ``LangfuseResourceManager`` singleton (which caches by ``public_key`` only and ignores a
# changed ``secret_key``/``host`` once a key is first seen). Keying the seam the same way
# keeps the cache honest: once a public key is cached, the same client + its OTel
# ``TracerProvider`` are reused (so `traced_run`'s spans and Langfuse's exporter stay on
# **one** provider), rather than the seam silently building a second provider whose spans
# Langfuse would never export (review #1). Single-process/single-config in production, so
# one entry; distinct test keys stay isolated. Each value is a ``(client, provider)`` tuple.
_CLIENTS: dict[str, tuple[Any, Any]] = {}


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
    key = (s.langfuse_public_key or "").strip()  # langfuse caches by public_key only
    if key not in _CLIENTS:
        from langfuse import Langfuse
        from opentelemetry.sdk.trace import TracerProvider

        provider = TracerProvider()
        client = Langfuse(
            public_key=key,
            secret_key=(s.langfuse_secret_key or "").strip(),
            host=(s.langfuse_host or None),
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


# --------------------------------------------------------------------------- #
# TASK-002 — instrument the PydanticAI Agent (prompt/output/retries/latency/cost).
# --------------------------------------------------------------------------- #
def build_instrumentation_settings(settings: Settings | None = None) -> Any:
    """The PydanticAI `InstrumentationSettings` exporting through the Langfuse provider.

    When enabled: ``InstrumentationSettings(tracer_provider=<the Langfuse client's OTel
    provider>, include_content=True)`` — ``include_content=True`` puts the **prompt** and the
    **structured output** into the span; the retries + latency + token usage/cost are emitted
    by PydanticAI's instrumentation automatically per `agent.run`. ``event_mode`` is left at
    the installed default (``version=2``/``"attributes"``; passing ``"logs"`` raises a
    deprecation warning), and no ``meter_provider`` is needed (v2 emits usage as a span
    attribute). Returns ``None`` when tracing is off.
    """
    s = settings or get_settings()
    if not is_tracing_enabled(s):
        return None
    from pydantic_ai.agent import InstrumentationSettings

    return InstrumentationSettings(
        tracer_provider=_tracer_provider(s),
        include_content=True,
    )


def instrument_agent(agent: Any, settings: Settings | None = None) -> Any:
    """Set ``agent.instrument`` to the built `InstrumentationSettings` when enabled (a
    per-agent opt-in), else leave the agent untouched (**no-op**). Returns the agent.

    Per-agent (not the global `Agent.instrument_all`) so the no-op is total and no global
    process state leaks into untraced contexts (tests, the no-key path).
    """
    instrumentation = build_instrumentation_settings(settings)
    if instrumentation is not None:
        agent.instrument = instrumentation
    return agent


# --------------------------------------------------------------------------- #
# TASK-003 — tag the trace with constitutionVersion + model (a parent span).
# --------------------------------------------------------------------------- #
def trace_attributes(*, constitution_version: str, model_id: str) -> dict[str, str]:
    """The trace tag set: ``{constitutionVersion, model}`` (pure, import-light)."""
    return {"constitutionVersion": constitution_version, "model": model_id}


def resolve_constitution_version(deps: Any, settings: Settings | None = None) -> str:
    """The constitution version to tag with — the node's deps value, else the Settings
    fallback (``"v1"``).

    E10·P1/E11·P1 stamp E3's `constitution_version(profile)` into the node context; the real
    `TaskContext` carries no version field, so the deps `constitution_version` (when present)
    is the sound source, falling back to `Settings.constitution_version`.
    """
    value = getattr(deps, "constitution_version", None)
    if isinstance(value, str) and value.strip():
        return value
    s = settings or get_settings()
    return s.constitution_version


@contextlib.contextmanager
def traced_run(
    name: str,
    *,
    constitution_version: str,
    model_id: str,
    settings: Settings | None = None,
) -> Iterator[None]:
    """A context manager opening a parent span that **tags** the run with
    ``constitutionVersion`` + ``model`` (the brief kind as the span ``name``), or a **no-op**
    when tracing is off.

    The span is opened on the Langfuse client's OTel `TracerProvider`, so the instrumented
    `agent.run` spans nest **under** it and the whole trace carries the tags + the
    prompt/output/retries/latency/usage. On an exception the span records the failure
    (OTel `start_as_current_span` sets an error status), so a `BriefGenerationError` (exhausted
    retries) is traced — without changing which error the node raises.
    """
    s = settings or get_settings()
    provider = _tracer_provider(s)
    if provider is None:
        yield
        return
    tracer = provider.get_tracer("coach-app")
    attrs = trace_attributes(constitution_version=constitution_version, model_id=model_id)
    with tracer.start_as_current_span(name) as span:
        for key, value in attrs.items():
            span.set_attribute(key, value)
        yield
