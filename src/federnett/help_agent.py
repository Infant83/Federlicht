from __future__ import annotations

import os
import re
import threading
import time
from dataclasses import dataclass
from pathlib import Path
from typing import Any

from .utils import safe_rel

try:
    import requests  # type: ignore
except Exception:  # pragma: no cover - optional runtime dependency
    requests = None  # type: ignore


_INCLUDE_PATHS = (
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
_MAX_SOURCE_TEXT = 1200
_MAX_CONTEXT_CHARS = 12000
_CACHE_LOCK = threading.Lock()
_INDEX_CACHE: dict[str, "_IndexCache"] = {}
_HISTORY_TURNS = 6
_HISTORY_CHARS = 900


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


def _is_path_allowed(rel_path: str) -> bool:
    rel = rel_path.replace("\\", "/")
    if not rel:
        return False
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
        if tok in _STOPWORDS:
            continue
        if tok in seen:
            continue
        seen.add(tok)
        deduped.append(tok)
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


def _chunk_score(path: str, text: str, tokens: list[str], question_l: str) -> float:
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
    return score


def _select_sources(root: Path, question: str, max_sources: int) -> tuple[list[dict[str, Any]], int]:
    index = _load_index(root)
    tokens = _query_tokens(question)
    question_l = question.strip().lower()
    scored: list[dict[str, Any]] = []
    for doc in index.docs.values():
        if not doc.lines:
            continue
        for start, end, text in _iter_chunks(doc.lines):
            score = _chunk_score(doc.rel_path, text, tokens, question_l)
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
    selected = scored[: max(1, max_sources)]
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


def _call_llm(
    question: str,
    sources: list[dict[str, Any]],
    model: str | None,
    history: list[dict[str, str]] | None = None,
) -> tuple[str, str]:
    api_key = os.getenv("OPENAI_API_KEY")
    if not api_key:
        raise RuntimeError("OPENAI_API_KEY is not set")
    if requests is None:
        raise RuntimeError("requests package is unavailable")
    chosen_model = (model or os.getenv("OPENAI_MODEL") or "").strip()
    if not chosen_model:
        raise RuntimeError("Model is not configured (set OPENAI_MODEL or pass model)")
    base_url = (os.getenv("OPENAI_BASE_URL") or os.getenv("OPENAI_API_BASE") or "https://api.openai.com").strip()
    url = base_url.rstrip("/") + "/v1/chat/completions"
    context = _build_context(sources)
    system = (
        "You are Federnett usage guide assistant. "
        "Answer in Korean by default. Provide practical steps and option guidance. "
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
        "  1) 핵심 답변(짧게)\n"
        "  2) 실행 절차\n"
        "  3) 옵션/체크 권장값\n"
        "  4) 주의사항\n"
        "  5) 근거 [S#] (소스가 있을 때)\n"
    )
    messages: list[dict[str, str]] = [{"role": "system", "content": system}]
    if history:
        messages.extend(_normalize_history(history))
    messages.append({"role": "user", "content": user})
    payload = {
        "model": chosen_model,
        "messages": messages,
        "temperature": 0.2,
        "max_tokens": 900,
    }
    resp = requests.post(
        url,
        headers={
            "Authorization": f"Bearer {api_key}",
            "Content-Type": "application/json",
        },
        json=payload,
        timeout=45,
    )
    if resp.status_code != 200:
        text = resp.text.strip()
        raise RuntimeError(f"LLM request failed: {resp.status_code} {text}")
    body = resp.json()
    choices = body.get("choices") or []
    if not choices:
        raise RuntimeError("LLM returned no choices")
    message = choices[0].get("message") or {}
    content = str(message.get("content") or "").strip()
    if not content:
        raise RuntimeError("LLM returned empty content")
    return content, chosen_model


def _fallback_answer(question: str, sources: list[dict[str, Any]]) -> str:
    if not sources:
        return (
            "질문과 직접 매칭되는 코드/문서를 찾지 못했습니다.\n"
            "기능명/옵션명을 포함해 다시 질문해 주세요.\n"
            "예: `Feather에서 --agentic-search와 --max-iter 차이`"
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


def answer_help_question(
    root: Path,
    question: str,
    *,
    model: str | None = None,
    max_sources: int = 8,
    history: list[dict[str, str]] | None = None,
) -> dict[str, Any]:
    q = (question or "").strip()
    if not q:
        raise ValueError("question is required")
    sources, indexed_files = _select_sources(root, q, max_sources=max(3, min(max_sources, 16)))
    error_msg = ""
    used_llm = False
    used_model = ""
    try:
        answer, used_model = _call_llm(q, sources, model=model, history=history)
        used_llm = True
    except Exception as exc:
        error_msg = str(exc)
        answer = _fallback_answer(q, sources)
    return {
        "answer": answer,
        "sources": sources,
        "used_llm": used_llm,
        "model": used_model,
        "error": error_msg,
        "indexed_files": indexed_files,
    }
