from __future__ import annotations

import json
import mimetypes
from pathlib import Path
import shutil
from typing import Any, Iterable, Optional

from .constants import INSTRUCTION_EXTS, SUMMARY_FILE_LIMIT
from .utils import iso_ts, resolve_under_root, safe_rel


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


def resolve_run_dir(root: Path, run_rel: str | None) -> Path:
    run_dir = resolve_under_root(root, run_rel)
    if not run_dir or not run_dir.exists() or not run_dir.is_dir():
        raise ValueError(f"Run folder not found: {run_rel}")
    if not _is_run_dir(run_dir):
        raise ValueError(f"Not a run folder: {run_rel}")
    return run_dir


def list_run_dirs(root: Path, run_roots: Iterable[Path]) -> list[dict[str, Any]]:
    runs: dict[str, dict[str, Any]] = {}
    for run_root in run_roots:
        if not run_root.exists():
            continue
        for candidate in run_root.iterdir():
            if not candidate.is_dir():
                continue
            if candidate.name.startswith("."):
                continue
            if not _is_run_dir(candidate):
                continue
            key = str(candidate.resolve())
            report_files = sorted(candidate.glob("report_full*.html"))
            latest_report = (
                max(report_files, key=lambda p: p.stat().st_mtime) if report_files else None
            )
            updated_ts = latest_report.stat().st_mtime if latest_report else candidate.stat().st_mtime
            run_rel = safe_rel(candidate, root)
            latest_rel = safe_rel(latest_report, root) if latest_report else None
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
                "run_root_rel": safe_rel(run_root, root),
                "run_root_abs": str(run_root.resolve()),
                "latest_report_rel": latest_rel,
                "latest_report_name": latest_report.name if latest_report else "",
                "report_count": len(report_files),
                "report_files": [safe_rel(p, root) for p in report_files],
                "updated_at": iso_ts(updated_ts),
            }
    items = sorted(runs.values(), key=lambda item: item["run_rel"])
    return items


def _find_run_root(run_dir: Path, run_roots: Iterable[Path]) -> Optional[Path]:
    matched: Optional[Path] = None
    for root in run_roots:
        try:
            run_dir.relative_to(root)
        except ValueError:
            continue
        if matched is None or len(str(root)) > len(str(matched)):
            matched = root
    return matched


def move_run_to_trash(root: Path, run_rel: str | None, run_roots: Iterable[Path]) -> dict[str, Any]:
    run_dir = resolve_run_dir(root, run_rel)
    run_root = _find_run_root(run_dir, run_roots)
    if not run_root:
        raise ValueError("Run folder is not under a configured run root.")
    trash_root = run_root / ".trash"
    trash_root.mkdir(parents=True, exist_ok=True)
    base_name = run_dir.name
    dest = trash_root / base_name
    counter = 1
    while dest.exists():
        dest = trash_root / f"{base_name}_{counter}"
        counter += 1
    shutil.move(str(run_dir), str(dest))
    return {
        "run_rel": safe_rel(run_dir, root),
        "trash_rel": safe_rel(dest, root),
        "trash_abs": str(dest.resolve()),
        "trashed": True,
    }


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
                "path": safe_rel(path, root),
                "updated_at": iso_ts(stat.st_mtime),
                "size": stat.st_size,
                "scope": "run",
                "dir_rel": safe_rel(run_instruction_dir, root),
            }
        )
    return items


def _instruction_dirs(root: Path, run_dir: Path) -> list[tuple[str, Path]]:
    dirs: list[tuple[str, Path]] = []
    dirs.append(("run", run_dir / "instruction"))
    dirs.append(("workspace", root / "instruction"))
    seen: set[str] = set()
    unique_dirs: list[tuple[str, Path]] = []
    for scope, path in dirs:
        key = str(path.resolve()) if path.exists() else str(path)
        if key in seen:
            continue
        seen.add(key)
        unique_dirs.append((scope, path))
    return unique_dirs


def list_instruction_files(root: Path, run_dir: Path) -> list[dict[str, Any]]:
    items: list[dict[str, Any]] = []
    for scope, instruction_dir in _instruction_dirs(root, run_dir):
        if not instruction_dir.exists():
            continue
        dir_rel = safe_rel(instruction_dir, root)
        run_rel = safe_rel(run_dir, root)
        for path in sorted(instruction_dir.rglob("*")):
            if not _is_instruction_file(path):
                continue
            stat = path.stat()
            items.append(
                {
                    "name": path.name,
                    "path": safe_rel(path, root),
                    "updated_at": iso_ts(stat.st_mtime),
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
    run_dir = resolve_run_dir(root, run_rel)
    pdfs = sorted(run_dir.glob("archive/**/*.pdf"))
    texts = sorted(run_dir.glob("archive/**/*.txt"))
    jsonls = sorted(run_dir.glob("archive/**/*.jsonl"))
    pptxs = sorted(run_dir.glob("archive/**/*.pptx"))
    extracts = sorted((run_dir / "archive" / "tavily_extract").glob("*.txt"))
    log_paths = sorted(
        set(
            list(run_dir.glob("_log*.txt"))
            + list((run_dir / "archive").glob("_log*.txt"))
            + list(run_dir.glob("_feather_log*.txt"))
            + list(run_dir.glob("_federlicht_log*.txt"))
        )
    )
    report_meta_path = run_dir / "report_notes" / "report_meta.json"
    report_meta: dict[str, Any] = {}
    if report_meta_path.exists():
        try:
            report_meta = json.loads(report_meta_path.read_text(encoding="utf-8"))
        except Exception:
            report_meta = {}
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
        f"Archive PPTX: {len(pptxs)}",
        f"Archive texts: {len(texts)}",
        f"Web extracts: {len(extracts)}",
        f"Logs: {len(log_paths)}",
        f"Reports: {len(reports)}",
        f"Instructions: {len(instructions)}",
    ]
    pdf_files = [safe_rel(p, root) for p in pdfs[:SUMMARY_FILE_LIMIT]]
    text_files = [
        safe_rel(p, root)
        for p in texts[:SUMMARY_FILE_LIMIT]
        if not p.name.startswith("_log")
    ]
    jsonl_files = [safe_rel(p, root) for p in jsonls[:SUMMARY_FILE_LIMIT]]
    pptx_files = [safe_rel(p, root) for p in pptxs[:SUMMARY_FILE_LIMIT]]
    extract_files = [safe_rel(p, root) for p in extracts[:SUMMARY_FILE_LIMIT]]
    log_files = [safe_rel(p, root) for p in log_paths[:SUMMARY_FILE_LIMIT]]
    return {
        "run_name": run_dir.name,
        "run_rel": safe_rel(run_dir, root),
        "run_abs": str(run_dir.resolve()),
        "counts": {
            "pdf": len(pdfs),
            "text": len(texts),
            "jsonl": len(jsonls),
            "pptx": len(pptxs),
            "extracts": len(extracts),
            "logs": len(log_paths),
            "index_md": len(index_mds),
            "report": len(reports),
            "instruction": len(instructions),
        },
        "latest_report_rel": safe_rel(latest_report, root) if latest_report else None,
        "latest_report_name": latest_report.name if latest_report else "",
        "report_files": [safe_rel(p, root) for p in reports],
        "index_files": [safe_rel(p, root) for p in index_mds],
        "instruction_files": instructions,
        "pdf_files": pdf_files,
        "pptx_files": pptx_files,
        "extract_files": extract_files,
        "log_files": log_files,
        "text_files": text_files,
        "jsonl_files": jsonl_files,
        "updated_at": iso_ts(updated_ts),
        "summary_lines": summary_lines,
        "report_meta": {
            "template": report_meta.get("template"),
            "free_format": report_meta.get("free_format"),
            "template_rigidity": report_meta.get("template_rigidity"),
            "template_adjust_mode": report_meta.get("template_adjust_mode"),
            "repair_mode": report_meta.get("repair_mode"),
            "language": report_meta.get("language"),
            "model": report_meta.get("model"),
            "temperature": report_meta.get("temperature"),
            "temperature_level": report_meta.get("temperature_level"),
            "max_chars": report_meta.get("max_chars"),
            "max_tool_chars": report_meta.get("max_tool_chars"),
            "max_pdf_pages": report_meta.get("max_pdf_pages"),
            "progress_chars": report_meta.get("progress_chars"),
            "quality_model": report_meta.get("quality_model"),
            "model_vision": report_meta.get("model_vision"),
            "output_format": report_meta.get("output_format"),
            "agent_profile": report_meta.get("agent_profile"),
        },
    }


def read_text_file(root: Path, raw_path: str | None) -> dict[str, Any]:
    path = resolve_under_root(root, raw_path)
    if not path or not path.exists() or not path.is_file():
        raise ValueError(f"File not found: {raw_path}")
    stat = path.stat()
    content = path.read_text(encoding="utf-8", errors="replace")
    return {
        "path": safe_rel(path, root),
        "abs_path": str(path.resolve()),
        "size": stat.st_size,
        "updated_at": iso_ts(stat.st_mtime),
        "content": content,
    }


def write_text_file(root: Path, raw_path: str | None, content: str) -> dict[str, Any]:
    path = resolve_under_root(root, raw_path)
    if not path:
        raise ValueError("Path is required.")
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(content, encoding="utf-8")
    stat = path.stat()
    return {
        "path": safe_rel(path, root),
        "abs_path": str(path.resolve()),
        "size": stat.st_size,
        "updated_at": iso_ts(stat.st_mtime),
    }


def _guess_content_type(path: Path) -> str:
    if path.suffix.lower() == ".md":
        return "text/markdown; charset=utf-8"
    mime, _ = mimetypes.guess_type(str(path))
    if not mime:
        return "application/octet-stream"
    if mime.startswith("text/"):
        return f"{mime}; charset=utf-8"
    return mime


def read_binary_file(root: Path, raw_path: str | None) -> tuple[Path, bytes, str]:
    path = resolve_under_root(root, raw_path)
    if not path or not path.exists() or not path.is_file():
        raise ValueError(f"File not found: {raw_path}")
    data = path.read_bytes()
    return path, data, _guess_content_type(path)


def list_dir(root: Path, raw_path: str | None) -> dict[str, Any]:
    path = resolve_under_root(root, raw_path) if raw_path else root
    if not path or not path.exists() or not path.is_dir():
        raise ValueError(f"Directory not found: {raw_path}")
    entries: list[dict[str, Any]] = []
    for child in sorted(path.iterdir()):
        stat = child.stat()
        entries.append(
            {
                "name": child.name,
                "path": safe_rel(child, root),
                "type": "dir" if child.is_dir() else "file",
                "size": stat.st_size,
                "updated_at": iso_ts(stat.st_mtime),
            }
        )
    return {"path": safe_rel(path, root), "entries": entries}


def list_run_logs(root: Path, run_rel: str | None) -> list[dict[str, Any]]:
    run_dir = resolve_run_dir(root, run_rel)
    log_paths = sorted(
        set(
            list(run_dir.glob("_log*.txt"))
            + list((run_dir / "archive").glob("_log*.txt"))
            + list(run_dir.glob("_feather_log*.txt"))
            + list(run_dir.glob("_federlicht_log*.txt"))
        ),
        key=lambda p: p.stat().st_mtime,
        reverse=True,
    )
    items: list[dict[str, Any]] = []
    run_rel_safe = safe_rel(run_dir, root)
    for path in log_paths:
        stat = path.stat()
        name = path.name
        lower = name.lower()
        if "federlicht" in lower:
            kind = "federlicht"
        elif "feather" in lower or lower.startswith("_log"):
            kind = "feather"
        else:
            kind = "log"
        items.append(
            {
                "id": safe_rel(path, root),
                "name": name,
                "path": safe_rel(path, root),
                "run_rel": run_rel_safe,
                "kind": kind,
                "status": "history",
                "updated_at": iso_ts(stat.st_mtime),
                "size": stat.st_size,
            }
        )
    return items


def _help_history_path(root: Path, run_rel: str | None) -> tuple[Path, str]:
    if run_rel:
        run_dir = resolve_run_dir(root, run_rel)
        notes_dir = run_dir / "report_notes"
        notes_dir.mkdir(parents=True, exist_ok=True)
        return notes_dir / "help_history.json", safe_rel(run_dir, root)
    shared_dir = root / "site" / "federnett"
    shared_dir.mkdir(parents=True, exist_ok=True)
    return shared_dir / "help_history_global.json", ""


def read_help_history(root: Path, run_rel: str | None) -> dict[str, Any]:
    path, resolved_run = _help_history_path(root, run_rel)
    items: list[dict[str, Any]] = []
    if path.exists():
        try:
            payload = json.loads(path.read_text(encoding="utf-8"))
            if isinstance(payload, list):
                for entry in payload:
                    if not isinstance(entry, dict):
                        continue
                    role = str(entry.get("role") or "").strip().lower()
                    if role not in {"user", "assistant"}:
                        continue
                    content = str(entry.get("content") or "").strip()
                    if not content:
                        continue
                    ts = str(entry.get("ts") or "")
                    items.append({"role": role, "content": content, "ts": ts})
        except Exception:
            items = []
    return {
        "run_rel": resolved_run or (run_rel or ""),
        "path": safe_rel(path, root),
        "items": items[-80:],
    }


def write_help_history(root: Path, run_rel: str | None, items: list[dict[str, Any]]) -> dict[str, Any]:
    path, resolved_run = _help_history_path(root, run_rel)
    cleaned: list[dict[str, Any]] = []
    for entry in items[-80:]:
        if not isinstance(entry, dict):
            continue
        role = str(entry.get("role") or "").strip().lower()
        if role not in {"user", "assistant"}:
            continue
        content = str(entry.get("content") or "").strip()
        if not content:
            continue
        ts = str(entry.get("ts") or "")
        cleaned.append({"role": role, "content": content[:4000], "ts": ts})
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(json.dumps(cleaned, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")
    return {
        "run_rel": resolved_run or (run_rel or ""),
        "path": safe_rel(path, root),
        "count": len(cleaned),
    }


def clear_help_history(root: Path, run_rel: str | None) -> dict[str, Any]:
    path, resolved_run = _help_history_path(root, run_rel)
    if path.exists():
        path.unlink()
    return {
        "run_rel": resolved_run or (run_rel or ""),
        "path": safe_rel(path, root),
        "cleared": True,
    }
