from __future__ import annotations

import io
import json
from pathlib import Path

import federnett.routes as routes_mod
from federnett.config import FedernettConfig
from federnett.jobs import JobRegistry
from federnett.routes import handle_api_get, handle_api_post


class DummyHandler:
    def __init__(self, cfg: FedernettConfig, path: str, payload: dict | None = None) -> None:
        self._cfg_obj = cfg
        self._jobs_obj = JobRegistry()
        self.path = path
        raw = json.dumps(payload or {}, ensure_ascii=False).encode("utf-8")
        self.headers = {"Content-Length": str(len(raw))}
        self.rfile = io.BytesIO(raw)
        self.json_response: tuple[int, object] | None = None
        self.bytes_response: tuple[int, bytes, str] | None = None
        self.streamed_job = None
        self.stream_status: int | None = None
        self.stream_headers: list[tuple[str, str]] = []
        self.wfile = io.BytesIO()

    def _cfg(self) -> FedernettConfig:
        return self._cfg_obj

    def _jobs(self) -> JobRegistry:
        return self._jobs_obj

    def _send_json(self, payload: object, status: int = 200) -> None:
        self.json_response = (status, payload)

    def _send_bytes(self, data: bytes, content_type: str, status: int = 200) -> None:
        self.bytes_response = (status, data, content_type)

    def _read_json(self) -> dict:
        length = int(self.headers.get("Content-Length", "0") or "0")
        if length <= 0:
            return {}
        raw = self.rfile.read(length)
        return json.loads(raw.decode("utf-8"))

    def _stream_job(self, job) -> None:
        self.streamed_job = job

    def send_response(self, code: int, message: str | None = None) -> None:
        self.stream_status = code

    def send_header(self, keyword: str, value: str) -> None:
        self.stream_headers.append((keyword, value))

    def end_headers(self) -> None:
        return


def make_cfg(tmp_path: Path) -> FedernettConfig:
    root = tmp_path
    static_dir = root / "site" / "federnett"
    static_dir.mkdir(parents=True, exist_ok=True)
    site_root = root / "site"
    site_root.mkdir(parents=True, exist_ok=True)
    run_root = root / "site" / "runs"
    run_root.mkdir(parents=True, exist_ok=True)
    return FedernettConfig(
        root=root,
        static_dir=static_dir,
        run_roots=[run_root],
        site_root=site_root,
    )


def test_handle_api_get_health(tmp_path: Path) -> None:
    cfg = make_cfg(tmp_path)
    handler = DummyHandler(cfg, "/api/health")
    handle_api_get(handler, list_models=lambda: [])
    assert handler.json_response == (200, {"status": "ok"})


def test_handle_api_get_models_uses_callback(tmp_path: Path) -> None:
    cfg = make_cfg(tmp_path)
    handler = DummyHandler(cfg, "/api/models")
    handle_api_get(handler, list_models=lambda: ["gpt-5", "gpt-5-mini"])
    assert handler.json_response == (200, ["gpt-5", "gpt-5-mini"])


def test_handle_api_post_help_ask_rejects_blank_question(tmp_path: Path) -> None:
    cfg = make_cfg(tmp_path)
    handler = DummyHandler(cfg, "/api/help/ask", payload={"question": "   "})
    handle_api_post(handler, render_template_preview=lambda _root, _payload: "")
    assert handler.json_response is not None
    status, body = handler.json_response
    assert status == 400
    assert isinstance(body, dict)
    assert "question must be a non-empty string" in str(body.get("error"))


def test_handle_api_post_unknown_endpoint(tmp_path: Path) -> None:
    cfg = make_cfg(tmp_path)
    handler = DummyHandler(cfg, "/api/does-not-exist", payload={})
    handle_api_post(handler, render_template_preview=lambda _root, _payload: "")
    assert handler.json_response == (404, {"error": "unknown_endpoint"})


def test_handle_api_get_output_suggestion_appends_suffix(tmp_path: Path) -> None:
    cfg = make_cfg(tmp_path)
    existing = tmp_path / "site" / "runs" / "demo" / "report_full.html"
    existing.parent.mkdir(parents=True, exist_ok=True)
    existing.write_text("old", encoding="utf-8")
    handler = DummyHandler(cfg, "/api/federlicht/output-suggestion?output=site/runs/demo/report_full.html")
    handle_api_get(handler, list_models=lambda: [])
    assert handler.json_response is not None
    status, body = handler.json_response
    assert status == 200
    assert isinstance(body, dict)
    assert body.get("requested_output") == "site/runs/demo/report_full.html"
    assert body.get("suggested_output") == "site/runs/demo/report_full_1.html"
    assert body.get("changed") is True


def test_handle_api_get_output_suggestion_with_run_prefix(tmp_path: Path) -> None:
    cfg = make_cfg(tmp_path)
    handler = DummyHandler(
        cfg,
        "/api/federlicht/output-suggestion?run=site/runs/demo&output=report_full.html",
    )
    handle_api_get(handler, list_models=lambda: [])
    assert handler.json_response is not None
    status, body = handler.json_response
    assert status == 200
    assert isinstance(body, dict)
    assert body.get("requested_output") == "site/runs/demo/report_full.html"
    assert body.get("suggested_output") == "site/runs/demo/report_full.html"
    assert body.get("changed") is False


def test_handle_api_post_help_ask_forwards_strict_model(tmp_path: Path, monkeypatch) -> None:
    cfg = make_cfg(tmp_path)
    captured: dict[str, object] = {}

    def _fake_answer(root, question, **kwargs):
        captured["root"] = root
        captured["question"] = question
        captured.update(kwargs)
        return {"answer": "ok", "sources": [], "used_llm": False, "model": ""}

    monkeypatch.setattr(routes_mod, "answer_help_question", _fake_answer)
    handler = DummyHandler(
        cfg,
        "/api/help/ask",
        payload={"question": "테스트", "model": "gpt-5", "strict_model": True},
    )
    handle_api_post(handler, render_template_preview=lambda _root, _payload: "")
    assert handler.json_response is not None
    status, body = handler.json_response
    assert status == 200
    assert isinstance(body, dict)
    assert captured.get("model") == "gpt-5"
    assert captured.get("strict_model") is True


def test_handle_api_post_help_ask_forwards_web_search_flag(tmp_path: Path, monkeypatch) -> None:
    cfg = make_cfg(tmp_path)
    captured: dict[str, object] = {}

    def _fake_answer(root, question, **kwargs):
        captured["root"] = root
        captured["question"] = question
        captured.update(kwargs)
        return {"answer": "ok", "sources": [], "used_llm": False, "model": ""}

    monkeypatch.setattr(routes_mod, "answer_help_question", _fake_answer)
    handler = DummyHandler(
        cfg,
        "/api/help/ask",
        payload={"question": "테스트", "web_search": True},
    )
    handle_api_post(handler, render_template_preview=lambda _root, _payload: "")
    assert handler.json_response is not None
    status, body = handler.json_response
    assert status == 200
    assert isinstance(body, dict)
    assert captured.get("web_search") is True


def test_handle_api_post_help_ask_stream_emits_sse(tmp_path: Path, monkeypatch) -> None:
    cfg = make_cfg(tmp_path)

    def _fake_stream(_root, _question, **_kwargs):
        yield {"event": "meta", "requested_model": "gpt-5.2"}
        yield {"event": "delta", "text": "안녕하세요"}
        yield {"event": "done", "answer": "안녕하세요", "sources": []}

    monkeypatch.setattr(routes_mod, "stream_help_question", _fake_stream)
    handler = DummyHandler(
        cfg,
        "/api/help/ask/stream",
        payload={"question": "테스트 스트림"},
    )
    handle_api_post(handler, render_template_preview=lambda _root, _payload: "")
    assert handler.stream_status == 200
    raw = handler.wfile.getvalue().decode("utf-8")
    assert "event: meta" in raw
    assert "event: delta" in raw
    assert "event: done" in raw


def test_handle_api_post_help_ask_stream_forwards_web_search_flag(tmp_path: Path, monkeypatch) -> None:
    cfg = make_cfg(tmp_path)
    captured: dict[str, object] = {}

    def _fake_stream(_root, _question, **kwargs):
        captured.update(kwargs)
        yield {"event": "done", "answer": "ok", "sources": []}

    monkeypatch.setattr(routes_mod, "stream_help_question", _fake_stream)
    handler = DummyHandler(
        cfg,
        "/api/help/ask/stream",
        payload={"question": "테스트 스트림", "web_search": True},
    )
    handle_api_post(handler, render_template_preview=lambda _root, _payload: "")
    assert handler.stream_status == 200
    assert captured.get("web_search") is True


def test_handle_api_get_help_history_forwards_profile_id(tmp_path: Path, monkeypatch) -> None:
    cfg = make_cfg(tmp_path)
    captured: dict[str, object] = {}

    def _fake_read_help_history(root, run_rel, profile_id=None):
        captured["root"] = root
        captured["run_rel"] = run_rel
        captured["profile_id"] = profile_id
        return {"run_rel": run_rel or "", "profile_id": profile_id or "", "items": []}

    monkeypatch.setattr(routes_mod, "read_help_history", _fake_read_help_history)
    handler = DummyHandler(cfg, "/api/help/history?run=site/runs/demo&profile_id=team_a")
    handle_api_get(handler, list_models=lambda: [])
    assert handler.json_response is not None
    status, body = handler.json_response
    assert status == 200
    assert isinstance(body, dict)
    assert captured.get("profile_id") == "team_a"
