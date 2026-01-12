import dataclasses
import datetime as dt
import glob
import json
import os
import re
import shutil
import time
from collections import Counter
from pathlib import Path
from typing import Iterable, List, Optional

import requests

from . import arxiv_ops
from . import linkedin_ops
from . import local_ops
from . import openalex_ops
from . import youtube_ops
from .models import Job, LocalPathSpec, QuerySpec
from .tavily import TavilyClient
from .utils import (
    append_jsonl,
    normalize_for_json,
    parse_date_from_filename,
    read_text,
    safe_filename,
    write_text,
)

ARXIV_ID_RE = re.compile(
    r"""
    (?:
        arxiv[.:]\s*|
        arXiv:\s*
    )?
    (?P<id>\d{4}\.\d{4,5})(?:v\d+)?
    """,
    re.IGNORECASE | re.VERBOSE,
)

URL_RE = re.compile(r"^https?://", re.IGNORECASE)

SITE_HINTS = {"linkedin", "arxiv", "news", "github", "youtube"}
YOUTUBE_QUERY_SITE_RE = re.compile(r"\bsite:(?:youtube\.com|youtu\.be)\b", re.IGNORECASE)
DIVIDER_CHARS = set("-_=*#")
LOCAL_DIRECTIVES = ("file:", "dir:", "glob:")
REQUEST_SLEEP_SEC = 0.5
SUMMARY_SENTENCES = 2
SUMMARY_CHARS = 400
SUMMARY_MAX_RESULTS = 5
YOUTUBE_TITLE_MAX_LEN = 80


class JobLogger:
    def __init__(self, log_path: Path, also_stdout: bool = True):
        self.log_path = log_path
        self.also_stdout = also_stdout

    def log(self, msg: str) -> None:
        stamp = dt.datetime.now().strftime("%Y-%m-%d %H:%M:%S")
        line = f"[{stamp}] {msg}"
        with self.log_path.open("a", encoding="utf-8") as f:
            f.write(line + "\n")
        if self.also_stdout:
            print(line, flush=True)


def is_divider_line(line: str) -> bool:
    return bool(line) and set(line) <= DIVIDER_CHARS


def parse_instruction_sections(content: str) -> List[List[str]]:
    sections: List[List[str]] = []
    current: List[str] = []
    for raw in content.splitlines():
        s = raw.strip()
        if not s or is_divider_line(s):
            if current:
                sections.append(current)
                current = []
            continue
        current.append(s)
    if current:
        sections.append(current)
    return sections


def flatten_sections(sections: List[List[str]]) -> List[str]:
    return [line for section in sections for line in section]


def parse_instruction_lines(content: str) -> List[str]:
    return flatten_sections(parse_instruction_sections(content))


def parse_query_text(query: str) -> List[List[str]]:
    normalized = query.replace(";", "\n")
    return parse_instruction_sections(normalized)


def strip_quotes(value: str) -> str:
    value = value.strip()
    if len(value) >= 2 and value[0] == value[-1] and value[0] in {"'", '"'}:
        return value[1:-1]
    return value


def parse_local_metadata(parts: List[str]) -> dict:
    meta: dict = {"title": None, "tags": [], "lang": None}
    for part in parts:
        if not part or "=" not in part:
            continue
        key, val = part.split("=", 1)
        key = key.strip().lower()
        val = strip_quotes(val.strip())
        if key == "title" and val:
            meta["title"] = val
        elif key == "tags" and val:
            tags = [t.strip() for t in val.split(",") if t.strip()]
            meta["tags"] = tags
        elif key == "lang" and val:
            meta["lang"] = val
    return meta


def resolve_path_value(value: str, base_dir: Path) -> Path:
    expanded = os.path.expandvars(strip_quotes(value))
    path = Path(expanded).expanduser()
    if not path.is_absolute():
        path = base_dir / path
    return path.resolve(strict=False)


def resolve_glob_value(value: str, base_dir: Path) -> str:
    expanded = os.path.expandvars(strip_quotes(value))
    if os.path.isabs(expanded):
        return expanded
    return os.path.join(str(base_dir), expanded)


def parse_local_directive(line: str, base_dir: Path) -> Optional[LocalPathSpec]:
    stripped = line.strip()
    lower = stripped.lower()
    for directive in LOCAL_DIRECTIVES:
        if lower.startswith(directive):
            rest = stripped[len(directive) :].strip()
            if not rest:
                return None
            parts = [p.strip() for p in rest.split("|")]
            path_part = parts[0]
            meta = parse_local_metadata(parts[1:])
            kind = directive.rstrip(":")
            if kind == "glob":
                value = resolve_glob_value(path_part, base_dir)
            else:
                value = str(resolve_path_value(path_part, base_dir))
            return LocalPathSpec(
                kind=kind,
                value=value,
                title=meta["title"],
                tags=meta["tags"],
                lang=meta["lang"],
            )
    return None


def is_pdf_url(url: str) -> bool:
    base = url.split("?", 1)[0].lower()
    return base.endswith(".pdf")


def url_to_pdf_name(url: str, fallback: str) -> str:
    base = url.split("?", 1)[0].rstrip("/").split("/")[-1] or fallback
    name = safe_filename(base, max_len=120)
    if not name.lower().endswith(".pdf"):
        name = f"{name}.pdf"
    return name


def apply_language_hint(query: str, lang_pref: Optional[str]) -> str:
    if not lang_pref:
        return query
    hint = None
    if lang_pref == "en":
        hint = "English"
    elif lang_pref == "ko":
        hint = "한국어"
    if not hint:
        return query
    lower = query.lower()
    if "english" in lower or "korean" in lower or "한국어" in query:
        return query
    return f"{query} ({hint})"


def language_score(text: str, lang_pref: Optional[str]) -> float:
    if not text or not lang_pref:
        return 0.0
    latin = sum("a" <= c.lower() <= "z" for c in text)
    hangul = sum("\uac00" <= c <= "\ud7a3" for c in text)
    total = latin + hangul
    if total == 0:
        return 0.0
    if lang_pref == "ko":
        return hangul / total
    if lang_pref == "en":
        return latin / total
    return 0.0


def prefer_results(results: List[dict], lang_pref: Optional[str]) -> List[dict]:
    if not lang_pref:
        return results

    def score(item: dict) -> float:
        title = str(item.get("title", ""))
        content = str(item.get("content", ""))
        return language_score(f"{title} {content}", lang_pref)

    return sorted(results, key=score, reverse=True)


def split_sentences(text: str) -> List[str]:
    parts = re.split(r"(?<=[.!?])\s+|\n+", text)
    return [p.strip() for p in parts if p and p.strip()]


def tokenize(text: str) -> List[str]:
    return re.findall(r"[A-Za-z]{2,}|[\uac00-\ud7a3]{2,}", text.lower())


def summarize_text(text: str, max_sentences: int = SUMMARY_SENTENCES, max_chars: int = SUMMARY_CHARS) -> str:
    clean = re.sub(r"\s+", " ", text).strip()
    if not clean:
        return ""
    if len(clean) <= max_chars:
        return clean

    sentences = split_sentences(clean)
    if not sentences:
        return clean[:max_chars].rstrip()
    if len(sentences) <= max_sentences:
        summary = " ".join(sentences)
        return summary[:max_chars].rstrip()

    tokens = tokenize(clean)
    if not tokens:
        summary = " ".join(sentences[:max_sentences])
        return summary[:max_chars].rstrip()

    freq = Counter(tokens)
    scored = []
    for idx, sent in enumerate(sentences):
        sent_tokens = tokenize(sent)
        if not sent_tokens:
            continue
        score = sum(freq.get(tok, 0) for tok in sent_tokens)
        scored.append((score, idx, sent))

    if not scored:
        summary = " ".join(sentences[:max_sentences])
        return summary[:max_chars].rstrip()

    top = sorted(scored, key=lambda x: (-x[0], x[1]))[:max_sentences]
    top_sorted = sorted(top, key=lambda x: x[1])
    summary = " ".join(s for _, _, s in top_sorted).strip()
    return summary[:max_chars].rstrip()


def add_result_summaries(results: List[dict]) -> None:
    for item in results:
        content = str(item.get("content") or "")
        if not content:
            content = str(item.get("title") or "")
        item["summary"] = summarize_text(content)


def summarize_results(results: List[dict]) -> str:
    parts: List[str] = []
    for item in results[:SUMMARY_MAX_RESULTS]:
        summary = item.get("summary") or item.get("content") or item.get("title")
        if summary:
            parts.append(str(summary))
    if not parts:
        return ""
    return summarize_text(" ".join(parts), max_sentences=3, max_chars=600)


def build_job(
    sections: List[List[str]],
    src_file: Path,
    out_root: Path,
    query_id: str,
    set_id: Optional[str],
    lang_pref: Optional[str],
    openalex_enabled: bool,
    openalex_max_results: int,
    youtube_enabled: bool,
    youtube_max_results: int,
    youtube_transcript: bool,
    youtube_order: str,
    days: int,
    max_results: int,
    download_pdf: bool,
    citations_enabled: bool,
    file_date: Optional[dt.date] = None,
) -> Job:
    date_val = file_date or parse_date_from_filename(src_file.stem) or dt.date.today()
    root_dir = out_root / query_id
    out_dir = root_dir / "archive"
    base_dir = src_file.parent

    urls: List[str] = []
    arxiv_ids: List[str] = []
    queries: List[str] = []
    query_specs: List[QuerySpec] = []
    site_hints: List[str] = []
    local_paths: List[LocalPathSpec] = []
    raw_lines = flatten_sections(sections)

    def dedup(seq: Iterable[str]) -> List[str]:
        seen = set()
        out: List[str] = []
        for x in seq:
            if x in seen:
                continue
            seen.add(x)
            out.append(x)
        return out

    def dedup_specs(specs: List[QuerySpec]) -> List[QuerySpec]:
        seen = set()
        out: List[QuerySpec] = []
        for spec in specs:
            key = (spec.text, tuple(spec.hints))
            if key in seen:
                continue
            seen.add(key)
            out.append(spec)
        return out

    for section in sections:
        section_hints: List[str] = []
        section_queries: List[str] = []
        for line in section:
            local_spec = parse_local_directive(line, base_dir)
            if local_spec:
                local_paths.append(local_spec)
                continue
            if URL_RE.match(line):
                urls.append(line)
                continue

            m = ARXIV_ID_RE.search(line)
            if m:
                arxiv_ids.append(m.group("id"))
                continue

            if line.lower() in SITE_HINTS:
                section_hints.append(line.lower())
                continue

            section_queries.append(line)

        hints = dedup(section_hints)
        if hints:
            site_hints.extend(hints)
        if section_queries:
            for query in section_queries:
                query_specs.append(QuerySpec(text=query, hints=hints))
                queries.append(query)

    return Job(
        date=date_val,
        src_file=src_file,
        root_dir=root_dir,
        out_dir=out_dir,
        query_id=query_id,
        set_id=set_id,
        lang_pref=lang_pref,
        openalex_enabled=openalex_enabled,
        openalex_max_results=openalex_max_results,
        youtube_enabled=youtube_enabled,
        youtube_max_results=youtube_max_results,
        youtube_transcript=youtube_transcript,
        youtube_order=youtube_order,
        days=days,
        max_results=max_results,
        download_pdf=download_pdf,
        citations_enabled=citations_enabled,
        queries=dedup(queries),
        query_specs=dedup_specs(query_specs),
        local_paths=local_paths,
        urls=dedup(urls),
        arxiv_ids=dedup(arxiv_ids),
        site_hints=dedup(site_hints),
        raw_lines=raw_lines,
    )


def parse_job(
    txt_path: Path,
    out_root: Path,
    query_id: str,
    set_id: Optional[str],
    lang_pref: Optional[str],
    openalex_enabled: bool,
    openalex_max_results: int,
    youtube_enabled: bool,
    youtube_max_results: int,
    youtube_transcript: bool,
    youtube_order: str,
    days: int,
    max_results: int,
    download_pdf: bool,
    citations_enabled: bool,
    file_date: Optional[dt.date] = None,
) -> Job:
    content = read_text(txt_path)
    sections = parse_instruction_sections(content)
    return build_job(
        sections=sections,
        src_file=txt_path,
        out_root=out_root,
        query_id=query_id,
        set_id=set_id,
        lang_pref=lang_pref,
        openalex_enabled=openalex_enabled,
        openalex_max_results=openalex_max_results,
        youtube_enabled=youtube_enabled,
        youtube_max_results=youtube_max_results,
        youtube_transcript=youtube_transcript,
        youtube_order=youtube_order,
        days=days,
        max_results=max_results,
        download_pdf=download_pdf,
        citations_enabled=citations_enabled,
        file_date=file_date,
    )


def collect_instruction_files(input_path: Path) -> List[Path]:
    if input_path.is_file():
        if input_path.suffix.lower() != ".txt":
            raise SystemExit(f"Input file must be .txt: {input_path}")
        return [input_path]
    if input_path.is_dir():
        return sorted(input_path.glob("*.txt"))
    raise SystemExit(f"Input path not found: {input_path}")


def infer_date(path: Path) -> dt.date:
    return parse_date_from_filename(path.stem) or parse_date_from_filename(path.parent.name) or dt.date.today()


def build_query_id(date_val: dt.date, set_id: Optional[str], idx: int, total: int) -> str:
    base = date_val.strftime("%Y%m%d")
    if set_id:
        sid = safe_filename(set_id, max_len=40).strip("_")
        if sid:
            base = f"{base}_{sid}"
        if total > 1:
            return f"{base}_{idx:03d}"
        return base
    return f"{base}_{idx:03d}"


def prepare_jobs(
    input_path: Optional[Path],
    query: Optional[str],
    output_root: Path,
    set_id: Optional[str],
    lang_pref: Optional[str],
    openalex_enabled: bool,
    openalex_max_results: Optional[int],
    youtube_enabled: bool,
    youtube_max_results: Optional[int],
    youtube_transcript: bool,
    youtube_order: str,
    days: int,
    max_results: int,
    download_pdf: bool,
    citations_enabled: bool,
) -> List[Job]:
    if query:
        sections = parse_query_text(query)
        if not sections:
            raise SystemExit("No instructions found in --query")
        date_val = dt.date.today()
        query_id = build_query_id(date_val, set_id, 1, 1)
        src_file = Path("instruction.txt")
        return [
            build_job(
                sections=sections,
                src_file=src_file,
                out_root=output_root,
                query_id=query_id,
                set_id=set_id,
                lang_pref=lang_pref,
                openalex_enabled=openalex_enabled,
                openalex_max_results=openalex_max_results or max_results,
                youtube_enabled=youtube_enabled,
                youtube_max_results=youtube_max_results or max_results,
                youtube_transcript=youtube_transcript,
                youtube_order=youtube_order,
                days=days,
                max_results=max_results,
                download_pdf=download_pdf,
                citations_enabled=citations_enabled,
                file_date=date_val,
            )
        ]

    if input_path is None:
        raise SystemExit("Missing input path")

    txt_files = collect_instruction_files(input_path)
    if not txt_files:
        raise SystemExit(f"No .txt files found in: {input_path}")

    total = len(txt_files)
    jobs: List[Job] = []
    for idx, txt in enumerate(txt_files, start=1):
        date_val = infer_date(txt)
        query_id = build_query_id(date_val, set_id, idx, total)
        jobs.append(
            parse_job(
                txt,
                output_root,
                query_id=query_id,
                set_id=set_id,
                lang_pref=lang_pref,
                openalex_enabled=openalex_enabled,
                openalex_max_results=openalex_max_results or max_results,
                youtube_enabled=youtube_enabled,
                youtube_max_results=youtube_max_results or max_results,
                youtube_transcript=youtube_transcript,
                youtube_order=youtube_order,
                days=days,
                max_results=max_results,
                download_pdf=download_pdf,
                citations_enabled=citations_enabled,
                file_date=date_val,
            )
        )
    return jobs


def copy_instruction(job: Job) -> None:
    instr_dir = job.root_dir / "instruction"
    instr_dir.mkdir(parents=True, exist_ok=True)
    if job.src_file.exists():
        text = read_text(job.src_file)
    else:
        text = "\n".join(job.raw_lines)
        if text:
            text += "\n"
    write_text(instr_dir / job.src_file.name, text)


def write_job_json(job: Job) -> None:
    payload = normalize_for_json(dataclasses.asdict(job))
    write_text(job.out_dir / "_job.json", json.dumps(payload, ensure_ascii=False, indent=2))


def apply_site_hint(query: str, hints: List[str]) -> str:
    q2 = query
    q2_lower = q2.lower()
    if "linkedin" in hints:
        if len(q2) <= 20 and "site:" not in q2_lower:
            q2 = f"{q2} site:linkedin.com"
            q2_lower = q2.lower()
    if "github" in hints:
        if "site:" not in q2_lower and any(k in q2_lower for k in ("github", "code", "repo", "implementation")):
            q2 = f"{q2} site:github.com"
            q2_lower = q2.lower()
    if "youtube" in hints:
        if "site:" not in q2_lower:
            q2 = f"{q2} site:youtube.com"
    return q2


def is_explicit_youtube_query(query: str) -> bool:
    lower = query.lower()
    if "youtube.com" in lower or "youtu.be" in lower:
        return True
    return bool(YOUTUBE_QUERY_SITE_RE.search(query))


def normalize_youtube_query(query: str) -> str:
    cleaned = YOUTUBE_QUERY_SITE_RE.sub("", query)
    return re.sub(r"\s+", " ", cleaned).strip()


def select_youtube_queries(job: Job) -> List[str]:
    explicit = [spec.text for spec in job.query_specs if is_explicit_youtube_query(spec.text)]
    if explicit:
        return explicit
    return [spec.text for spec in job.query_specs if "youtube" in spec.hints]


def run_tavily_extract(job: Job, tavily: TavilyClient, logger: JobLogger) -> None:
    if not job.urls:
        return
    extract_dir = job.out_dir / "tavily_extract"
    for idx, url in enumerate(job.urls, start=1):
        if job.youtube_enabled and youtube_ops.extract_video_id(url):
            logger.log(f"TAVILY EXTRACT SKIP (youtube): {url}")
            continue
        activity_id = linkedin_ops.extract_activity_id(url)
        if activity_id:
            try:
                logger.log(f"LINKEDIN EMBED EXTRACT: {url}")
                data = linkedin_ops.extract_public_post(url)
                if data:
                    out_txt = extract_dir / f"{idx:04d}_{safe_filename(url)}.txt"
                    write_text(out_txt, json.dumps(data, ensure_ascii=False, indent=2))
                    time.sleep(REQUEST_SLEEP_SEC)
                    continue
                logger.log(f"WARN linkedin embed empty content url={url}")
            except Exception as e:
                logger.log(f"WARN linkedin embed failed url={url} err={repr(e)}")
        try:
            logger.log(f"TAVILY EXTRACT: {url}")
            data = tavily.extract(url=url, include_images=False, extract_depth="advanced")
            out_txt = extract_dir / f"{idx:04d}_{safe_filename(url)}.txt"
            write_text(out_txt, json.dumps(data, ensure_ascii=False, indent=2))
            time.sleep(REQUEST_SLEEP_SEC)
        except Exception as e:
            logger.log(f"ERROR extract url={url} err={repr(e)}")


def expand_local_spec(spec: LocalPathSpec, logger: JobLogger) -> List[Path]:
    if spec.kind == "file":
        return [Path(spec.value)]
    if spec.kind == "dir":
        base = Path(spec.value)
        if not base.exists():
            logger.log(f"WARN local dir not found: {spec.value}")
            return []
        if not base.is_dir():
            logger.log(f"WARN local dir is not a directory: {spec.value}")
            return []
        return [p for p in base.rglob("*") if p.is_file()]
    if spec.kind == "glob":
        matches = [Path(p) for p in glob.glob(spec.value, recursive=True)]
        return [p for p in matches if p.is_file()]
    logger.log(f"WARN unknown local spec kind: {spec.kind}")
    return []


def run_local_ingest(job: Job, logger: JobLogger) -> None:
    if not job.local_paths:
        return

    raw_dir = job.out_dir / "local" / "raw"
    text_dir = job.out_dir / "local" / "text"
    manifest_path = job.out_dir / "local" / "manifest.jsonl"
    seen: set[str] = set()

    def rel_path(path: Path) -> str:
        rel = os.path.relpath(path.resolve(), job.out_dir.resolve())
        rel = Path(rel).as_posix()
        rel = f"./{rel}" if not rel.startswith(".") else rel
        return rel

    for spec in job.local_paths:
        matches = expand_local_spec(spec, logger)
        if not matches:
            if spec.kind == "glob":
                logger.log(f"WARN local glob matched no files: {spec.value}")
            continue
        for path in matches:
            key = str(path.resolve())
            if key in seen:
                continue
            seen.add(key)
            if not path.exists():
                logger.log(f"WARN local file not found: {path}")
                continue
            if not local_ops.is_supported(path):
                logger.log(f"WARN local unsupported file type: {path.name}")
                continue

            try:
                digest = local_ops.compute_sha1(path)
                doc_id = local_ops.build_doc_id(digest)
                slug = local_ops.slug_from_path(path)
                ext = path.suffix.lower()
                raw_name = f"{doc_id}--{slug}{ext}"
                text_name = f"{doc_id}--{slug}.txt"
                raw_path = raw_dir / raw_name
                if not raw_path.exists():
                    shutil.copy2(path, raw_path)

                text_path = text_dir / text_name
                text_value = None
                try:
                    text_value = local_ops.extract_text(path)
                    if text_value:
                        write_text(text_path, text_value)
                except Exception as e:
                    logger.log(f"ERROR local text extract file={path.name} err={repr(e)}")

                stat = path.stat()
                title = spec.title or path.stem
                payload = {
                    "doc_id": doc_id,
                    "source": "local",
                    "title": title,
                    "tags": spec.tags,
                    "lang": spec.lang,
                    "raw_path": rel_path(raw_path),
                    "content_path": rel_path(text_path) if text_value else None,
                    "file_ext": ext,
                    "file_name": path.name,
                    "source_path": str(path),
                    "file_size": stat.st_size,
                    "modified": dt.datetime.fromtimestamp(stat.st_mtime).isoformat(),
                    "hash": digest,
                    "query_id": job.query_id,
                }
                append_jsonl(manifest_path, payload)
            except Exception as e:
                logger.log(f"ERROR local ingest file={path.name} err={repr(e)}")


def run_url_pdf_downloads(job: Job, logger: JobLogger) -> None:
    if not job.download_pdf or not job.urls:
        return
    pdf_dir = job.out_dir / "web" / "pdf"
    text_dir = job.out_dir / "web" / "text"
    for idx, url in enumerate(job.urls, start=1):
        if not is_pdf_url(url):
            continue
        try:
            filename = url_to_pdf_name(url, f"url_{idx:04d}.pdf")
            pdf_path = pdf_dir / filename
            if not pdf_path.exists():
                logger.log(f"WEB PDF DOWNLOAD: {url} -> {pdf_path.name}")
                arxiv_ops.arxiv_download_pdf(url, pdf_path)
            if arxiv_ops.PYMUPDF_AVAILABLE:
                txt_path = text_dir / f"{pdf_path.stem}.txt"
                if not txt_path.exists():
                    logger.log(f"PDF->TEXT: {pdf_path.name}")
                    txt = arxiv_ops.pdf_to_text(pdf_path)
                    write_text(txt_path, txt)
            else:
                logger.log("ERROR missing dependency: pymupdf (pip install pymupdf)")
        except Exception as e:
            logger.log(f"ERROR web pdf url={url} err={repr(e)}")


def run_tavily_search(job: Job, tavily: TavilyClient, logger: JobLogger) -> None:
    if not job.query_specs:
        return
    search_path = job.out_dir / "tavily_search.jsonl"
    for spec in job.query_specs:
        try:
            q2 = apply_site_hint(spec.text, spec.hints)
            q2 = apply_language_hint(q2, job.lang_pref)
            logger.log(f"TAVILY SEARCH: {q2}")
            res = tavily.search(
                query=q2,
                max_results=job.max_results,
                search_depth="advanced",
                include_raw_content=False,
            )
            payload = {"query": q2, "result": res}
            if isinstance(res, dict) and isinstance(res.get("results"), list):
                add_result_summaries(res["results"])
                payload["query_summary"] = summarize_results(res["results"])
                if job.lang_pref:
                    payload["lang_pref"] = job.lang_pref
                    payload["preferred_results"] = prefer_results(res["results"], job.lang_pref)
            append_jsonl(search_path, payload)
            time.sleep(REQUEST_SLEEP_SEC)
        except Exception as e:
            logger.log(f"ERROR search query={spec.text} err={repr(e)}")


def run_youtube(job: Job, logger: JobLogger) -> None:
    if not job.youtube_enabled:
        return

    api_key = os.getenv("YOUTUBE_API_KEY")
    if not api_key:
        logger.log("ERROR missing environment variable: YOUTUBE_API_KEY")
        return

    videos_path = job.out_dir / "youtube" / "videos.jsonl"
    transcript_dir = job.out_dir / "youtube" / "transcripts"

    published_after = dt.datetime.combine(job.date - dt.timedelta(days=job.days), dt.time.min)
    published_before = dt.datetime.combine(job.date, dt.time.max)
    relevance_language = job.lang_pref
    details_cache: dict[str, dict] = {}
    seen_ids: set[str] = set()
    quota_exceeded = False

    def add_summary(video: dict) -> None:
        desc = str(video.get("description") or "")
        if desc and not video.get("summary"):
            video["summary"] = summarize_text(desc)

    def extract_hashtags(text: str) -> List[str]:
        tags: List[str] = []
        for match in re.findall(r"(?:^|\s)#(\w[\w-]{1,64})", text):
            tag = f"#{match}"
            if tag not in tags:
                tags.append(tag)
        return tags

    def build_transcript_path(video_id: str, title: str) -> tuple[Path, str]:
        safe_title = safe_filename(title or "", max_len=YOUTUBE_TITLE_MAX_LEN).strip("_")
        if not safe_title:
            safe_title = "untitled"
        name = f"youtu.be-{video_id}-{safe_title}.txt"
        rel_path = f"./youtube/transcripts/{name}"
        return transcript_dir / name, rel_path

    def format_transcript_header(video: dict, url: str) -> str:
        title = str(video.get("title") or "-")
        channel = str(video.get("channel_title") or "-")
        published = str(video.get("published_at") or "-")
        tags = video.get("tags") or []
        if not isinstance(tags, list):
            tags = [str(tags)]
        tags_text = ", ".join(str(t) for t in tags) if tags else "-"
        desc = str(video.get("description") or "")
        hashtags = extract_hashtags(desc)
        hashtags_text = ", ".join(hashtags) if hashtags else "-"
        summary = " ".join(str(video.get("summary") or summarize_text(desc) or "-").split())
        lines = [
            f"Title: {title}",
            f"URL: {url}",
        ]
        direct_url = video.get("direct_url")
        if direct_url and direct_url != url:
            lines.append(f"Direct URL: {direct_url}")
        lines.extend(
            [
                f"Video ID: {video.get('video_id') or '-'}",
                f"Channel: {channel}",
                f"Published: {published}",
                f"Tags: {tags_text}",
                f"Hashtags: {hashtags_text}",
                f"Summary: {summary}",
            ]
        )
        source = video.get("source")
        if source:
            lines.append(f"Source: {source}")
        return "\n".join(lines).rstrip() + "\n\n"

    def attach_transcript(video: dict) -> None:
        video_id = video.get("video_id")
        if not video_id:
            return
        title = str(video.get("title") or "")
        out_txt, rel_path = build_transcript_path(video_id, title)
        if out_txt.exists():
            video["transcript_path"] = rel_path
            return

        legacy_path = transcript_dir / f"{video_id}.txt"
        legacy_text = read_text(legacy_path) if legacy_path.exists() else None
        try:
            if legacy_text is None:
                logger.log(f"YOUTUBE TRANSCRIPT: {video_id}")
                segments = youtube_ops.fetch_transcript(
                    video_id,
                    languages=[job.lang_pref] if job.lang_pref else None,
                )
                transcript_text = youtube_ops.format_transcript(segments)
            else:
                transcript_text = legacy_text.strip()

            url = video.get("url") or f"https://www.youtube.com/watch?v={video_id}"
            header = format_transcript_header(video, url)
            body = transcript_text.strip()
            payload = header + (body + "\n" if body else "")
            write_text(out_txt, payload)
            video["transcript_path"] = rel_path
            if legacy_path.exists():
                legacy_path.unlink()
        except Exception as e:
            status = youtube_ops.classify_transcript_error(e)
            if status == "blocked":
                logger.log(
                    "WARN youtube transcript blocked by YouTube. "
                    "Set YOUTUBE_PROXY or disable --yt-transcript."
                )
            elif status == "unavailable":
                logger.log(f"WARN youtube transcript unavailable id={video_id} err={repr(e)}")
            else:
                logger.log(f"ERROR youtube transcript id={video_id} err={repr(e)}")

    youtube_queries = select_youtube_queries(job)
    if not youtube_queries:
        logger.log("YOUTUBE SEARCH SKIP: no youtube hint or explicit site:youtube.com queries")
    for q in youtube_queries:
        try:
            q2 = normalize_youtube_query(q)
            if not q2:
                continue
            logger.log(f"YOUTUBE SEARCH: {q} order={job.youtube_order} max={job.youtube_max_results}")
            videos = youtube_ops.youtube_search(
                query=q2,
                api_key=api_key,
                max_results=job.youtube_max_results,
                order=job.youtube_order,
                published_after=published_after,
                published_before=published_before,
                relevance_language=relevance_language,
                details_cache=details_cache,
            )
            for vid in videos:
                add_summary(vid)
                video_id = vid.get("video_id")
                if video_id:
                    seen_ids.add(video_id)

            if job.youtube_transcript and videos:
                if not youtube_ops.TRANSCRIPT_AVAILABLE:
                    logger.log("ERROR missing dependency: youtube-transcript-api (pip install youtube-transcript-api)")
                else:
                    for vid in videos:
                        attach_transcript(vid)
            append_jsonl(videos_path, {"query": q, "videos": videos})
            time.sleep(REQUEST_SLEEP_SEC)
        except requests.exceptions.HTTPError as e:
            reason, message = youtube_ops.parse_api_error(e.response)
            if reason == "quotaExceeded":
                logger.log(f"ERROR youtube quota exceeded: {message or 'quota exceeded'}")
                quota_exceeded = True
                break
            logger.log(f"ERROR youtube query={q} err={reason or repr(e)}")
        except Exception as e:
            logger.log(f"ERROR youtube query={q} err={repr(e)}")

    direct_urls = []
    for url in job.urls:
        video_id = youtube_ops.extract_video_id(url)
        if video_id:
            direct_urls.append((url, video_id))

    if not direct_urls:
        return

    seen_ids = set()
    direct_ids: List[str] = []
    for _, vid in direct_urls:
        if vid in seen_ids:
            continue
        seen_ids.add(vid)
        direct_ids.append(vid)

    details: dict[str, dict] = {}
    need_ids = [vid for vid in direct_ids if vid not in details_cache]
    if need_ids:
        try:
            details = youtube_ops.fetch_video_details(need_ids, api_key)
            details_cache.update(details)
        except requests.exceptions.HTTPError as e:
            reason, message = youtube_ops.parse_api_error(e.response)
            if reason == "quotaExceeded":
                logger.log(f"WARN youtube direct metadata skipped due to quota: {message or 'quota exceeded'}")
            else:
                logger.log(f"WARN youtube direct metadata failed: {reason or repr(e)}")
        except Exception as e:
            logger.log(f"WARN youtube direct metadata failed: {repr(e)}")

    for url, vid in direct_urls:
        logger.log(f"YOUTUBE DIRECT: {url}")
        info = details_cache.get(vid)
        if info:
            video = youtube_ops.detail_to_metadata(info, source="direct_url")
        else:
            video = {
                "video_id": vid,
                "url": f"https://www.youtube.com/watch?v={vid}",
                "source": "direct_url",
            }
        video["direct_url"] = url
        add_summary(video)
        if job.youtube_transcript:
            if not youtube_ops.TRANSCRIPT_AVAILABLE:
                logger.log("ERROR missing dependency: youtube-transcript-api (pip install youtube-transcript-api)")
            else:
                attach_transcript(video)
        append_jsonl(videos_path, {"direct_url": url, "video": video})
        seen_ids.add(vid)

    if quota_exceeded:
        tavily_path = job.out_dir / "tavily_search.jsonl"
        if not tavily_path.exists():
            return
        for line in tavily_path.read_text(encoding="utf-8", errors="ignore").splitlines():
            line = line.strip()
            if not line:
                continue
            try:
                data = json.loads(line)
            except json.JSONDecodeError:
                continue
            result = data.get("result") or {}
            query = data.get("query") or result.get("query")
            results = result.get("results") or []
            for res in results:
                url = res.get("url") or ""
                video_id = youtube_ops.extract_video_id(url)
                if not video_id or video_id in seen_ids:
                    continue
                video = {
                    "video_id": video_id,
                    "url": url,
                    "title": res.get("title"),
                    "summary": res.get("summary") or summarize_text(res.get("content") or ""),
                    "source": "tavily_url",
                }
                if query:
                    video["query"] = query
                if job.youtube_transcript:
                    if not youtube_ops.TRANSCRIPT_AVAILABLE:
                        logger.log("ERROR missing dependency: youtube-transcript-api (pip install youtube-transcript-api)")
                    else:
                        attach_transcript(video)
                append_jsonl(videos_path, {"tavily_url": url, "video": video, "query": query})
                seen_ids.add(video_id)


def run_openalex(job: Job, logger: JobLogger) -> None:
    if not job.openalex_enabled or not job.queries:
        return

    works_path = job.out_dir / "openalex" / "works.jsonl"
    pdf_dir = job.out_dir / "openalex" / "pdf"
    text_dir = job.out_dir / "openalex" / "text"
    api_key = os.getenv("OPENALEX_API_KEY")
    mailto = os.getenv("OPENALEX_MAILTO")
    downloaded_by_url: dict[str, Path] = {}

    for q in job.queries:
        try:
            logger.log(f"OPENALEX SEARCH: {q}")
            works = openalex_ops.openalex_search_recent(
                query=q,
                end_date=job.date,
                days=job.days,
                max_results=job.openalex_max_results,
                api_key=api_key,
                mailto=mailto,
            )
            for w in works:
                download_url = None
                if job.download_pdf:
                    pdf_urls = w.get("pdf_urls") or []
                    if w.get("pdf_url"):
                        pdf_urls = [w["pdf_url"]] + [u for u in pdf_urls if u != w["pdf_url"]]
                    last_err = None
                    for url in pdf_urls:
                        try:
                            if url in downloaded_by_url and downloaded_by_url[url].exists():
                                download_url = url
                                pdf_path = downloaded_by_url[url]
                                logger.log(f"OPENALEX PDF REUSE: {url} -> {pdf_path.name}")
                                if arxiv_ops.PYMUPDF_AVAILABLE:
                                    txt_path = text_dir / f"{pdf_path.stem}.txt"
                                    if not txt_path.exists():
                                        logger.log(f"PDF->TEXT: {pdf_path.name}")
                                        txt = arxiv_ops.pdf_to_text(pdf_path)
                                        write_text(txt_path, txt)
                                else:
                                    logger.log("ERROR missing dependency: pymupdf (pip install pymupdf)")
                                break
                            oa_id = (
                                w.get("openalex_id_short")
                                or safe_filename(w.get("doi") or "", max_len=40)
                                or "openalex"
                            )
                            pdf_path = pdf_dir / f"{oa_id}.pdf"
                            if not pdf_path.exists():
                                logger.log(f"OPENALEX PDF DOWNLOAD: {url} -> {pdf_path.name}")
                                openalex_ops.openalex_download_pdf(
                                    url,
                                    pdf_path,
                                    referer=w.get("landing_page_url"),
                                )
                            download_url = url
                            downloaded_by_url[url] = pdf_path

                            if arxiv_ops.PYMUPDF_AVAILABLE:
                                txt_path = text_dir / f"{pdf_path.stem}.txt"
                                if not txt_path.exists():
                                    logger.log(f"PDF->TEXT: {pdf_path.name}")
                                    txt = arxiv_ops.pdf_to_text(pdf_path)
                                    write_text(txt_path, txt)
                            else:
                                logger.log("ERROR missing dependency: pymupdf (pip install pymupdf)")
                            break
                        except Exception as e:
                            last_err = e
                            logger.log(f"WARN openalex pdf download failed url={url} err={repr(e)}")
                            continue

                    if download_url is None and pdf_urls:
                        logger.log(
                            f"ERROR openalex pdf download failed query={q} err={repr(last_err)} urls={pdf_urls[:3]}"
                        )

                if download_url:
                    w = dict(w)
                    w["downloaded_pdf_url"] = download_url
                append_jsonl(works_path, {"query": q, "work": w})

            time.sleep(REQUEST_SLEEP_SEC)
        except Exception as e:
            logger.log(f"ERROR openalex query={q} err={repr(e)}")


def run_arxiv_ids(job: Job, logger: JobLogger) -> None:
    if not job.arxiv_ids:
        return
    if not arxiv_ops.ARXIV_AVAILABLE:
        logger.log("ERROR missing dependency: arxiv (pip install arxiv)")
        return

    arxiv_meta_path = job.out_dir / "arxiv" / "papers.jsonl"
    arxiv_pdf_dir = job.out_dir / "arxiv" / "pdf"
    arxiv_text_dir = job.out_dir / "arxiv" / "text"

    api_key = os.getenv("OPENALEX_API_KEY")
    mailto = os.getenv("OPENALEX_MAILTO")
    citations_cache: dict[str, Optional[int]] = {}

    def enrich_citations(meta: dict) -> dict:
        if not job.citations_enabled:
            return meta
        if meta.get("cited_by_count") is not None:
            return meta
        doi = meta.get("doi")
        arxiv_id = meta.get("arxiv_id")
        key = doi or arxiv_id
        if not key:
            return meta
        if key in citations_cache:
            count = citations_cache[key]
        else:
            try:
                count = openalex_ops.openalex_get_citations(
                    doi=doi,
                    arxiv_id=arxiv_id,
                    api_key=api_key,
                    mailto=mailto,
                )
            except Exception as e:
                logger.log(f"WARN citations lookup failed arxiv_id={arxiv_id} err={repr(e)}")
                count = None
            citations_cache[key] = count
        if count is not None:
            meta["cited_by_count"] = count
        return meta

    for aid in job.arxiv_ids:
        try:
            logger.log(f"ARXIV ID FETCH: {aid}")
            got = arxiv_ops.search_by_id(aid)
            if not got:
                logger.log(f"ARXIV ID NOT FOUND: {aid}")
                continue

            meta = arxiv_ops.result_to_metadata(got)
            meta = enrich_citations(meta)
            append_jsonl(arxiv_meta_path, meta)

            if job.download_pdf and got.pdf_url:
                pdf_path = arxiv_pdf_dir / f"{got.get_short_id()}.pdf"
                download_ok = pdf_path.exists()
                if not download_ok:
                    logger.log(f"ARXIV PDF DOWNLOAD: {got.pdf_url} -> {pdf_path.name}")
                    try:
                        arxiv_ops.arxiv_download_pdf(got.pdf_url, pdf_path)
                        download_ok = True
                    except Exception as e:
                        logger.log(f"WARN arxiv pdf download failed id={aid} url={got.pdf_url} err={repr(e)}")
                else:
                    logger.log(f"ARXIV PDF EXISTS: {pdf_path.name}")

                if download_ok and arxiv_ops.PYMUPDF_AVAILABLE:
                    try:
                        txt_path = arxiv_text_dir / f"{got.get_short_id()}.txt"
                        if not txt_path.exists():
                            logger.log(f"PDF->TEXT: {pdf_path.name}")
                            txt = arxiv_ops.pdf_to_text(pdf_path)
                            write_text(txt_path, txt)
                    except Exception as e:
                        logger.log(f"ERROR pdf_to_text id={aid} err={repr(e)}")
                elif download_ok:
                    logger.log("ERROR missing dependency: pymupdf (pip install pymupdf)")

            time.sleep(REQUEST_SLEEP_SEC)
        except Exception as e:
            logger.log(f"ERROR arxiv id={aid} err={repr(e)}")


def run_arxiv_recent(job: Job, logger: JobLogger) -> None:
    run_recent_arxiv = any(("arxiv" in ln.lower() or "논문" in ln) for ln in job.raw_lines)
    if not run_recent_arxiv or not job.queries:
        return
    if not arxiv_ops.ARXIV_AVAILABLE:
        logger.log("ERROR missing dependency: arxiv (pip install arxiv)")
        return

    arxiv_meta_path = job.out_dir / "arxiv" / "papers.jsonl"
    arxiv_pdf_dir = job.out_dir / "arxiv" / "pdf"
    arxiv_text_dir = job.out_dir / "arxiv" / "text"
    best_q = sorted(job.queries, key=len, reverse=True)[0]

    api_key = os.getenv("OPENALEX_API_KEY")
    mailto = os.getenv("OPENALEX_MAILTO")
    citations_cache: dict[str, Optional[int]] = {}

    def enrich_citations(meta: dict) -> dict:
        if not job.citations_enabled:
            return meta
        if meta.get("cited_by_count") is not None:
            return meta
        doi = meta.get("doi")
        arxiv_id = meta.get("arxiv_id")
        key = doi or arxiv_id
        if not key:
            return meta
        if key in citations_cache:
            count = citations_cache[key]
        else:
            try:
                count = openalex_ops.openalex_get_citations(
                    doi=doi,
                    arxiv_id=arxiv_id,
                    api_key=api_key,
                    mailto=mailto,
                )
            except Exception as e:
                logger.log(f"WARN citations lookup failed arxiv_id={arxiv_id} err={repr(e)}")
                count = None
            citations_cache[key] = count
        if count is not None:
            meta["cited_by_count"] = count
        return meta

    try:
        logger.log(f"ARXIV RECENT SEARCH: query='{best_q}' days={job.days}")
        papers = arxiv_ops.arxiv_search_recent(
            query=best_q,
            end_date=job.date,
            days=job.days,
            max_results=job.max_results,
        )
        for p in papers:
            p = enrich_citations(p)
            append_jsonl(arxiv_meta_path, {"source": "recent_search", "query": best_q, "paper": p})

            if job.download_pdf and p.get("pdf_url") and p.get("arxiv_id"):
                pdf_path = arxiv_pdf_dir / f"{p['arxiv_id']}.pdf"
                download_ok = pdf_path.exists()
                if not download_ok:
                    logger.log(f"ARXIV PDF DOWNLOAD: {p['pdf_url']} -> {pdf_path.name}")
                    try:
                        arxiv_ops.arxiv_download_pdf(p["pdf_url"], pdf_path)
                        download_ok = True
                    except Exception as e:
                        logger.log(
                            f"WARN arxiv pdf download failed arxiv_id={p['arxiv_id']} url={p['pdf_url']} err={repr(e)}"
                        )

                if download_ok and arxiv_ops.PYMUPDF_AVAILABLE:
                    try:
                        txt_path = arxiv_text_dir / f"{p['arxiv_id']}.txt"
                        if not txt_path.exists():
                            logger.log(f"PDF->TEXT: {pdf_path.name}")
                            txt = arxiv_ops.pdf_to_text(pdf_path)
                            write_text(txt_path, txt)
                    except Exception as e:
                        logger.log(f"ERROR pdf_to_text arxiv_id={p['arxiv_id']} err={repr(e)}")
                elif download_ok:
                    logger.log("ERROR missing dependency: pymupdf (pip install pymupdf)")

        time.sleep(REQUEST_SLEEP_SEC)
    except Exception as e:
        logger.log(f"ERROR arxiv recent search err={repr(e)}")


def build_index_md(job: Job) -> str:
    base = job.out_dir

    def rel_path_str(path: Path, base_dir: Path) -> str:
        rel = os.path.relpath(path.resolve(), base_dir.resolve())
        rel = Path(rel).as_posix()
        rel = f"./{rel}" if not rel.startswith(".") else rel
        return rel

    def fmt_path(path: Path, base_dir: Path) -> str:
        return f"`{rel_path_str(path, base_dir)}`"

    def shell_escape(arg: str) -> str:
        # Minimal quoting for readability; wrap if spaces or quotes exist.
        if not arg:
            return "\"\""
        if any(c in arg for c in (' ', '"')):
            return '"' + arg.replace('"', '\\"') + '"'
        return arg

    def build_repro_command(j: Job) -> str:
        args = [
            "python",
            "-m",
            "hidair_feather",
            "--input",
            str(j.src_file),
            "--output",
            str(j.root_dir.parent),
            "--days",
            str(j.days),
            "--max-results",
            str(j.max_results),
        ]
        if j.download_pdf:
            args.append("--download-pdf")
        if j.lang_pref:
            args += ["--lang", j.lang_pref]
        if j.openalex_enabled:
            args.append("--openalex")
        if j.openalex_max_results:
            args += ["--oa-max-results", str(j.openalex_max_results)]
        if j.youtube_enabled:
            args.append("--youtube")
        if j.youtube_transcript:
            args.append("--yt-transcript")
        if j.youtube_max_results and j.youtube_max_results != j.max_results:
            args += ["--yt-max-results", str(j.youtube_max_results)]
        if j.youtube_order and j.youtube_order != "relevance":
            args += ["--yt-order", j.youtube_order]
        if j.set_id:
            args += ["--set-id", j.set_id]
        return " ".join(shell_escape(a) for a in args)

    def load_youtube_transcript_meta(path: Path) -> dict:
        meta: dict = {}
        if not path.exists():
            return meta
        for line in path.read_text(encoding="utf-8", errors="ignore").splitlines():
            line = line.strip()
            if not line:
                continue
            try:
                data = json.loads(line)
            except json.JSONDecodeError:
                continue
            videos: List[dict] = []
            if isinstance(data.get("videos"), list):
                videos = [v for v in data.get("videos") if isinstance(v, dict)]
            elif isinstance(data.get("video"), dict):
                videos = [data.get("video")]
            for video in videos:
                transcript_path = video.get("transcript_path")
                if not transcript_path or transcript_path in meta:
                    continue
                meta[transcript_path] = {
                    "title": video.get("title") or "-",
                    "source": video.get("url") or video.get("direct_url") or "-",
                }
        return meta

    def load_arxiv_meta(path: Path) -> dict:
        meta: dict = {}
        if not path.exists():
            return meta
        for line in path.read_text(encoding="utf-8", errors="ignore").splitlines():
            line = line.strip()
            if not line:
                continue
            try:
                data = json.loads(line)
            except json.JSONDecodeError:
                continue
            if not isinstance(data, dict):
                continue
            paper = data.get("paper") if isinstance(data.get("paper"), dict) else data
            if not isinstance(paper, dict):
                continue
            arxiv_id = paper.get("arxiv_id")
            if not arxiv_id or arxiv_id in meta:
                continue
            meta[arxiv_id] = {
                "title": paper.get("title") or "-",
                "source": paper.get("pdf_url") or paper.get("entry_id") or "-",
                "citations": paper.get("cited_by_count"),
            }
        return meta

    def load_openalex_meta(path: Path) -> dict:
        meta: dict = {}
        if not path.exists():
            return meta
        for line in path.read_text(encoding="utf-8", errors="ignore").splitlines():
            line = line.strip()
            if not line:
                continue
            try:
                data = json.loads(line)
            except json.JSONDecodeError:
                continue
            if not isinstance(data, dict):
                continue
            work = data.get("work") if isinstance(data.get("work"), dict) else None
            if not work:
                continue
            oa_id = work.get("openalex_id_short") or safe_filename(work.get("doi") or "", max_len=40) or "openalex"
            if oa_id in meta:
                continue
            pdf_urls = work.get("pdf_urls") or []
            pdf_url = work.get("downloaded_pdf_url") or work.get("pdf_url") or (pdf_urls[0] if pdf_urls else None)
            source = pdf_url or work.get("landing_page_url") or "-"
            meta[oa_id] = {
                "title": work.get("title") or "-",
                "source": source,
                "citations": work.get("cited_by_count"),
            }
        return meta

    def load_web_pdf_sources(j: Job) -> dict:
        sources: dict = {}
        for idx, url in enumerate(j.urls, start=1):
            if not is_pdf_url(url):
                continue
            name = url_to_pdf_name(url, f"url_{idx:04d}.pdf")
            sources[name] = url
        return sources

    def load_local_manifest(path: Path) -> List[dict]:
        entries: List[dict] = []
        if not path.exists():
            return entries
        for line in path.read_text(encoding="utf-8", errors="ignore").splitlines():
            line = line.strip()
            if not line:
                continue
            try:
                data = json.loads(line)
            except json.JSONDecodeError:
                continue
            if isinstance(data, dict):
                entries.append(data)
        return entries

    def one_line(value: Optional[str]) -> str:
        if not value:
            return "-"
        return " ".join(str(value).split())

    def format_citations(value: object) -> str:
        if value is None:
            return "-"
        return str(value)

    idx_md: List[str] = []
    idx_md.append(f"# Archive {job.query_id}\n\n")
    idx_md.append(f"- Query ID: `{job.query_id}`\n")
    idx_md.append(f"- Date: {job.date.isoformat()} (range: last {job.days} days)\n")
    query_count = len(job.query_specs) if job.query_specs else len(job.queries)
    idx_md.append(f"- Queries: {query_count} | URLs: {len(job.urls)} | arXiv IDs: {len(job.arxiv_ids)}\n\n")

    idx_md.append("## Run Command\n")
    idx_md.append(f"- `{build_repro_command(job)}`\n\n")

    idx_md.append("## Instruction\n")
    instr_dir = job.root_dir / "instruction"
    if instr_dir.exists():
        instr_files = sorted(instr_dir.glob("*.txt"))
        if instr_files:
            for f in instr_files:
                idx_md.append(f"- {fmt_path(f, base)}\n")
        else:
            idx_md.append("- (no instruction files found)\n")
    else:
        idx_md.append("- (instruction folder missing)\n")
    idx_md.append("\n")

    local_manifest = job.out_dir / "local" / "manifest.jsonl"
    if local_manifest.exists():
        idx_md.append("## Local Files\n")
        idx_md.append(f"- {fmt_path(local_manifest, base)}\n")
        local_entries = load_local_manifest(local_manifest)
        idx_md.append(f"- Files: {len(local_entries)}\n")
        text_count = sum(1 for entry in local_entries if entry.get("content_path"))
        idx_md.append(f"- Texts: {text_count}\n")
        for entry in local_entries[:50]:
            text_path = entry.get("content_path") or "-"
            raw_path = entry.get("raw_path") or "-"
            title = one_line(entry.get("title"))
            source = one_line(entry.get("source_path"))
            idx_md.append(f"- Text file: `{text_path}` | Raw: `{raw_path}` | Title: {title} | Source: {source}\n")
        if len(local_entries) > 50:
            idx_md.append(f"- ... and {len(local_entries)-50} more\n")
        idx_md.append("\n")

    if (job.out_dir / "tavily_search.jsonl").exists():
        idx_md.append("## Tavily Search\n")
        idx_md.append(f"- {fmt_path(job.out_dir / 'tavily_search.jsonl', base)}\n")
        idx_md.append("- Includes per-result `summary` and `query_summary`\n\n")

    extract_dir = job.out_dir / "tavily_extract"
    if extract_dir.exists():
        files = sorted(extract_dir.glob("*.txt"))
        idx_md.append("## Tavily Extract\n")
        for f in files[:50]:
            idx_md.append(f"- {fmt_path(f, base)}\n")
        if len(files) > 50:
            idx_md.append(f"- ... and {len(files)-50} more\n")
        idx_md.append("\n")

    youtube_dir = job.out_dir / "youtube"
    if youtube_dir.exists():
        idx_md.append("## YouTube\n")
        videos_path = youtube_dir / "videos.jsonl"
        youtube_meta = load_youtube_transcript_meta(videos_path) if videos_path.exists() else {}
        if videos_path.exists():
            idx_md.append(f"- {fmt_path(videos_path, base)}\n")
        transcript_dir = youtube_dir / "transcripts"
        transcripts = list(transcript_dir.glob("*.txt")) if transcript_dir.exists() else []
        idx_md.append(f"- Transcripts: {len(transcripts)}\n")
        for f in transcripts[:50]:
            rel = rel_path_str(f, base)
            meta = youtube_meta.get(rel) or {}
            title = one_line(meta.get("title"))
            source = one_line(meta.get("source"))
            idx_md.append(f"- Transcript file: {fmt_path(f, base)} | Title: {title} | Source: {source}\n")
        if len(transcripts) > 50:
            idx_md.append(f"- ... and {len(transcripts)-50} more\n")
        idx_md.append("\n")

    web_pdf_dir = job.out_dir / "web" / "pdf"
    web_text_dir = job.out_dir / "web" / "text"
    if web_pdf_dir.exists():
        idx_md.append("## Web PDFs\n")
        pdfs = sorted(web_pdf_dir.glob("*.pdf"))
        txts = sorted(web_text_dir.glob("*.txt")) if web_text_dir.exists() else []
        web_sources = load_web_pdf_sources(job)
        idx_md.append(f"- PDFs: {len(pdfs)}\n")
        for f in pdfs[:50]:
            source = one_line(web_sources.get(f.name))
            idx_md.append(f"- PDF file: {fmt_path(f, base)} | Source: {source}\n")
        if len(pdfs) > 50:
            idx_md.append(f"- ... and {len(pdfs)-50} more\n")
        idx_md.append(f"- Extracted texts: {len(txts)}\n")
        for f in txts[:50]:
            source = one_line(web_sources.get(f.with_suffix(".pdf").name))
            idx_md.append(f"- Text file: {fmt_path(f, base)} | Source: {source}\n")
        if len(txts) > 50:
            idx_md.append(f"- ... and {len(txts)-50} more\n")
        idx_md.append("\n")

    openalex_dir = job.out_dir / "openalex"
    if openalex_dir.exists():
        idx_md.append("## OpenAlex (OA)\n")
        works_path = openalex_dir / "works.jsonl"
        openalex_meta = load_openalex_meta(works_path) if works_path.exists() else {}
        if works_path.exists():
            idx_md.append(f"- {fmt_path(works_path, base)}\n")
        pdfs = list((openalex_dir / "pdf").glob("*.pdf")) if (openalex_dir / "pdf").exists() else []
        txts = list((openalex_dir / "text").glob("*.txt")) if (openalex_dir / "text").exists() else []
        idx_md.append(f"- PDFs: {len(pdfs)}\n")
        for f in pdfs[:50]:
            meta = openalex_meta.get(f.stem) or {}
            title = one_line(meta.get("title"))
            source = one_line(meta.get("source"))
            citations = format_citations(meta.get("citations"))
            idx_md.append(
                f"- PDF file: {fmt_path(f, base)} | Title: {title} | Source: {source} | Citations: {citations}\n"
            )
        if len(pdfs) > 50:
            idx_md.append(f"- ... and {len(pdfs)-50} more\n")
        idx_md.append(f"- Extracted texts: {len(txts)}\n")
        for f in txts[:50]:
            meta = openalex_meta.get(f.stem) or {}
            title = one_line(meta.get("title"))
            source = one_line(meta.get("source"))
            citations = format_citations(meta.get("citations"))
            idx_md.append(
                f"- Text file: {fmt_path(f, base)} | Title: {title} | Source: {source} | Citations: {citations}\n"
            )
        if len(txts) > 50:
            idx_md.append(f"- ... and {len(txts)-50} more\n")
        idx_md.append("\n")

    if (job.out_dir / "arxiv").exists():
        idx_md.append("## arXiv\n")
        papers_path = job.out_dir / "arxiv" / "papers.jsonl"
        arxiv_meta = load_arxiv_meta(papers_path) if papers_path.exists() else {}
        if papers_path.exists():
            idx_md.append(f"- {fmt_path(papers_path, base)}\n")
        pdfs = list((job.out_dir / "arxiv/pdf").glob("*.pdf")) if (job.out_dir / "arxiv/pdf").exists() else []
        txts = list((job.out_dir / "arxiv/text").glob("*.txt")) if (job.out_dir / "arxiv/text").exists() else []
        idx_md.append(f"- PDFs: {len(pdfs)}\n")
        for f in pdfs[:50]:
            meta = arxiv_meta.get(f.stem) or {}
            title = one_line(meta.get("title"))
            source = one_line(meta.get("source"))
            citations = format_citations(meta.get("citations"))
            idx_md.append(
                f"- PDF file: {fmt_path(f, base)} | Title: {title} | Source: {source} | Citations: {citations}\n"
            )
        if len(pdfs) > 50:
            idx_md.append(f"- ... and {len(pdfs)-50} more\n")
        idx_md.append(f"- Extracted texts: {len(txts)}\n\n")
        for f in txts[:50]:
            meta = arxiv_meta.get(f.stem) or {}
            title = one_line(meta.get("title"))
            source = one_line(meta.get("source"))
            citations = format_citations(meta.get("citations"))
            idx_md.append(
                f"- Text file: {fmt_path(f, base)} | Title: {title} | Source: {source} | Citations: {citations}\n"
            )
        if len(txts) > 50:
            idx_md.append(f"- ... and {len(txts)-50} more\n")
        idx_md.append("\n")

    return "".join(idx_md)


def run_job(job: Job, tavily: TavilyClient, stdout: bool = True) -> None:
    job.out_dir.mkdir(parents=True, exist_ok=True)
    logger = JobLogger(job.out_dir / "_log.txt", also_stdout=stdout)

    copy_instruction(job)
    write_job_json(job)

    logger.log(f"JOB START: {job.src_file.name} date={job.date.isoformat()} days={job.days} max_results={job.max_results}")

    run_local_ingest(job, logger)
    run_tavily_extract(job, tavily, logger)
    run_url_pdf_downloads(job, logger)
    run_tavily_search(job, tavily, logger)
    run_youtube(job, logger)
    run_openalex(job, logger)
    run_arxiv_ids(job, logger)
    run_arxiv_recent(job, logger)

    write_text(job.out_dir / f"{job.query_id}-index.md", build_index_md(job))

    logger.log("JOB END")
