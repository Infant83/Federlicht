from __future__ import annotations

import io
import json
from pathlib import Path

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
