"""Shared version resolver for local/dev and installed package contexts."""

from __future__ import annotations

import re
from importlib.metadata import PackageNotFoundError, version as package_version
from pathlib import Path

DEFAULT_VERSION = "1.5.0"


def _read_pyproject_version() -> str | None:
    current = Path(__file__).resolve()
    for parent in current.parents:
        candidate = parent / "pyproject.toml"
        if not candidate.exists():
            continue
        try:
            text = candidate.read_text(encoding="utf-8", errors="replace")
        except Exception:
            continue
        match = re.search(r'(?m)^version\s*=\s*"([^"]+)"\s*$', text)
        if match:
            return match.group(1).strip()
    return None


def resolve_version() -> str:
    local_version = _read_pyproject_version()
    if local_version:
        return local_version
    try:
        installed_version = package_version("federlicht")
    except PackageNotFoundError:
        installed_version = ""
    return installed_version or DEFAULT_VERSION


VERSION = resolve_version()

