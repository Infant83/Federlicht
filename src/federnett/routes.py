from __future__ import annotations

from pathlib import Path
from typing import Any, Callable, Protocol
from urllib.parse import parse_qs, unquote, urlparse

from .agent_profiles import delete_agent_profile, get_agent_profile, list_agent_profiles, save_agent_profile
from .commands import (
    _build_feather_cmd,
    _build_federlicht_cmd,
    _build_generate_prompt_cmd,
    _build_generate_template_cmd,
)
from .filesystem import (
    clear_help_history,
    list_dir as _list_dir,
    list_instruction_files as _list_instruction_files,
    list_run_dirs,
    list_run_logs,
    move_run_to_trash,
    read_binary_file as _read_binary_file,
    read_help_history,
    read_text_file as _read_text_file,
    resolve_run_dir as _resolve_run_dir,
    summarize_run,
    write_help_history,
    write_text_file as _write_text_file,
)
from .help_agent import answer_help_question
from .jobs import Job
from .templates import list_template_styles, list_templates, read_template_style, template_details
from .utils import resolve_under_root as _resolve_under_root, safe_rel as _safe_rel


class HandlerLike(Protocol):
    path: str
    headers: Any
    rfile: Any

    def _cfg(self): ...

    def _jobs(self): ...

    def _send_json(self, payload: Any, status: int = 200) -> None: ...

    def _send_bytes(self, data: bytes, content_type: str, status: int = 200) -> None: ...

    def _read_json(self) -> dict[str, Any]: ...

    def _stream_job(self, job: Job) -> None: ...


def _send_running_conflict(handler: HandlerLike, exc: RuntimeError) -> None:
    running = handler._jobs().find_running()
    handler._send_json(
        {
            "error": str(exc),
            "running_job_id": getattr(running, "job_id", None),
            "running_kind": getattr(running, "kind", None),
        },
        status=409,
    )


def _resolve_unique_output_path(root: Path, raw_output: str) -> dict[str, Any]:
    requested = _resolve_under_root(root, raw_output)
    if not requested:
        raise ValueError("output path is required")
    companion_suffixes = [".pdf"] if requested.suffix.lower() == ".tex" else []

    def has_companion_conflict(path: Path) -> bool:
        for suffix in companion_suffixes:
            if path.with_suffix(suffix).exists():
                return True
        return False

    suggested = requested
    if suggested.exists() or has_companion_conflict(suggested):
        parent = suggested.parent
        stem = suggested.stem
        suffix = suggested.suffix
        counter = 1
        while True:
            candidate = parent / f"{stem}_{counter}{suffix}"
            if candidate.exists() or has_companion_conflict(candidate):
                counter += 1
                continue
            suggested = candidate
            break

    return {
        "requested_output": _safe_rel(requested, root),
        "suggested_output": _safe_rel(suggested, root),
        "changed": requested != suggested,
        "requested_exists": requested.exists(),
    }


def handle_api_get(
    handler: HandlerLike,
    *,
    list_models: Callable[[], list[str]],
) -> None:
    cfg = handler._cfg()
    parsed = urlparse(handler.path)
    path = parsed.path
    qs = parse_qs(parsed.query)
    if path == "/api/health":
        handler._send_json({"status": "ok"})
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
        handler._send_json(payload)
        return
    if path == "/api/runs":
        runs = list_run_dirs(cfg.root, cfg.run_roots)
        handler._send_json(runs)
        return
    if path == "/api/templates":
        run_rel = (qs.get("run") or [None])[0]
        handler._send_json(list_templates(cfg.root, run=run_rel))
        return
    if path == "/api/template-styles":
        run_rel = (qs.get("run") or [None])[0]
        handler._send_json(list_template_styles(cfg.root, run=run_rel))
        return
    if path.startswith("/api/template-styles/"):
        name = unquote(path.split("/", 3)[3])
        try:
            payload = read_template_style(cfg.root, name)
        except ValueError as exc:
            handler._send_json({"error": str(exc)}, status=404)
            return
        handler._send_json(payload)
        return
    if path.startswith("/api/templates/"):
        name = unquote(path.split("/", 3)[3])
        try:
            payload = template_details(cfg.root, name)
        except ValueError as exc:
            handler._send_json({"error": str(exc)}, status=404)
            return
        handler._send_json(payload)
        return
    if path == "/api/template-preview":
        name = (qs.get("name") or [None])[0]
        if not name:
            handler._send_json({"error": "name is required"}, status=400)
            return
        try:
            detail = template_details(cfg.root, unquote(name))
        except ValueError as exc:
            handler._send_json({"error": str(exc)}, status=404)
            return
        css_name = detail.get("meta", {}).get("css")
        css_content = None
        extra_body_class = None
        if css_name:
            try:
                css_content = read_template_style(cfg.root, css_name).get("content")
                css_base = Path(css_name).stem
                if css_base:
                    extra_body_class = f"template-{css_base.lower()}"
            except Exception:
                css_content = None
        lines = [f"# Template Preview: {detail.get('name', name)}", ""]
        if detail.get("meta", {}).get("description"):
            lines.append(detail["meta"]["description"])
            lines.append("")
        if detail.get("writer_guidance"):
            lines.append("## Writer Notes")
            lines.extend([f"- {note}" for note in detail["writer_guidance"]])
            lines.append("")
        for section in detail.get("sections", []):
            lines.append(f"## {section}")
            guide = detail.get("guides", {}).get(section)
            if guide:
                lines.append(f"*Guidance:* {guide}")
            lines.append(
                "Sample paragraph to preview layout, spacing, and typography. "
                "Replace with real content when generating the report."
            )
            lines.append("")
        markdown = "\n".join(lines).strip() + "\n"
        try:
            from federlicht.render.html import markdown_to_html, wrap_html  # type: ignore
        except Exception:
            handler._send_json({"error": "preview renderer unavailable"}, status=500)
            return
        body_html = markdown_to_html(markdown)
        rendered = wrap_html(
            detail.get("name", name),
            body_html,
            template_name=detail.get("name", name),
            theme_css=css_content,
            extra_body_class=extra_body_class,
        )
        handler._send_json({"html": rendered})
        return
    if path == "/api/agent-profiles":
        handler._send_json({"profiles": list_agent_profiles(cfg.root)})
        return
    if path.startswith("/api/agent-profiles/"):
        profile_id = unquote(path.split("/", 3)[3])
        source = (qs.get("source") or [None])[0]
        try:
            payload = get_agent_profile(cfg.root, profile_id, source=source)
        except ValueError as exc:
            handler._send_json({"error": str(exc)}, status=404)
            return
        handler._send_json(payload)
        return
    if path == "/api/models":
        handler._send_json(list_models())
        return
    if path == "/api/federlicht/output-suggestion":
        raw_output = (qs.get("output") or [None])[0]
        run_rel = (qs.get("run") or [None])[0]
        output_value = str(raw_output or "").strip()
        if not output_value:
            handler._send_json({"error": "output is required"}, status=400)
            return
        if run_rel and "/" not in output_value and "\\" not in output_value:
            output_value = f"{str(run_rel).strip().strip('/').strip()}/{output_value}"
        try:
            payload = _resolve_unique_output_path(cfg.root, output_value)
        except ValueError as exc:
            handler._send_json({"error": str(exc)}, status=400)
            return
        handler._send_json(payload)
        return
    if path == "/api/run-summary":
        run_rel = (qs.get("run") or [None])[0]
        try:
            payload = summarize_run(cfg.root, run_rel)
        except ValueError as exc:
            handler._send_json({"error": str(exc)}, status=400)
            return
        handler._send_json(payload)
        return
    if path == "/api/run-logs":
        run_rel = (qs.get("run") or [None])[0]
        try:
            payload = list_run_logs(cfg.root, run_rel)
        except ValueError as exc:
            handler._send_json({"error": str(exc)}, status=400)
            return
        handler._send_json(payload)
        return
    if path == "/api/help/history":
        run_rel = (qs.get("run") or [None])[0]
        try:
            payload = read_help_history(cfg.root, run_rel)
        except ValueError as exc:
            handler._send_json({"error": str(exc)}, status=400)
            return
        handler._send_json(payload)
        return
    if path == "/api/run-instructions":
        run_rel = (qs.get("run") or [None])[0]
        try:
            run_dir = _resolve_run_dir(cfg.root, run_rel)
            payload = _list_instruction_files(cfg.root, run_dir)
        except ValueError as exc:
            handler._send_json({"error": str(exc)}, status=400)
            return
        handler._send_json(payload)
        return
    if path == "/api/fs":
        raw_path = (qs.get("path") or [None])[0]
        try:
            payload = _list_dir(cfg.root, raw_path)
        except ValueError as exc:
            handler._send_json({"error": str(exc)}, status=404)
            return
        handler._send_json(payload)
        return
    if path == "/api/files":
        raw_path = (qs.get("path") or [None])[0]
        try:
            payload = _read_text_file(cfg.root, raw_path)
        except ValueError as exc:
            handler._send_json({"error": str(exc)}, status=404)
            return
        handler._send_json(payload)
        return
    if path == "/api/raw":
        raw_path = (qs.get("path") or [None])[0]
        try:
            _file_path, data, content_type = _read_binary_file(cfg.root, raw_path)
        except ValueError as exc:
            handler._send_json({"error": str(exc)}, status=404)
            return
        handler._send_bytes(data, content_type)
        return
    if path.startswith("/raw/"):
        raw_path = unquote(path[len("/raw/") :])
        try:
            _file_path, data, content_type = _read_binary_file(cfg.root, raw_path)
        except ValueError as exc:
            handler._send_json({"error": str(exc)}, status=404)
            return
        handler._send_bytes(data, content_type)
        return
    if path.startswith("/api/jobs/") and path.endswith("/status"):
        job_id = path.split("/")[3]
        job = handler._jobs().get(job_id)
        if not job:
            handler._send_json({"error": "job_not_found"}, status=404)
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
        handler._send_json(payload)
        return
    if path.startswith("/api/jobs/") and path.endswith("/events"):
        job_id = path.split("/")[3]
        job = handler._jobs().get(job_id)
        if not job:
            handler._send_json({"error": "job_not_found"}, status=404)
            return
        handler._stream_job(job)
        return
    handler._send_json({"error": "unknown_endpoint"}, status=404)


def handle_api_post(
    handler: HandlerLike,
    *,
    render_template_preview: Callable[[Path, dict[str, Any]], str],
) -> None:
    cfg = handler._cfg()
    parsed = urlparse(handler.path)
    path = parsed.path
    qs = parse_qs(parsed.query)
    payload = handler._read_json()
    try:
        if path == "/api/feather/start":
            cmd = _build_feather_cmd(cfg, payload)
            try:
                job = handler._jobs().start("feather", cmd, cfg.root)
            except RuntimeError as exc:
                _send_running_conflict(handler, exc)
                return
            handler._send_json({"job_id": job.job_id})
            return
        if path == "/api/templates/generate":
            cmd = _build_generate_template_cmd(cfg, payload)
            try:
                job = handler._jobs().start("template", cmd, cfg.root)
            except RuntimeError as exc:
                _send_running_conflict(handler, exc)
                return
            handler._send_json({"job_id": job.job_id})
            return
        if path == "/api/federlicht/start":
            cmd = _build_federlicht_cmd(cfg, payload)
            try:
                job = handler._jobs().start("federlicht", cmd, cfg.root)
            except RuntimeError as exc:
                _send_running_conflict(handler, exc)
                return
            handler._send_json({"job_id": job.job_id})
            return
        if path == "/api/federlicht/generate_prompt":
            cmd = _build_generate_prompt_cmd(cfg, payload)
            try:
                job = handler._jobs().start("generate_prompt", cmd, cfg.root)
            except RuntimeError as exc:
                _send_running_conflict(handler, exc)
                return
            handler._send_json({"job_id": job.job_id})
            return
        if path == "/api/files":
            raw_path = payload.get("path")
            content = payload.get("content")
            if not isinstance(content, str):
                raise ValueError("content must be a string")
            result = _write_text_file(cfg.root, raw_path, content)
            handler._send_json(result)
            return
        if path == "/api/runs/trash":
            run_rel = payload.get("run")
            result = move_run_to_trash(cfg.root, run_rel, cfg.run_roots)
            handler._send_json(result)
            return
        if path == "/api/template-preview":
            html = render_template_preview(cfg.root, payload)
            handler._send_json({"html": html})
            return
        if path == "/api/agent-profiles/save":
            profile = payload.get("profile")
            if not isinstance(profile, dict):
                raise ValueError("profile must be an object")
            memory_text = payload.get("memory_text")
            store = payload.get("store") or "site"
            result = save_agent_profile(cfg.root, profile, memory_text=memory_text, store=store)
            handler._send_json(result)
            return
        if path == "/api/agent-profiles/delete":
            profile_id = payload.get("id")
            result = delete_agent_profile(cfg.root, profile_id)
            handler._send_json(result)
            return
        if path == "/api/upload":
            name = (qs.get("name") or ["upload.bin"])[0]
            safe_name = Path(name).name or "upload.bin"
            target_dir = cfg.root / "site" / "uploads"
            target_dir.mkdir(parents=True, exist_ok=True)
            target_path = target_dir / safe_name
            length = int(handler.headers.get("Content-Length", "0") or "0")
            if length <= 0:
                raise ValueError("empty upload")
            data = handler.rfile.read(length)
            target_path.write_bytes(data)
            handler._send_json(
                {
                    "name": safe_name,
                    "path": _safe_rel(target_path, cfg.root),
                    "abs_path": str(target_path.resolve()),
                    "size": target_path.stat().st_size,
                }
            )
            return
        if path == "/api/help/ask":
            question = payload.get("question")
            if not isinstance(question, str) or not question.strip():
                raise ValueError("question must be a non-empty string")
            model = payload.get("model")
            model_value = str(model).strip() if isinstance(model, str) else None
            strict_model_raw = payload.get("strict_model")
            strict_model_value = bool(strict_model_raw) if isinstance(strict_model_raw, bool) else False
            run_rel = payload.get("run")
            run_value = str(run_rel).strip() if isinstance(run_rel, str) else None
            history_raw = payload.get("history")
            history_value = history_raw if isinstance(history_raw, list) else None
            max_sources_raw = payload.get("max_sources")
            try:
                max_sources = int(max_sources_raw) if max_sources_raw is not None else 8
            except Exception:
                max_sources = 8
            result = answer_help_question(
                cfg.root,
                question,
                model=model_value,
                strict_model=strict_model_value,
                max_sources=max_sources,
                history=history_value,
                run_rel=run_value,
            )
            handler._send_json(result)
            return
        if path == "/api/help/history":
            run_rel = payload.get("run")
            run_value = str(run_rel).strip() if isinstance(run_rel, str) else None
            items = payload.get("items")
            if not isinstance(items, list):
                raise ValueError("items must be an array")
            result = write_help_history(cfg.root, run_value, items)
            handler._send_json(result)
            return
        if path == "/api/help/history/clear":
            run_rel = payload.get("run")
            run_value = str(run_rel).strip() if isinstance(run_rel, str) else None
            result = clear_help_history(cfg.root, run_value)
            handler._send_json(result)
            return
        if path.startswith("/api/jobs/") and path.endswith("/kill"):
            job_id = path.split("/")[3]
            job = handler._jobs().get(job_id)
            if not job:
                handler._send_json({"error": "job_not_found"}, status=404)
                return
            killed = job.kill()
            handler._send_json({"job_id": job_id, "killed": killed})
            return
    except ValueError as exc:
        handler._send_json({"error": str(exc)}, status=400)
        return
    handler._send_json({"error": "unknown_endpoint"}, status=404)
