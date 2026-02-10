from __future__ import annotations

import argparse
import json
import mimetypes
import os
import socket
import sys
import traceback
import webbrowser
from http import HTTPStatus
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
from pathlib import Path
from typing import Any, Iterable, Optional

from federlicht.versioning import VERSION as FEDERLICHT_VERSION

from .config import FedernettConfig
from .constants import DEFAULT_RUN_ROOTS, DEFAULT_STATIC_DIR, DEFAULT_SITE_ROOT
from .jobs import Job, JobRegistry
from .routes import handle_api_get as _dispatch_api_get, handle_api_post as _dispatch_api_post
from .templates import read_template_style
from .utils import json_bytes as _json_bytes


def _resolve_federnett_server_version() -> str:
    return f"federnett/{FEDERLICHT_VERSION}"


class FedernettHandler(BaseHTTPRequestHandler):
    server_version = _resolve_federnett_server_version()

    def _cfg(self) -> FedernettConfig:
        return self.server.cfg  # type: ignore[attr-defined]

    def _jobs(self) -> JobRegistry:
        return self.server.jobs  # type: ignore[attr-defined]

    def log_message(self, format: str, *args: Any) -> None:
        # Keep server logs compact; job logs stream separately.
        sys.stderr.write("[federnett] " + format % args + "\n")

    def _send_json(self, payload: Any, status: int = 200) -> None:
        data = _json_bytes(payload)
        self.send_response(status)
        self.send_header("Content-Type", "application/json; charset=utf-8")
        self.send_header("Content-Length", str(len(data)))
        self.end_headers()
        self.wfile.write(data)

    def _send_bytes(self, data: bytes, content_type: str, status: int = 200) -> None:
        self.send_response(status)
        self.send_header("Content-Type", content_type)
        self.send_header("Content-Length", str(len(data)))
        self.end_headers()
        self.wfile.write(data)

    def _read_json(self) -> dict[str, Any]:
        length = int(self.headers.get("Content-Length", "0") or "0")
        if length <= 0:
            return {}
        raw = self.rfile.read(length)
        try:
            return json.loads(raw.decode("utf-8"))
        except Exception:
            return {}

    def do_GET(self) -> None:  # noqa: N802
        try:
            if self.path.startswith("/api/") or self.path.startswith("/raw/"):
                self._handle_api_get()
                return
            self._serve_static()
        except Exception as exc:  # pragma: no cover - safety net for local servers
            tb = traceback.format_exc()
            sys.stderr.write(f"[federnett] GET error: {exc}\n{tb}\n")
            try:
                self.send_error(HTTPStatus.INTERNAL_SERVER_ERROR, str(exc))
            except Exception:
                pass

    def do_POST(self) -> None:  # noqa: N802
        try:
            if not self.path.startswith("/api/"):
                self.send_error(HTTPStatus.NOT_FOUND, "Unknown endpoint")
                return
            self._handle_api_post()
        except Exception as exc:  # pragma: no cover - safety net for local servers
            tb = traceback.format_exc()
            sys.stderr.write(f"[federnett] POST error: {exc}\n{tb}\n")
            try:
                self.send_error(HTTPStatus.INTERNAL_SERVER_ERROR, str(exc))
            except Exception:
                pass

    def _handle_api_get(self) -> None:
        _dispatch_api_get(
            self,
            list_models=_list_models,
        )

    def _handle_api_post(self) -> None:
        _dispatch_api_post(
            self,
            render_template_preview=_render_template_preview,
        )

    def _stream_job(self, job: Job) -> None:
        self.send_response(HTTPStatus.OK)
        self.send_header("Content-Type", "text/event-stream; charset=utf-8")
        self.send_header("Cache-Control", "no-cache")
        self.send_header("Connection", "keep-alive")
        self.end_headers()

        last_index = 0
        # Send buffered logs first.
        while True:
            new_logs, done = job.wait_for_logs(last_index, timeout=1.0)
            for entry in new_logs:
                last_index = entry["index"] + 1
                data = json.dumps(entry, ensure_ascii=False)
                chunk = f"event: log\ndata: {data}\n\n".encode("utf-8")
                try:
                    self.wfile.write(chunk)
                    self.wfile.flush()
                except BrokenPipeError:
                    return
            if done and last_index >= len(job.logs):
                status_payload = json.dumps(
                    {"status": job.status, "returncode": job.returncode},
                    ensure_ascii=False,
                )
                try:
                    self.wfile.write(f"event: done\ndata: {status_payload}\n\n".encode("utf-8"))
                    self.wfile.flush()
                except BrokenPipeError:
                    pass
                return

    def _serve_static(self) -> None:
        cfg = self._cfg()
        static_dir = cfg.static_dir
        rel = self.path.split("?", 1)[0].lstrip("/")
        if not rel:
            rel = "index.html"
        target = (static_dir / rel).resolve()
        try:
            target.relative_to(static_dir.resolve())
        except Exception:
            self.send_error(HTTPStatus.FORBIDDEN, "Invalid path")
            return
        if target.is_dir():
            target = target / "index.html"
        if not target.exists():
            # SPA fallback.
            target = static_dir / "index.html"
        if not target.exists():
            self.send_error(HTTPStatus.NOT_FOUND, "Missing static assets")
            return
        ctype, _ = mimetypes.guess_type(str(target))
        data = target.read_bytes()
        self.send_response(HTTPStatus.OK)
        self.send_header("Content-Type", (ctype or "text/html") + "; charset=utf-8")
        self.send_header("Content-Length", str(len(data)))
        self.end_headers()
        self.wfile.write(data)


class FedernettHTTPServer(ThreadingHTTPServer):
    # Avoid multiple federnett processes binding the same port on Windows.
    allow_reuse_address = False

    def server_bind(self) -> None:  # pragma: no cover - platform-dependent
        if os.name == "nt":
            try:
                self.socket.setsockopt(socket.SOL_SOCKET, socket.SO_EXCLUSIVEADDRUSE, 1)
            except Exception:
                pass
        try:
            self.socket.setsockopt(socket.SOL_SOCKET, socket.SO_REUSEADDR, 0)
        except Exception:
            pass
        super().server_bind()


def _list_models() -> list[str]:
    api_key = os.getenv("OPENAI_API_KEY")
    base_url = os.getenv("OPENAI_BASE_URL") or os.getenv("OPENAI_API_BASE")
    if not api_key:
        return []
    if not base_url:
        base_url = "https://api.openai.com"
    try:
        import requests  # type: ignore
    except Exception:
        return []
    endpoints = [
        ("GET", base_url.rstrip("/") + "/v1/models"),
        ("GET", base_url.rstrip("/") + "/models"),
        ("POST", base_url.rstrip("/") + "/models"),
    ]
    headers = {
        "Authorization": f"Bearer {api_key}",
        "Content-Type": "application/json",
    }
    models: list[str] = []
    for method, url in endpoints:
        try:
            if method == "POST":
                resp = requests.post(url, headers=headers, json={}, timeout=6)
            else:
                resp = requests.get(url, headers=headers, timeout=6)
        except Exception:
            continue
        if resp.status_code != 200:
            continue
        try:
            payload = resp.json()
        except Exception:
            continue
        data = payload.get("data")
        if not isinstance(data, list):
            # Some compatible servers return {"models":[...]}.
            data = payload.get("models")
        if not isinstance(data, list):
            continue
        for entry in data:
            if isinstance(entry, dict) and entry.get("id"):
                models.append(str(entry["id"]))
            elif isinstance(entry, str):
                models.append(entry)
        if models:
            break
    return sorted(set(models))


def _render_template_preview(root: Path, payload: dict[str, Any]) -> str:
    try:
        from federlicht.render.html import markdown_to_html, wrap_html  # type: ignore
    except Exception:
        return "<p>Preview renderer unavailable.</p>"
    name = str(payload.get("name") or "template")
    title = str(payload.get("title") or f"{name} preview")
    sections = payload.get("sections") or []
    guides = payload.get("guides") or {}
    writer_guidance = payload.get("writer_guidance") or []
    css_name = str(payload.get("css") or "").strip()
    css_content = None
    extra_body_class = None
    if css_name:
        try:
            css_content = read_template_style(root, css_name).get("content")
            css_base = Path(css_name).stem
            if css_base:
                extra_body_class = f"template-{css_base.lower()}"
        except Exception:
            css_content = None
    lines: list[str] = [f"# {title}", ""]
    if writer_guidance:
        lines.append("## Writer Notes")
        for note in writer_guidance:
            if note:
                lines.append(f"- {note}")
        lines.append("")
    for section in sections:
        if not section:
            continue
        lines.append(f"## {section}")
        guide = guides.get(section) if isinstance(guides, dict) else None
        if guide:
            lines.append(f"*Guidance:* {guide}")
        lines.append(
            "Sample paragraph to preview layout, spacing, and typography. "
            "Replace with real content when generating the report."
        )
        lines.append("")
    markdown = "\n".join(lines).strip() + "\n"
    body_html = markdown_to_html(markdown)
    return wrap_html(
        title,
        body_html,
        template_name=name,
        theme_css=css_content,
        extra_body_class=extra_body_class,
    )


def _parse_run_roots(root: Path, raw: str) -> list[Path]:
    items: list[Path] = []
    for token in raw.split(","):
        token = token.strip()
        if not token:
            continue
        candidate = (root / token).resolve()
        try:
            candidate.relative_to(root)
        except Exception:
            continue
        items.append(candidate)
    return items or [(root / rel).resolve() for rel in DEFAULT_RUN_ROOTS]


class _HelpFormatter(argparse.ArgumentDefaultsHelpFormatter, argparse.RawTextHelpFormatter):
    """Preserve example formatting while still showing defaults."""


def build_parser() -> argparse.ArgumentParser:
    examples = """Examples:
  # Local repo root. Run discovery stays under this directory.
  federnett --root . --port 8765
  # Share on the LAN (bind all interfaces).
  federnett --root . --host 0.0.0.0 --port 8765
  # Runs live in multiple folders under the repo.
  federnett --root . --run-roots examples/runs,site/runs,data/runs
  # Custom UI location + site root (still under --root).
  federnett --root . --static-dir site/federnett --site-root site
  # Headless server: do not open a browser.
  federnett --root . --no-open-browser
  # Module entrypoint.
  python -m federnett.app --root . --port 8765
"""
    ap = argparse.ArgumentParser(
        prog="federnett",
        description="Federnett studio (Federlicht platform): web control plane for Feather intake and Federlicht reporting.",
        epilog=examples,
        formatter_class=_HelpFormatter,
    )
    ap.add_argument("--host", default="127.0.0.1", help="Host to bind.")
    ap.add_argument("--port", type=int, default=8765, help="Port to bind.")
    ap.add_argument(
        "--root",
        default=".",
        help=(
            "Workspace root (base directory). All paths are resolved under this "
            "directory and path escapes are rejected."
        ),
    )
    ap.add_argument(
        "--run-roots",
        default=",".join(DEFAULT_RUN_ROOTS),
        help=(
            "Comma-separated run folders to scan under --root. Each run-root "
            "is scanned one level deep for run directories."
        ),
    )
    ap.add_argument(
        "--static-dir",
        default=DEFAULT_STATIC_DIR,
        help="Static UI directory to serve under --root.",
    )
    ap.add_argument(
        "--site-root",
        default=DEFAULT_SITE_ROOT,
        help=(
            "Site root path under --root used when building file links for "
            "run folders."
        ),
    )
    ap.add_argument(
        "--open-browser",
        action=argparse.BooleanOptionalAction,
        default=True,
        help="Open the UI in a browser on startup.",
    )
    return ap


def main(argv: Optional[Iterable[str]] = None) -> int:
    args = build_parser().parse_args(argv)
    root = Path(args.root).resolve()
    static_dir = (root / args.static_dir).resolve()
    site_root = (root / args.site_root).resolve()
    run_roots = _parse_run_roots(root, args.run_roots)

    cfg = FedernettConfig(root=root, static_dir=static_dir, run_roots=run_roots, site_root=site_root)
    jobs = JobRegistry()

    server = FedernettHTTPServer((args.host, args.port), FedernettHandler)
    server.cfg = cfg  # type: ignore[attr-defined]
    server.jobs = jobs  # type: ignore[attr-defined]

    url = f"http://{args.host}:{args.port}/"
    print(f"[federnett] Serving {url}")
    print(f"[federnett] Root: {root}")
    if not static_dir.exists():
        print(f"[federnett] Static dir missing: {static_dir}", file=sys.stderr)
    if args.open_browser:
        try:
            webbrowser.open(url)
        except Exception:
            pass

    try:
        server.serve_forever()
    except KeyboardInterrupt:
        print("\n[federnett] Shutting down.")
    finally:
        server.server_close()
    return 0


if __name__ == "__main__":
    raise SystemExit(main())

