import datetime as dt
import json
import re
from pathlib import Path
from typing import Any, Dict, Optional


def safe_filename(s: str, max_len: int = 120) -> str:
    s = re.sub(r"[^\w\-.]+", "_", s, flags=re.UNICODE).strip("_")
    return s[:max_len] if len(s) > max_len else s


def read_text(path: Path) -> str:
    return path.read_text(encoding="utf-8", errors="ignore")


def write_text(path: Path, text: str) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(text, encoding="utf-8")


def append_jsonl(path: Path, obj: Dict[str, Any]) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    with path.open("a", encoding="utf-8") as f:
        f.write(json.dumps(obj, ensure_ascii=False) + "\n")


def parse_date_from_filename(name: str) -> Optional[dt.date]:
    # expects YYYYMMDD
    m = re.match(r"^(?P<y>\d{4})(?P<m>\d{2})(?P<d>\d{2})$", name)
    if not m:
        return None
    try:
        return dt.date(int(m["y"]), int(m["m"]), int(m["d"]))
    except Exception:
        return None


def normalize_for_json(value: Any) -> Any:
    if isinstance(value, dict):
        return {k: normalize_for_json(v) for k, v in value.items()}
    if isinstance(value, list):
        return [normalize_for_json(v) for v in value]
    if isinstance(value, tuple):
        return [normalize_for_json(v) for v in value]
    if isinstance(value, Path):
        return str(value)
    if isinstance(value, (dt.datetime, dt.date)):
        return value.isoformat()
    return value
