import json
from dataclasses import dataclass
from pathlib import Path
from typing import Dict, List, Optional


@dataclass
class RunSummary:
    run_dir: Path
    query_id: str
    date: Optional[str]
    queries: int
    urls: int
    arxiv_ids: int
    index_path: Optional[Path]
    tavily_search: bool
    tavily_extract_count: int
    arxiv_papers: bool
    arxiv_pdf_count: int
    arxiv_text_count: int
    openalex_works: bool
    openalex_pdf_count: int
    openalex_text_count: int
    youtube_videos: bool
    youtube_video_count: int
    youtube_transcript_count: int
    local_raw_count: int
    local_text_count: int
    web_pdf_count: int
    web_text_count: int


def find_run_dirs(root: Path) -> List[Path]:
    if not root.exists():
        raise SystemExit(f"Path not found: {root}")
    if (root / "archive").exists():
        return [root]
    if root.name == "archive" and root.parent.exists():
        return [root.parent]
    dirs: List[Path] = []
    for entry in sorted(root.iterdir()):
        if entry.is_dir() and (entry / "archive").exists():
            dirs.append(entry)
    return dirs


def load_job_counts(run_dir: Path) -> tuple[Optional[str], int, int, int]:
    job_path = run_dir / "archive" / "_job.json"
    if not job_path.exists():
        return None, 0, 0, 0
    try:
        data = json.loads(job_path.read_text(encoding="utf-8"))
    except Exception:
        return None, 0, 0, 0
    date = data.get("date")
    query_specs = data.get("query_specs")
    if isinstance(query_specs, list):
        queries = len(query_specs)
    else:
        queries = len(data.get("queries") or [])
    urls = len(data.get("urls") or [])
    arxiv_ids = len(data.get("arxiv_ids") or [])
    return date, queries, urls, arxiv_ids


def pick_index_path(run_dir: Path, query_id: str) -> Optional[Path]:
    archive = run_dir / "archive"
    cand = archive / f"{query_id}-index.md"
    if cand.exists():
        return cand
    matches = sorted(archive.glob("*-index.md"))
    if matches:
        return matches[0]
    legacy = archive / "index.md"
    if legacy.exists():
        return legacy
    return None


def count_youtube_videos(path: Path) -> int:
    if not path.exists():
        return 0
    total = 0
    for line in path.read_text(encoding="utf-8", errors="ignore").splitlines():
        line = line.strip()
        if not line:
            continue
        try:
            data = json.loads(line)
        except json.JSONDecodeError:
            continue
        videos = data.get("videos")
        if isinstance(videos, list):
            total += len(videos)
            continue
        video = data.get("video")
        if isinstance(video, dict):
            total += 1
    return total


def collect_run_summary(run_dir: Path) -> RunSummary:
    query_id = run_dir.name
    archive = run_dir / "archive"
    date, queries, urls, arxiv_ids = load_job_counts(run_dir)
    index_path = pick_index_path(run_dir, query_id)

    tavily_search = (archive / "tavily_search.jsonl").exists()
    tavily_extract_count = len(list((archive / "tavily_extract").glob("*.txt"))) if (archive / "tavily_extract").exists() else 0

    arxiv_papers = (archive / "arxiv" / "papers.jsonl").exists()
    arxiv_pdf_count = len(list((archive / "arxiv" / "pdf").glob("*.pdf"))) if (archive / "arxiv" / "pdf").exists() else 0
    arxiv_text_count = len(list((archive / "arxiv" / "text").glob("*.txt"))) if (archive / "arxiv" / "text").exists() else 0

    openalex_works = (archive / "openalex" / "works.jsonl").exists()
    openalex_pdf_count = len(list((archive / "openalex" / "pdf").glob("*.pdf"))) if (archive / "openalex" / "pdf").exists() else 0
    openalex_text_count = (
        len(list((archive / "openalex" / "text").glob("*.txt"))) if (archive / "openalex" / "text").exists() else 0
    )

    youtube_videos = (archive / "youtube" / "videos.jsonl").exists()
    youtube_video_count = count_youtube_videos(archive / "youtube" / "videos.jsonl") if youtube_videos else 0
    youtube_transcript_count = (
        len(list((archive / "youtube" / "transcripts").glob("*.txt")))
        if (archive / "youtube" / "transcripts").exists()
        else 0
    )

    web_pdf_count = len(list((archive / "web" / "pdf").glob("*.pdf"))) if (archive / "web" / "pdf").exists() else 0
    web_text_count = len(list((archive / "web" / "text").glob("*.txt"))) if (archive / "web" / "text").exists() else 0
    local_raw_count = len(list((archive / "local" / "raw").glob("*"))) if (archive / "local" / "raw").exists() else 0
    local_text_count = len(list((archive / "local" / "text").glob("*.txt"))) if (archive / "local" / "text").exists() else 0

    return RunSummary(
        run_dir=run_dir,
        query_id=query_id,
        date=date,
        queries=queries,
        urls=urls,
        arxiv_ids=arxiv_ids,
        index_path=index_path,
        tavily_search=tavily_search,
        tavily_extract_count=tavily_extract_count,
        arxiv_papers=arxiv_papers,
        arxiv_pdf_count=arxiv_pdf_count,
        arxiv_text_count=arxiv_text_count,
        openalex_works=openalex_works,
        openalex_pdf_count=openalex_pdf_count,
        openalex_text_count=openalex_text_count,
        youtube_videos=youtube_videos,
        youtube_video_count=youtube_video_count,
        youtube_transcript_count=youtube_transcript_count,
        local_raw_count=local_raw_count,
        local_text_count=local_text_count,
        web_pdf_count=web_pdf_count,
        web_text_count=web_text_count,
    )


def format_run_list(summaries: List[RunSummary]) -> str:
    if not summaries:
        return "No runs found."
    q_width = max(len(s.query_id) for s in summaries)
    header = (
        f"{'QueryID'.ljust(q_width)}  Date        Q/U/A   Tavily    arXiv    OpenAlex  YouTube  Local   WebPDF  Index"
    )
    lines = [header, "-" * len(header)]
    for s in summaries:
        date = (s.date or "-")[:10]
        q_u_a = f"{s.queries}/{s.urls}/{s.arxiv_ids}".ljust(7)
        tavily = "S" if s.tavily_search else "-"
        if s.tavily_extract_count:
            tavily = f"{tavily}+E{s.tavily_extract_count}"
        arxiv = f"{s.arxiv_pdf_count}/{s.arxiv_text_count}" if s.arxiv_papers else "-"
        oa = f"{s.openalex_pdf_count}/{s.openalex_text_count}" if s.openalex_works else "-"
        yt = f"{s.youtube_video_count}/{s.youtube_transcript_count}" if s.youtube_videos else "-"
        local = f"{s.local_raw_count}/{s.local_text_count}" if (s.local_raw_count or s.local_text_count) else "-"
        web = f"{s.web_pdf_count}/{s.web_text_count}" if (s.web_pdf_count or s.web_text_count) else "-"
        idx = "Y" if s.index_path else "-"
        lines.append(
            f"{s.query_id.ljust(q_width)}  {date}  {q_u_a}  {tavily.ljust(8)}  {arxiv.ljust(7)}  {oa.ljust(8)}  {yt.ljust(7)}  {local.ljust(6)}  {web.ljust(6)}  {idx}"
        )
    return "\n".join(lines)


def summary_to_dict(summary: RunSummary) -> dict:
    return {
        "query_id": summary.query_id,
        "path": str(summary.run_dir),
        "date": summary.date,
        "counts": {
            "queries": summary.queries,
            "urls": summary.urls,
            "arxiv_ids": summary.arxiv_ids,
        },
        "index_path": str(summary.index_path) if summary.index_path else None,
        "tavily_search": summary.tavily_search,
        "tavily_extract_count": summary.tavily_extract_count,
        "arxiv_papers": summary.arxiv_papers,
        "arxiv_pdf_count": summary.arxiv_pdf_count,
        "arxiv_text_count": summary.arxiv_text_count,
        "openalex_works": summary.openalex_works,
        "openalex_pdf_count": summary.openalex_pdf_count,
        "openalex_text_count": summary.openalex_text_count,
        "youtube_videos": summary.youtube_videos,
        "youtube_video_count": summary.youtube_video_count,
        "youtube_transcript_count": summary.youtube_transcript_count,
        "local_raw_count": summary.local_raw_count,
        "local_text_count": summary.local_text_count,
        "web_pdf_count": summary.web_pdf_count,
        "web_text_count": summary.web_text_count,
    }


def render_review(run_dir: Path) -> str:
    summary = collect_run_summary(run_dir)
    lines = [
        f"Run: {summary.query_id}",
        f"Path: {summary.run_dir}",
        f"Date: {summary.date or '-'}",
        f"Counts: queries={summary.queries} urls={summary.urls} arxiv_ids={summary.arxiv_ids}",
        "",
        "Outputs:",
        f"- index: {summary.index_path if summary.index_path else '(missing)'}",
        f"- tavily_search.jsonl: {'yes' if summary.tavily_search else 'no'}",
        f"- tavily_extract: {summary.tavily_extract_count} files",
        f"- arxiv/papers.jsonl: {'yes' if summary.arxiv_papers else 'no'} (pdf={summary.arxiv_pdf_count}, txt={summary.arxiv_text_count})",
        f"- openalex/works.jsonl: {'yes' if summary.openalex_works else 'no'} (pdf={summary.openalex_pdf_count}, txt={summary.openalex_text_count})",
        f"- youtube/videos.jsonl: {'yes' if summary.youtube_videos else 'no'} (videos={summary.youtube_video_count}, transcripts={summary.youtube_transcript_count})",
        f"- local: {summary.local_raw_count} raw (txt={summary.local_text_count})",
        f"- web/pdf: {summary.web_pdf_count} (txt={summary.web_text_count})",
        "",
    ]
    if summary.index_path and summary.index_path.exists():
        lines.append("Index:")
        lines.append(summary.index_path.read_text(encoding="utf-8", errors="ignore").strip())
    return "\n".join(lines)


def render_review_json(run_dir: Path) -> str:
    summary = collect_run_summary(run_dir)
    payload = summary_to_dict(summary)
    if summary.index_path and summary.index_path.exists():
        payload["index_text"] = summary.index_path.read_text(encoding="utf-8", errors="ignore").strip()
    else:
        payload["index_text"] = None
    return json.dumps(payload, indent=2)


def render_review_full(run_dir: Path) -> str:
    summary = collect_run_summary(run_dir)
    archive = run_dir / "archive"
    lines = [
        f"Run: {summary.query_id}",
        f"Path: {summary.run_dir}",
        f"Date: {summary.date or '-'}",
        f"Counts: queries={summary.queries} urls={summary.urls} arxiv_ids={summary.arxiv_ids}",
        "",
    ]

    if summary.index_path and summary.index_path.exists():
        lines.append("===== INDEX =====")
        lines.append(summary.index_path.read_text(encoding="utf-8", errors="ignore").strip())
        lines.append("")

    def append_text_file(label: str, path: Path) -> None:
        if not path.exists():
            return
        lines.append(f"===== {label} =====")
        lines.append(f"-- {path} --")
        lines.append(path.read_text(encoding="utf-8", errors="ignore").strip())
        lines.append("")

    def append_text_files(label: str, paths: List[Path]) -> None:
        if not paths:
            return
        lines.append(f"===== {label} =====")
        for path in paths:
            lines.append(f"-- {path} --")
            lines.append(path.read_text(encoding="utf-8", errors="ignore").strip())
            lines.append("")

    def append_jsonl_full(label: str, path: Path) -> None:
        if not path.exists():
            return
        lines.append(f"===== {label} =====")
        lines.append(render_jsonl_review_full(path))
        lines.append("")

    append_jsonl_full("Tavily Search (full)", archive / "tavily_search.jsonl")
    append_text_files("Tavily Extract (full)", sorted((archive / "tavily_extract").glob("*.txt")))
    append_jsonl_full("OpenAlex Works (full)", archive / "openalex" / "works.jsonl")
    append_jsonl_full("arXiv Papers (full)", archive / "arxiv" / "papers.jsonl")
    append_jsonl_full("YouTube Videos (full)", archive / "youtube" / "videos.jsonl")

    append_text_files("OpenAlex Texts (full)", sorted((archive / "openalex" / "text").glob("*.txt")))
    append_text_files("arXiv Texts (full)", sorted((archive / "arxiv" / "text").glob("*.txt")))
    append_text_files("Web Texts (full)", sorted((archive / "web" / "text").glob("*.txt")))
    append_text_files("YouTube Transcripts (full)", sorted((archive / "youtube" / "transcripts").glob("*.txt")))
    append_jsonl_full("Local Manifest (full)", archive / "local" / "manifest.jsonl")
    append_text_files("Local Texts (full)", sorted((archive / "local" / "text").glob("*.txt")))

    return "\n".join(lines).rstrip()


def truncate_text(value: Optional[str], max_len: int) -> str:
    if not value:
        return "-"
    text = " ".join(str(value).split())
    if len(text) <= max_len:
        return text
    if max_len <= 3:
        return text[:max_len]
    return f"{text[: max_len - 3]}..."


def classify_result_types(results: List[dict]) -> Dict[str, int]:
    counts = {"pdf": 0, "arxiv": 0, "web": 0}
    for result in results:
        url = str(result.get("url") or "").lower()
        if url.endswith(".pdf"):
            counts["pdf"] += 1
        elif "arxiv.org" in url:
            counts["arxiv"] += 1
        else:
            counts["web"] += 1
    return counts


def render_tavily_search_review(path: Path) -> str:
    rows: List[dict] = []
    total_entries = 0
    for line in path.read_text(encoding="utf-8", errors="ignore").splitlines():
        line = line.strip()
        if not line:
            continue
        total_entries += 1
        try:
            data = json.loads(line)
        except json.JSONDecodeError:
            rows.append(
                {
                    "query": "(invalid json)",
                    "results": 0,
                    "types": "-",
                    "top_summary": "-",
                    "query_summary": "-",
                }
            )
            continue
        query = data.get("query") or (data.get("result") or {}).get("query") or "-"
        result_block = data.get("result") or {}
        results = result_block.get("results") or []
        counts = classify_result_types(results)
        type_parts = []
        if counts["pdf"]:
            type_parts.append(f"pdf={counts['pdf']}")
        if counts["arxiv"]:
            type_parts.append(f"arxiv={counts['arxiv']}")
        if counts["web"]:
            type_parts.append(f"web={counts['web']}")
        type_text = ",".join(type_parts) if type_parts else "-"

        top_summary = "-"
        if results:
            best = max(results, key=lambda item: item.get("score") or 0)
            top_summary = best.get("summary") or best.get("content") or "-"
        query_summary = data.get("query_summary") or result_block.get("answer") or "-"
        rows.append(
            {
                "query": query,
                "results": len(results),
                "types": type_text,
                "top_summary": top_summary,
                "query_summary": query_summary,
            }
        )

    if not rows:
        return f"{path.name}: no entries found."

    query_w = min(max(len(str(row["query"])) for row in rows), 32)
    types_w = min(max(len(str(row["types"])) for row in rows), 18)
    top_w = 48
    qsum_w = 64
    header = (
        f"{'Query'.ljust(query_w)}  {'Results':>7}  {'Types'.ljust(types_w)}  "
        f"{'Top Summary'.ljust(top_w)}  {'Query Summary'.ljust(qsum_w)}"
    )
    lines = [
        f"Tavily search summary: {path} (entries={total_entries})",
        header,
        "-" * len(header),
    ]
    for row in rows:
        lines.append(
            f"{truncate_text(row['query'], query_w).ljust(query_w)}  "
            f"{str(row['results']).rjust(7)}  "
            f"{truncate_text(row['types'], types_w).ljust(types_w)}  "
            f"{truncate_text(row['top_summary'], top_w).ljust(top_w)}  "
            f"{truncate_text(row['query_summary'], qsum_w).ljust(qsum_w)}"
        )
    return "\n".join(lines)


def render_generic_jsonl_review(path: Path, preview_lines: int = 5) -> str:
    rows = []
    total_entries = 0
    for line in path.read_text(encoding="utf-8", errors="ignore").splitlines():
        line = line.strip()
        if not line:
            continue
        total_entries += 1
        if len(rows) >= preview_lines:
            continue
        try:
            data = json.loads(line)
            keys = ",".join(list(data.keys())[:6]) if isinstance(data, dict) else type(data).__name__
        except json.JSONDecodeError:
            keys = "(invalid json)"
        rows.append({"line": total_entries, "keys": keys, "preview": line})

    lines = [f"JSONL review: {path} (entries={total_entries})"]
    if not rows:
        return "\n".join(lines)
    header = f"{'Line':>4}  {'Keys':<32}  Preview"
    lines.extend([header, "-" * len(header)])
    for row in rows:
        lines.append(
            f"{str(row['line']).rjust(4)}  "
            f"{truncate_text(row['keys'], 32).ljust(32)}  "
            f"{truncate_text(row['preview'], 80)}"
        )
    if total_entries > preview_lines:
        lines.append(f"... ({total_entries - preview_lines} more lines)")
    return "\n".join(lines)


def render_jsonl_review(path: Path) -> str:
    if path.name == "tavily_search.jsonl":
        return render_tavily_search_review(path)
    return render_generic_jsonl_review(path)


def format_scalar(value: object) -> str:
    if value is None:
        return "null"
    if isinstance(value, bool):
        return "true" if value else "false"
    if isinstance(value, (int, float)):
        return str(value)
    return str(value)


def format_multiline(value: str, indent: int) -> List[str]:
    pad = " " * indent
    return [f"{pad}{line}" for line in value.splitlines()]


def format_pretty(value: object, indent: int = 0) -> List[str]:
    pad = " " * indent
    if isinstance(value, dict):
        lines: List[str] = []
        for key, val in value.items():
            if isinstance(val, (dict, list)):
                lines.append(f"{pad}{key}:")
                lines.extend(format_pretty(val, indent + 2))
                continue
            if isinstance(val, str) and "\n" in val:
                lines.append(f"{pad}{key}: |")
                lines.extend(format_multiline(val, indent + 2))
            else:
                lines.append(f"{pad}{key}: {format_scalar(val)}")
        return lines
    if isinstance(value, list):
        lines = []
        for item in value:
            if isinstance(item, (dict, list)):
                lines.append(f"{pad}-")
                lines.extend(format_pretty(item, indent + 2))
                continue
            if isinstance(item, str) and "\n" in item:
                lines.append(f"{pad}- |")
                lines.extend(format_multiline(item, indent + 2))
            else:
                lines.append(f"{pad}- {format_scalar(item)}")
        return lines
    if isinstance(value, str) and "\n" in value:
        return [f"{pad}|", *format_multiline(value, indent + 2)]
    return [f"{pad}{format_scalar(value)}"]


def render_jsonl_review_full(path: Path) -> str:
    lines = [f"Full JSONL: {path}"]
    entries = 0
    for line in path.read_text(encoding="utf-8", errors="ignore").splitlines():
        line = line.strip()
        if not line:
            continue
        entries += 1
        lines.append(f"[{entries}]")
        try:
            data = json.loads(line)
            lines.extend(format_pretty(data))
        except json.JSONDecodeError:
            lines.append(line)
        lines.append("")
    if entries == 0:
        lines.append("(no entries)")
    return "\n".join(lines).rstrip()
