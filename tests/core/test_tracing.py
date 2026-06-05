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
