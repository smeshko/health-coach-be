"""E12·P1 tracing-seam tests — Langfuse mocked, model mocked (no live network/keys).

The Langfuse client constructor is monkeypatched so no real client/network is built, and
(in TASK-002/003) the model is mocked via `Agent.override` — so the tracing wiring is
exercised without a live Anthropic or Langfuse call.
"""

from __future__ import annotations

import pytest

from app.core import tracing
from app.core.settings import Settings


def _settings(*, pk: str | None = "pk-test-123", sk: str | None = "sk-test-456", host=None):
    return Settings(
        api_token="test-api-token-0123456789",
        app_db_path="/tmp/app.db",
        langfuse_public_key=pk,
        langfuse_secret_key=sk,
        langfuse_host=host,
    )


class _FakeLangfuse:
    instances: list = []

    def __init__(self, **kwargs):
        self.kwargs = kwargs
        _FakeLangfuse.instances.append(self)


@pytest.fixture(autouse=True)
def _reset():
    tracing.reset_tracing_cache()
    _FakeLangfuse.instances = []
    yield
    tracing.reset_tracing_cache()


@pytest.fixture
def _fake_langfuse(monkeypatch):
    import langfuse

    monkeypatch.setattr(langfuse, "Langfuse", _FakeLangfuse)
    return _FakeLangfuse


# --------------------------------------------------------------------------- #
# TASK-001 — is_tracing_enabled + get_langfuse_client.
# --------------------------------------------------------------------------- #
def test_is_tracing_enabled_requires_both_keys():
    assert tracing.is_tracing_enabled(_settings()) is True
    assert tracing.is_tracing_enabled(_settings(pk=None)) is False
    assert tracing.is_tracing_enabled(_settings(sk=None)) is False


def test_blank_or_whitespace_key_reads_as_disabled():
    assert tracing.is_tracing_enabled(_settings(pk="")) is False
    assert tracing.is_tracing_enabled(_settings(sk="   ")) is False


def test_host_is_optional():
    assert tracing.is_tracing_enabled(_settings(host=None)) is True


def test_get_langfuse_client_none_when_disabled(_fake_langfuse):
    assert tracing.get_langfuse_client(_settings(pk=None)) is None
    assert _fake_langfuse.instances == []  # never constructed on the no-key path


def test_get_langfuse_client_built_once_from_settings(_fake_langfuse):
    s = _settings()
    c1 = tracing.get_langfuse_client(s)
    c2 = tracing.get_langfuse_client(s)
    assert isinstance(c1, _FakeLangfuse)
    assert c1 is c2  # process singleton
    assert len(_fake_langfuse.instances) == 1  # built at most once
    assert c1.kwargs["public_key"] == "pk-test-123"
    assert c1.kwargs["secret_key"] == "sk-test-456"
    # The client is handed a TracerProvider it shares with the instrumentation.
    assert c1.kwargs.get("tracer_provider") is not None


# --------------------------------------------------------------------------- #
# TASK-002 — instrument_agent + the process() hook.
# --------------------------------------------------------------------------- #
from pydantic import BaseModel  # noqa: E402

from app.core.agent_node import PydanticAgentNode, build_agent  # noqa: E402
from app.core.nodes import AgentConfig  # noqa: E402
from app.core.task_context import TaskContext  # noqa: E402


class _Out(BaseModel):
    value: str


class _Deps(BaseModel):
    constitution_version: str | None = None


class _ToyNode(PydanticAgentNode):
    """A brief-agnostic toy AgentNode over the shared base (no profile/context needed)."""

    DepsType = _Deps
    OutputType = _Out
    mode = "daily"

    def get_agent_config(self) -> AgentConfig:
        return AgentConfig(model_id="claude-opus-4-8", output_type=_Out)

    def build_system_prompt(self, task_context):
        return "system"

    def build_run_input(self, task_context):
        return "go"

    def build_deps(self, task_context):
        return _Deps(constitution_version="2026.1")


def _function_model_returning(value: str):
    from pydantic_ai.messages import ModelResponse, ToolCallPart
    from pydantic_ai.models.function import AgentInfo, FunctionModel

    def _respond(messages, info: AgentInfo) -> ModelResponse:
        tool = info.output_tools[0]
        return ModelResponse(parts=[ToolCallPart(tool_name=tool.name, args={"value": value})])

    return FunctionModel(_respond)


def _patch_build_agent(monkeypatch, model):
    import app.core.agent_node as mod

    real = mod.build_agent

    def _wrap(*args, **kwargs):
        agent = real(*args, **kwargs)
        original_run = agent.run

        async def _run(*a, **k):
            with agent.override(model=model):
                return await original_run(*a, **k)

        agent.run = _run
        return agent

    monkeypatch.setattr(mod, "build_agent", _wrap)


def test_instrument_agent_sets_instrument_when_enabled(_fake_langfuse):
    agent = build_agent(
        AgentConfig(model_id="claude-opus-4-8", output_type=_Out),
        system_prompt="s",
        deps_type=_Deps,
    )
    tracing.instrument_agent(agent, _settings())
    assert agent.instrument  # a truthy InstrumentationSettings
    assert agent.instrument.include_content is True


def test_instrument_agent_noop_when_disabled():
    agent = build_agent(
        AgentConfig(model_id="claude-opus-4-8", output_type=_Out),
        system_prompt="s",
        deps_type=_Deps,
    )
    tracing.instrument_agent(agent, _settings(pk=None))
    assert not agent.instrument  # unchanged (falsy default)


def _inmemory_exporter_on_provider(provider):
    from opentelemetry.sdk.trace.export import SimpleSpanProcessor
    from opentelemetry.sdk.trace.export.in_memory_span_exporter import InMemorySpanExporter

    exporter = InMemorySpanExporter()
    provider.add_span_processor(SimpleSpanProcessor(exporter))
    return exporter


def test_traced_process_run_emits_spans(monkeypatch, _fake_langfuse):
    import asyncio

    s = _settings()
    monkeypatch.setattr(tracing, "get_settings", lambda: s)
    # Build the client+provider, then attach an in-memory exporter to capture spans.
    tracing.get_langfuse_client(s)
    exporter = _inmemory_exporter_on_provider(tracing._tracer_provider(s))

    _patch_build_agent(monkeypatch, _function_model_returning("ok"))
    ctx = TaskContext(event=None, metadata={})
    node = _ToyNode(task_context=ctx)
    asyncio.run(node.process(ctx))

    assert node.get_output(_ToyNode).value == "ok"  # behaviour unchanged
    spans = exporter.get_finished_spans()
    assert spans, "a traced run must emit at least one span"


def test_untraced_process_run_emits_nothing_and_is_identical(monkeypatch):
    import asyncio

    s = _settings(pk=None)  # disabled
    monkeypatch.setattr(tracing, "get_settings", lambda: s)
    built = {"n": 0}
    monkeypatch.setattr(
        tracing, "_client_and_provider", lambda *a, **k: (built.__setitem__("n", built["n"] + 1), (None, None))[1]
    )

    _patch_build_agent(monkeypatch, _function_model_returning("ok"))
    ctx = TaskContext(event=None, metadata={})
    node = _ToyNode(task_context=ctx)
    asyncio.run(node.process(ctx))
    assert node.get_output(_ToyNode).value == "ok"  # identical result


def test_agent_node_has_no_langfuse_or_otel_import():
    import pathlib
    import re

    src = pathlib.Path("app/core/agent_node.py").read_text(encoding="utf-8")
    assert not re.search(r"import langfuse|from langfuse|import opentelemetry|from opentelemetry", src)
