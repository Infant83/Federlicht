#!/usr/bin/env python3
# -*- coding: utf-8 -*-

"""
Generate a report from a HiDair Feather run using deepagents.

Usage:
  python scripts/deepagents_report.py --run ./runs/20260107_ai-trends --output ./runs/20260107_ai-trends/report.md
  python scripts/deepagents_report.py --run ./runs/20260107_ai-trends/archive --model gpt-4o
"""

from __future__ import annotations

import argparse
import html as html_lib
import re
from html.parser import HTMLParser
import json
import sys
from pathlib import Path
from typing import Optional


DEFAULT_MODEL = "gpt-5.2"


def parse_args() -> argparse.Namespace:
    ap = argparse.ArgumentParser(description="Deepagents report generator for HiDair Feather runs.")
    ap.add_argument("--run", required=True, help="Path to run folder or archive folder.")
    ap.add_argument("--output", help="Write report to this path (default: print to stdout).")
    ap.add_argument("--lang", default="ko", help="Report language preference (default: ko).")
    ap.add_argument("--prompt", help="Report focus prompt to guide the analysis.")
    ap.add_argument("--prompt-file", help="Path to a text file containing a report focus prompt.")
    ap.add_argument(
        "--model",
        default=DEFAULT_MODEL,
        help=f"Model name (default: {DEFAULT_MODEL} if supported).",
    )
    ap.add_argument(
        "--progress",
        action=argparse.BooleanOptionalAction,
        default=True,
        help="Print intermediate progress snippets (default: enabled).",
    )
    ap.add_argument("--progress-chars", type=int, default=800, help="Max chars for progress snippets.")
    ap.add_argument("--max-files", type=int, default=200, help="Max files to list in tool output.")
    ap.add_argument("--max-chars", type=int, default=12000, help="Max chars returned by read tool.")
    ap.add_argument("--max-refs", type=int, default=200, help="Max references to append (default: 200).")
    return ap.parse_args()


def resolve_archive(path: Path) -> tuple[Path, str]:
    path = path.resolve()
    if path.name == "archive":
        archive_dir = path
        run_dir = path.parent
    else:
        run_dir = path
        archive_dir = path / "archive"
    if not archive_dir.exists():
        raise FileNotFoundError(f"Archive folder not found: {archive_dir}")
    query_id = run_dir.name
    return archive_dir, query_id


def find_index_file(archive_dir: Path, query_id: str) -> Optional[Path]:
    candidate = archive_dir / f"{query_id}-index.md"
    if candidate.exists():
        return candidate
    legacy = archive_dir / "index.md"
    if legacy.exists():
        return legacy
    matches = sorted(archive_dir.glob("*-index.md"))
    if matches:
        return matches[0]
    return None


def extract_agent_text(result: object) -> str:
    if isinstance(result, dict):
        messages = result.get("messages")
        if messages:
            last = messages[-1]
            content = getattr(last, "content", None)
            if content is None and isinstance(last, dict):
                content = last.get("content")
            if content is not None:
                return str(content)
    return str(result)


def normalize_lang(value: str) -> str:
    text = value.strip().lower()
    if text in {"ko", "kor", "korean", "kr"}:
        return "Korean"
    if text in {"en", "eng", "english"}:
        return "English"
    return value.strip()


def load_report_prompt(prompt_text: Optional[str], prompt_file: Optional[str]) -> Optional[str]:
    parts: list[str] = []
    if prompt_file:
        path = Path(prompt_file)
        content = path.read_text(encoding="utf-8", errors="replace").strip()
        if content:
            parts.append(content)
    if prompt_text:
        text = prompt_text.strip()
        if text:
            parts.append(text)
    if not parts:
        return None
    return "\n\n".join(parts)


def choose_format(output: Optional[str]) -> str:
    if output and output.lower().endswith((".html", ".htm")):
        return "html"
    return "md"


def markdown_to_html(markdown_text: str) -> str:
    try:
        import markdown  # type: ignore
    except Exception:
        escaped = html_lib.escape(markdown_text)
        return f"<pre>{escaped}</pre>"
    return markdown.markdown(markdown_text, extensions=["extra", "tables", "fenced_code"])


_URL_RE = re.compile(r"(https?://[^\s<]+)")
_REL_PATH_RE = re.compile(r"(?<![\w/])(\./[A-Za-z0-9_./-]+)")
_ARCHIVE_PATH_RE = re.compile(r"(/archive/[A-Za-z0-9_./-]+)")
_WINDOWS_ABS_RE = re.compile(r"^[A-Za-z]:/")


def _linkify_text(text: str) -> str:
    def replace_url(match: re.Match[str]) -> str:
        url = match.group(1)
        trimmed = url.rstrip(").,;")
        suffix = url[len(trimmed) :]
        return f'<a href="{html_lib.escape(trimmed)}">{html_lib.escape(trimmed)}</a>{suffix}'

    def replace_rel(match: re.Match[str]) -> str:
        path = match.group(1)
        return f'<a href="{html_lib.escape(path)}">{html_lib.escape(path)}</a>'

    def replace_archive(match: re.Match[str]) -> str:
        path = match.group(1)
        href = f".{path}"
        return f'<a href="{html_lib.escape(href)}">{html_lib.escape(path)}</a>'

    text = _URL_RE.sub(replace_url, text)
    text = _REL_PATH_RE.sub(replace_rel, text)
    text = _ARCHIVE_PATH_RE.sub(replace_archive, text)
    return text


class _LinkifyHTMLParser(HTMLParser):
    def __init__(self) -> None:
        super().__init__(convert_charrefs=False)
        self._parts: list[str] = []
        self._stack: list[str] = []

    def handle_starttag(self, tag: str, attrs: list[tuple[str, Optional[str]]]) -> None:
        self._stack.append(tag)
        self._parts.append(self._rebuild_tag(tag, attrs, closed=False))

    def handle_startendtag(self, tag: str, attrs: list[tuple[str, Optional[str]]]) -> None:
        self._parts.append(self._rebuild_tag(tag, attrs, closed=True))

    def handle_endtag(self, tag: str) -> None:
        if self._stack and self._stack[-1] == tag:
            self._stack.pop()
        self._parts.append(f"</{tag}>")

    def handle_data(self, data: str) -> None:
        if any(t in {"a", "code", "pre"} for t in self._stack):
            self._parts.append(data)
        else:
            self._parts.append(_linkify_text(data))

    def handle_entityref(self, name: str) -> None:
        self._parts.append(f"&{name};")

    def handle_charref(self, name: str) -> None:
        self._parts.append(f"&#{name};")

    def handle_comment(self, data: str) -> None:
        self._parts.append(f"<!--{data}-->")

    def _rebuild_tag(self, tag: str, attrs: list[tuple[str, Optional[str]]], closed: bool) -> str:
        if not attrs:
            return f"<{tag}{' /' if closed else ''}>"
        parts = []
        for key, value in attrs:
            if value is None:
                parts.append(key)
            else:
                parts.append(f'{key}="{html_lib.escape(value, quote=True)}"')
        attrs_str = " ".join(parts)
        return f"<{tag} {attrs_str}{' /' if closed else ''}>"

    def get_html(self) -> str:
        return "".join(self._parts)


def linkify_html(html_text: str) -> str:
    parser = _LinkifyHTMLParser()
    parser.feed(html_text)
    return parser.get_html()


class SafeFilesystemBackend:
    def __init__(self, root_dir: Path) -> None:
        from deepagents.backends import FilesystemBackend  # type: ignore

        class _Backend(FilesystemBackend):
            def _map_windows_path(self, normalized: str) -> Optional[str]:
                root_norm = str(self.cwd).replace("\\", "/")
                if normalized.lower().startswith(root_norm.lower()):
                    rel = normalized[len(root_norm) :].lstrip("/")
                    return f"/{rel}" if rel else "/"
                for marker in ("/archive", "/instruction", "/report", "/report_notes"):
                    idx = normalized.lower().find(marker)
                    if idx != -1:
                        rel = normalized[idx + 1 :]
                        return f"/{rel}"
                return None

            def _resolve_path(self, key: str) -> Path:  # type: ignore[override]
                if self.virtual_mode and isinstance(key, str):
                    raw = key.strip()
                    normalized = raw.replace("\\", "/")
                    if _WINDOWS_ABS_RE.match(normalized):
                        mapped = self._map_windows_path(normalized)
                        if mapped is not None:
                            return super()._resolve_path(mapped)
                return super()._resolve_path(key)

        self._backend = _Backend(root_dir=root_dir, virtual_mode=True)

    def __getattr__(self, name: str):
        return getattr(self._backend, name)


def wrap_html(title: str, body_html: str) -> str:
    safe_title = html_lib.escape(title)
    return (
        "<!doctype html>\n"
        "<html lang=\"en\">\n"
        "<head>\n"
        "  <meta charset=\"utf-8\" />\n"
        f"  <title>{safe_title}</title>\n"
        "  <style>\n"
        "    :root {\n"
        "      --ink: #1d1c1a;\n"
        "      --muted: #5a5956;\n"
        "      --accent: #b24a2f;\n"
        "      --paper: #ffffff;\n"
        "      --paper-alt: #f6f1e8;\n"
        "      --rule: #e7dfd2;\n"
        "      --shadow: rgba(0, 0, 0, 0.08);\n"
        "      --link: #1d4e89;\n"
        "      --link-hover: #0d2b4a;\n"
        "    }\n"
        "    * { box-sizing: border-box; }\n"
        "    body {\n"
        "      margin: 0;\n"
        "      color: var(--ink);\n"
        "      background: radial-gradient(1200px 600px at 20% -10%, #f2efe8 0%, #f7f4ee 45%, #fdfcf9 100%);\n"
        "      font-family: \"Iowan Old Style\", \"Charter\", \"Palatino Linotype\", \"Book Antiqua\", Georgia, serif;\n"
        "      line-height: 1.6;\n"
        "    }\n"
        "    .page {\n"
        "      max-width: 980px;\n"
        "      margin: 48px auto 80px;\n"
        "      padding: 0 24px;\n"
        "    }\n"
        "    .masthead {\n"
        "      border-bottom: 1px solid var(--rule);\n"
        "      padding-bottom: 16px;\n"
        "      margin-bottom: 32px;\n"
        "    }\n"
        "    .kicker {\n"
        "      font-family: \"Avenir Next\", \"Gill Sans\", \"Trebuchet MS\", \"Helvetica Neue\", sans-serif;\n"
        "      font-size: 0.82rem;\n"
        "      letter-spacing: 0.22em;\n"
        "      text-transform: uppercase;\n"
        "      color: var(--accent);\n"
        "    }\n"
        "    .report-title {\n"
        "      font-family: \"Avenir Next\", \"Gill Sans\", \"Trebuchet MS\", \"Helvetica Neue\", sans-serif;\n"
        "      font-size: 2.4rem;\n"
        "      margin: 8px 0 6px;\n"
        "    }\n"
        "    .report-deck {\n"
        "      color: var(--muted);\n"
        "      font-size: 1.05rem;\n"
        "    }\n"
        "    .article {\n"
        "      background: var(--paper);\n"
        "      border: 1px solid var(--rule);\n"
        "      border-radius: 16px;\n"
        "      padding: 36px 40px;\n"
        "      box-shadow: 0 18px 45px var(--shadow);\n"
        "    }\n"
        "    .article h1, .article h2, .article h3, .article h4 {\n"
        "      font-family: \"Avenir Next\", \"Gill Sans\", \"Trebuchet MS\", \"Helvetica Neue\", sans-serif;\n"
        "      color: var(--ink);\n"
        "    }\n"
        "    .article h1 { font-size: 2rem; margin-top: 0; }\n"
        "    .article h2 {\n"
        "      font-size: 1.5rem;\n"
        "      margin-top: 2.4rem;\n"
        "      padding-top: 0.6rem;\n"
        "      border-top: 1px solid var(--rule);\n"
        "    }\n"
        "    .article h3 { font-size: 1.2rem; margin-top: 1.6rem; }\n"
        "    .article p { font-size: 1.05rem; }\n"
        "    .article ul, .article ol { padding-left: 1.4rem; }\n"
        "    .article blockquote {\n"
        "      border-left: 3px solid var(--accent);\n"
        "      margin: 1.6rem 0;\n"
        "      padding: 0.5rem 1.2rem;\n"
        "      background: var(--paper-alt);\n"
        "      color: var(--muted);\n"
        "      font-style: italic;\n"
        "    }\n"
        "    .article a {\n"
        "      color: var(--link);\n"
        "      text-decoration: none;\n"
        "      border-bottom: 1px solid rgba(29, 78, 137, 0.35);\n"
        "    }\n"
        "    .article a:hover { color: var(--link-hover); border-bottom-color: var(--link-hover); }\n"
        "    .article code {\n"
        "      background: #f7f6f3;\n"
        "      padding: 2px 4px;\n"
        "      border-radius: 6px;\n"
        "      font-family: \"SFMono-Regular\", \"Consolas\", \"Liberation Mono\", \"Courier New\", monospace;\n"
        "      font-size: 0.95em;\n"
        "    }\n"
        "    .article pre {\n"
        "      background: #f7f6f3;\n"
        "      border: 1px solid var(--rule);\n"
        "      border-radius: 12px;\n"
        "      padding: 14px;\n"
        "      overflow-x: auto;\n"
        "      white-space: pre-wrap;\n"
        "    }\n"
        "    .article table { border-collapse: collapse; width: 100%; margin: 1.2rem 0; }\n"
        "    .article th, .article td { border: 1px solid var(--rule); padding: 8px 10px; }\n"
        "    .article th { background: var(--paper-alt); text-align: left; }\n"
        "    .article hr { border: none; border-top: 1px solid var(--rule); margin: 2rem 0; }\n"
        "    @media (max-width: 720px) {\n"
        "      .page { margin: 32px auto 56px; }\n"
        "      .article { padding: 24px; }\n"
        "      .report-title { font-size: 1.9rem; }\n"
        "    }\n"
        "  </style>\n"
        "</head>\n"
        "<body>\n"
        "  <div class=\"page\">\n"
        "    <header class=\"masthead\">\n"
        "      <div class=\"kicker\">HiDair Feather</div>\n"
        f"      <div class=\"report-title\">{safe_title}</div>\n"
        "      <div class=\"report-deck\">Research review and tech survey</div>\n"
        "    </header>\n"
        "    <main class=\"article\">\n"
        f"{body_html}\n"
        "    </main>\n"
        "  </div>\n"
        "</body>\n"
        "</html>\n"
    )


def iter_jsonl(path: Path):
    with path.open("r", encoding="utf-8", errors="replace") as handle:
        for line in handle:
            line = line.strip()
            if not line:
                continue
            try:
                yield json.loads(line)
            except json.JSONDecodeError:
                continue


def collect_references(archive_dir: Path, run_dir: Path, max_refs: int) -> list[dict]:
    refs: list[dict] = []
    seen: set[str] = set()

    def add_ref(url: Optional[str], title: Optional[str], source: str, archive_path: Path, extra: Optional[str] = None) -> None:
        if not url:
            return
        url = url.strip()
        if not url or url in seen:
            return
        seen.add(url)
        refs.append(
            {
                "title": title or url,
                "url": url,
                "source": source,
                "archive": f"./{archive_path.relative_to(run_dir).as_posix()}",
                "extra": extra,
            }
        )

    def limit_reached() -> bool:
        return max_refs > 0 and len(refs) >= max_refs

    tavily = archive_dir / "tavily_search.jsonl"
    if tavily.exists():
        for entry in iter_jsonl(tavily):
            results = entry.get("result", {}).get("results") or entry.get("results") or []
            for item in results:
                add_ref(item.get("url"), item.get("title"), "tavily", tavily)
                if limit_reached():
                    return refs

    openalex = archive_dir / "openalex" / "works.jsonl"
    if openalex.exists():
        for entry in iter_jsonl(openalex):
            work = entry.get("work") or entry
            url = work.get("landing_page_url") or work.get("doi") or work.get("pdf_url")
            title = work.get("title")
            add_ref(url, title, "openalex", openalex)
            if limit_reached():
                return refs

    arxiv = archive_dir / "arxiv" / "papers.jsonl"
    if arxiv.exists():
        for entry in iter_jsonl(arxiv):
            url = entry.get("entry_id") or entry.get("pdf_url")
            title = entry.get("title")
            add_ref(url, title, "arxiv", arxiv)
            if limit_reached():
                return refs

    youtube = archive_dir / "youtube" / "videos.jsonl"
    if youtube.exists():
        for entry in iter_jsonl(youtube):
            video = entry.get("video") or {}
            url = video.get("url") or entry.get("direct_url")
            title = video.get("title") or entry.get("title")
            extra = None
            channel = video.get("channel_title")
            if channel:
                extra = f"channel: {channel}"
            add_ref(url, title, "youtube", youtube, extra=extra)
            if limit_reached():
                return refs

    local = archive_dir / "local" / "manifest.jsonl"
    if local.exists():
        for entry in iter_jsonl(local):
            source_path = entry.get("source_path") or entry.get("path")
            title = entry.get("title") or source_path
            add_ref(source_path, title, "local", local)
            if limit_reached():
                return refs

    return refs


def render_references_md(refs: list[dict]) -> str:
    if not refs:
        return ""
    lines = ["", "## Source Index (Auto)", ""]
    for ref in refs:
        extra = f" ({ref['extra']})" if ref.get("extra") else ""
        title = ref["title"]
        url = ref["url"]
        archive = ref["archive"]
        lines.append(
            f"- [{title}]({url}){extra} [source: {ref['source']}; archive: [{archive}]({archive})]"
        )
    return "\n".join(lines)


def extract_keywords(text: Optional[str]) -> list[str]:
    if not text:
        return []
    tokens = re.findall(r"[A-Za-z]{3,}|[가-힣]{2,}", text)
    stop = {
        "focus",
        "insight",
        "insights",
        "trend",
        "trends",
        "implication",
        "implications",
        "analysis",
        "review",
        "report",
        "paper",
        "papers",
        "research",
        "technical",
        "technology",
        "applications",
    }
    cleaned = []
    for token in tokens:
        low = token.lower()
        if low in stop:
            continue
        cleaned.append(low)
    return sorted(set(cleaned))


def extract_urls(text: Optional[str]) -> list[str]:
    if not text:
        return []
    return _URL_RE.findall(text)


def filter_references(refs: list[dict], prompt_text: Optional[str], report_text: str, max_refs: int) -> list[dict]:
    if not refs:
        return []
    urls = set(extract_urls(report_text))
    selected = [ref for ref in refs if ref["url"] in urls]
    if not selected:
        keywords = extract_keywords(prompt_text)
        if keywords:
            filtered = []
            for ref in refs:
                hay = f"{ref['title']} {ref['url']}".lower()
                if any(key in hay for key in keywords):
                    filtered.append(ref)
            selected = filtered
    if not selected:
        selected = refs
    if max_refs > 0:
        selected = selected[:max_refs]
    return selected


def normalize_report_paths(text: str, run_dir: Path) -> str:
    variants = [str(run_dir), str(run_dir).replace("\\", "/")]
    for variant in variants:
        if not variant:
            continue
        text = text.replace(variant, ".")
        text = text.replace("/" + variant, ".")
        text = text.replace("\\" + variant, ".")
    return text


def print_progress(label: str, content: str, enabled: bool, max_chars: int) -> None:
    if not enabled:
        return
    snippet = content.strip()
    if max_chars > 0 and len(snippet) > max_chars:
        snippet = f"{snippet[:max_chars]}\n... [truncated]"
    print(f"\n[{label}]\n{snippet}\n")


def main() -> int:
    args = parse_args()
    try:
        from deepagents import create_deep_agent  # type: ignore
    except Exception:
        print("deepagents is required. Install with: python -m pip install deepagents", file=sys.stderr)
        return 1

    archive_dir, query_id = resolve_archive(Path(args.run))
    archive_dir = archive_dir.resolve()
    run_dir = archive_dir.parent
    index_file = find_index_file(archive_dir, query_id)
    backend = SafeFilesystemBackend(root_dir=run_dir)

    def resolve_rel_path(rel_path: str) -> Path:
        candidate = Path(rel_path)
        if not candidate.is_absolute():
            candidate = archive_dir / candidate
        resolved = candidate.resolve()
        if archive_dir != resolved and archive_dir not in resolved.parents:
            raise ValueError(f"Path is outside archive: {rel_path}")
        if not resolved.exists():
            raise FileNotFoundError(f"Path does not exist: {rel_path}")
        return resolved

    def list_archive_files(max_files: Optional[int] = None) -> str:
        """List archive files with sizes. Use to discover what to read."""
        files = []
        for path in sorted(archive_dir.rglob("*")):
            if path.is_file():
                rel = path.relative_to(archive_dir).as_posix()
                files.append({"path": rel, "bytes": path.stat().st_size})
        limit = args.max_files if max_files is None else max_files
        payload = {"total_files": len(files), "files": files[:limit]}
        return json.dumps(payload, indent=2, ensure_ascii=True)

    def read_archive_file(rel_path: str, start: int = 0, max_chars: Optional[int] = None) -> str:
        """Read a text file from the archive with optional paging."""
        try:
            path = resolve_rel_path(rel_path)
        except (FileNotFoundError, ValueError) as exc:
            return f"[error] {exc}"
        text = path.read_text(encoding="utf-8", errors="replace")
        start = max(0, start)
        limit = args.max_chars if max_chars is None else max_chars
        return text[start : start + limit]

    language = normalize_lang(args.lang)
    report_prompt = load_report_prompt(args.prompt, args.prompt_file)
    system_prompt = (
        "You are a research report writer. Use the provided tools to read files in a HiDair Feather archive. "
        "Summarize findings with evidence, cite file paths, and avoid guessing. When possible, include original "
        "source URLs in references (not only archive paths). Always read available JSONL metadata files "
        "(tavily_search.jsonl, openalex/works.jsonl, arxiv/papers.jsonl, youtube/videos.jsonl, local/manifest.jsonl) "
        "before writing the report; if a file is large, sample multiple chunks with paging. "
        "The JSONL files are indices of sources; do not dump raw JSON. Use them to locate and summarize source content. "
        "Follow any report focus prompt provided in the user message. "
        "Ignore off-topic sources that do not match the report focus. "
        f"Write the report in {language}. Keep proper nouns and source titles in their original language. "
        "Note: the filesystem root '/' is mapped to the run folder."
    )

    user_message = [
        f"Generate a concise report for run '{query_id}'.",
        f"Archive path: {archive_dir}",
        "Use the tools to list files and read index/jsonl/text as needed.",
        "Required: read any JSONL metadata files that exist (tavily_search.jsonl, openalex/works.jsonl, "
        "arxiv/papers.jsonl, youtube/videos.jsonl, local/manifest.jsonl).",
    ]
    if index_file:
        rel_index = index_file.relative_to(archive_dir).as_posix()
        user_message.append(f"Index file: {rel_index}")
    if report_prompt:
        user_message.append("Report focus prompt:")
        user_message.append(report_prompt)

    kwargs = {
        "tools": [list_archive_files, read_archive_file],
        "system_prompt": system_prompt,
        "backend": backend,
    }
    agent = None
    if args.model:
        try:
            agent = create_deep_agent(model=args.model, **kwargs)
        except Exception as exc:  # pragma: no cover - fallback path
            msg = str(exc).lower()
            if args.model == DEFAULT_MODEL and any(token in msg for token in ("model", "unsupported", "unknown")):
                print(
                    f"Model '{DEFAULT_MODEL}' not supported by this deepagents setup. Falling back to default.",
                    file=sys.stderr,
                )
            else:
                raise
    if agent is None:
        agent = create_deep_agent(**kwargs)
    result = agent.invoke({"messages": [{"role": "user", "content": "\n".join(user_message)}]})
    report = extract_agent_text(result)
    report = normalize_report_paths(report, run_dir)
    if report_prompt:
        report = f"{report.rstrip()}\n\n## Report Prompt\n{report_prompt}\n"
    refs = collect_references(archive_dir, run_dir, args.max_refs)
    refs = filter_references(refs, report_prompt, report, args.max_refs)
    report = f"{report.rstrip()}{render_references_md(refs)}"
    print_progress("Report Preview", report, args.progress, args.progress_chars)

    output_format = choose_format(args.output)
    rendered = report
    if output_format == "html":
        rendered = wrap_html(f"HiDair Feather Report - {query_id}", linkify_html(markdown_to_html(report)))

    if args.output:
        out_path = Path(args.output)
        out_path.parent.mkdir(parents=True, exist_ok=True)
        out_path.write_text(rendered, encoding="utf-8")
        print(f"Wrote report: {out_path}")
    else:
        print(rendered)

    return 0


if __name__ == "__main__":
    raise SystemExit(main())
