from __future__ import annotations

from dataclasses import dataclass
from typing import Any

import pytest

from federnett import help_agent


@dataclass
class _FakeResponse:
    status_code: int
    text: str = ""
    payload: dict[str, Any] | None = None

    def json(self) -> dict[str, Any]:
        return self.payload or {}


class _RequestsStub:
    def __init__(self) -> None:
        self.calls: list[dict[str, Any]] = []

    def post(self, url: str, *, headers: dict[str, str], json: dict[str, Any], timeout: int) -> _FakeResponse:
        self.calls.append({"url": url, "headers": headers, "json": json, "timeout": timeout})
        if "max_completion_tokens" in json:
            return _FakeResponse(
                400,
                text=(
                    '{"error":{"message":"Unsupported parameter: \'max_completion_tokens\'"}}'
                ),
            )
        return _FakeResponse(
            200,
            payload={
                "choices": [
                    {
                        "message": {
                            "content": "요약 답변",
                        }
                    }
                ]
            },
        )


class _EndpointFallbackStub:
    def __init__(self) -> None:
        self.calls: list[dict[str, Any]] = []

    def post(self, url: str, *, headers: dict[str, str], json: dict[str, Any], timeout: int) -> _FakeResponse:
        self.calls.append({"url": url, "headers": headers, "json": json, "timeout": timeout})
        if url.endswith("/v1/chat/completions"):
            return _FakeResponse(404, text='{"error":{"message":"Not Found"}}')
        return _FakeResponse(
            200,
            payload={
                "choices": [
                    {
                        "message": {
                            "content": "fallback endpoint answer",
                        }
                    }
                ]
            },
        )


class _ResponsesOnlyStub:
    def __init__(self) -> None:
        self.calls: list[dict[str, Any]] = []

    def post(self, url: str, *, headers: dict[str, str], json: dict[str, Any], timeout: int) -> _FakeResponse:
        self.calls.append({"url": url, "headers": headers, "json": json, "timeout": timeout})
        if url.endswith("/responses"):
            return _FakeResponse(
                200,
                payload={
                    "output_text": "responses endpoint answer",
                },
            )
        return _FakeResponse(404, text='{"error":{"message":"Not Found"}}')


class _ModelFallbackStub:
    def __init__(self) -> None:
        self.calls: list[dict[str, Any]] = []

    def post(self, url: str, *, headers: dict[str, str], json: dict[str, Any], timeout: int) -> _FakeResponse:
        self.calls.append({"url": url, "headers": headers, "json": json, "timeout": timeout})
        model = str(json.get("model") or "")
        if model == "gpt-5-nano":
            return _FakeResponse(404, text='{"error":{"message":"Model gpt-5-nano does not exist"}}')
        return _FakeResponse(
            200,
            payload={
                "choices": [
                    {
                        "message": {
                            "content": "fallback model answer",
                        }
                    }
                ]
            },
        )


def _sample_sources() -> list[dict[str, Any]]:
    return [
        {
            "id": "S1",
            "path": "README.md",
            "start_line": 1,
            "end_line": 3,
            "excerpt": "Federnett guide",
        }
    ]


def test_chat_completion_urls_with_v1_base() -> None:
    urls = help_agent._chat_completion_urls("http://localhost:8080/v1")
    assert "http://localhost:8080/v1/chat/completions" in urls
    assert "http://localhost:8080/chat/completions" in urls


def test_call_llm_retries_token_budget_parameter(monkeypatch) -> None:
    stub = _RequestsStub()
    monkeypatch.setattr(help_agent, "requests", stub)
    monkeypatch.setenv("OPENAI_API_KEY", "test-key")
    monkeypatch.setenv("OPENAI_MODEL", "gpt-4o-mini")
    monkeypatch.setenv("OPENAI_BASE_URL", "https://llm.example")

    answer, model = help_agent._call_llm("테스트 질문", _sample_sources(), model=None, history=None)

    assert answer == "요약 답변"
    assert model == "gpt-4o-mini"
    assert len(stub.calls) >= 2
    assert "max_completion_tokens" in stub.calls[0]["json"]
    assert "max_tokens" in stub.calls[1]["json"]


def test_call_llm_falls_back_to_secondary_endpoint(monkeypatch) -> None:
    stub = _EndpointFallbackStub()
    monkeypatch.setattr(help_agent, "requests", stub)
    monkeypatch.setenv("OPENAI_API_KEY", "test-key")
    monkeypatch.setenv("OPENAI_MODEL", "gpt-4o-mini")
    monkeypatch.setenv("OPENAI_BASE_URL", "https://gw.example")

    answer, model = help_agent._call_llm("endpoint fallback", _sample_sources(), model=None, history=None)

    assert answer == "fallback endpoint answer"
    assert model == "gpt-4o-mini"
    assert len(stub.calls) >= 2
    assert stub.calls[0]["url"].endswith("/v1/chat/completions")
    assert any(call["url"].endswith("/chat/completions") for call in stub.calls[1:])


def test_call_llm_uses_responses_endpoint_when_chat_missing(monkeypatch) -> None:
    stub = _ResponsesOnlyStub()
    monkeypatch.setattr(help_agent, "requests", stub)
    monkeypatch.setenv("OPENAI_API_KEY", "test-key")
    monkeypatch.setenv("OPENAI_MODEL", "gpt-4o-mini")
    monkeypatch.setenv("OPENAI_BASE_URL", "https://gw.example")

    answer, model = help_agent._call_llm("responses fallback", _sample_sources(), model=None, history=None)

    assert answer == "responses endpoint answer"
    assert model == "gpt-4o-mini"
    assert any(call["url"].endswith("/responses") for call in stub.calls)


def test_call_llm_falls_back_when_model_unavailable(monkeypatch) -> None:
    stub = _ModelFallbackStub()
    monkeypatch.setattr(help_agent, "requests", stub)
    monkeypatch.setenv("OPENAI_API_KEY", "test-key")
    monkeypatch.setenv("OPENAI_MODEL", "gpt-4o-mini")
    monkeypatch.setenv("OPENAI_BASE_URL", "https://gw.example")
    with pytest.raises(RuntimeError):
        help_agent._call_llm("model fallback", _sample_sources(), model="gpt-5-nano", history=None)
    models_seen = [str(call["json"].get("model") or "") for call in stub.calls]
    assert "gpt-5-nano" in models_seen
    assert "gpt-4o-mini" not in models_seen


def test_call_llm_falls_back_when_explicit_model_unavailable_and_allowed(monkeypatch) -> None:
    stub = _ModelFallbackStub()
    monkeypatch.setattr(help_agent, "requests", stub)
    monkeypatch.setenv("OPENAI_API_KEY", "test-key")
    monkeypatch.setenv("OPENAI_MODEL", "gpt-4o-mini")
    monkeypatch.setenv("OPENAI_BASE_URL", "https://gw.example")
    monkeypatch.setenv("FEDERNETT_HELP_ALLOW_MODEL_FALLBACK", "true")

    answer, model = help_agent._call_llm("model fallback", _sample_sources(), model="gpt-5-nano", history=None)

    assert answer == "fallback model answer"
    assert model == "gpt-4o-mini"
    models_seen = [str(call["json"].get("model") or "") for call in stub.calls]
    assert "gpt-5-nano" in models_seen
    assert "gpt-4o-mini" in models_seen


def test_call_llm_strict_model_blocks_fallback(monkeypatch) -> None:
    stub = _ModelFallbackStub()
    monkeypatch.setattr(help_agent, "requests", stub)
    monkeypatch.setenv("OPENAI_API_KEY", "test-key")
    monkeypatch.setenv("OPENAI_MODEL", "gpt-4o-mini")
    monkeypatch.setenv("OPENAI_BASE_URL", "https://gw.example")
    monkeypatch.setenv("FEDERNETT_HELP_ALLOW_MODEL_FALLBACK", "true")

    with pytest.raises(RuntimeError):
        help_agent._call_llm(
            "model fallback",
            _sample_sources(),
            model="gpt-5-nano",
            history=None,
            strict_model=True,
        )

    models_seen = [str(call["json"].get("model") or "") for call in stub.calls]
    assert "gpt-5-nano" in models_seen
    assert "gpt-4o-mini" not in models_seen


def test_resolve_requested_model_supports_openai_model_reference(monkeypatch) -> None:
    monkeypatch.setenv("OPENAI_MODEL", "gpt-5-mini")
    chosen, explicit = help_agent._resolve_requested_model("$OPENAI_MODEL")
    assert chosen == "gpt-5-mini"
    assert explicit is False


def test_stream_help_question_emits_delta_and_done(monkeypatch, tmp_path) -> None:
    root = tmp_path
    monkeypatch.setattr(help_agent, "_select_sources", lambda *_args, **_kwargs: (_sample_sources(), 3))

    def _fake_call_llm_stream(_q, _sources, **_kwargs):
        def _iter():
            yield "부분 "
            yield "응답"
        return _iter(), "gpt-4o-mini"

    monkeypatch.setattr(help_agent, "_call_llm_stream", _fake_call_llm_stream)
    events = list(
        help_agent.stream_help_question(
            root,
            "질문",
            model="gpt-4o-mini",
            history=[{"role": "user", "content": "prev"}],
        )
    )
    event_types = [evt.get("event") for evt in events]
    assert "activity" in event_types
    assert "meta" in event_types
    assert "delta" in event_types
    assert event_types[-1] == "done"
    done_payload = events[-1]
    assert done_payload.get("answer") == "부분 응답"
    assert isinstance(done_payload.get("capabilities"), dict)


def test_answer_help_question_runs_web_search_when_enabled(monkeypatch, tmp_path) -> None:
    monkeypatch.setattr(help_agent, "_select_sources", lambda *_args, **_kwargs: (_sample_sources(), 5))
    monkeypatch.setattr(help_agent, "_call_llm", lambda *_args, **_kwargs: ("웹검색 답변", "gpt-4o-mini"))
    monkeypatch.setattr(help_agent, "_run_help_web_research", lambda *_args, **_kwargs: "web research done")

    result = help_agent.answer_help_question(
        tmp_path,
        "웹검색 질문",
        model="gpt-4o-mini",
        web_search=True,
        run_rel="site/runs/demo",
    )

    assert result["answer"] == "웹검색 답변"
    assert result["web_search"] is True
    assert result["web_search_note"] == "web research done"
    assert isinstance(result.get("capabilities"), dict)


def test_stream_help_question_emits_web_search_meta(monkeypatch, tmp_path) -> None:
    monkeypatch.setattr(help_agent, "_select_sources", lambda *_args, **_kwargs: (_sample_sources(), 5))
    monkeypatch.setattr(help_agent, "_run_help_web_research", lambda *_args, **_kwargs: "web research done")

    def _fake_call_llm_stream(_q, _sources, **_kwargs):
        def _iter():
            yield "스트림 "
            yield "응답"
        return _iter(), "gpt-4o-mini"

    monkeypatch.setattr(help_agent, "_call_llm_stream", _fake_call_llm_stream)
    events = list(
        help_agent.stream_help_question(
            tmp_path,
            "웹검색 질문",
            model="gpt-4o-mini",
            web_search=True,
            run_rel="site/runs/demo",
        )
    )
    meta_event = next(evt for evt in events if evt.get("event") == "meta")
    assert meta_event["web_search"] is True
    assert meta_event["web_search_note"] == "web research done"
    assert isinstance(meta_event.get("capabilities"), dict)
    web_activity = [evt for evt in events if evt.get("event") == "activity" and evt.get("id") == "web_research"]
    assert web_activity
    assert events[-1]["event"] == "done"
    assert events[-1]["web_search"] is True
    assert events[-1]["web_search_note"] == "web research done"


def test_is_path_allowed_allows_run_prefix_when_opted_in() -> None:
    rel = "site/runs/demo/instruction/demo.txt"
    assert help_agent._is_path_allowed(rel) is False
    assert help_agent._is_path_allowed(rel, allow_run_prefixes=True) is True


def test_answer_help_question_skips_web_search_when_query_is_local(monkeypatch, tmp_path) -> None:
    monkeypatch.setattr(help_agent, "_select_sources", lambda *_args, **_kwargs: (_sample_sources(), 5))
    monkeypatch.setattr(help_agent, "_call_llm", lambda *_args, **_kwargs: ("ok", "gpt-4o-mini"))

    def _should_not_run(*_args, **_kwargs):
        raise AssertionError("web research should have been skipped")

    monkeypatch.setattr(help_agent, "_run_help_web_research", _should_not_run)
    result = help_agent.answer_help_question(
        tmp_path,
        "federlicht 옵션 설명해줘",
        web_search=True,
        run_rel="site/runs/demo",
    )
    assert result["web_search"] is True
    assert "skipped" in str(result["web_search_note"])
