from __future__ import annotations

import json
import os
import shlex
import time
from datetime import datetime, timezone
from pathlib import Path
from typing import Any, Optional


def now_ts() -> float:
    return time.time()


def json_bytes(payload: Any) -> bytes:
    return json.dumps(payload, ensure_ascii=False).encode("utf-8")


def iso_ts(ts: float | None) -> str:
    if not ts:
        return ""
    try:
        return datetime.fromtimestamp(ts, tz=timezone.utc).isoformat()
    except Exception:
        return ""


def safe_rel(path: Path, root: Path) -> str:
    try:
        return path.relative_to(root).as_posix()
    except Exception:
        return path.as_posix()


def resolve_under_root(root: Path, raw: str | None) -> Optional[Path]:
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


def parse_bool(payload: dict[str, Any], key: str) -> Optional[bool]:
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


def extra_args(extra: str | None) -> list[str]:
    if not extra:
        return []
    try:
        return shlex.split(extra)
    except Exception:
        return []


def expand_env_reference(value: str | None) -> str | None:
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
