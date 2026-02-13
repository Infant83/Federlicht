from __future__ import annotations

import json
import os
import re
from dataclasses import dataclass
from pathlib import Path
from typing import Any, Optional

DEFAULT_PROFILE_ID = "default"
PROFILE_DIR_ENV = "FEDERLICHT_PROFILE_DIR"
APPLY_TO_ALIASES = {
    "plan": "planner",
    "plans": "planner",
    "align": "alignment",
    "aligned": "alignment",
    "aligner": "alignment",
}
APPLY_TO_FRAGMENT_REPAIRS: tuple[tuple[tuple[str, ...], str], ...] = (
    (("pla", "er"), "planner"),
    (("alig", "me", "t"), "alignment"),
)


def default_profiles_dir() -> Path:
    return Path(__file__).parent / "profiles"


@dataclass
class AgentProfile:
    profile_id: str
    name: str
    tagline: str
    author_name: str
    organization: str
    system_prompt: str
    apply_to: list[str]
    version: str
    memory_path: Optional[Path]
    memory_text: Optional[str]
    raw: dict[str, Any]


def resolve_profiles_dir(profile_dir: Optional[str] = None) -> Path:
    if profile_dir:
        return Path(profile_dir).expanduser().resolve()
    env = os.getenv(PROFILE_DIR_ENV)
    if env:
        return Path(env).expanduser().resolve()
    return default_profiles_dir().resolve()


def _normalize_apply_to(value: Any) -> list[str]:
    values = value if isinstance(value, (list, tuple, set)) else [value]
    tokens: list[str] = []
    for entry in values:
        raw = str(entry or "")
        for token in re.split(r"[,\n]+", raw):
            cleaned = token.strip().lower()
            if not cleaned:
                continue
            tokens.append(APPLY_TO_ALIASES.get(cleaned, cleaned))
    repaired: list[str] = []
    idx = 0
    while idx < len(tokens):
        matched = False
        for parts, replacement in APPLY_TO_FRAGMENT_REPAIRS:
            size = len(parts)
            chunk = tuple(tokens[idx : idx + size])
            if len(chunk) == size and chunk == parts:
                repaired.append(replacement)
                idx += size
                matched = True
                break
        if matched:
            continue
        repaired.append(tokens[idx])
        idx += 1
    deduped: list[str] = []
    seen: set[str] = set()
    for token in repaired:
        normalized = str(token).strip().lower()
        if not normalized or normalized in seen:
            continue
        seen.add(normalized)
        deduped.append(normalized)
    if "planner" in seen:
        deduped = [token for token in deduped if token not in {"pla", "er"}]
    if "alignment" in seen:
        deduped = [token for token in deduped if token not in {"alig", "me", "t"}]
    return deduped


def load_registry(profile_dir: Path) -> dict[str, dict[str, Any]]:
    registry_path = profile_dir / "registry.json"
    if registry_path.exists():
        try:
            data = json.loads(registry_path.read_text(encoding="utf-8"))
            if isinstance(data, dict):
                return data
        except Exception:
            return {}
    registry: dict[str, dict[str, Any]] = {}
    if profile_dir.exists():
        for path in profile_dir.glob("*.json"):
            if path.name == "registry.json":
                continue
            key = path.stem
            registry[key] = {"file": path.name}
    return registry


def list_profiles(profile_dir: Path) -> list[dict[str, Any]]:
    registry = load_registry(profile_dir)
    profiles: list[dict[str, Any]] = []
    for key, meta in registry.items():
        entry = {"id": key, **(meta or {})}
        file_name = entry.get("file") or f"{key}.json"
        payload = {}
        try:
            payload = json.loads((profile_dir / file_name).read_text(encoding="utf-8"))
        except Exception:
            payload = {}
        profiles.append(
            {
                "id": payload.get("id") or key,
                "name": payload.get("name") or key,
                "tagline": payload.get("tagline") or "",
                "author_name": payload.get("author_name") or "",
                "organization": payload.get("organization") or "",
                "version": payload.get("version") or "",
                "apply_to": _normalize_apply_to(payload.get("apply_to") or []),
                "file": file_name,
            }
        )
    return profiles


def load_profile(profile_id: Optional[str], profile_dir: Optional[str] = None) -> AgentProfile:
    resolved_dir = resolve_profiles_dir(profile_dir)
    registry = load_registry(resolved_dir)
    if not profile_id:
        profile_id = DEFAULT_PROFILE_ID
    profile_id = str(profile_id).strip().lower()
    entry = registry.get(profile_id)
    if not entry and profile_id != DEFAULT_PROFILE_ID:
        entry = registry.get(DEFAULT_PROFILE_ID)
        profile_id = DEFAULT_PROFILE_ID
    file_name = None
    if entry:
        file_name = entry.get("file")
    if not file_name:
        file_name = f"{profile_id}.json"
    profile_path = resolved_dir / file_name
    data: dict[str, Any] = {}
    if profile_path.exists():
        try:
            data = json.loads(profile_path.read_text(encoding="utf-8"))
        except Exception:
            data = {}
    name = str(data.get("name") or profile_id)
    tagline = str(data.get("tagline") or "")
    author_name = str(data.get("author_name") or "").strip()
    organization = str(data.get("organization") or "").strip()
    system_prompt = str(data.get("system_prompt") or "").strip()
    apply_to = _normalize_apply_to(data.get("apply_to") or ["writer"])
    version = str(data.get("version") or "")
    memory_path = None
    memory_text = None
    memory_hook = data.get("memory_hook")
    if isinstance(memory_hook, dict) and memory_hook.get("path"):
        memory_path = resolved_dir / str(memory_hook.get("path"))
        if memory_path.exists():
            try:
                memory_text = memory_path.read_text(encoding="utf-8").strip()
            except Exception:
                memory_text = None
    return AgentProfile(
        profile_id=profile_id,
        name=name,
        tagline=tagline,
        author_name=author_name,
        organization=organization,
        system_prompt=system_prompt,
        apply_to=apply_to,
        version=version,
        memory_path=memory_path,
        memory_text=memory_text,
        raw=data,
    )


def profile_applies_to(profile: AgentProfile, agent_name: str) -> bool:
    name = agent_name.strip().lower()
    return name in {entry.lower() for entry in profile.apply_to}


def build_profile_context(profile: AgentProfile) -> str:
    parts = [
        f"Profile: {profile.name}",
    ]
    if profile.tagline:
        parts.append(profile.tagline)
    if profile.system_prompt:
        parts.append("Profile prompt:")
        parts.append(profile.system_prompt.strip())
    if profile.memory_text:
        parts.append("Memory hook:")
        parts.append(profile.memory_text.strip())
    return "\n".join(parts).strip()


def profile_summary(profile: AgentProfile) -> dict[str, Any]:
    return {
        "id": profile.profile_id,
        "name": profile.name,
        "tagline": profile.tagline,
        "author_name": profile.author_name,
        "organization": profile.organization,
        "version": profile.version,
        "apply_to": profile.apply_to,
        "memory_path": str(profile.memory_path) if profile.memory_path else None,
        "has_memory": bool(profile.memory_text),
        "system_prompt": profile.system_prompt,
    }
