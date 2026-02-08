from __future__ import annotations

import json
import re
import secrets
from pathlib import Path
from typing import Any, Optional

from .utils import safe_rel

PROFILE_ID_RE = re.compile(r"[A-Za-z0-9_.-]+\Z")
SIX_DIGIT_PROFILE_ID_RE = re.compile(r"\d{6}\Z")


def _load_json(path: Path) -> dict[str, Any]:
    try:
        return json.loads(path.read_text(encoding="utf-8"))
    except Exception:
        return {}


def _write_json(path: Path, payload: dict[str, Any]) -> None:
    path.write_text(json.dumps(payload, indent=2, ensure_ascii=False) + "\n", encoding="utf-8")


def _profile_dir(root: Path, source: str) -> Path:
    if source == "builtin":
        return root / "src" / "federlicht" / "profiles"
    if source == "site":
        return root / "site" / "agent_profiles"
    raise ValueError("Invalid profile source")


def _load_registry(dir_path: Path) -> dict[str, Any]:
    registry_path = dir_path / "registry.json"
    if registry_path.exists():
        payload = _load_json(registry_path)
        if isinstance(payload, dict):
            return payload
    return {}


def _iter_profile_files(dir_path: Path) -> dict[str, Path]:
    registry = _load_registry(dir_path)
    files: dict[str, Path] = {}
    for key, entry in registry.items():
        if isinstance(entry, dict) and entry.get("file"):
            files[str(key)] = dir_path / str(entry["file"])
    if files:
        return files
    # Fallback: scan json files when registry missing.
    for path in dir_path.glob("*.json"):
        if path.name == "registry.json":
            continue
        files[path.stem] = path
    return files


def _sanitize_profile_id(raw: str) -> str:
    if not raw:
        raise ValueError("Profile id is required")
    if not PROFILE_ID_RE.fullmatch(raw):
        raise ValueError("Profile id contains invalid characters")
    return raw


def _is_six_digit_profile_id(raw: str) -> bool:
    return bool(SIX_DIGIT_PROFILE_ID_RE.fullmatch(raw or ""))


def _generate_site_profile_id(dir_path: Path) -> str:
    existing: set[str] = set()
    registry = _load_registry(dir_path)
    for key in registry.keys():
        key_text = str(key)
        if _is_six_digit_profile_id(key_text):
            existing.add(key_text)
    for path in dir_path.glob("*.json"):
        if path.name == "registry.json":
            continue
        stem = path.stem
        if _is_six_digit_profile_id(stem):
            existing.add(stem)
    for _ in range(512):
        candidate = f"{secrets.randbelow(1_000_000):06d}"
        if candidate not in existing:
            return candidate
    raise ValueError("Unable to allocate a unique 6-digit profile id")


def list_agent_profiles(root: Path) -> list[dict[str, Any]]:
    profiles: list[dict[str, Any]] = []
    for source in ("builtin", "site"):
        dir_path = _profile_dir(root, source)
        if not dir_path.exists():
            continue
        for profile_id, path in _iter_profile_files(dir_path).items():
            if not path.exists():
                continue
            data = _load_json(path)
            profiles.append(
                {
                    "id": data.get("id") or profile_id,
                    "name": data.get("name") or profile_id,
                    "tagline": data.get("tagline") or "",
                    "author_name": data.get("author_name") or "",
                    "organization": data.get("organization") or "",
                    "apply_to": data.get("apply_to") or [],
                    "source": source,
                    "path": safe_rel(path, root),
                    "read_only": source == "builtin",
                    "memory_hook": data.get("memory_hook") or {},
                }
            )
    profiles.sort(key=lambda p: (p["source"], p["id"]))
    return profiles


def get_agent_profile(
    root: Path, profile_id: str, source: Optional[str] = None
) -> dict[str, Any]:
    profile_id = _sanitize_profile_id(profile_id)
    sources = [source] if source else ["site", "builtin"]
    for src in sources:
        if src is None:
            continue
        dir_path = _profile_dir(root, src)
        if not dir_path.exists():
            continue
        files = _iter_profile_files(dir_path)
        path = files.get(profile_id)
        if not path or not path.exists():
            continue
        data = _load_json(path)
        memory_text = ""
        memory_hook = data.get("memory_hook") or {}
        memory_path = memory_hook.get("path") if isinstance(memory_hook, dict) else None
        if memory_path:
            mem_file = dir_path / Path(memory_path).name
            if mem_file.exists():
                memory_text = mem_file.read_text(encoding="utf-8", errors="replace")
        return {
            "profile": data,
            "memory_text": memory_text,
            "source": src,
            "path": safe_rel(path, root),
            "read_only": src == "builtin",
        }
    raise ValueError("Profile not found")


def save_agent_profile(
    root: Path,
    profile: dict[str, Any],
    memory_text: Optional[str] = None,
    store: str = "site",
) -> dict[str, Any]:
    if store != "site":
        raise ValueError("Only site profiles can be saved")
    dir_path = _profile_dir(root, "site")
    dir_path.mkdir(parents=True, exist_ok=True)

    raw_id = str(profile.get("id") or "").strip()
    profile_id = ""
    if raw_id and _is_six_digit_profile_id(raw_id):
        profile_id = raw_id
    elif raw_id and PROFILE_ID_RE.fullmatch(raw_id) and (dir_path / f"{raw_id}.json").exists():
        # Keep legacy site profile IDs editable; new profiles use 6-digit IDs.
        profile_id = raw_id
    else:
        profile_id = _generate_site_profile_id(dir_path)
    profile["id"] = profile_id

    name = str(profile.get("name") or "").strip()
    author_name = str(profile.get("author_name") or "").strip()
    if name and not author_name:
        profile["author_name"] = name
    org = str(profile.get("organization") or "").strip()
    if org:
        profile["organization"] = org
    elif "organization" in profile:
        profile.pop("organization", None)

    path = dir_path / f"{profile_id}.json"

    memory_hook = profile.get("memory_hook") or {}
    if not isinstance(memory_hook, dict):
        memory_hook = {}
    if memory_text is not None:
        mem_name = memory_hook.get("path") or f"{profile_id}_memory.txt"
        mem_name = Path(mem_name).name
        mem_path = dir_path / mem_name
        mem_path.write_text(memory_text, encoding="utf-8")
        memory_hook["path"] = mem_name
        profile["memory_hook"] = memory_hook

    _write_json(path, profile)
    registry = _load_registry(dir_path)
    registry[profile_id] = {"file": path.name}
    _write_json(dir_path / "registry.json", registry)
    return {
        "id": profile_id,
        "path": safe_rel(path, root),
        "source": "site",
    }


def delete_agent_profile(root: Path, profile_id: str) -> dict[str, Any]:
    profile_id = _sanitize_profile_id(profile_id)
    dir_path = _profile_dir(root, "site")
    if not dir_path.exists():
        raise ValueError("No site profiles directory")
    files = _iter_profile_files(dir_path)
    path = files.get(profile_id) or (dir_path / f"{profile_id}.json")
    memory_path = None
    if path.exists():
        data = _load_json(path)
        memory_hook = data.get("memory_hook") or {}
        if isinstance(memory_hook, dict) and memory_hook.get("path"):
            memory_path = dir_path / Path(str(memory_hook["path"])).name
        path.unlink()
    if memory_path and memory_path.exists():
        memory_path.unlink()
    registry = _load_registry(dir_path)
    if profile_id in registry:
        registry.pop(profile_id, None)
        _write_json(dir_path / "registry.json", registry)
    return {"id": profile_id, "deleted": True}
