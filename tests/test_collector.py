import datetime as dt
import json
from pathlib import Path

import feather.collector as collector
from feather.collector import (
    _agentic_endpoints,
    _build_heuristic_agentic_actions,
    _planner_chat_request,
    build_query_id,
    collect_instruction_files,
    is_explicit_youtube_query,
    normalize_youtube_query,
    parse_job,
    parse_instruction_sections,
    prepare_jobs,
    select_youtube_queries,
)
from feather.models import Job, QuerySpec


def test_collect_instruction_files_with_file(tmp_path) -> None:
    path = tmp_path / "instruction.txt"
    path.write_text("test", encoding="utf-8")
    files = collect_instruction_files(path)
    assert files == [path]


def test_build_query_id_rules(tmp_path) -> None:
    output_root = tmp_path
    used: set[str] = set()
    assert build_query_id("alpha", output_root, used) == "alpha"
    assert build_query_id("alpha", output_root, used) == "alpha_01"
    (output_root / "beta").mkdir()
    used.clear()
    assert build_query_id("beta", output_root, used) == "beta_01"


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
        arxiv_source=False,
        update_run=False,
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
        arxiv_source=False,
        update_run=False,
        citations_enabled=True,
    )
    assert len(jobs) == 1
    job = jobs[0]
    assert job.query_id == "quantum_computing"
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
        arxiv_source=False,
        update_run=False,
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
    job.query_specs = [
        QuerySpec(text="video gen ai", hints=[]),
        QuerySpec(text="가격 비교", hints=[]),
    ]
    assert select_youtube_queries(job) == ["video gen ai", "가격 비교"]


def test_agentic_endpoints_builds_chat_and_responses(monkeypatch) -> None:
    monkeypatch.setenv("OPENAI_BASE_URL", "https://api.openai.com/v1")
    endpoints = _agentic_endpoints()
    assert ("chat", "https://api.openai.com/v1/chat/completions") in endpoints
    assert ("responses", "https://api.openai.com/v1/responses") in endpoints
    assert endpoints[0][0] == "responses"


def test_build_heuristic_agentic_actions_prefers_missing_coverage() -> None:
    job = Job(
        date=dt.date(2026, 1, 4),
        src_file=Path("x.txt"),
        root_dir=Path("out"),
        out_dir=Path("out/archive"),
        query_id="20260104_test",
        lang_pref="ko",
        openalex_enabled=False,
        openalex_max_results=5,
        youtube_enabled=True,
        youtube_max_results=4,
        youtube_transcript=False,
        youtube_order="relevance",
        days=30,
        max_results=6,
        download_pdf=False,
        arxiv_source=False,
        update_run=True,
        citations_enabled=True,
        queries=["동영상 생성 ai"],
        query_specs=[QuerySpec(text="동영상 생성 ai", hints=[])],
        local_paths=[],
        urls=[],
        arxiv_ids=[],
        site_hints=[],
        raw_lines=[],
    )
    metrics = {
        "tavily_search_entries": 0,
        "tavily_extract_files": 0,
        "openalex_works": 0,
        "arxiv_papers": 0,
        "youtube_videos": 0,
        "candidate_urls": ["https://example.com/a", "https://example.com/b"],
    }
    actions = _build_heuristic_agentic_actions(job, metrics)
    types = [a.get("type") for a in actions]
    assert "tavily_search" in types
    assert "tavily_extract" in types
    assert "youtube_search" in types


def test_build_heuristic_agentic_actions_guarantees_search_fallback() -> None:
    job = Job(
        date=dt.date(2026, 1, 4),
        src_file=Path("x.txt"),
        root_dir=Path("out"),
        out_dir=Path("out/archive"),
        query_id="20260104_test",
        lang_pref="ko",
        openalex_enabled=False,
        openalex_max_results=5,
        youtube_enabled=False,
        youtube_max_results=5,
        youtube_transcript=False,
        youtube_order="relevance",
        days=30,
        max_results=6,
        download_pdf=False,
        arxiv_source=False,
        update_run=True,
        citations_enabled=True,
        queries=["동영상 생성 ai"],
        query_specs=[QuerySpec(text="동영상 생성 ai", hints=[])],
        local_paths=[],
        urls=[],
        arxiv_ids=[],
        site_hints=[],
        raw_lines=[],
    )
    metrics = {
        "tavily_search_entries": 12,
        "tavily_extract_files": 4,
        "openalex_works": 0,
        "arxiv_papers": 0,
        "youtube_videos": 0,
        "candidate_urls": [],
    }
    actions = _build_heuristic_agentic_actions(job, metrics)
    assert actions
    assert actions[0]["type"] == "tavily_search"
    assert "최신 동향" in str(actions[0]["query"])


def test_planner_chat_request_retries_payload_variants(monkeypatch) -> None:
    class StubResponse:
        def __init__(self, status_code: int, payload: dict):
            self.status_code = status_code
            self._payload = payload
            self.text = json.dumps(payload, ensure_ascii=False)

        def json(self) -> dict:
            return self._payload

    class StubLogger:
        def __init__(self):
            self.lines: list[str] = []

        def log(self, msg: str) -> None:
            self.lines.append(msg)

    responses = [
        StubResponse(
            400,
            {
                "error": {
                    "message": "Unsupported parameter: 'max_completion_tokens'",
                }
            },
        ),
        StubResponse(
            400,
            {
                "error": {
                    "message": "Unsupported parameter: 'max_tokens'",
                }
            },
        ),
        StubResponse(
            400,
            {
                "error": {
                    "message": "Unsupported parameter: 'response_format'",
                }
            },
        ),
        StubResponse(
            200,
            {
                "choices": [
                    {
                        "message": {
                            "content": "{\"done\": false, \"actions\": []}",
                        }
                    }
                ]
            },
        ),
    ]
    captured_calls: list[dict] = []

    def fake_post(_endpoint: str, json: dict, headers: dict, timeout: int):  # type: ignore[override]
        captured_calls.append(dict(json))
        return responses.pop(0)

    monkeypatch.setattr(collector.requests, "post", fake_post)
    logger = StubLogger()

    payload = _planner_chat_request(
        "https://api.openai.com/v1/chat/completions",
        "gpt-5-nano",
        "sys",
        "user",
        {"Content-Type": "application/json"},
        logger,
    )

    assert "choices" in payload
    assert len(captured_calls) == 4
    assert "max_completion_tokens" in captured_calls[0]
    assert "max_tokens" in captured_calls[1]
    assert "response_format" in captured_calls[2]
    assert "max_completion_tokens" not in captured_calls[2]
    assert "max_tokens" not in captured_calls[2]
    assert "response_format" not in captured_calls[3]
    assert any("retry with max_tokens" in line for line in logger.lines)
    assert any("retry without token budget" in line for line in logger.lines)
    assert any("retry without response_format" in line for line in logger.lines)


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
