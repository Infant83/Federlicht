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
from typing import Any, Dict, Iterable, List, Optional

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

ARXIV_URL_RE = re.compile(
    r"""
    https?://(?:www\.)?arxiv\.org/
    (?:
        abs|
        pdf
    )/
    (?P<id>\d{4}\.\d{4,5})(?:v\d+)?(?:\.pdf)?
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
ARXIV_TEX_MAX_CHARS = 200000
ARXIV_FIGURE_EXTS = {".pdf", ".png", ".jpg", ".jpeg", ".eps", ".svg"}
INSTRUCTION_EXTS = {".txt", ".md", ".text", ".prompt", ".instruct", ".instruction"}
AGENTIC_TRACE_JSONL = "agentic_trace.jsonl"
AGENTIC_TRACE_MD = "agentic_trace.md"
AGENTIC_DEFAULT_MODEL = "gpt-4o-mini"
AGENTIC_DEFAULT_MAX_ITER = 3


def is_instruction_file(path: Path) -> bool:
    if not path.is_file():
        return False
    if path.name.startswith("."):
        return False
    suffix = path.suffix.lower()
    if suffix in INSTRUCTION_EXTS:
        return True
    return suffix == ""


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
    arxiv_source: bool,
    update_run: bool,
    citations_enabled: bool,
    agentic_search: bool = False,
    agentic_model: Optional[str] = None,
    agentic_max_iter: int = 0,
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
                if download_pdf or arxiv_source:
                    url_match = ARXIV_URL_RE.match(line)
                    if url_match:
                        arxiv_ids.append(url_match.group("id"))
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
        arxiv_source=arxiv_source,
        update_run=update_run,
        citations_enabled=citations_enabled,
        queries=dedup(queries),
        query_specs=dedup_specs(query_specs),
        local_paths=local_paths,
        urls=dedup(urls),
        arxiv_ids=dedup(arxiv_ids),
        site_hints=dedup(site_hints),
        raw_lines=raw_lines,
        agentic_search=agentic_search,
        agentic_model=agentic_model,
        agentic_max_iter=agentic_max_iter,
    )


def parse_job(
    txt_path: Path,
    out_root: Path,
    query_id: str,
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
    arxiv_source: bool,
    update_run: bool,
    citations_enabled: bool,
    agentic_search: bool = False,
    agentic_model: Optional[str] = None,
    agentic_max_iter: int = 0,
    file_date: Optional[dt.date] = None,
) -> Job:
    content = read_text(txt_path)
    sections = parse_instruction_sections(content)
    return build_job(
        sections=sections,
        src_file=txt_path,
        out_root=out_root,
        query_id=query_id,
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
        arxiv_source=arxiv_source,
        update_run=update_run,
        citations_enabled=citations_enabled,
        agentic_search=agentic_search,
        agentic_model=agentic_model,
        agentic_max_iter=agentic_max_iter,
        file_date=file_date,
    )


def collect_instruction_files(input_path: Path) -> List[Path]:
    if input_path.is_file():
        if not is_instruction_file(input_path):
            raise SystemExit(f"Input file must be a text-like file: {input_path}")
        return [input_path]
    if input_path.is_dir():
        return sorted(p for p in input_path.rglob("*") if is_instruction_file(p))
    raise SystemExit(f"Input path not found: {input_path}")


def infer_date(path: Path) -> dt.date:
    return parse_date_from_filename(path.stem) or parse_date_from_filename(path.parent.name) or dt.date.today()


def normalize_query_id_base(value: str) -> str:
    base = safe_filename(value, max_len=80).strip("_")
    return base or "run"


def derive_query_id_base_from_sections(sections: List[List[str]]) -> str:
    for section in sections:
        for line in section:
            lower = line.lower()
            if lower in SITE_HINTS:
                continue
            if lower.startswith(LOCAL_DIRECTIVES):
                continue
            if URL_RE.match(line):
                continue
            if ARXIV_ID_RE.search(line):
                continue
            return line
    return "query"


def build_query_id(base: str, output_root: Path, used_ids: set[str], reuse_existing: bool = False) -> str:
    base = normalize_query_id_base(base)
    candidate = base
    if reuse_existing and (output_root / candidate).exists():
        used_ids.add(candidate)
        return candidate
    if candidate not in used_ids and not (output_root / candidate).exists():
        used_ids.add(candidate)
        return candidate
    idx = 1
    while True:
        suffix = f"_{idx:02d}" if idx < 100 else f"_{idx}"
        candidate = f"{base}{suffix}"
        if candidate in used_ids:
            idx += 1
            continue
        if not (output_root / candidate).exists():
            used_ids.add(candidate)
            return candidate
        idx += 1


def prepare_jobs(
    input_path: Optional[Path],
    query: Optional[str],
    output_root: Path,
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
    arxiv_source: bool,
    update_run: bool,
    citations_enabled: bool,
    agentic_search: bool = False,
    agentic_model: Optional[str] = None,
    agentic_max_iter: int = 0,
) -> List[Job]:
    used_ids: set[str] = set()
    if query:
        sections = parse_query_text(query)
        if not sections:
            raise SystemExit("No instructions found in --query")
        date_val = dt.date.today()
        base = derive_query_id_base_from_sections(sections)
        query_id = build_query_id(base, output_root, used_ids, reuse_existing=update_run)
        src_file = Path("instruction.txt")
        return [
            build_job(
                sections=sections,
                src_file=src_file,
                out_root=output_root,
                query_id=query_id,
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
                arxiv_source=arxiv_source,
                update_run=update_run,
                citations_enabled=citations_enabled,
                agentic_search=agentic_search,
                agentic_model=agentic_model,
                agentic_max_iter=agentic_max_iter,
                file_date=date_val,
            )
        ]

    if input_path is None:
        raise SystemExit("Missing input path")

    txt_files = collect_instruction_files(input_path)
    if not txt_files:
        raise SystemExit(f"No .txt files found in: {input_path}")

    jobs: List[Job] = []
    for txt in txt_files:
        date_val = infer_date(txt)
        base = txt.stem
        query_id = build_query_id(base, output_root, used_ids, reuse_existing=update_run)
        jobs.append(
            parse_job(
                txt,
                output_root,
                query_id=query_id,
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
                arxiv_source=arxiv_source,
                update_run=update_run,
                citations_enabled=citations_enabled,
                agentic_search=agentic_search,
                agentic_model=agentic_model,
                agentic_max_iter=agentic_max_iter,
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


def load_jsonl_entries(path: Path) -> List[dict]:
    if not path.exists():
        return []
    entries: List[dict] = []
    for line in path.read_text(encoding="utf-8", errors="replace").splitlines():
        if not line.strip():
            continue
        try:
            data = json.loads(line)
        except json.JSONDecodeError:
            continue
        if isinstance(data, dict):
            entries.append(data)
    return entries


def normalize_arxiv_id(arxiv_id: str) -> str:
    return re.sub(r"v\d+$", "", arxiv_id.strip())


def load_existing_arxiv_ids(path: Path) -> set[str]:
    ids: set[str] = set()
    for entry in load_jsonl_entries(path):
        if "arxiv_id" in entry:
            arxiv_id = entry.get("arxiv_id")
        elif "paper" in entry and isinstance(entry.get("paper"), dict):
            arxiv_id = entry["paper"].get("arxiv_id")
        else:
            arxiv_id = None
        if arxiv_id:
            ids.add(normalize_arxiv_id(str(arxiv_id)))
    return ids


def openalex_work_key(work: dict) -> Optional[str]:
    if not isinstance(work, dict):
        return None
    key = work.get("openalex_id_short")
    if isinstance(key, str) and key:
        return key
    openalex_id = work.get("openalex_id") or work.get("id")
    if isinstance(openalex_id, str):
        key = openalex_ops.openalex_id_short(openalex_id)
        if key:
            return key
    doi = work.get("doi")
    if isinstance(doi, str):
        doi_key = safe_filename(doi, max_len=40)
        if doi_key:
            return doi_key
    title = work.get("title")
    if isinstance(title, str):
        title_key = safe_filename(title, max_len=60)
        if title_key:
            return title_key
    return None


def load_existing_openalex_ids(path: Path) -> set[str]:
    ids: set[str] = set()
    for entry in load_jsonl_entries(path):
        work = entry.get("work") if isinstance(entry.get("work"), dict) else entry
        if not isinstance(work, dict):
            continue
        key = openalex_work_key(work)
        if key:
            ids.add(key)
    return ids


def load_existing_youtube_ids(path: Path) -> set[str]:
    ids: set[str] = set()
    for entry in load_jsonl_entries(path):
        videos: List[dict] = []
        if isinstance(entry.get("videos"), list):
            videos = [v for v in entry.get("videos") if isinstance(v, dict)]
        elif isinstance(entry.get("video"), dict):
            videos = [entry.get("video")]
        for video in videos:
            video_id = video.get("video_id")
            if video_id:
                ids.add(str(video_id))
    return ids


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
    existing_suffixes: set[str] = set()
    if job.update_run and extract_dir.exists():
        for path in extract_dir.glob("*.txt"):
            name = path.name
            suffix = name.split("_", 1)[-1] if "_" in name else name
            if suffix:
                existing_suffixes.add(suffix)
    for idx, url in enumerate(job.urls, start=1):
        safe_name = f"{safe_filename(url)}.txt"
        if job.update_run and safe_name in existing_suffixes:
            logger.log(f"TAVILY EXTRACT SKIP (exists): {safe_name}")
            continue
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
                    if job.update_run and out_txt.exists():
                        logger.log(f"LINKEDIN EMBED EXTRACT SKIP (exists): {out_txt.name}")
                        continue
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
            if job.update_run and out_txt.exists():
                logger.log(f"TAVILY EXTRACT SKIP (exists): {out_txt.name}")
                continue
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
    raw_dir.mkdir(parents=True, exist_ok=True)
    text_dir.mkdir(parents=True, exist_ok=True)
    seen: set[str] = set()
    if job.update_run and manifest_path.exists():
        for entry in load_jsonl_entries(manifest_path):
            doc_id = entry.get("doc_id")
            if doc_id:
                seen.add(str(doc_id))

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
                if job.update_run and doc_id in seen:
                    continue
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
    existing_by_query: dict[str, dict] = {}
    if job.update_run and search_path.exists():
        for entry in load_jsonl_entries(search_path):
            query = entry.get("query")
            if isinstance(query, str) and query not in existing_by_query:
                existing_by_query[query] = entry
        if existing_by_query:
            logger.log(f"TAVILY SEARCH UPDATE: {len(existing_by_query)} cached queries")
    new_entries: list[dict] = []
    for spec in job.query_specs:
        try:
            q2 = apply_site_hint(spec.text, spec.hints)
            q2 = apply_language_hint(q2, job.lang_pref)
            if job.update_run and q2 in existing_by_query:
                logger.log(f"TAVILY SEARCH SKIP (exists): {q2}")
                continue
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
            if job.update_run:
                new_entries.append(payload)
            else:
                append_jsonl(search_path, payload)
            time.sleep(REQUEST_SLEEP_SEC)
        except Exception as e:
            logger.log(f"ERROR search query={spec.text} err={repr(e)}")
    if job.update_run and new_entries:
        merged: list[dict] = []
        seen: set[str] = set()
        for entry in list(existing_by_query.values()):
            query = entry.get("query")
            if isinstance(query, str) and query not in seen:
                merged.append(entry)
                seen.add(query)
        for entry in new_entries:
            query = entry.get("query")
            if isinstance(query, str):
                seen.add(query)
            merged.append(entry)
        search_path.parent.mkdir(parents=True, exist_ok=True)
        search_path.write_text(
            "\n".join(json.dumps(item, ensure_ascii=False) for item in merged) + "\n",
            encoding="utf-8",
        )


def run_youtube(job: Job, logger: JobLogger) -> None:
    if not job.youtube_enabled:
        return

    api_key = os.getenv("YOUTUBE_API_KEY")
    if not api_key:
        logger.log("ERROR missing environment variable: YOUTUBE_API_KEY")
        return

    videos_path = job.out_dir / "youtube" / "videos.jsonl"
    transcript_dir = job.out_dir / "youtube" / "transcripts"
    existing_ids: set[str] = set()
    if job.update_run and videos_path.exists():
        existing_ids = load_existing_youtube_ids(videos_path)
        if existing_ids:
            logger.log(f"YOUTUBE UPDATE: {len(existing_ids)} cached videos")

    published_after = dt.datetime.combine(job.date - dt.timedelta(days=job.days), dt.time.min)
    published_before = dt.datetime.combine(job.date, dt.time.max)
    relevance_language = job.lang_pref
    details_cache: dict[str, dict] = {}
    seen_ids: set[str] = set(existing_ids)
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
            fresh: List[dict] = []
            for vid in videos:
                add_summary(vid)
                video_id = vid.get("video_id")
                if job.update_run and video_id and video_id in seen_ids:
                    continue
                if video_id:
                    seen_ids.add(video_id)
                fresh.append(vid)
            videos = fresh
            if job.update_run and not videos:
                logger.log(f"YOUTUBE SEARCH SKIP (no new videos): {q}")
                continue

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
        if job.update_run and vid in existing_ids:
            logger.log(f"YOUTUBE DIRECT SKIP (exists): {url}")
            continue
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
    existing_ids: set[str] = set()
    if job.update_run and works_path.exists():
        existing_ids = load_existing_openalex_ids(works_path)
        if existing_ids:
            logger.log(f"OPENALEX UPDATE: {len(existing_ids)} cached works")

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
                work_key = openalex_work_key(w)
                oa_id = work_key or "openalex"
                skip_entry = bool(job.update_run and work_key and work_key in existing_ids)
                if skip_entry:
                    logger.log(f"OPENALEX SKIP (exists): {oa_id}")
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
                if skip_entry:
                    continue
                append_jsonl(works_path, {"query": q, "work": w})
                if work_key:
                    existing_ids.add(work_key)

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
    existing_ids: set[str] = set()
    if job.update_run and arxiv_meta_path.exists():
        existing_ids = load_existing_arxiv_ids(arxiv_meta_path)
        if existing_ids:
            logger.log(f"ARXIV UPDATE: {len(existing_ids)} cached papers")

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
        base_id = normalize_arxiv_id(aid)
        skip_meta = job.update_run and base_id in existing_ids
        if skip_meta and not job.download_pdf:
            logger.log(f"ARXIV ID SKIP (exists): {aid}")
            continue
        try:
            logger.log(f"ARXIV ID FETCH: {aid}")
            got = arxiv_ops.search_by_id(aid)
            if not got:
                logger.log(f"ARXIV ID NOT FOUND: {aid}")
                continue

            meta = arxiv_ops.result_to_metadata(got)
            meta = enrich_citations(meta)
            if not skip_meta:
                append_jsonl(arxiv_meta_path, meta)
                existing_ids.add(base_id)

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
    existing_ids: set[str] = set()
    if job.update_run and arxiv_meta_path.exists():
        existing_ids = load_existing_arxiv_ids(arxiv_meta_path)
        if existing_ids:
            logger.log(f"ARXIV UPDATE: {len(existing_ids)} cached papers")

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
        manifest_path = job.out_dir / "arxiv" / "src_manifest.jsonl"
        existing_src: set[str] = set()
        if job.arxiv_source and manifest_path.exists():
            try:
                for line in manifest_path.read_text(encoding="utf-8", errors="replace").splitlines():
                    if not line.strip():
                        continue
                    payload = json.loads(line)
                    arxiv_id = payload.get("arxiv_id")
                    if arxiv_id:
                        existing_src.add(arxiv_id)
            except Exception:
                pass
        for p in papers:
            base_id = normalize_arxiv_id(str(p.get("arxiv_id") or ""))
            skip_meta = job.update_run and base_id in existing_ids
            p = enrich_citations(p)
            if skip_meta:
                logger.log(f"ARXIV RECENT SKIP (exists): {base_id}")
            else:
                append_jsonl(arxiv_meta_path, {"source": "recent_search", "query": best_q, "paper": p})
                if base_id:
                    existing_ids.add(base_id)

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
            if job.arxiv_source and p.get("arxiv_id"):
                download_arxiv_source_for_id(job, logger, p["arxiv_id"], manifest_path, existing_src)

        time.sleep(REQUEST_SLEEP_SEC)
    except Exception as e:
        logger.log(f"ERROR arxiv recent search err={repr(e)}")


def find_main_tex(tex_files: List[Path]) -> Optional[Path]:
    for path in tex_files:
        try:
            head = path.read_text(encoding="utf-8", errors="replace")[:8000]
        except Exception:
            continue
        if "\\documentclass" in head or "\\begin{document}" in head:
            return path
    return tex_files[0] if tex_files else None


def extract_includegraphics(tex_text: str) -> List[str]:
    pattern = re.compile(r"\\includegraphics\\*?(?:\\[[^\\]]*\\])?\\{([^}]+)\\}")
    return [m.group(1).strip() for m in pattern.finditer(tex_text)]


def extract_tex_text(tex_files: List[Path], max_chars: int = ARXIV_TEX_MAX_CHARS) -> str:
    parts: List[str] = []
    total = 0
    for path in tex_files:
        try:
            text = path.read_text(encoding="utf-8", errors="replace")
        except Exception:
            continue
        header = f"\n\n===== {path.name} =====\n"
        chunk = header + text
        parts.append(chunk)
        total += len(chunk)
        if total >= max_chars:
            break
    return "".join(parts)


def collect_arxiv_source_info(src_dir: Path, run_dir: Path) -> dict:
    tex_files = sorted(src_dir.rglob("*.tex"))
    fig_files = sorted(
        [p for p in src_dir.rglob("*") if p.is_file() and p.suffix.lower() in ARXIV_FIGURE_EXTS]
    )
    main_tex = find_main_tex(tex_files)
    includegraphics: List[str] = []
    for tex in tex_files:
        try:
            includegraphics.extend(extract_includegraphics(tex.read_text(encoding="utf-8", errors="replace")))
        except Exception:
            continue
    fig_map: List[dict] = []
    if includegraphics and fig_files:
        by_name = {p.name: p for p in fig_files}
        by_stem = {}
        for p in fig_files:
            by_stem.setdefault(p.stem, []).append(p)
        for ref in includegraphics:
            ref_name = Path(ref).name
            match = None
            if ref_name in by_name:
                match = by_name[ref_name]
            elif ref_name in by_stem:
                match = by_stem[ref_name][0]
            if match:
                fig_map.append({"ref": ref, "file": f"./{match.relative_to(run_dir).as_posix()}"})
    return {
        "tex_files": [f"./{p.relative_to(run_dir).as_posix()}" for p in tex_files],
        "main_tex": f"./{main_tex.relative_to(run_dir).as_posix()}" if main_tex else None,
        "figure_files": [f"./{p.relative_to(run_dir).as_posix()}" for p in fig_files],
        "includegraphics": includegraphics,
        "figure_matches": fig_map,
    }


def download_arxiv_source_for_id(
    job: Job,
    logger: JobLogger,
    arxiv_id: str,
    manifest_path: Path,
    existing: set[str],
) -> None:
    if arxiv_id in existing:
        return
    src_root = job.out_dir / "arxiv" / "src"
    text_dir = job.out_dir / "arxiv" / "src_text"
    tar_path = src_root / f"{arxiv_id}.tar.gz"
    extract_dir = src_root / arxiv_id
    try:
        if not tar_path.exists():
            logger.log(f"ARXIV SRC DOWNLOAD: {arxiv_id}")
            arxiv_ops.arxiv_download_source(arxiv_id, tar_path)
        if not extract_dir.exists():
            logger.log(f"ARXIV SRC EXTRACT: {tar_path.name}")
            arxiv_ops.extract_arxiv_source(tar_path, extract_dir)
        info = collect_arxiv_source_info(extract_dir, job.out_dir)
        tex_paths = []
        for rel in info["tex_files"]:
            rel_path = rel.lstrip("./") if isinstance(rel, str) else str(rel)
            tex_paths.append(job.out_dir / rel_path)
        text = extract_tex_text(tex_paths, max_chars=ARXIV_TEX_MAX_CHARS)
        text_path = text_dir / f"{arxiv_id}.txt"
        if text and not text_path.exists():
            write_text(text_path, text)
        payload = {
            "arxiv_id": arxiv_id,
            "source_archive": f"./{tar_path.relative_to(job.out_dir).as_posix()}",
            "source_dir": f"./{extract_dir.relative_to(job.out_dir).as_posix()}",
            "text_path": f"./{text_path.relative_to(job.out_dir).as_posix()}" if text_path.exists() else None,
            "tex_files": info["tex_files"],
            "main_tex": info["main_tex"],
            "figure_files": info["figure_files"],
            "includegraphics": info["includegraphics"],
            "figure_matches": info["figure_matches"],
            "query_id": job.query_id,
        }
        append_jsonl(manifest_path, payload)
        existing.add(arxiv_id)
    except Exception as e:
        logger.log(f"ERROR arxiv src download id={arxiv_id} err={repr(e)}")


def run_arxiv_sources(job: Job, logger: JobLogger) -> None:
    if not job.arxiv_source or not job.arxiv_ids:
        return
    manifest_path = job.out_dir / "arxiv" / "src_manifest.jsonl"
    existing: set[str] = set()
    if manifest_path.exists():
        try:
            for line in manifest_path.read_text(encoding="utf-8", errors="replace").splitlines():
                if not line.strip():
                    continue
                payload = json.loads(line)
                arxiv_id = payload.get("arxiv_id")
                if arxiv_id:
                    existing.add(arxiv_id)
        except Exception:
            pass
    for aid in job.arxiv_ids:
        download_arxiv_source_for_id(job, logger, aid, manifest_path, existing)

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
            "feather",
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
        if j.arxiv_source:
            args.append("--arxiv-src")
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
        if j.update_run:
            args.append("--update-run")
        if j.agentic_search:
            args.append("--agentic-search")
            if j.agentic_model:
                args += ["--model", j.agentic_model]
            if j.agentic_max_iter and j.agentic_max_iter > 0:
                args += ["--max-iter", str(j.agentic_max_iter)]
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

        src_manifest = job.out_dir / "arxiv" / "src_manifest.jsonl"
        src_dir = job.out_dir / "arxiv" / "src"
        src_text_dir = job.out_dir / "arxiv" / "src_text"
        if src_manifest.exists() or src_dir.exists() or src_text_dir.exists():
            idx_md.append("## arXiv Source\n")
            if src_manifest.exists():
                idx_md.append(f"- {fmt_path(src_manifest, base)}\n")
            tarballs = sorted(src_dir.glob("*.tar.gz")) if src_dir.exists() else []
            idx_md.append(f"- Source archives: {len(tarballs)}\n")
            for f in tarballs[:50]:
                idx_md.append(f"- Source tar: {fmt_path(f, base)}\n")
            if len(tarballs) > 50:
                idx_md.append(f"- ... and {len(tarballs)-50} more\n")
            texts = sorted(src_text_dir.glob("*.txt")) if src_text_dir.exists() else []
            idx_md.append(f"- Extracted TeX texts: {len(texts)}\n")
            for f in texts[:50]:
                idx_md.append(f"- TeX text: {fmt_path(f, base)}\n")
            if len(texts) > 50:
                idx_md.append(f"- ... and {len(texts)-50} more\n")
            idx_md.append("\n")

    trace_json = job.out_dir / AGENTIC_TRACE_JSONL
    trace_md = job.out_dir / AGENTIC_TRACE_MD
    if trace_json.exists() or trace_md.exists():
        idx_md.append("## Agentic Trace\n")
        if trace_json.exists():
            idx_md.append(f"- {fmt_path(trace_json, base)}\n")
        if trace_md.exists():
            idx_md.append(f"- {fmt_path(trace_md, base)}\n")
        idx_md.append("\n")

    return "".join(idx_md)


def run_job(job: Job, tavily: TavilyClient, stdout: bool = True) -> None:
    job.out_dir.mkdir(parents=True, exist_ok=True)
    log_path = job.out_dir / "_log.txt"
    logger = JobLogger(log_path, also_stdout=stdout)

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
    run_arxiv_sources(job, logger)

    _finalize_job_outputs(job, log_path, logger)


def _finalize_job_outputs(job: Job, log_path: Path, logger: JobLogger) -> None:
    write_text(job.out_dir / f"{job.query_id}-index.md", build_index_md(job))

    logger.log("JOB END")
    feather_log = job.out_dir / "_feather_log.txt"
    try:
        if log_path.exists():
            shutil.copy2(log_path, feather_log)
    except Exception:
        pass


def _resolve_agentic_model(model_name: Optional[str]) -> str:
    token = (model_name or "").strip()
    if token:
        return token
    env_model = os.getenv("OPENAI_MODEL", "").strip()
    if env_model:
        return env_model
    return AGENTIC_DEFAULT_MODEL


def _agentic_endpoint() -> str:
    base = (os.getenv("OPENAI_BASE_URL") or "https://api.openai.com/v1").strip().rstrip("/")
    if base.endswith("/chat/completions"):
        return base
    if base.endswith("/v1"):
        return f"{base}/chat/completions"
    return f"{base}/chat/completions"


def _parse_json_object(text: str) -> Optional[Dict[str, Any]]:
    raw = (text or "").strip()
    if not raw:
        return None
    try:
        data = json.loads(raw)
        if isinstance(data, dict):
            return data
    except Exception:
        pass
    match = re.search(r"\{[\s\S]*\}", raw)
    if not match:
        return None
    try:
        data = json.loads(match.group(0))
    except Exception:
        return None
    return data if isinstance(data, dict) else None


def _call_agentic_planner(model_name: str, payload: Dict[str, Any], logger: JobLogger) -> Dict[str, Any]:
    endpoint = _agentic_endpoint()
    api_key = (os.getenv("OPENAI_API_KEY") or "").strip()
    headers = {"Content-Type": "application/json"}
    if api_key:
        headers["Authorization"] = f"Bearer {api_key}"
    system_prompt = (
        "You are Feather's agentic source planner. "
        "Use the archive state and instruction goals to select the next best data-collection actions. "
        "Prefer high-value, non-duplicative actions. "
        "Return strict JSON with keys: done (bool), reason (string), actions (array). "
        "Each action must include type plus query/url and optional max_results. "
        "Allowed types: tavily_search, tavily_extract, arxiv_recent, openalex_search, youtube_search, stop."
    )
    user_prompt = json.dumps(payload, ensure_ascii=False, indent=2)
    request_body: Dict[str, Any] = {
        "model": model_name,
        "messages": [
            {"role": "system", "content": system_prompt},
            {"role": "user", "content": user_prompt},
        ],
        "temperature": 0.1,
        "response_format": {"type": "json_object"},
    }
    try:
        response = requests.post(endpoint, json=request_body, headers=headers, timeout=120)
        if response.status_code >= 400 and "response_format" in request_body:
            logger.log("AGENTIC planner fallback: retry without response_format")
            request_body.pop("response_format", None)
            response = requests.post(endpoint, json=request_body, headers=headers, timeout=120)
        response.raise_for_status()
    except Exception as exc:
        raise RuntimeError(f"agentic planner request failed: {repr(exc)}") from exc
    try:
        data = response.json()
    except Exception as exc:
        raise RuntimeError(f"agentic planner returned non-JSON response: {repr(exc)}") from exc
    content = ""
    choices = data.get("choices")
    if isinstance(choices, list) and choices:
        message = choices[0].get("message") if isinstance(choices[0], dict) else None
        if isinstance(message, dict):
            message_content = message.get("content")
            if isinstance(message_content, str):
                content = message_content
            elif isinstance(message_content, list):
                parts: List[str] = []
                for chunk in message_content:
                    if isinstance(chunk, dict) and isinstance(chunk.get("text"), str):
                        parts.append(chunk["text"])
                content = "\n".join(parts).strip()
    parsed = _parse_json_object(content)
    if not parsed:
        raise RuntimeError("agentic planner produced unparseable output")
    if not isinstance(parsed.get("actions"), list):
        parsed["actions"] = []
    parsed["done"] = bool(parsed.get("done", False))
    parsed["reason"] = str(parsed.get("reason") or "")
    return parsed


def _jsonl_count(path: Path) -> int:
    if not path.exists():
        return 0
    count = 0
    with path.open("r", encoding="utf-8", errors="ignore") as handle:
        for line in handle:
            if line.strip():
                count += 1
    return count


def _youtube_video_count(path: Path) -> int:
    if not path.exists():
        return 0
    count = 0
    with path.open("r", encoding="utf-8", errors="ignore") as handle:
        for line in handle:
            line = line.strip()
            if not line:
                continue
            try:
                payload = json.loads(line)
            except Exception:
                continue
            videos = payload.get("videos")
            if isinstance(videos, list):
                count += len(videos)
            elif isinstance(payload.get("video"), dict):
                count += 1
    return count


def _collect_candidate_urls(search_path: Path, limit: int = 20) -> List[str]:
    out: List[str] = []
    seen: set[str] = set()
    if not search_path.exists():
        return out
    for line in search_path.read_text(encoding="utf-8", errors="ignore").splitlines():
        if len(out) >= limit:
            break
        line = line.strip()
        if not line:
            continue
        try:
            row = json.loads(line)
        except Exception:
            continue
        result = row.get("result")
        if not isinstance(result, dict):
            continue
        results = result.get("results")
        if not isinstance(results, list):
            continue
        for item in results:
            if len(out) >= limit:
                break
            if not isinstance(item, dict):
                continue
            url = item.get("url")
            if not isinstance(url, str):
                continue
            cleaned = url.strip()
            if not cleaned or cleaned in seen:
                continue
            seen.add(cleaned)
            out.append(cleaned)
    return out


def _collect_agentic_metrics(job: Job) -> Dict[str, Any]:
    archive = job.out_dir
    metrics = {
        "tavily_search_entries": _jsonl_count(archive / "tavily_search.jsonl"),
        "tavily_extract_files": len(list((archive / "tavily_extract").glob("*.txt")))
        if (archive / "tavily_extract").exists()
        else 0,
        "openalex_works": _jsonl_count(archive / "openalex" / "works.jsonl"),
        "arxiv_papers": _jsonl_count(archive / "arxiv" / "papers.jsonl"),
        "youtube_videos": _youtube_video_count(archive / "youtube" / "videos.jsonl"),
        "youtube_transcripts": len(list((archive / "youtube" / "transcripts").glob("*.txt")))
        if (archive / "youtube" / "transcripts").exists()
        else 0,
        "web_pdf": len(list((archive / "web" / "pdf").glob("*.pdf"))) if (archive / "web" / "pdf").exists() else 0,
        "web_text": len(list((archive / "web" / "text").glob("*.txt"))) if (archive / "web" / "text").exists() else 0,
    }
    metrics["candidate_urls"] = _collect_candidate_urls(archive / "tavily_search.jsonl", limit=20)
    return metrics


def _coerce_action_max(value: Any, default_value: int) -> int:
    try:
        parsed = int(value)
    except Exception:
        parsed = default_value
    if parsed < 1:
        parsed = 1
    return min(parsed, 20)


def _normalize_actions(plan: Dict[str, Any]) -> List[Dict[str, Any]]:
    actions = plan.get("actions")
    if not isinstance(actions, list):
        return []
    normalized: List[Dict[str, Any]] = []
    for item in actions[:8]:
        if not isinstance(item, dict):
            continue
        action_type = str(item.get("type") or "").strip().lower()
        if not action_type:
            continue
        normalized.append(
            {
                "type": action_type,
                "query": str(item.get("query") or "").strip(),
                "url": str(item.get("url") or "").strip(),
                "max_results": item.get("max_results"),
                "why": str(item.get("why") or "").strip(),
            }
        )
    return normalized


def _render_agentic_trace_md(trace_path: Path, out_path: Path, query_id: str) -> None:
    if not trace_path.exists():
        return
    rows: List[dict] = []
    for line in trace_path.read_text(encoding="utf-8", errors="ignore").splitlines():
        line = line.strip()
        if not line:
            continue
        try:
            payload = json.loads(line)
        except Exception:
            continue
        if isinstance(payload, dict):
            rows.append(payload)
    lines = [f"# Agentic Trace: {query_id}", ""]
    for row in rows:
        phase = str(row.get("phase") or "-")
        iteration = row.get("iter")
        lines.append(f"## Iter {iteration} / {phase}")
        if phase == "plan":
            reason = str(row.get("reason") or "").strip()
            if reason:
                lines.append(f"- Decision: {reason}")
            actions = row.get("actions") or []
            if isinstance(actions, list):
                for action in actions:
                    if not isinstance(action, dict):
                        continue
                    action_type = action.get("type") or "-"
                    query = action.get("query") or action.get("url") or "-"
                    lines.append(f"- Action: `{action_type}` | `{query}`")
        elif phase == "review":
            delta = row.get("delta") or {}
            if isinstance(delta, dict):
                formatted = ", ".join(f"{k}: {v:+d}" for k, v in delta.items() if isinstance(v, int) and v != 0)
                if formatted:
                    lines.append(f"- Delta: {formatted}")
            if row.get("done"):
                lines.append("- Done: yes")
        lines.append("")
    write_text(out_path, "\n".join(lines).strip() + "\n")


def _execute_agentic_actions(
    job: Job,
    actions: List[Dict[str, Any]],
    tavily: TavilyClient,
    logger: JobLogger,
) -> int:
    executed = 0
    for action in actions:
        action_type = action.get("type", "")
        if action_type in {"stop", "done"}:
            logger.log("AGENTIC action: stop")
            continue
        if action_type == "tavily_search":
            query = action.get("query") or ""
            if not query:
                logger.log("AGENTIC action skipped (missing query): tavily_search")
                continue
            action_max = _coerce_action_max(action.get("max_results"), job.max_results)
            temp_job = dataclasses.replace(
                job,
                query_specs=[QuerySpec(text=query, hints=[])],
                queries=[query],
                max_results=action_max,
                update_run=True,
            )
            logger.log(f"AGENTIC action: tavily_search query={query} max={action_max}")
            run_tavily_search(temp_job, tavily, logger)
            executed += 1
            continue
        if action_type == "tavily_extract":
            url = action.get("url") or ""
            if not URL_RE.match(url):
                logger.log("AGENTIC action skipped (invalid url): tavily_extract")
                continue
            temp_job = dataclasses.replace(job, urls=[url], update_run=True)
            logger.log(f"AGENTIC action: tavily_extract url={url}")
            run_tavily_extract(temp_job, tavily, logger)
            run_url_pdf_downloads(temp_job, logger)
            executed += 1
            continue
        if action_type == "openalex_search":
            query = action.get("query") or ""
            if not query:
                logger.log("AGENTIC action skipped (missing query): openalex_search")
                continue
            action_max = _coerce_action_max(action.get("max_results"), job.openalex_max_results or job.max_results)
            temp_job = dataclasses.replace(
                job,
                queries=[query],
                openalex_enabled=True,
                openalex_max_results=action_max,
                update_run=True,
            )
            logger.log(f"AGENTIC action: openalex_search query={query} max={action_max}")
            run_openalex(temp_job, logger)
            executed += 1
            continue
        if action_type == "arxiv_recent":
            query = action.get("query") or ""
            if not query:
                logger.log("AGENTIC action skipped (missing query): arxiv_recent")
                continue
            action_max = _coerce_action_max(action.get("max_results"), job.max_results)
            temp_job = dataclasses.replace(
                job,
                queries=[query],
                raw_lines=[query, "논문"],
                max_results=action_max,
                update_run=True,
            )
            logger.log(f"AGENTIC action: arxiv_recent query={query} max={action_max}")
            run_arxiv_recent(temp_job, logger)
            executed += 1
            continue
        if action_type == "youtube_search":
            query = action.get("query") or ""
            if not query:
                logger.log("AGENTIC action skipped (missing query): youtube_search")
                continue
            action_max = _coerce_action_max(action.get("max_results"), job.youtube_max_results or job.max_results)
            temp_job = dataclasses.replace(
                job,
                query_specs=[QuerySpec(text=query, hints=["youtube"])],
                queries=[query],
                youtube_enabled=True,
                youtube_max_results=action_max,
                update_run=True,
            )
            logger.log(f"AGENTIC action: youtube_search query={query} max={action_max}")
            run_youtube(temp_job, logger)
            executed += 1
            continue
        logger.log(f"AGENTIC action skipped (unknown type): {action_type}")
    return executed


def run_job_agentic(
    job: Job,
    tavily: TavilyClient,
    model_name: Optional[str] = None,
    max_iter: Optional[int] = None,
    stdout: bool = True,
) -> None:
    job.out_dir.mkdir(parents=True, exist_ok=True)
    log_path = job.out_dir / "_log.txt"
    trace_path = job.out_dir / AGENTIC_TRACE_JSONL
    logger = JobLogger(log_path, also_stdout=stdout)
    if not trace_path.exists():
        trace_path.parent.mkdir(parents=True, exist_ok=True)

    copy_instruction(job)
    write_job_json(job)

    resolved_model = _resolve_agentic_model(model_name or job.agentic_model)
    iterations = max_iter if max_iter is not None else job.agentic_max_iter
    if not iterations or iterations < 1:
        iterations = AGENTIC_DEFAULT_MAX_ITER
    logger.log(
        f"JOB START (agentic): {job.src_file.name} date={job.date.isoformat()} max_results={job.max_results} model={resolved_model}"
    )

    # Bootstrap with the deterministic pipeline so agentic turns can build on concrete archive outputs.
    run_local_ingest(job, logger)
    run_tavily_extract(job, tavily, logger)
    run_url_pdf_downloads(job, logger)
    run_tavily_search(job, tavily, logger)
    run_youtube(job, logger)
    run_openalex(job, logger)
    run_arxiv_ids(job, logger)
    run_arxiv_recent(job, logger)
    run_arxiv_sources(job, logger)

    trace_entries: List[dict] = []
    for iter_idx in range(1, iterations + 1):
        metrics_before = _collect_agentic_metrics(job)
        plan_payload = {
            "query_id": job.query_id,
            "iteration": iter_idx,
            "max_iterations": iterations,
            "instruction_lines": job.raw_lines,
            "goals": {
                "days": job.days,
                "default_max_results": job.max_results,
            },
            "current_archive": metrics_before,
            "last_trace": trace_entries[-4:],
            "guidance": (
                "Choose next high-value actions only. "
                "If evidence coverage is sufficient for the instruction, set done=true."
            ),
        }
        try:
            plan = _call_agentic_planner(resolved_model, plan_payload, logger)
        except Exception as exc:
            logger.log(f"AGENTIC planner error iter={iter_idx}: {repr(exc)}")
            break
        actions = _normalize_actions(plan)
        plan_entry = {
            "iter": iter_idx,
            "phase": "plan",
            "done": bool(plan.get("done", False)),
            "reason": str(plan.get("reason") or ""),
            "actions": actions,
            "metrics_before": metrics_before,
        }
        append_jsonl(trace_path, plan_entry)
        trace_entries.append(plan_entry)
        if plan_entry["done"] and not actions:
            logger.log(f"AGENTIC stop iter={iter_idx}: {plan_entry['reason'] or 'planner done'}")
            break
        executed = _execute_agentic_actions(job, actions, tavily, logger)
        metrics_after = _collect_agentic_metrics(job)
        delta = {}
        for key, before in metrics_before.items():
            after = metrics_after.get(key)
            if isinstance(before, int) and isinstance(after, int):
                delta[key] = after - before
        review_entry = {
            "iter": iter_idx,
            "phase": "review",
            "executed": executed,
            "done": bool(plan.get("done", False)),
            "reason": str(plan.get("reason") or ""),
            "delta": delta,
            "metrics_after": metrics_after,
        }
        append_jsonl(trace_path, review_entry)
        trace_entries.append(review_entry)
        if plan_entry["done"]:
            logger.log(f"AGENTIC stop iter={iter_idx}: {plan_entry['reason'] or 'planner done'}")
            break
        if executed == 0:
            logger.log(f"AGENTIC stop iter={iter_idx}: no executable actions")
            break
    _render_agentic_trace_md(trace_path, job.out_dir / AGENTIC_TRACE_MD, job.query_id)
    _finalize_job_outputs(job, log_path, logger)
