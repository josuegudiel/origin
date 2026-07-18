"""Tests del OllamaClient + LLMIntentResolver con httpx mockeado."""
from __future__ import annotations

import pytest

pytest.importorskip("httpx")
pytest.importorskip("pytest_httpx")


from origin.engine.config import Command, LlmSettings, Profile
from origin.engine.llm import IntentResolution, LLMIntentResolver, OllamaClient, OllamaError


def _profile() -> Profile:
    return Profile(
        id="flight",
        commands=[
            Command(
                id="request_landing",
                phrases_es=["pide hangar"],
                phrases_en=["request landing"],
                keys=["alt+n"],
                label_es="Pedir hangar",
                label_en="Request landing",
            ),
            Command(
                id="quantum_mode",
                phrases_es=["quantum"],
                phrases_en=["quantum"],
                keys=["b"],
            ),
        ],
    )


def test_chat_json_parses_response(httpx_mock):
    httpx_mock.add_response(
        method="POST",
        url="http://localhost:11434/api/chat",
        json={"message": {"content": '{"commands":["request_landing"],"confidence":"high"}'}},
    )
    client = OllamaClient("http://localhost:11434", "test-model", 5000)
    raw = client.chat_json("system", "user")
    assert raw["commands"] == ["request_landing"]


def test_chat_json_bad_json_raises(httpx_mock):
    httpx_mock.add_response(
        method="POST",
        url="http://localhost:11434/api/chat",
        json={"message": {"content": "not json"}},
    )
    client = OllamaClient("http://localhost:11434", "test-model", 5000)
    with pytest.raises(OllamaError):
        client.chat_json("s", "u")


def test_chat_json_http_error_raises(httpx_mock):
    httpx_mock.add_response(
        method="POST",
        url="http://localhost:11434/api/chat",
        status_code=500,
    )
    client = OllamaClient("http://localhost:11434", "test-model", 5000)
    with pytest.raises(OllamaError):
        client.chat_json("s", "u")


def test_preflight_ok(httpx_mock):
    httpx_mock.add_response(
        method="GET",
        url="http://localhost:11434/api/tags",
        json={"models": [{"name": "llama3.1:8b"}]},
    )
    client = OllamaClient("http://localhost:11434", "llama3.1:8b", 5000)
    assert client.preflight() is None


def test_preflight_model_missing(httpx_mock):
    httpx_mock.add_response(
        method="GET",
        url="http://localhost:11434/api/tags",
        json={"models": [{"name": "other:7b"}]},
    )
    client = OllamaClient("http://localhost:11434", "llama3.1:8b", 5000)
    err = client.preflight()
    assert err and "model_not_pulled" in err


def test_resolver_filters_invalid_command_ids(httpx_mock):
    httpx_mock.add_response(
        method="POST",
        url="http://localhost:11434/api/chat",
        json={"message": {"content": '{"commands":["request_landing","invalid_id","quantum_mode"],"confidence":"high","reasoning":""}'}},
    )
    client = OllamaClient("http://localhost:11434", "test", 5000)
    resolver = LLMIntentResolver(client, LlmSettings(enabled=True))
    res = resolver.resolve("pide hangar y quantum", _profile(), "es")
    assert res.commands == ["request_landing", "quantum_mode"]


def test_resolver_caps_at_max_commands(httpx_mock):
    many = ['"' + c + '"' for c in ["request_landing"] * 10]
    httpx_mock.add_response(
        method="POST",
        url="http://localhost:11434/api/chat",
        json={"message": {"content": '{"commands":[' + ",".join(many) + '],"confidence":"high","reasoning":""}'}},
    )
    client = OllamaClient("http://localhost:11434", "test", 5000)
    resolver = LLMIntentResolver(client, LlmSettings(enabled=True, max_commands_per_resolution=3))
    res = resolver.resolve("x", _profile(), "es")
    assert len(res.commands) == 3


def test_resolver_returns_low_on_http_error(httpx_mock):
    httpx_mock.add_response(
        method="POST",
        url="http://localhost:11434/api/chat",
        status_code=500,
    )
    client = OllamaClient("http://localhost:11434", "test", 5000)
    resolver = LLMIntentResolver(client, LlmSettings(enabled=True))
    res = resolver.resolve("x", _profile(), "es")
    assert res.confidence == "low"
    assert res.commands == []


def test_resolver_returns_low_on_bad_schema(httpx_mock):
    httpx_mock.add_response(
        method="POST",
        url="http://localhost:11434/api/chat",
        json={"message": {"content": '{"wrong_field":"oops"}'}},
    )
    client = OllamaClient("http://localhost:11434", "test", 5000)
    resolver = LLMIntentResolver(client, LlmSettings(enabled=True))
    res = resolver.resolve("x", _profile(), "es")
    # bad_schema → low/empty
    assert res.commands == []
