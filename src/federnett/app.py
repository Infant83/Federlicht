from __future__ import annotations

import argparse
import json
import mimetypes
import os
import shlex
import socket
import subprocess
import sys
import threading
import time
import uuid
import webbrowser
from datetime import datetime, timezone
from dataclasses import dataclass, field
from http import HTTPStatus
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
from pathlib import Path
from typing import Any, Iterable, Optional
from urllib.parse import parse_qs, urlparse
import traceback


DEFAULT_RUN_ROOTS = ("site/runs", "examples/runs", "runs")
DEFAULT_STATIC_DIR = "site/federnett"
DEFAULT_SITE_ROOT = "site"
INSTRUCTION_EXTS = {".txt", ".md", ".text", ".prompt", ".instruct", ".instruction"}
SUMMARY_FILE_LIMIT = 40


def _now_ts() -> float:
    return time.time()


def _json_bytes(payload: Any) -> bytes:
    return json.dumps(payload, ensure_ascii=False).encode("utf-8")


def _iso_ts(ts: float | None) -> str:
    if not ts:
        return ""
    try:
        return datetime.fromtimestamp(ts, tz=timezone.utc).isoformat()
    except Exception:
        return ""


def _safe_rel(path: Path, root: Path) -> str:
    try:
        return path.relative_to(root).as_posix()
    except Exception:
        return path.as_posix()


def _is_instruction_file(path: Path) -> bool:
    if not path.is_file():
        return False
    if path.name.startswith("."):
        return False
    suffix = path.suffix.lower()
    if suffix in INSTRUCTION_EXTS:
        return True
    return suffix == ""


def _is_run_dir(path: Path) -> bool:
    if not path.is_dir():
        return False
    markers = ("archive", "report_notes", "instruction")
    return any((path / marker).exists() for marker in markers)


def list_run_dirs(root: Path, run_roots: Iterable[Path]) -> list[dict[str, Any]]:
    runs: dict[str, dict[str, Any]] = {}
    for run_root in run_roots:
        if not run_root.exists():
            continue
        for candidate in run_root.iterdir():
            if not candidate.is_dir():
                continue
            if not _is_run_dir(candidate):
                continue
            key = str(candidate.resolve())
            report_files = sorted(candidate.glob("report_full*.html"))
            latest_report = (
                max(report_files, key=lambda p: p.stat().st_mtime) if report_files else None
            )
            updated_ts = latest_report.stat().st_mtime if latest_report else candidate.stat().st_mtime
            run_rel = _safe_rel(candidate, root)
            latest_rel = _safe_rel(latest_report, root) if latest_report else None
            runs[key] = {
                # Legacy fields (kept for compatibility).
                "name": candidate.name,
                "path": run_rel,
                "abs_path": str(candidate.resolve()),
                "latest_report": latest_rel,
                "has_report": bool(latest_report),
                # Normalized fields used by the UI.
                "run_name": candidate.name,
                "run_rel": run_rel,
                "run_abs": str(candidate.resolve()),
                "run_root_rel": _safe_rel(run_root, root),
                "run_root_abs": str(run_root.resolve()),
                "latest_report_rel": latest_rel,
                "latest_report_name": latest_report.name if latest_report else "",
                "report_count": len(report_files),
                "report_files": [_safe_rel(p, root) for p in report_files],
                "updated_at": _iso_ts(updated_ts),
            }
    items = sorted(runs.values(), key=lambda item: item["run_rel"])
    return items


def list_templates(root: Path) -> list[str]:
    templates_dir = root / "src" / "federlicht" / "templates"
    if not templates_dir.exists():
        return []
    names = sorted(p.stem for p in templates_dir.glob("*.md"))
    return names


def _resolve_under_root(root: Path, raw: str | None) -> Optional[Path]:
    if not raw:
        return None
    candidate = Path(raw).expanduser()
    if not candidate.is_absolute():
        candidate = (root / candidate).resolve()
    else:
        candidate = candidate.resolve()
    try:
        candidate.relative_to(root)
    except Exception as exc:
        raise ValueError(f"Path escapes root: {raw}") from exc
    return candidate


def _resolve_run_dir(root: Path, run_rel: str | None) -> Path:
    run_dir = _resolve_under_root(root, run_rel)
    if not run_dir or not run_dir.exists() or not run_dir.is_dir():
        raise ValueError(f"Run folder not found: {run_rel}")
    if not _is_run_dir(run_dir):
        raise ValueError(f"Not a run folder: {run_rel}")
    return run_dir


def _list_run_instruction_files(root: Path, run_dir: Path) -> list[dict[str, Any]]:
    items: list[dict[str, Any]] = []
    run_instruction_dir = run_dir / "instruction"
    if not run_instruction_dir.exists():
        return items
    for path in sorted(run_instruction_dir.rglob("*")):
        if not _is_instruction_file(path):
            continue
        stat = path.stat()
        items.append(
            {
                "name": path.name,
                "path": _safe_rel(path, root),
                "updated_at": _iso_ts(stat.st_mtime),
                "size": stat.st_size,
                "scope": "run",
                "dir_rel": _safe_rel(run_instruction_dir, root),
            }
        )
    return items


def _instruction_dirs(root: Path, run_dir: Path) -> list[tuple[str, Path]]:
    dirs: list[tuple[str, Path]] = []
    dirs.append(("run", run_dir / "instruction"))
    dirs.append(("workspace", root / "instruction"))
    dirs.append(("examples", root / "examples" / "instructions"))
    seen: set[str] = set()
    unique_dirs: list[tuple[str, Path]] = []
    for scope, path in dirs:
        key = str(path.resolve()) if path.exists() else str(path)
        if key in seen:
            continue
        seen.add(key)
        unique_dirs.append((scope, path))
    return unique_dirs


def _list_instruction_files(root: Path, run_dir: Path) -> list[dict[str, Any]]:
    items: list[dict[str, Any]] = []
    for scope, instruction_dir in _instruction_dirs(root, run_dir):
        if not instruction_dir.exists():
            continue
        dir_rel = _safe_rel(instruction_dir, root)
        run_rel = _safe_rel(run_dir, root)
        for path in sorted(instruction_dir.rglob("*")):
            if not _is_instruction_file(path):
                continue
            stat = path.stat()
            items.append(
                {
                    "name": path.name,
                    "path": _safe_rel(path, root),
                    "updated_at": _iso_ts(stat.st_mtime),
                    "size": stat.st_size,
                    "scope": scope,
                    "dir_rel": dir_rel,
                    "run_rel": run_rel if scope == "run" else "",
                }
            )
    scope_order = {"run": 0, "workspace": 1, "examples": 2}
    items.sort(
        key=lambda item: (
            scope_order.get(str(item.get("scope", "")), 99),
            str(item.get("path", "")),
        )
    )
    return items


def summarize_run(root: Path, run_rel: str | None) -> dict[str, Any]:
    run_dir = _resolve_run_dir(root, run_rel)
    pdfs = sorted(run_dir.glob("archive/**/*.pdf"))
    texts = sorted(run_dir.glob("archive/**/*.txt"))
    jsonls = sorted(run_dir.glob("archive/**/*.jsonl"))
    index_mds = sorted(run_dir.glob("archive/*-index.md"))
    reports = sorted(run_dir.glob("report_full*.html"))
    latest_report = max(reports, key=lambda p: p.stat().st_mtime) if reports else None
    updated_ts = max(
        [run_dir.stat().st_mtime]
        + [p.stat().st_mtime for p in reports]
        + [p.stat().st_mtime for p in index_mds],
        default=run_dir.stat().st_mtime,
    )
    instructions = _list_run_instruction_files(root, run_dir)
    summary_lines = [
        f"Archive PDFs: {len(pdfs)}",
        f"Archive texts: {len(texts)}",
        f"Archive indices (jsonl): {len(jsonls)}",
        f"Reports: {len(reports)}",
        f"Instructions: {len(instructions)}",
    ]
    pdf_files = [_safe_rel(p, root) for p in pdfs[:SUMMARY_FILE_LIMIT]]
    text_files = [_safe_rel(p, root) for p in texts[:SUMMARY_FILE_LIMIT]]
    jsonl_files = [_safe_rel(p, root) for p in jsonls[:SUMMARY_FILE_LIMIT]]
    return {
        "run_name": run_dir.name,
        "run_rel": _safe_rel(run_dir, root),
        "run_abs": str(run_dir.resolve()),
        "counts": {
            "pdf": len(pdfs),
            "text": len(texts),
            "jsonl": len(jsonls),
            "index_md": len(index_mds),
            "report": len(reports),
            "instruction": len(instructions),
        },
        "latest_report_rel": _safe_rel(latest_report, root) if latest_report else None,
        "latest_report_name": latest_report.name if latest_report else "",
        "report_files": [_safe_rel(p, root) for p in reports],
        "index_files": [_safe_rel(p, root) for p in index_mds],
        "instruction_files": instructions,
        "pdf_files": pdf_files,
        "text_files": text_files,
        "jsonl_files": jsonl_files,
        "updated_at": _iso_ts(updated_ts),
        "summary_lines": summary_lines,
    }


def _read_text_file(root: Path, raw_path: str | None) -> dict[str, Any]:
    path = _resolve_under_root(root, raw_path)
    if not path or not path.exists() or not path.is_file():
        raise ValueError(f"File not found: {raw_path}")
    stat = path.stat()
    content = path.read_text(encoding="utf-8", errors="replace")
    return {
        "path": _safe_rel(path, root),
        "abs_path": str(path.resolve()),
        "size": stat.st_size,
        "updated_at": _iso_ts(stat.st_mtime),
        "content": content,
    }


def _write_text_file(root: Path, raw_path: str | None, content: str) -> dict[str, Any]:
    path = _resolve_under_root(root, raw_path)
    if not path:
        raise ValueError("Path is required.")
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(content, encoding="utf-8")
    stat = path.stat()
    return {
        "path": _safe_rel(path, root),
        "abs_path": str(path.resolve()),
        "size": stat.st_size,
        "updated_at": _iso_ts(stat.st_mtime),
    }


def _parse_template_frontmatter(path: Path) -> dict[str, Any]:
    text = path.read_text(encoding="utf-8", errors="replace")
    lines = text.splitlines()
    if not lines or lines[0].strip() != "---":
        return {"meta": {}, "sections": [], "guides": {}, "writer_guidance": []}
    end_idx = None
    for i in range(1, len(lines)):
        if lines[i].strip() == "---":
            end_idx = i
            break
    if end_idx is None:
        return {"meta": {}, "sections": [], "guides": {}, "writer_guidance": []}
    meta: dict[str, str] = {}
    sections: list[str] = []
    guides: dict[str, str] = {}
    writer_guidance: list[str] = []
    for raw in lines[1:end_idx]:
        line = raw.strip()
        if not line or line.startswith("#") or ":" not in line:
            continue
        key, value = line.split(":", 1)
        key = key.strip()
        value = value.strip()
        if key == "section":
            sections.append(value)
        elif key.startswith("guide "):
            guides[key[len("guide ") :].strip()] = value
        elif key == "writer_guidance":
            writer_guidance.append(value)
        else:
            meta[key] = value
    return {
        "meta": meta,
        "sections": sections,
        "guides": guides,
        "writer_guidance": writer_guidance,
    }


def template_details(root: Path, name: str) -> dict[str, Any]:
    path = root / "src" / "federlicht" / "templates" / f"{name}.md"
    if not path.exists():
        raise ValueError(f"Template not found: {name}")
    parsed = _parse_template_frontmatter(path)
    return {
        "name": name,
        "path": _safe_rel(path, root),
        "meta": parsed["meta"],
        "sections": parsed["sections"],
        "guides": parsed["guides"],
        "writer_guidance": parsed["writer_guidance"],
    }


def _parse_bool(payload: dict[str, Any], key: str) -> Optional[bool]:
    if key not in payload:
        return None
    value = payload.get(key)
    if isinstance(value, bool):
        return value
    if isinstance(value, str):
        lowered = value.strip().lower()
        if lowered in {"1", "true", "yes", "on"}:
            return True
        if lowered in {"0", "false", "no", "off"}:
            return False
    return None


def _extra_args(extra: str | None) -> list[str]:
    if not extra:
        return []
    try:
        return shlex.split(extra)
    except Exception:
        return []


def _expand_env_reference(value: str | None) -> str | None:
    if not value:
        return value
    raw = value.strip()
    name = None
    if raw.startswith("${") and raw.endswith("}"):
        name = raw[2:-1].strip()
    elif raw.startswith("$") and len(raw) > 1:
        name = raw[1:].strip()
    elif raw.startswith("%") and raw.endswith("%") and len(raw) > 2:
        name = raw[1:-1].strip()
    if name:
        expanded = os.environ.get(name)
        if expanded:
            return expanded
    return value


@dataclass
class Job:
    job_id: str
    kind: str
    command: list[str]
    cwd: Path
    created_at: float = field(default_factory=_now_ts)
    status: str = "running"
    returncode: Optional[int] = None
    logs: list[dict[str, Any]] = field(default_factory=list)
    _lock: threading.Lock = field(default_factory=threading.Lock)
    _cond: threading.Condition = field(init=False)
    _proc: Optional[subprocess.Popen[str]] = None

    def __post_init__(self) -> None:
        self._cond = threading.Condition(self._lock)

    def attach(self, proc: subprocess.Popen[str]) -> None:
        self._proc = proc

    def append_log(self, text: str, stream: str = "stdout") -> None:
        if not text:
            return
        with self._cond:
            entry = {
                "index": len(self.logs),
                "ts": _now_ts(),
                "stream": stream,
                "text": text.rstrip("\n"),
            }
            self.logs.append(entry)
            self._cond.notify_all()

    def mark_done(self, returncode: int) -> None:
        with self._cond:
            self.returncode = returncode
            self.status = "done" if returncode == 0 else "error"
            self._cond.notify_all()

    def kill(self) -> bool:
        proc = self._proc
        if not proc or proc.poll() is not None:
            return False
        proc.kill()
        with self._cond:
            self.status = "killed"
            self._cond.notify_all()
        return True

    def wait_for_logs(self, last_index: int, timeout: float = 1.0) -> tuple[list[dict[str, Any]], bool]:
        with self._cond:
            if last_index >= len(self.logs) and self.status == "running":
                self._cond.wait(timeout=timeout)
            new_logs = self.logs[last_index:]
            done = self.status != "running"
            return new_logs, done


class JobRegistry:
    def __init__(self) -> None:
        self._jobs: dict[str, Job] = {}
        self._lock = threading.Lock()

    def get(self, job_id: str) -> Optional[Job]:
        with self._lock:
            return self._jobs.get(job_id)

    def start(self, kind: str, command: list[str], cwd: Path) -> Job:
        job_id = uuid.uuid4().hex[:12]
        job = Job(job_id=job_id, kind=kind, command=command, cwd=cwd)
        with self._lock:
            self._jobs[job_id] = job
        self._launch(job)
        return job

    def _launch(self, job: Job) -> None:
        env = os.environ.copy()
        try:
            src_path = str((job.cwd / "src").resolve())
            current = env.get("PYTHONPATH", "")
            if current:
                if src_path not in current.split(os.pathsep):
                    env["PYTHONPATH"] = os.pathsep.join([src_path, current])
            else:
                env["PYTHONPATH"] = src_path
        except Exception:
            # If path resolution fails, fall back to default env.
            env = os.environ.copy()
        proc = subprocess.Popen(
            job.command,
            cwd=str(job.cwd),
            env=env,
            stdout=subprocess.PIPE,
            stderr=subprocess.STDOUT,
            text=True,
            encoding="utf-8",
            errors="replace",
            bufsize=1,
        )
        job.attach(proc)
        job.append_log(f"$ {' '.join(job.command)}", stream="meta")

        def reader() -> None:
            assert proc.stdout is not None
            try:
                for line in proc.stdout:
                    job.append_log(line)
            finally:
                rc = proc.wait()
                job.mark_done(rc)

        threading.Thread(target=reader, name=f"federnett-job-{job.job_id}", daemon=True).start()


@dataclass
class FedernettConfig:
    root: Path
    static_dir: Path
    run_roots: list[Path]
    site_root: Path


def _build_feather_cmd(cfg: FedernettConfig, payload: dict[str, Any]) -> list[str]:
    input_path = payload.get("input")
    query = payload.get("query")
    output_root = payload.get("output")
    if not output_root:
        raise ValueError("Feather requires an output path.")
    if not input_path and not query:
        raise ValueError("Feather requires either input or query.")

    cmd: list[str] = [sys.executable, "-m", "feather"]
    if input_path:
        resolved_input = _resolve_under_root(cfg.root, str(input_path))
        cmd.extend(["--input", str(resolved_input)])
    elif query:
        cmd.extend(["--query", str(query)])

    resolved_output = _resolve_under_root(cfg.root, str(output_root))
    cmd.extend(["--output", str(resolved_output)])

    lang = payload.get("lang")
    if lang:
        cmd.extend(["--lang", str(lang)])
    days = payload.get("days")
    if days:
        cmd.extend(["--days", str(days)])
    max_results = payload.get("max_results")
    if max_results:
        cmd.extend(["--max-results", str(max_results)])

    if _parse_bool(payload, "download_pdf"):
        cmd.append("--download-pdf")
    if _parse_bool(payload, "arxiv_src"):
        cmd.append("--arxiv-src")
    if _parse_bool(payload, "openalex"):
        cmd.append("--openalex")
    if _parse_bool(payload, "youtube"):
        cmd.append("--youtube")
    if _parse_bool(payload, "yt_transcript"):
        cmd.append("--yt-transcript")
    yt_order = payload.get("yt_order")
    if yt_order:
        cmd.extend(["--yt-order", str(yt_order)])
    if _parse_bool(payload, "update_run"):
        cmd.append("--update-run")
    if _parse_bool(payload, "no_stdout_log"):
        cmd.append("--no-stdout-log")
    if _parse_bool(payload, "no_citations"):
        cmd.append("--no-citations")

    cmd.extend(_extra_args(payload.get("extra_args")))
    return cmd


def _build_federlicht_cmd(cfg: FedernettConfig, payload: dict[str, Any]) -> list[str]:
    run_dir = payload.get("run")
    if not run_dir:
        raise ValueError("Federlicht requires a run path.")
    resolved_run = _resolve_under_root(cfg.root, str(run_dir))

    cmd: list[str] = [sys.executable, "-m", "federlicht.report", "--run", str(resolved_run)]
    output_path = payload.get("output")
    if output_path:
        resolved_output = _resolve_under_root(cfg.root, str(output_path))
        cmd.extend(["--output", str(resolved_output)])
    template = payload.get("template")
    if template:
        cmd.extend(["--template", str(template)])
    lang = payload.get("lang")
    if lang:
        cmd.extend(["--lang", str(lang)])
    depth = payload.get("depth")
    if depth:
        cmd.extend(["--depth", str(depth)])
    prompt = payload.get("prompt")
    if prompt:
        cmd.extend(["--prompt", str(prompt)])
    prompt_file = payload.get("prompt_file")
    if prompt_file:
        resolved_prompt = _resolve_under_root(cfg.root, str(prompt_file))
        cmd.extend(["--prompt-file", str(resolved_prompt)])
    stages = payload.get("stages")
    if stages:
        cmd.extend(["--stages", str(stages)])
    skip_stages = payload.get("skip_stages")
    if skip_stages:
        cmd.extend(["--skip-stages", str(skip_stages)])
    model = _expand_env_reference(payload.get("model"))
    if model:
        cmd.extend(["--model", str(model)])
    check_model = _expand_env_reference(payload.get("check_model"))
    if check_model:
        cmd.extend(["--check-model", str(check_model)])
    model_vision = _expand_env_reference(payload.get("model_vision"))
    if model_vision:
        cmd.extend(["--model-vision", str(model_vision)])
    quality_iterations = payload.get("quality_iterations")
    if quality_iterations is not None and str(quality_iterations) != "":
        cmd.extend(["--quality-iterations", str(quality_iterations)])
    quality_strategy = payload.get("quality_strategy")
    if quality_strategy:
        cmd.extend(["--quality-strategy", str(quality_strategy)])
    max_chars = payload.get("max_chars")
    if max_chars:
        cmd.extend(["--max-chars", str(max_chars)])
    max_pdf_pages = payload.get("max_pdf_pages")
    if max_pdf_pages is not None and str(max_pdf_pages) != "":
        cmd.extend(["--max-pdf-pages", str(max_pdf_pages)])
    tags = payload.get("tags")
    if tags:
        cmd.extend(["--tags", str(tags)])
    if _parse_bool(payload, "no_tags"):
        cmd.append("--no-tags")
    if _parse_bool(payload, "figures"):
        cmd.append("--figures")
    if _parse_bool(payload, "no_figures"):
        cmd.append("--no-figures")
    figures_mode = payload.get("figures_mode")
    if figures_mode:
        cmd.extend(["--figures-mode", str(figures_mode)])
    figures_select = payload.get("figures_select")
    if figures_select:
        resolved_select = _resolve_under_root(cfg.root, str(figures_select))
        cmd.extend(["--figures-select", str(resolved_select)])
    if _parse_bool(payload, "web_search"):
        cmd.append("--web-search")
    site_output = payload.get("site_output")
    if site_output:
        resolved_site = _resolve_under_root(cfg.root, str(site_output))
        cmd.extend(["--site-output", str(resolved_site)])

    cmd.extend(_extra_args(payload.get("extra_args")))
    return cmd


def _build_generate_prompt_cmd(cfg: FedernettConfig, payload: dict[str, Any]) -> list[str]:
    run_dir = payload.get("run")
    if not run_dir:
        raise ValueError("Prompt generation requires a run path.")
    resolved_run = _resolve_under_root(cfg.root, str(run_dir))

    cmd: list[str] = [
        sys.executable,
        "-m",
        "federlicht.report",
        "--run",
        str(resolved_run),
        "--generate-prompt",
    ]
    output_path = payload.get("output")
    if output_path:
        resolved_output = _resolve_under_root(cfg.root, str(output_path))
        cmd.extend(["--output", str(resolved_output)])
    template = payload.get("template")
    if template:
        cmd.extend(["--template", str(template)])
    depth = payload.get("depth")
    if depth:
        cmd.extend(["--depth", str(depth)])
    model = _expand_env_reference(payload.get("model"))
    if model:
        cmd.extend(["--model", str(model)])
    cmd.extend(_extra_args(payload.get("extra_args")))
    return cmd


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
            if self.path.startswith("/api/"):
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
        if path == "/api/files":
            raw_path = (qs.get("path") or [None])[0]
            try:
                payload = _read_text_file(cfg.root, raw_path)
            except ValueError as exc:
                self._send_json({"error": str(exc)}, status=404)
                return
            self._send_json(payload)
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
