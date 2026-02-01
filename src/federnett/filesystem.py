from __future__ import annotations

import mimetypes
from pathlib import Path
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
    pdf_files = [safe_rel(p, root) for p in pdfs[:SUMMARY_FILE_LIMIT]]
    text_files = [safe_rel(p, root) for p in texts[:SUMMARY_FILE_LIMIT]]
    jsonl_files = [safe_rel(p, root) for p in jsonls[:SUMMARY_FILE_LIMIT]]
    return {
        "run_name": run_dir.name,
        "run_rel": safe_rel(run_dir, root),
        "run_abs": str(run_dir.resolve()),
        "counts": {
            "pdf": len(pdfs),
            "text": len(texts),
            "jsonl": len(jsonls),
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
        "text_files": text_files,
        "jsonl_files": jsonl_files,
        "updated_at": iso_ts(updated_ts),
        "summary_lines": summary_lines,
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
