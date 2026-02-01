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
from urllib.parse import parse_qs, urlparse, unquote

from .commands import _build_feather_cmd, _build_federlicht_cmd, _build_generate_prompt_cmd
from .config import FedernettConfig
from .constants import DEFAULT_RUN_ROOTS, DEFAULT_STATIC_DIR, DEFAULT_SITE_ROOT
from .filesystem import (
    list_run_dirs,
    summarize_run,
    list_instruction_files as _list_instruction_files,
    read_text_file as _read_text_file,
    read_binary_file as _read_binary_file,
    write_text_file as _write_text_file,
    list_dir as _list_dir,
    resolve_run_dir as _resolve_run_dir,
)
from .jobs import Job, JobRegistry
from .templates import list_templates, template_details
from .utils import json_bytes as _json_bytes, safe_rel as _safe_rel


class FedernettHandler(BaseHTTPRequestHandler):
    server_version = "federnett/0.1"

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
        cfg = self._cfg()
        parsed = urlparse(self.path)
        path = parsed.path
        qs = parse_qs(parsed.query)
        if path == "/api/health":
            self._send_json({"status": "ok"})
            return
        if path == "/api/info":
            payload = {
                "root": _safe_rel(cfg.root, cfg.root),
                "root_abs": str(cfg.root.resolve()),
                "run_roots": [_safe_rel(p, cfg.root) for p in cfg.run_roots],
                "run_roots_abs": [str(p.resolve()) for p in cfg.run_roots],
                "site_root": _safe_rel(cfg.site_root, cfg.root),
                "site_root_abs": str(cfg.site_root.resolve()),
                "templates": list_templates(cfg.root),
            }
            self._send_json(payload)
            return
        if path == "/api/runs":
            runs = list_run_dirs(cfg.root, cfg.run_roots)
            # Return a plain list for UI compatibility.
            self._send_json(runs)
            return
        if path == "/api/templates":
            # Return a plain list for UI compatibility.
            self._send_json(list_templates(cfg.root))
            return
        if path.startswith("/api/templates/"):
            name = path.split("/", 3)[3]
            try:
                payload = template_details(cfg.root, name)
            except ValueError as exc:
                self._send_json({"error": str(exc)}, status=404)
                return
            self._send_json(payload)
            return
        if path == "/api/run-summary":
            run_rel = (qs.get("run") or [None])[0]
            try:
                payload = summarize_run(cfg.root, run_rel)
            except ValueError as exc:
                self._send_json({"error": str(exc)}, status=400)
                return
            self._send_json(payload)
            return
        if path == "/api/run-instructions":
            run_rel = (qs.get("run") or [None])[0]
            try:
                run_dir = _resolve_run_dir(cfg.root, run_rel)
                payload = _list_instruction_files(cfg.root, run_dir)
            except ValueError as exc:
                self._send_json({"error": str(exc)}, status=400)
                return
            self._send_json(payload)
            return
        if path == "/api/fs":
            raw_path = (qs.get("path") or [None])[0]
            try:
                payload = _list_dir(cfg.root, raw_path)
            except ValueError as exc:
                self._send_json({"error": str(exc)}, status=404)
                return
            self._send_json(payload)
            return
        if path == "/api/files":
            raw_path = (qs.get("path") or [None])[0]
            try:
                payload = _read_text_file(cfg.root, raw_path)
            except ValueError as exc:
                self._send_json({"error": str(exc)}, status=404)
                return
            self._send_json(payload)
            return
        if path == "/api/raw":
            raw_path = (qs.get("path") or [None])[0]
            try:
                file_path, data, content_type = _read_binary_file(cfg.root, raw_path)
            except ValueError as exc:
                self._send_json({"error": str(exc)}, status=404)
                return
            self._send_bytes(data, content_type)
            return
        if path.startswith("/raw/"):
            raw_path = unquote(path[len("/raw/"):])
            try:
                file_path, data, content_type = _read_binary_file(cfg.root, raw_path)
            except ValueError as exc:
                self._send_json({"error": str(exc)}, status=404)
                return
            self._send_bytes(data, content_type)
            return
        if path.startswith("/api/jobs/") and path.endswith("/status"):
            job_id = path.split("/")[3]
            job = self._jobs().get(job_id)
            if not job:
                self._send_json({"error": "job_not_found"}, status=404)
                return
            payload = {
                "job_id": job.job_id,
                "kind": job.kind,
                "status": job.status,
                "returncode": job.returncode,
                "command": job.command,
                "cwd": _safe_rel(job.cwd, cfg.root),
                "log_count": len(job.logs),
            }
            self._send_json(payload)
            return
        if path.startswith("/api/jobs/") and path.endswith("/events"):
            job_id = path.split("/")[3]
            job = self._jobs().get(job_id)
            if not job:
                self._send_json({"error": "job_not_found"}, status=404)
                return
            self._stream_job(job)
            return
        self._send_json({"error": "unknown_endpoint"}, status=404)

    def _handle_api_post(self) -> None:
        cfg = self._cfg()
        parsed = urlparse(self.path)
        path = parsed.path
        payload = self._read_json()
        try:
            if path == "/api/feather/start":
                cmd = _build_feather_cmd(cfg, payload)
                job = self._jobs().start("feather", cmd, cfg.root)
                self._send_json({"job_id": job.job_id})
                return
            if path == "/api/federlicht/start":
                cmd = _build_federlicht_cmd(cfg, payload)
                job = self._jobs().start("federlicht", cmd, cfg.root)
                self._send_json({"job_id": job.job_id})
                return
            if path == "/api/federlicht/generate_prompt":
                cmd = _build_generate_prompt_cmd(cfg, payload)
                job = self._jobs().start("generate_prompt", cmd, cfg.root)
                self._send_json({"job_id": job.job_id})
                return
            if path == "/api/files":
                raw_path = payload.get("path")
                content = payload.get("content")
                if not isinstance(content, str):
                    raise ValueError("content must be a string")
                result = _write_text_file(cfg.root, raw_path, content)
                self._send_json(result)
                return
            if path.startswith("/api/jobs/") and path.endswith("/kill"):
                job_id = path.split("/")[3]
                job = self._jobs().get(job_id)
                if not job:
                    self._send_json({"error": "job_not_found"}, status=404)
                    return
                killed = job.kill()
                self._send_json({"job_id": job_id, "killed": killed})
                return
        except ValueError as exc:
            self._send_json({"error": str(exc)}, status=400)
            return
        self._send_json({"error": "unknown_endpoint"}, status=404)

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
        description="Federnett: a friendly web studio for Feather and Federlicht.",
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
