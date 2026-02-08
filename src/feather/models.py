from dataclasses import dataclass
from datetime import date
from pathlib import Path
from typing import List, Optional


@dataclass
class QuerySpec:
    text: str
    hints: List[str]


@dataclass
class LocalPathSpec:
    kind: str
    value: str
    title: Optional[str]
    tags: List[str]
    lang: Optional[str]


@dataclass
class Job:
    date: date
    src_file: Path
    root_dir: Path
    out_dir: Path
    query_id: str
    lang_pref: Optional[str]
    openalex_enabled: bool
    openalex_max_results: int
    youtube_enabled: bool
    youtube_max_results: int
    youtube_transcript: bool
    youtube_order: str
    days: int
    max_results: int
    download_pdf: bool
    arxiv_source: bool
    update_run: bool
    citations_enabled: bool
    queries: List[str]
    query_specs: List[QuerySpec]
    local_paths: List[LocalPathSpec]
    urls: List[str]
    arxiv_ids: List[str]
    site_hints: List[str]
    raw_lines: List[str]
    agentic_search: bool = False
    agentic_model: Optional[str] = None
    agentic_max_iter: int = 0
