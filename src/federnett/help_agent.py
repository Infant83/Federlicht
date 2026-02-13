from __future__ import annotations

import json
import os
import re
import threading
import time
from dataclasses import dataclass
from pathlib import Path
from typing import Any, Iterator

from .utils import safe_rel

try:
    import requests  # type: ignore
except Exception:  # pragma: no cover - optional runtime dependency
    requests = None  # type: ignore


_INCLUDE_PATHS = (
    "pyproject.toml",
    "CHANGELOG.md",
    "README.md",
    "docs",
    "src",
    "scripts",
    "site/federnett",
)
_EXCLUDE_PREFIXES = (
    "site/runs",
    "site/analytics",
)
_EXCLUDE_PARTS = {
    ".git",
    "__pycache__",
    ".venv",
    "venv",
    "node_modules",
    ".pytest_cache",
    ".mypy_cache",
    ".ruff_cache",
}
_TEXT_EXTS = {
    ".md",
    ".txt",
    ".py",
    ".html",
    ".css",
    ".js",
    ".ts",
    ".json",
    ".toml",
    ".yml",
    ".yaml",
}
_STOPWORDS = {
    "the",
    "and",
    "for",
    "with",
    "from",
    "that",
    "this",
    "are",
    "was",
    "how",
    "what",
    "when",
    "where",
    "which",
    "agent",
    "help",
    "code",
    "using",
    "use",
    "show",
    "설명",
    "기능",
    "옵션",
    "사용법",
    "방법",
    "관련",
    "그리고",
    "에서",
    "있는",
    "합니다",
    "해주세요",
}
_MAX_FILE_BYTES = 400_000
_CHUNK_LINES = 80
_CHUNK_OVERLAP = 24
_MAX_SOURCE_TEXT = 360
_MAX_CONTEXT_CHARS = 12000
_CACHE_LOCK = threading.Lock()
_INDEX_CACHE: dict[str, "_IndexCache"] = {}
_HISTORY_TURNS = 6
_HISTORY_CHARS = 900
_META_PATH_HINTS = (
    "pyproject.toml",
    "CHANGELOG.md",
    "README.md",
    "docs/federlicht_report.md",
    "docs/federnett_roadmap.md",
    "src/federnett/app.py",
    "src/federnett/help_agent.py",
)
_RUN_CONTEXT_PATTERNS = (
    "instruction/*.txt",
    "instruction/*.md",
    "report/*.md",
    "report/*.txt",
    "report_notes/*.md",
    "supporting/help_agent/web_search.jsonl",
    "supporting/help_agent/web_extract/*.txt",
    "supporting/help_agent/web_text/*.txt",
    "README.md",
)


@dataclass
class _Doc:
    rel_path: str
    mtime_ns: int
    size: int
    lines: list[str]


@dataclass
class _IndexCache:
    docs: dict[str, _Doc]
    built_at: float


def _is_path_allowed(rel_path: str, *, allow_run_prefixes: bool = False) -> bool:
    rel = rel_path.replace("\\", "/")
    if not rel:
        return False
    if not allow_run_prefixes:
        for prefix in _EXCLUDE_PREFIXES:
            if rel == prefix or rel.startswith(f"{prefix}/"):
                return False
    parts = [p for p in rel.split("/") if p]
    if any(part in _EXCLUDE_PARTS for part in parts):
        return False
    if any(part.endswith(".egg-info") or part.endswith(".dist-info") for part in parts):
        return False
    if any(part.startswith(".") and part not in {".well-known"} for part in parts):
        return False
    suffix = Path(rel).suffix.lower()
    if suffix and suffix not in _TEXT_EXTS:
        return False
    return True


def _iter_candidate_files(root: Path) -> list[Path]:
    files: list[Path] = []
    seen: set[str] = set()
    for raw in _INCLUDE_PATHS:
        target = (root / raw).resolve()
        if not target.exists():
            continue
        if target.is_file():
            rel = safe_rel(target, root)
            if _is_path_allowed(rel) and rel not in seen:
                seen.add(rel)
                files.append(target)
            continue
        for child in target.rglob("*"):
            if not child.is_file():
                continue
            rel = safe_rel(child, root)
            if rel in seen or not _is_path_allowed(rel):
                continue
            try:
                if child.stat().st_size > _MAX_FILE_BYTES:
                    continue
            except OSError:
                continue
            seen.add(rel)
            files.append(child)
    return files


def _read_doc(path: Path, root: Path) -> _Doc | None:
    try:
        stat = path.stat()
    except OSError:
        return None
    try:
        text = path.read_text(encoding="utf-8", errors="replace")
    except OSError:
        return None
    rel = safe_rel(path, root)
    return _Doc(
        rel_path=rel,
        mtime_ns=stat.st_mtime_ns,
        size=stat.st_size,
        lines=text.splitlines(),
    )


def _load_index(root: Path) -> _IndexCache:
    key = str(root.resolve())
    with _CACHE_LOCK:
        cached = _INDEX_CACHE.get(key)
        docs = dict(cached.docs) if cached else {}
        current: dict[str, Path] = {}
        for path in _iter_candidate_files(root):
            rel = safe_rel(path, root)
            current[rel] = path
        for rel in list(docs.keys()):
            if rel not in current:
                docs.pop(rel, None)
        for rel, path in current.items():
            try:
                stat = path.stat()
            except OSError:
                continue
            prev = docs.get(rel)
            if prev and prev.mtime_ns == stat.st_mtime_ns and prev.size == stat.st_size:
                continue
            doc = _read_doc(path, root)
            if doc is None:
                continue
            docs[rel] = doc
        out = _IndexCache(docs=docs, built_at=time.time())
        _INDEX_CACHE[key] = out
        return out


def _query_tokens(question: str) -> list[str]:
    lowered = question.strip().lower()
    raw_tokens = re.findall(r"[a-z0-9_가-힣-]{2,}", lowered)
    deduped: list[str] = []
    seen: set[str] = set()
    for tok in raw_tokens:
        parts = [tok]
        # Split mixed-script tokens (e.g., "federnett에서" -> "federnett", "에서")
        parts.extend(re.findall(r"[a-z0-9_]{2,}", tok))
        parts.extend(re.findall(r"[가-힣]{2,}", tok))
        for part in parts:
            if part in _STOPWORDS:
                continue
            if part in seen:
                continue
            seen.add(part)
            deduped.append(part)
    return deduped


def _iter_chunks(lines: list[str]) -> list[tuple[int, int, str]]:
    if not lines:
        return []
    if len(lines) <= _CHUNK_LINES:
        return [(1, len(lines), "\n".join(lines))]
    chunks: list[tuple[int, int, str]] = []
    step = max(1, _CHUNK_LINES - _CHUNK_OVERLAP)
    start = 0
    while start < len(lines):
        end = min(start + _CHUNK_LINES, len(lines))
        text = "\n".join(lines[start:end])
        chunks.append((start + 1, end, text))
        if end >= len(lines):
            break
        start += step
    return chunks


def _chunk_score(
    path: str,
    text: str,
    tokens: list[str],
    question_l: str,
    run_rel_l: str = "",
) -> float:
    if not text:
        return 0.0
    text_l = text.lower()
    path_l = path.lower()
    text_tokens = re.findall(r"[a-z0-9_가-힣-]{2,}", text_l)
    token_counts: dict[str, int] = {}
    for token in text_tokens:
        token_counts[token] = token_counts.get(token, 0) + 1
    path_tokens = set(re.findall(r"[a-z0-9_가-힣-]{2,}", path_l))
    score = 0.0
    if question_l and len(question_l) >= 6 and question_l in text_l:
        score += 10.0
    if run_rel_l and path_l.startswith(run_rel_l):
        score += 4.0
    for tok in tokens:
        count = token_counts.get(tok, 0)
        if count:
            score += float(min(count, 8) * 2)
        if tok in path_tokens:
            score += 2.0
        if tok.startswith("--") and tok in text_l:
            score += 3.0
    option_intent = any(
        tok.startswith("--") or tok in {"option", "options", "arg", "args", "옵션"}
        for tok in tokens
    )
    if option_intent and "--" in text and ("option" in text_l or "arg" in text_l):
        score += 1.0
    meta_intent = any(
        token in question_l
        for token in ("version", "버전", "changelog", "변경", "release", "readme", "업데이트")
    )
    if meta_intent and any(
        marker in path_l for marker in ("pyproject.toml", "readme.md", "changelog.md", "__init__.py")
    ):
        score += 7.0
    auth_intent = any(
        token in question_l
        for token in ("login", "signin", "auth", "계정", "로그인", "권한", "인증", "프로필")
    )
    if auth_intent and any(marker in path_l for marker in ("auth", "profile", "agent_profiles", "federnett")):
        score += 5.0
    return score


def _fallback_sources(index: _IndexCache, max_sources: int) -> list[dict[str, Any]]:
    out: list[dict[str, Any]] = []
    for hint in _META_PATH_HINTS:
        doc = index.docs.get(hint)
        if not doc or not doc.lines:
            continue
        excerpt = "\n".join(doc.lines[: min(20, len(doc.lines))]).strip()
        if len(excerpt) > _MAX_SOURCE_TEXT:
            excerpt = excerpt[: _MAX_SOURCE_TEXT - 1] + "..."
        out.append(
            {
                "path": doc.rel_path,
                "start_line": 1,
                "end_line": min(len(doc.lines), 20),
                "score": 0.1,
                "excerpt": excerpt,
            },
        )
        if len(out) >= max(1, max_sources):
            break
    for idx, item in enumerate(out, start=1):
        item["id"] = f"S{idx}"
    return out


def _resolve_run_dir(root: Path, run_rel: str | None) -> Path | None:
    normalized = (run_rel or "").strip().replace("\\", "/").strip("/")
    if not normalized:
        return None
    try:
        run_dir = (root / normalized).resolve()
        run_dir.relative_to(root.resolve())
    except Exception:
        return None
    if not run_dir.exists() or not run_dir.is_dir():
        return None
    return run_dir


def _iter_run_context_files(root: Path, run_rel: str | None) -> list[Path]:
    run_dir = _resolve_run_dir(root, run_rel)
    if run_dir is None:
        return []
    files: list[Path] = []
    seen: set[str] = set()
    for pattern in _RUN_CONTEXT_PATTERNS:
        for path in run_dir.glob(pattern):
            if not path.is_file():
                continue
            rel = safe_rel(path, root)
            if rel in seen or not _is_path_allowed(rel, allow_run_prefixes=True):
                continue
            if "/archive/" in rel.replace("\\", "/").lower():
                continue
            try:
                if path.stat().st_size > _MAX_FILE_BYTES:
                    continue
            except OSError:
                continue
            seen.add(rel)
            files.append(path)
    return files


def _score_run_context_sources(
    root: Path,
    run_rel: str | None,
    *,
    tokens: list[str],
    question_l: str,
    max_sources: int,
) -> list[dict[str, Any]]:
    scored: list[dict[str, Any]] = []
    run_rel_l = (run_rel or "").strip().replace("\\", "/").strip("/").lower()
    for path in _iter_run_context_files(root, run_rel):
        doc = _read_doc(path, root)
        if doc is None or not doc.lines:
            continue
        for start, end, text in _iter_chunks(doc.lines):
            score = _chunk_score(doc.rel_path, text, tokens, question_l, run_rel_l=run_rel_l)
            if score <= 0:
                continue
            excerpt = text.strip()
            if len(excerpt) > _MAX_SOURCE_TEXT:
                excerpt = excerpt[: _MAX_SOURCE_TEXT - 1] + "..."
            scored.append(
                {
                    "path": doc.rel_path,
                    "start_line": start,
                    "end_line": end,
                    "score": round(score + 3.0, 3),
                    "excerpt": excerpt,
                }
            )
    scored.sort(
        key=lambda item: (-float(item["score"]), len(str(item["path"])), int(item["start_line"])),
    )
    return scored[: max(1, max_sources)]


def _select_sources(
    root: Path,
    question: str,
    max_sources: int,
    run_rel: str | None = None,
) -> tuple[list[dict[str, Any]], int]:
    index = _load_index(root)
    tokens = _query_tokens(question)
    question_l = question.strip().lower()
    run_rel_l = (run_rel or "").strip().replace("\\", "/").strip("/").lower()
    scored: list[dict[str, Any]] = []
    for doc in index.docs.values():
        if not doc.lines:
            continue
        for start, end, text in _iter_chunks(doc.lines):
            score = _chunk_score(doc.rel_path, text, tokens, question_l, run_rel_l=run_rel_l)
            if score <= 0:
                continue
            excerpt = text.strip()
            if len(excerpt) > _MAX_SOURCE_TEXT:
                excerpt = excerpt[: _MAX_SOURCE_TEXT - 1] + "..."
            scored.append(
                {
                    "path": doc.rel_path,
                    "start_line": start,
                    "end_line": end,
                    "score": round(score, 3),
                    "excerpt": excerpt,
                }
            )
    scored.sort(
        key=lambda item: (-float(item["score"]), len(str(item["path"])), int(item["start_line"])),
    )
    run_context_scored = _score_run_context_sources(
        root,
        run_rel,
        tokens=tokens,
        question_l=question_l,
        max_sources=max(2, min(6, max_sources)),
    )
    if run_context_scored:
        scored.extend(run_context_scored)
        scored.sort(
            key=lambda item: (-float(item["score"]), len(str(item["path"])), int(item["start_line"])),
        )
    selected: list[dict[str, Any]] = []
    seen_chunks: set[tuple[str, int, int]] = set()
    for item in scored:
        key = (
            str(item.get("path") or ""),
            int(item.get("start_line") or 0),
            int(item.get("end_line") or 0),
        )
        if key in seen_chunks:
            continue
        seen_chunks.add(key)
        selected.append(item)
        if len(selected) >= max(1, max_sources):
            break
    if not selected:
        selected = _fallback_sources(index, max_sources)
    for idx, item in enumerate(selected, start=1):
        item["id"] = f"S{idx}"
    return selected, len(index.docs)


def _build_context(sources: list[dict[str, Any]]) -> str:
    chunks: list[str] = []
    used = 0
    for src in sources:
        piece = (
            f"[{src['id']}] {src['path']}:{src['start_line']}-{src['end_line']}\n"
            f"{src['excerpt']}\n"
        )
        next_used = used + len(piece)
        if next_used > _MAX_CONTEXT_CHARS and chunks:
            break
        chunks.append(piece)
        used = next_used
    return "\n".join(chunks).strip()


def _normalize_history(history: Any) -> list[dict[str, str]]:
    if not isinstance(history, list):
        return []
    cleaned: list[dict[str, str]] = []
    for item in history[-_HISTORY_TURNS:]:
        if not isinstance(item, dict):
            continue
        role = str(item.get("role") or "").strip().lower()
        if role not in {"user", "assistant"}:
            continue
        content = str(item.get("content") or "").strip()
        if not content:
            continue
        cleaned.append(
            {
                "role": role,
                "content": content[:_HISTORY_CHARS],
            },
        )
    return cleaned


def _build_help_web_queries(question: str, history: list[dict[str, str]] | None) -> list[str]:
    queries: list[str] = []
    primary = str(question or "").strip()
    if primary:
        queries.append(primary)
    normalized = _normalize_history(history)
    for item in reversed(normalized):
        if item.get("role") != "user":
            continue
        text = str(item.get("content") or "").strip()
        if not text:
            continue
        if text == primary:
            continue
        queries.append(text)
        if len(queries) >= 3:
            break
    deduped: list[str] = []
    seen: set[str] = set()
    for query in queries:
        key = query.lower()
        if key in seen:
            continue
        seen.add(key)
        deduped.append(query)
    return deduped[:3]


def _should_run_help_web_search(question: str, history: list[dict[str, str]] | None) -> bool:
    text = str(question or "").strip().lower()
    if not text:
        return False
    triggers = (
        "웹검색",
        "web search",
        "검색",
        "찾아",
        "최신",
        "뉴스",
        "논문",
        "paper",
        "arxiv",
        "openalex",
        "link",
        "source",
        "근거",
        "시장",
        "동향",
    )
    if any(token in text for token in triggers):
        return True
    normalized = _normalize_history(history)
    for item in reversed(normalized):
        if item.get("role") != "user":
            continue
        prev = str(item.get("content") or "").strip().lower()
        if any(token in prev for token in triggers):
            return True
    return False


def _run_help_web_research(
    root: Path,
    *,
    question: str,
    run_rel: str | None,
    history: list[dict[str, str]] | None,
) -> str:
    run_dir = _resolve_run_dir(root, run_rel)
    if run_dir is None:
        return "web_search skipped: run folder not selected."
    api_key = str(os.getenv("TAVILY_API_KEY") or "").strip()
    if not api_key:
        return "web_search skipped: TAVILY_API_KEY is not set."
    queries = _build_help_web_queries(question, history)
    if not queries:
        return "web_search skipped: no query generated."
    try:
        from feather.web_research import run_supporting_web_research

        supporting_dir = run_dir / "supporting" / "help_agent"
        summary, _ = run_supporting_web_research(
            supporting_dir=supporting_dir,
            queries=queries,
            max_results=4,
            max_fetch=4,
            max_chars=3200,
            max_pdf_pages=8,
            api_key=api_key,
        )
        rel_dir = safe_rel(supporting_dir, root)
        return f"{summary} (dir={rel_dir})"
    except Exception as exc:
        return f"web_search failed: {exc}"


def _normalize_api_base_url(base_url: str) -> str:
    base = (base_url or "https://api.openai.com").strip().rstrip("/")
    lowered = base.lower()
    for suffix in (
        "/v1/chat/completions",
        "/chat/completions",
        "/v1/responses",
        "/responses",
    ):
        if lowered.endswith(suffix):
            base = base[: -len(suffix)]
            lowered = base.lower()
            break
    return base.rstrip("/")


def _chat_completion_urls(base_url: str) -> list[str]:
    base = _normalize_api_base_url(base_url)
    candidates: list[str]
    if base.endswith("/v1"):
        root = base[:-3].rstrip("/")
        candidates = [
            f"{base}/chat/completions",
            f"{root}/v1/chat/completions",
            f"{root}/chat/completions",
        ]
    else:
        candidates = [f"{base}/v1/chat/completions", f"{base}/chat/completions"]
    out: list[str] = []
    seen: set[str] = set()
    for url in candidates:
        normalized = url.rstrip("/")
        if not normalized or normalized in seen:
            continue
        seen.add(normalized)
        out.append(normalized)
    return out


def _responses_urls(base_url: str) -> list[str]:
    base = _normalize_api_base_url(base_url)
    candidates: list[str]
    if base.endswith("/v1"):
        root = base[:-3].rstrip("/")
        candidates = [
            f"{base}/responses",
            f"{root}/v1/responses",
            f"{root}/responses",
        ]
    else:
        candidates = [f"{base}/v1/responses", f"{base}/responses"]
    out: list[str] = []
    seen: set[str] = set()
    for url in candidates:
        normalized = url.rstrip("/")
        if not normalized or normalized in seen:
            continue
        seen.add(normalized)
        out.append(normalized)
    return out


def _payload_variants(base_payload: dict[str, Any]) -> list[dict[str, Any]]:
    first = dict(base_payload)
    first["max_completion_tokens"] = 900
    second = dict(base_payload)
    second["max_tokens"] = 900
    third = dict(base_payload)
    third.pop("temperature", None)
    return [first, second, third]


def _responses_payload_variants(base_payload: dict[str, Any]) -> list[dict[str, Any]]:
    first = dict(base_payload)
    first["max_output_tokens"] = 900
    second = dict(base_payload)
    third = dict(base_payload)
    third.pop("temperature", None)
    return [first, second, third]


def _is_unsupported_token_error(text: str, key_name: str) -> bool:
    lowered = (text or "").lower()
    return "unsupported parameter" in lowered and key_name.lower() in lowered


def _expand_env_reference(raw_value: str) -> str:
    text = str(raw_value or "").strip()
    if not text:
        return ""
    if text.startswith("${") and text.endswith("}") and len(text) > 3:
        key = text[2:-1].strip()
        return str(os.getenv(key) or "").strip()
    if text.startswith("$") and len(text) > 1 and " " not in text:
        key = text[1:].strip()
        return str(os.getenv(key) or "").strip()
    return text


def _resolve_requested_model(model_input: str | None) -> tuple[str, bool]:
    raw = str(model_input or "").strip()
    if raw:
        expanded = _expand_env_reference(raw)
        if expanded:
            # Explicit "$OPENAI_MODEL" is treated as auto-resolution to env model.
            return expanded, not raw.startswith("$")
        if raw.startswith("$"):
            return "", False
        return raw, True
    env_model = _expand_env_reference(str(os.getenv("OPENAI_MODEL") or ""))
    return env_model, False


def _is_model_unavailable_error(status_code: int, text: str) -> bool:
    lowered = (text or "").lower()
    model_hint = any(token in lowered for token in ("model", "deployment"))
    not_found_hint = any(
        token in lowered
        for token in (
            "not found",
            "does not exist",
            "unknown model",
            "unavailable",
            "access",
            "permission",
            "invalid model",
        )
    )
    return (status_code in {400, 404} and model_hint and not_found_hint) or (
        status_code == 404 and "model_not_found" in lowered
    )


def _extract_chat_content(body: dict[str, Any]) -> str:
    choices = body.get("choices") or []
    if not choices:
        return ""
    message = choices[0].get("message") or {}
    return str(message.get("content") or "").strip()


def _extract_responses_content(body: dict[str, Any]) -> str:
    text = body.get("output_text")
    if isinstance(text, str) and text.strip():
        return text.strip()
    output = body.get("output")
    chunks: list[str] = []
    if isinstance(output, list):
        for item in output:
            if not isinstance(item, dict):
                continue
            content = item.get("content")
            if isinstance(content, list):
                for part in content:
                    if not isinstance(part, dict):
                        continue
                    part_type = str(part.get("type") or "").strip().lower()
                    part_text = part.get("text")
                    if part_type in {"output_text", "text"} and isinstance(part_text, str) and part_text.strip():
                        chunks.append(part_text.strip())
            elif isinstance(content, str) and content.strip():
                chunks.append(content.strip())
    if chunks:
        return "\n".join(chunks).strip()
    return _extract_chat_content(body)


def _iter_sse_json_objects(resp: Any) -> Iterator[dict[str, Any]]:
    for raw_line in resp.iter_lines(decode_unicode=True):
        if raw_line is None:
            continue
        line = str(raw_line).strip()
        if not line or not line.startswith("data:"):
            continue
        payload = line[5:].strip()
        if not payload or payload == "[DONE]":
            break
        try:
            parsed = json.loads(payload)
        except Exception:
            continue
        if isinstance(parsed, dict):
            yield parsed


def _iter_text_fragments(value: Any) -> Iterator[str]:
    if isinstance(value, str):
        if value:
            yield value
        return
    if isinstance(value, list):
        for entry in value:
            if isinstance(entry, str):
                if entry:
                    yield entry
                continue
            if not isinstance(entry, dict):
                continue
            for key in ("text", "content", "value"):
                token = entry.get(key)
                if isinstance(token, str) and token:
                    yield token
                    break


def _iter_chat_stream_content(resp: Any) -> Iterator[str]:
    content_type = str(resp.headers.get("Content-Type") or "").lower()
    if "text/event-stream" not in content_type:
        try:
            body = resp.json()
        except Exception:
            return
        text = _extract_chat_content(body)
        if text:
            yield text
        return
    for event in _iter_sse_json_objects(resp):
        choices = event.get("choices")
        if not isinstance(choices, list) or not choices:
            continue
        first = choices[0] if isinstance(choices[0], dict) else {}
        delta = first.get("delta")
        if isinstance(delta, dict):
            for token in _iter_text_fragments(delta.get("content")):
                yield token
            continue
        message = first.get("message")
        if isinstance(message, dict):
            for token in _iter_text_fragments(message.get("content")):
                yield token


def _iter_responses_stream_content(resp: Any) -> Iterator[str]:
    content_type = str(resp.headers.get("Content-Type") or "").lower()
    if "text/event-stream" not in content_type:
        try:
            body = resp.json()
        except Exception:
            return
        text = _extract_responses_content(body)
        if text:
            yield text
        return
    seen_delta = False
    for event in _iter_sse_json_objects(resp):
        event_type = str(event.get("type") or "").strip().lower()
        if event_type == "response.output_text.delta":
            delta = event.get("delta")
            if isinstance(delta, str) and delta:
                seen_delta = True
                yield delta
            continue
        if event_type == "response.output_text.done":
            text = event.get("text")
            if not seen_delta and isinstance(text, str) and text.strip():
                yield text.strip()
            continue
        if event_type == "response.completed":
            response_payload = event.get("response")
            if isinstance(response_payload, dict):
                text = _extract_responses_content(response_payload)
                if text and not seen_delta:
                    yield text
            continue


def _call_llm_stream(
    question: str,
    sources: list[dict[str, Any]],
    model: str | None,
    history: list[dict[str, str]] | None = None,
    strict_model: bool = False,
) -> tuple[Iterator[str], str]:
    api_key = os.getenv("OPENAI_API_KEY")
    if not api_key:
        raise RuntimeError("OPENAI_API_KEY is not set")
    if requests is None:
        raise RuntimeError("requests package is unavailable")
    chosen_model, explicit_model = _resolve_requested_model(model)
    if not chosen_model:
        raise RuntimeError("Model is not configured (set OPENAI_MODEL or pass model)")
    base_url = _normalize_api_base_url(
        (os.getenv("OPENAI_BASE_URL") or os.getenv("OPENAI_API_BASE") or "https://api.openai.com").strip()
    )
    chat_urls = _chat_completion_urls(base_url)
    responses_urls = _responses_urls(base_url)
    context = _build_context(sources)
    system = (
        "You are Federnett usage guide assistant. "
        "Default output language is Korean. "
        "Prioritize Federnett UI workflow first, then explain CLI only if explicitly requested. "
        "If CLI is not explicitly requested, do not output shell command lines. "
        "For version/release questions, prioritize pyproject.toml and CHANGELOG evidence first. "
        "Do not invent features/settings not grounded in the provided context. "
        "If a feature is unavailable, explicitly say it is unavailable now. "
        "Do not suggest unsafe/destructive commands. "
        "Do not claim execution you did not perform or files you did not modify. "
        "Keep replies concise and actionable. "
        "Use provided context when relevant; if uncertain, explicitly say so. "
        "For pure greeting/small-talk, respond in 1-2 short sentences and ask what they want to do next. "
        "For technical usage questions, include evidence with [S#] markers when sources exist."
    )
    user = (
        f"질문:\n{question}\n\n"
        f"컨텍스트(코드/문서 발췌):\n{context}\n\n"
        "출력 지침:\n"
        "- 인사/잡담이면 1~2문장으로 짧게 답하고 형식 목록은 생략.\n"
        "- 사용법 질문이면 아래 형식을 사용:\n"
        "  1) 핵심 답변(짧게, Federnett 기준)\n"
        "  2) 실행 절차\n"
        "  3) 옵션/체크 권장값\n"
        "  4) 주의사항\n"
        "  5) 근거 [S#] (소스가 있을 때)\n"
        "- 코드블록은 반드시 마크다운 fenced code block(```)을 사용.\n"
        "- 질문자가 CLI를 명시하지 않았다면 Federnett UI 단계로 안내.\n"
        "- CLI를 요청받지 않은 상태에서는 명령어를 출력하지 말고, 화면 기준 동작만 안내.\n"
        "- 제공된 소스에 없는 기능(예: 로그인/SSO/권한체계)은 임의로 추가하지 말 것.\n"
        "- 이 에이전트는 안내 전용이므로, 파일 수정/실행을 했다고 쓰지 말 것.\n"
    )
    messages: list[dict[str, str]] = [{"role": "system", "content": system}]
    if history:
        messages.extend(_normalize_history(history))
    messages.append({"role": "user", "content": user})
    headers = {
        "Authorization": f"Bearer {api_key}",
        "Content-Type": "application/json",
    }
    last_error = "LLM request failed: no endpoint attempted"
    for candidate_model in _resolve_model_candidates(
        chosen_model,
        explicit=explicit_model,
        strict_model=bool(strict_model),
    ):
        model_unavailable = False
        chat_payload_base = {
            "model": candidate_model,
            "messages": messages,
            "temperature": 0.2,
            "stream": True,
        }
        for url in chat_urls:
            for payload in _payload_variants(chat_payload_base):
                resp = requests.post(
                    url,
                    headers=headers,
                    json=payload,
                    timeout=90,
                    stream=True,
                )
                if resp.status_code == 200:
                    def _chat_iter(response_obj: Any = resp) -> Iterator[str]:
                        with response_obj:
                            yield from _iter_chat_stream_content(response_obj)
                    return _chat_iter(), candidate_model
                text = (resp.text or "").strip()
                resp.close()
                last_error = f"LLM request failed: {resp.status_code} {text}"
                if _is_model_unavailable_error(resp.status_code, text):
                    model_unavailable = True
                    break
                if resp.status_code == 404:
                    break
                if _is_unsupported_token_error(text, "max_tokens"):
                    continue
                if _is_unsupported_token_error(text, "max_completion_tokens"):
                    continue
                if _is_unsupported_token_error(text, "temperature"):
                    continue
            if model_unavailable:
                break
        if model_unavailable:
            continue
        responses_payload_base = {
            "model": candidate_model,
            "input": messages,
            "temperature": 0.2,
            "stream": True,
        }
        for url in responses_urls:
            for payload in _responses_payload_variants(responses_payload_base):
                resp = requests.post(
                    url,
                    headers=headers,
                    json=payload,
                    timeout=90,
                    stream=True,
                )
                if resp.status_code == 200:
                    def _responses_iter(response_obj: Any = resp) -> Iterator[str]:
                        with response_obj:
                            yield from _iter_responses_stream_content(response_obj)
                    return _responses_iter(), candidate_model
                text = (resp.text or "").strip()
                resp.close()
                last_error = f"LLM request failed: {resp.status_code} {text}"
                if _is_model_unavailable_error(resp.status_code, text):
                    model_unavailable = True
                    break
                if resp.status_code == 404:
                    break
                if _is_unsupported_token_error(text, "max_output_tokens"):
                    continue
                if _is_unsupported_token_error(text, "temperature"):
                    continue
            if model_unavailable:
                break
        if model_unavailable:
            continue
    raise RuntimeError(last_error)


def _resolve_model_candidates(chosen_model: str, *, explicit: bool, strict_model: bool = False) -> list[str]:
    allow_fallback = str(os.getenv("FEDERNETT_HELP_ALLOW_MODEL_FALLBACK") or "").strip().lower() in {
        "1",
        "true",
        "yes",
        "on",
    }
    candidates: list[str] = []
    for token in (chosen_model,):
        if token and token not in candidates:
            candidates.append(token)
    if explicit and (strict_model or not allow_fallback):
        return candidates
    for token in (
        _expand_env_reference(str(os.getenv("OPENAI_MODEL") or "")),
        _expand_env_reference(str(os.getenv("FEDERNETT_HELP_FALLBACK_MODEL") or "gpt-4o-mini")),
    ):
        if token and token not in candidates:
            candidates.append(token)
    return candidates


def _call_llm(
    question: str,
    sources: list[dict[str, Any]],
    model: str | None,
    history: list[dict[str, str]] | None = None,
    strict_model: bool = False,
) -> tuple[str, str]:
    api_key = os.getenv("OPENAI_API_KEY")
    if not api_key:
        raise RuntimeError("OPENAI_API_KEY is not set")
    if requests is None:
        raise RuntimeError("requests package is unavailable")
    chosen_model, explicit_model = _resolve_requested_model(model)
    if not chosen_model:
        raise RuntimeError("Model is not configured (set OPENAI_MODEL or pass model)")
    base_url = _normalize_api_base_url(
        (os.getenv("OPENAI_BASE_URL") or os.getenv("OPENAI_API_BASE") or "https://api.openai.com").strip()
    )
    chat_urls = _chat_completion_urls(base_url)
    responses_urls = _responses_urls(base_url)
    context = _build_context(sources)
    system = (
        "You are Federnett usage guide assistant. "
        "Default output language is Korean. "
        "Prioritize Federnett UI workflow first, then explain CLI only if explicitly requested. "
        "If CLI is not explicitly requested, do not output shell command lines. "
        "For version/release questions, prioritize pyproject.toml and CHANGELOG evidence first. "
        "Do not invent features/settings not grounded in the provided context. "
        "If a feature is unavailable, explicitly say it is unavailable now. "
        "Do not suggest unsafe/destructive commands. "
        "Do not claim execution you did not perform or files you did not modify. "
        "Keep replies concise and actionable. "
        "Use provided context when relevant; if uncertain, explicitly say so. "
        "For pure greeting/small-talk, respond in 1-2 short sentences and ask what they want to do next. "
        "For technical usage questions, include evidence with [S#] markers when sources exist."
    )
    user = (
        f"질문:\n{question}\n\n"
        f"컨텍스트(코드/문서 발췌):\n{context}\n\n"
        "출력 지침:\n"
        "- 인사/잡담이면 1~2문장으로 짧게 답하고 형식 목록은 생략.\n"
        "- 사용법 질문이면 아래 형식을 사용:\n"
        "  1) 핵심 답변(짧게, Federnett 기준)\n"
        "  2) 실행 절차\n"
        "  3) 옵션/체크 권장값\n"
        "  4) 주의사항\n"
        "  5) 근거 [S#] (소스가 있을 때)\n"
        "- 코드블록은 반드시 마크다운 fenced code block(```)을 사용.\n"
        "- 질문자가 CLI를 명시하지 않았다면 Federnett UI 단계로 안내.\n"
        "- CLI를 요청받지 않은 상태에서는 명령어를 출력하지 말고, 화면 기준 동작만 안내.\n"
        "- 제공된 소스에 없는 기능(예: 로그인/SSO/권한체계)은 임의로 추가하지 말 것.\n"
        "- 이 에이전트는 안내 전용이므로, 파일 수정/실행을 했다고 쓰지 말 것.\n"
    )
    messages: list[dict[str, str]] = [{"role": "system", "content": system}]
    if history:
        messages.extend(_normalize_history(history))
    messages.append({"role": "user", "content": user})
    headers = {
        "Authorization": f"Bearer {api_key}",
        "Content-Type": "application/json",
    }
    last_error = "LLM request failed: no endpoint attempted"
    resp = None
    for candidate_model in _resolve_model_candidates(
        chosen_model,
        explicit=explicit_model,
        strict_model=bool(strict_model),
    ):
        model_unavailable = False
        chat_payload_base = {
            "model": candidate_model,
            "messages": messages,
            "temperature": 0.2,
        }
        for url in chat_urls:
            for payload in _payload_variants(chat_payload_base):
                resp = requests.post(
                    url,
                    headers=headers,
                    json=payload,
                    timeout=45,
                )
                if resp.status_code == 200:
                    body = resp.json()
                    content = _extract_chat_content(body)
                    if content:
                        return content, candidate_model
                    last_error = "LLM returned empty content"
                    continue
                text = resp.text.strip()
                last_error = f"LLM request failed: {resp.status_code} {text}"
                if _is_model_unavailable_error(resp.status_code, text):
                    model_unavailable = True
                    break
                if resp.status_code == 404:
                    # Endpoint mismatch (common on OpenAI-compatible gateways): try next URL.
                    break
                if _is_unsupported_token_error(text, "max_tokens"):
                    continue
                if _is_unsupported_token_error(text, "max_completion_tokens"):
                    continue
                if _is_unsupported_token_error(text, "temperature"):
                    continue
                # For other errors, keep trying alternates but preserve the latest detail.
            if model_unavailable:
                break
            if resp is not None and resp.status_code == 200:
                break
        if model_unavailable:
            continue
        responses_payload_base = {
            "model": candidate_model,
            "input": messages,
            "temperature": 0.2,
        }
        for url in responses_urls:
            for payload in _responses_payload_variants(responses_payload_base):
                resp = requests.post(
                    url,
                    headers=headers,
                    json=payload,
                    timeout=45,
                )
                if resp.status_code == 200:
                    body = resp.json()
                    content = _extract_responses_content(body)
                    if content:
                        return content, candidate_model
                    last_error = "LLM returned empty content"
                    continue
                text = resp.text.strip()
                last_error = f"LLM request failed: {resp.status_code} {text}"
                if _is_model_unavailable_error(resp.status_code, text):
                    model_unavailable = True
                    break
                if resp.status_code == 404:
                    break
                if _is_unsupported_token_error(text, "max_output_tokens"):
                    continue
                if _is_unsupported_token_error(text, "temperature"):
                    continue
            if model_unavailable:
                break
            if resp is not None and resp.status_code == 200:
                break
        if model_unavailable:
            continue
    raise RuntimeError(last_error)


def _fallback_answer(question: str, sources: list[dict[str, Any]]) -> str:
    if not sources:
        return (
            "LLM 호출 또는 소스 매칭이 실패했습니다.\n"
            "질문에 기능명/옵션명/파일명을 함께 적어 다시 시도해 주세요.\n"
            "예: `federlicht의 --template-rigidity와 --temperature-level 차이`"
        )
    lines = [
        "LLM 응답을 사용할 수 없어 코드/문서 검색 결과 기반으로 요약합니다.",
        "",
        f"- 질문: {question}",
        "- 권장: 아래 근거 파일을 순서대로 열어 옵션과 실행 절차를 확인하세요.",
        "",
        "핵심 근거:",
    ]
    for src in sources[:6]:
        head = src.get("excerpt", "").splitlines()[0] if src.get("excerpt") else ""
        head = head[:150]
        lines.append(
            f"- [{src['id']}] `{src['path']}:{src['start_line']}` {head}",
        )
    return "\n".join(lines).strip()


def _infer_safe_action(question: str, run_rel: str | None = None) -> dict[str, Any] | None:
    q = (question or "").strip().lower()
    if not q:
        return None
    explicit_run = any(
        token in q
        for token in ("실행", "run", "start", "돌려", "해줘", "해 줘", "시작", "재작성", "다시 작성")
    )
    if not explicit_run:
        return None
    if any(token in q for token in ("feather부터", "연속", "end-to-end", "파이프라인")):
        return {
            "type": "run_feather_then_federlicht",
            "label": "Feather -> Federlicht 실행",
            "run_rel": run_rel or "",
            "safety": "현재 화면 폼 값만 사용",
            "summary": "수집부터 보고서 생성까지 연속 실행",
        }
    if "feather" in q or any(token in q for token in ("자료 수집", "검색", "크롤링", "아카이브")):
        return {
            "type": "run_feather",
            "label": "Feather 실행",
            "run_rel": run_rel or "",
            "safety": "현재 화면 폼 값만 사용",
            "summary": "자료 수집/아카이브 실행",
        }
    if "federlicht" in q or "보고서" in q:
        return {
            "type": "run_federlicht",
            "label": "Federlicht 실행",
            "run_rel": run_rel or "",
            "safety": "현재 화면 폼 값만 사용",
            "summary": "현재 Run 기준 보고서 생성",
        }
    return None


def _help_capabilities(web_search_enabled: bool) -> dict[str, list[dict[str, Any]]]:
    return {
        "tools": [
            {
                "id": "source_index",
                "label": "Source Index",
                "description": "코드/문서/런 아티팩트 인덱스를 검색해 근거 후보를 선택합니다.",
            },
            {
                "id": "web_research",
                "label": "Web Search",
                "description": "웹 보강 검색(Tavily)을 수행해 최신 근거를 보완합니다.",
                "enabled": bool(web_search_enabled),
            },
            {
                "id": "llm_generate",
                "label": "LLM Generate",
                "description": "선별된 근거를 바탕으로 답변을 생성합니다.",
            },
        ],
        "skills": [
            {
                "id": "action_runner",
                "label": "Action Runner",
                "description": "질문 문맥 기반으로 안전한 실행 제안을 생성합니다.",
            }
        ],
        "mcp": [],
    }


def answer_help_question(
    root: Path,
    question: str,
    *,
    model: str | None = None,
    strict_model: bool = False,
    max_sources: int = 8,
    history: list[dict[str, str]] | None = None,
    run_rel: str | None = None,
    web_search: bool = False,
) -> dict[str, Any]:
    q = (question or "").strip()
    if not q:
        raise ValueError("question is required")
    web_note = ""
    if web_search:
        if _should_run_help_web_search(q, history):
            web_note = _run_help_web_research(root, question=q, run_rel=run_rel, history=history)
        else:
            web_note = "web_search enabled: skipped (query does not require web lookup)."
    sources, indexed_files = _select_sources(
        root,
        q,
        max_sources=max(3, min(max_sources, 16)),
        run_rel=run_rel,
    )
    error_msg = ""
    used_llm = False
    used_model = ""
    requested_model, explicit_model = _resolve_requested_model(model)
    try:
        answer, used_model = _call_llm(
            q,
            sources,
            model=model,
            history=history,
            strict_model=bool(strict_model),
        )
        used_llm = True
    except Exception as exc:
        error_msg = str(exc)
        answer = _fallback_answer(q, sources)
    return {
        "answer": answer,
        "sources": sources,
        "used_llm": used_llm,
        "model": used_model,
        "requested_model": requested_model,
        "model_selection": "explicit" if explicit_model else "auto",
        "model_fallback": bool(used_llm and requested_model and used_model and requested_model != used_model),
        "error": error_msg,
        "indexed_files": indexed_files,
        "web_search": bool(web_search),
        "web_search_note": web_note,
        "action": _infer_safe_action(q, run_rel=run_rel),
        "capabilities": _help_capabilities(bool(web_search)),
    }


def stream_help_question(
    root: Path,
    question: str,
    *,
    model: str | None = None,
    strict_model: bool = False,
    max_sources: int = 8,
    history: list[dict[str, str]] | None = None,
    run_rel: str | None = None,
    web_search: bool = False,
) -> Iterator[dict[str, Any]]:
    q = (question or "").strip()
    if not q:
        raise ValueError("question is required")
    web_note = ""
    yield {
        "event": "activity",
        "id": "source_index",
        "status": "running",
        "message": "코드/문서 인덱스를 탐색 중입니다.",
    }
    if web_search:
        yield {
            "event": "activity",
            "id": "web_research",
            "status": "running",
            "message": "웹 보강 검색을 준비 중입니다.",
        }
        if _should_run_help_web_search(q, history):
            web_note = _run_help_web_research(root, question=q, run_rel=run_rel, history=history)
        else:
            web_note = "web_search enabled: skipped (query does not require web lookup)."
        web_status = "error" if web_note.lower().startswith("web_search failed") else "done"
        if "skipped" in web_note.lower():
            web_status = "skipped"
        yield {
            "event": "activity",
            "id": "web_research",
            "status": web_status,
            "message": web_note or "web search completed",
        }
    else:
        yield {
            "event": "activity",
            "id": "web_research",
            "status": "disabled",
            "message": "web_search 옵션이 꺼져 있습니다.",
        }
    sources, indexed_files = _select_sources(
        root,
        q,
        max_sources=max(3, min(max_sources, 16)),
        run_rel=run_rel,
    )
    yield {
        "event": "activity",
        "id": "source_index",
        "status": "done",
        "message": f"근거 후보 {indexed_files}개 인덱스 완료",
    }
    requested_model, explicit_model = _resolve_requested_model(model)
    yield {
        "event": "meta",
        "requested_model": requested_model,
        "model_selection": "explicit" if explicit_model else "auto",
        "indexed_files": indexed_files,
        "web_search": bool(web_search),
        "web_search_note": web_note,
        "capabilities": _help_capabilities(bool(web_search)),
    }
    error_msg = ""
    used_llm = False
    used_model = ""
    answer_parts: list[str] = []
    yield {
        "event": "activity",
        "id": "llm_generate",
        "status": "running",
        "message": "답변 생성 중입니다.",
    }
    try:
        chunk_iter, used_model = _call_llm_stream(
            q,
            sources,
            model=model,
            history=history,
            strict_model=bool(strict_model),
        )
        used_llm = True
        for chunk in chunk_iter:
            token = str(chunk or "")
            if not token:
                continue
            answer_parts.append(token)
            yield {"event": "delta", "text": token}
    except Exception as exc:
        error_msg = str(exc)
        yield {
            "event": "activity",
            "id": "llm_generate",
            "status": "error",
            "message": error_msg,
        }
    answer = "".join(answer_parts).strip()
    if not answer:
        answer = _fallback_answer(q, sources)
        if used_llm:
            used_llm = False
            if not error_msg:
                error_msg = "LLM returned empty content"
    if not error_msg:
        model_note = used_model or requested_model or "configured default"
        yield {
            "event": "activity",
            "id": "llm_generate",
            "status": "done",
            "message": f"완료 · model={model_note}",
        }
    yield {"event": "sources", "sources": sources}
    yield {
        "event": "done",
        "answer": answer,
        "sources": sources,
        "used_llm": used_llm,
        "model": used_model,
        "requested_model": requested_model,
        "model_selection": "explicit" if explicit_model else "auto",
        "model_fallback": bool(used_llm and requested_model and used_model and requested_model != used_model),
        "error": error_msg,
        "indexed_files": indexed_files,
        "web_search": bool(web_search),
        "web_search_note": web_note,
        "action": _infer_safe_action(q, run_rel=run_rel),
        "capabilities": _help_capabilities(bool(web_search)),
    }
