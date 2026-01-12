import datetime as dt
from pathlib import Path

from hidair_feather.collector import (
    build_query_id,
    collect_instruction_files,
    is_explicit_youtube_query,
    normalize_youtube_query,
    parse_job,
    parse_instruction_sections,
    prepare_jobs,
    select_youtube_queries,
)
from hidair_feather.models import Job, QuerySpec


def test_collect_instruction_files_with_file(tmp_path) -> None:
    path = tmp_path / "instruction.txt"
    path.write_text("test", encoding="utf-8")
    files = collect_instruction_files(path)
    assert files == [path]


def test_build_query_id_rules() -> None:
    date_val = dt.date(2026, 1, 4)
    assert build_query_id(date_val, None, 1, 3) == "20260104_001"
    assert build_query_id(date_val, "oled", 1, 1) == "20260104_oled"
    assert build_query_id(date_val, "oled", 2, 3) == "20260104_oled_002"


def test_parse_job_extracts_parts(tmp_path) -> None:
    content = "\n".join(
        [
            "linkedin",
            "https://example.com/post",
            "arXiv:2401.01234",
            "quantum computing",
            "",
            "github",
            "agentic ai code",
            "",
            "file: doc.txt | title=Local Doc | tags=one,two | lang=en",
        ]
    )
    path = tmp_path / "20260104.txt"
    path.write_text(content, encoding="utf-8")
    (tmp_path / "doc.txt").write_text("local content", encoding="utf-8")

    job = parse_job(
        path,
        tmp_path,
        query_id="20260104_test",
        set_id=None,
        lang_pref=None,
        openalex_enabled=False,
        openalex_max_results=5,
        youtube_enabled=False,
        youtube_max_results=5,
        youtube_transcript=False,
        youtube_order="relevance",
        days=30,
        max_results=5,
        download_pdf=False,
        citations_enabled=True,
    )

    assert job.urls == ["https://example.com/post"]
    assert job.arxiv_ids == ["2401.01234"]
    assert job.site_hints == ["linkedin", "github"]
    assert job.queries == ["quantum computing", "agentic ai code"]
    assert job.query_specs == [
        QuerySpec(text="quantum computing", hints=["linkedin"]),
        QuerySpec(text="agentic ai code", hints=["github"]),
    ]
    assert len(job.local_paths) == 1
    local = job.local_paths[0]
    assert local.kind == "file"
    assert local.title == "Local Doc"
    assert local.tags == ["one", "two"]
    assert local.lang == "en"


def test_prepare_jobs_with_query(tmp_path) -> None:
    jobs = prepare_jobs(
        input_path=None,
        query="quantum computing; arXiv:2401.01234; https://example.com",
        output_root=tmp_path,
        set_id="qc",
        lang_pref="en",
        openalex_enabled=False,
        openalex_max_results=None,
        youtube_enabled=False,
        youtube_max_results=None,
        youtube_transcript=False,
        youtube_order="relevance",
        days=7,
        max_results=3,
        download_pdf=False,
        citations_enabled=True,
    )
    assert len(jobs) == 1
    job = jobs[0]
    assert job.query_id.endswith("_qc")
    assert job.set_id == "qc"
    assert job.lang_pref == "en"
    assert job.urls == ["https://example.com"]
    assert job.arxiv_ids == ["2401.01234"]
    assert job.queries == ["quantum computing"]
    assert job.query_specs == [QuerySpec(text="quantum computing", hints=[])]
    assert job.local_paths == []


def test_select_youtube_queries() -> None:
    job = Job(
        date=dt.date(2026, 1, 4),
        src_file=Path("x.txt"),
        root_dir=Path("out"),
        out_dir=Path("out/archive"),
        query_id="20260104_test",
        set_id=None,
        lang_pref=None,
        openalex_enabled=False,
        openalex_max_results=5,
        youtube_enabled=True,
        youtube_max_results=5,
        youtube_transcript=False,
        youtube_order="relevance",
        days=30,
        max_results=5,
        download_pdf=False,
        citations_enabled=True,
        queries=["site:youtube.com quantum ai", "plain query"],
        query_specs=[
            QuerySpec(text="site:youtube.com quantum ai", hints=[]),
            QuerySpec(text="plain query", hints=[]),
        ],
        local_paths=[],
        urls=[],
        arxiv_ids=[],
        site_hints=[],
        raw_lines=[],
    )
    assert select_youtube_queries(job) == ["site:youtube.com quantum ai"]
    job.query_specs = [QuerySpec(text="plain query", hints=["youtube"])]
    assert select_youtube_queries(job) == ["plain query"]


def test_normalize_youtube_query() -> None:
    assert normalize_youtube_query("site:youtube.com quantum ai") == "quantum ai"
    assert normalize_youtube_query("quantum ai") == "quantum ai"
    assert is_explicit_youtube_query("https://www.youtube.com/watch?v=abc") is True
    assert is_explicit_youtube_query("site:youtube.com quantum") is True
    assert is_explicit_youtube_query("plain query") is False


def test_parse_instruction_sections_dividers() -> None:
    content = "\n".join(
        [
            "linkedin",
            "news",
            "agentic ai",
            "-----",
            "",
            "youtube",
            "demo videos",
        ]
    )
    sections = parse_instruction_sections(content)
    assert sections == [
        ["linkedin", "news", "agentic ai"],
        ["youtube", "demo videos"],
    ]
