from __future__ import annotations

from pathlib import Path
from typing import Callable, Optional
import hashlib
import json
import os
import re
import time
import urllib.parse

import requests

from . import __version__
from .tavily import TavilyClient
from .local_ops import html_to_text


def request_headers() -> dict[str, str]:
    return {"User-Agent": f"Feather/{__version__} (+https://example.invalid)"}


def slugify_url(url: str, max_len: int = 80) -> str:
    parsed = urllib.parse.urlparse(url)
    host = parsed.netloc.replace("www.", "")
    path = parsed.path.strip("/").replace("/", "_")
    base = "_".join([part for part in (host, path) if part])
    cleaned = re.sub(r"[^A-Za-z0-9._-]+", "_", base).strip("_")
    if not cleaned:
        cleaned = "resource"
    digest = hashlib.sha1(url.encode("utf-8")).hexdigest()[:8]
    trimmed = cleaned[:max_len]
    return f"{trimmed}-{digest}" if digest else trimmed


def truncate_for_view(text: str, max_chars: int) -> tuple[str, bool]:
    if max_chars <= 0 or len(text) <= max_chars:
        return text, False
    return text[:max_chars].rstrip(), True


def select_top_urls(search_entries: list[dict], max_fetch: int) -> list[dict]:
    scored: list[tuple[float, dict]] = []
    for entry in search_entries:
        results = entry.get("result", {}).get("results") or entry.get("results") or []
        for item in results:
            url = item.get("url")
            if not url:
                continue
            score = item.get("score") or 0.0
            scored.append((float(score), item))
    scored.sort(key=lambda pair: pair[0], reverse=True)
    selected: list[dict] = []
    seen: set[str] = set()
    for _, item in scored:
        url = item.get("url")
        if not url or url in seen:
            continue
        seen.add(url)
        selected.append(item)
        if len(selected) >= max_fetch:
            break
    return selected


def run_supporting_web_research(
    supporting_dir: Path,
    queries: list[str],
    max_results: int,
    max_fetch: int,
    max_chars: int,
    max_pdf_pages: int,
    *,
    api_key: Optional[str] = None,
    pdf_text_reader: Optional[Callable[[Path, int, int, int], str]] = None,
) -> tuple[str, list[dict]]:
    api_key = api_key or os.getenv("TAVILY_API_KEY")
    if not api_key:
        return "Web research skipped: missing TAVILY_API_KEY.", []
    supporting_dir.mkdir(parents=True, exist_ok=True)
    search_path = supporting_dir / "web_search.jsonl"
    fetch_path = supporting_dir / "web_fetch.jsonl"
    extract_dir = supporting_dir / "web_extract"
    pdf_dir = supporting_dir / "web_pdf"
    text_dir = supporting_dir / "web_text"
    extract_dir.mkdir(parents=True, exist_ok=True)
    pdf_dir.mkdir(parents=True, exist_ok=True)
    text_dir.mkdir(parents=True, exist_ok=True)
    search_entries: list[dict] = []

    def append_jsonl(path: Path, payload: dict) -> None:
        with path.open("a", encoding="utf-8") as handle:
            handle.write(json.dumps(payload, ensure_ascii=False) + "\n")

    tavily = TavilyClient(api_key=api_key)
    for query in queries:
        try:
            result = tavily.search(
                query=query,
                max_results=max_results,
                search_depth="advanced",
                include_raw_content=False,
            )
            entry = {"query": query, "result": result, "timestamp": time.time()}
            append_jsonl(search_path, entry)
            search_entries.append(entry)
        except Exception as exc:
            append_jsonl(search_path, {"query": query, "error": str(exc), "timestamp": time.time()})

    selected = select_top_urls(search_entries, max_fetch)
    for idx, item in enumerate(selected, start=1):
        url = item.get("url")
        if not url:
            continue
        slug = slugify_url(url)
        record = {
            "url": url,
            "title": item.get("title"),
            "score": item.get("score"),
            "timestamp": time.time(),
        }
        try:
            is_pdf = url.lower().endswith(".pdf")
            if not is_pdf:
                try:
                    head = requests.head(url, timeout=20, headers=request_headers(), allow_redirects=True)
                    ctype = head.headers.get("content-type", "").lower()
                    if "pdf" in ctype:
                        is_pdf = True
                except Exception:
                    pass
            if is_pdf:
                pdf_path = pdf_dir / f"{idx:03d}_{slug}.pdf"
                text_path = text_dir / f"{idx:03d}_{slug}.txt"
                with requests.get(url, stream=True, timeout=60, headers=request_headers()) as resp:
                    resp.raise_for_status()
                    with pdf_path.open("wb") as handle:
                        for chunk in resp.iter_content(chunk_size=8192):
                            if chunk:
                                handle.write(chunk)
                record["pdf_path"] = pdf_path.as_posix()
                if pdf_text_reader:
                    pdf_text = pdf_text_reader(pdf_path, max_pdf_pages, max_chars, 0)
                    text_path.write_text(pdf_text, encoding="utf-8")
                    record["text_path"] = text_path.as_posix()
            else:
                extract_path = extract_dir / f"{idx:03d}_{slug}.txt"
                try:
                    extract_res = tavily.extract(url=url, include_images=False, extract_depth="advanced")
                    content = ""
                    results = extract_res.get("results") or extract_res.get("data") or []
                    if results and isinstance(results, list):
                        content = results[0].get("content") or results[0].get("raw_content") or ""
                    if not content:
                        content = json.dumps(extract_res, ensure_ascii=False)
                except Exception:
                    resp = requests.get(url, timeout=60, headers=request_headers())
                    resp.raise_for_status()
                    content = html_to_text(resp.text)
                content, truncated = truncate_for_view(content, max_chars)
                if truncated:
                    content = f"[truncated]\n{content}"
                extract_path.write_text(content, encoding="utf-8")
                record["extract_path"] = extract_path.as_posix()
        except Exception as exc:
            record["error"] = str(exc)
        append_jsonl(fetch_path, record)

    summary_lines = [
        f"Web research queries: {len(queries)}",
        f"Web search results stored: {search_path.relative_to(supporting_dir).as_posix()}",
        f"Web extracts stored: {extract_dir.relative_to(supporting_dir).as_posix()}",
    ]
    return "\n".join(summary_lines), search_entries
