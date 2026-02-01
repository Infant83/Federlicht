from __future__ import annotations

from pathlib import Path
from typing import Any

from .utils import safe_rel


def list_templates(root: Path) -> list[str]:
    templates_dir = root / "src" / "federlicht" / "templates"
    if not templates_dir.exists():
        return []
    names = sorted(p.stem for p in templates_dir.glob("*.md"))
    return names


def _parse_template_frontmatter(path: Path) -> dict[str, Any]:
    text = path.read_text(encoding="utf-8", errors="replace")
    if not text.startswith("---"):
        return {"meta": {}, "sections": [], "guides": {}, "writer_guidance": []}
    _, raw = text.split("---", 1)
    front, *_ = raw.split("---", 1)
    lines = [line.rstrip() for line in front.splitlines() if line.strip()]
    meta: dict[str, str] = {}
    sections: list[str] = []
    guides: dict[str, str] = {}
    writer_guidance: list[str] = []
    for line in lines:
        if ":" not in line:
            continue
        key, value = [chunk.strip() for chunk in line.split(":", 1)]
        if not key:
            continue
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
        "path": safe_rel(path, root),
        "meta": parsed["meta"],
        "sections": parsed["sections"],
        "guides": parsed["guides"],
        "writer_guidance": parsed["writer_guidance"],
    }
