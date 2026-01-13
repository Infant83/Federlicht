import json

from feather.review import (
    collect_run_summary,
    find_run_dirs,
    format_run_list,
    render_jsonl_review,
    render_review_json,
)


def create_run(tmp_path, name: str):
    run_dir = tmp_path / name
    archive = run_dir / "archive"
    archive.mkdir(parents=True)
    (archive / "_job.json").write_text(
        json.dumps(
            {
                "date": "2026-01-04",
                "queries": ["query"],
                "urls": ["https://example.com"],
                "arxiv_ids": ["2401.01234"],
            }
        ),
        encoding="utf-8",
    )
    (archive / "tavily_search.jsonl").write_text("{}", encoding="utf-8")
    tavily_extract = archive / "tavily_extract"
    tavily_extract.mkdir()
    (tavily_extract / "0001.txt").write_text("x", encoding="utf-8")

    arxiv = archive / "arxiv"
    arxiv.mkdir()
    (arxiv / "papers.jsonl").write_text("{}", encoding="utf-8")
    arxiv_pdf = arxiv / "pdf"
    arxiv_text = arxiv / "text"
    arxiv_pdf.mkdir()
    arxiv_text.mkdir()
    (arxiv_pdf / "a.pdf").write_bytes(b"%PDF-1.4")
    (arxiv_text / "a.txt").write_text("x", encoding="utf-8")

    openalex = archive / "openalex"
    openalex.mkdir()
    (openalex / "works.jsonl").write_text("{}", encoding="utf-8")
    openalex_pdf = openalex / "pdf"
    openalex_text = openalex / "text"
    openalex_pdf.mkdir()
    openalex_text.mkdir()
    (openalex_pdf / "oa.pdf").write_bytes(b"%PDF-1.4")
    (openalex_text / "oa.txt").write_text("x", encoding="utf-8")

    local = archive / "local"
    local_raw = local / "raw"
    local_text = local / "text"
    local_raw.mkdir(parents=True)
    local_text.mkdir()
    (local_raw / "local.pdf").write_bytes(b"%PDF-1.4")
    (local_text / "local.txt").write_text("x", encoding="utf-8")

    web = archive / "web"
    web_pdf = web / "pdf"
    web_text = web / "text"
    web_pdf.mkdir(parents=True)
    web_text.mkdir()
    (web_pdf / "w.pdf").write_bytes(b"%PDF-1.4")
    (web_text / "w.txt").write_text("x", encoding="utf-8")

    youtube = archive / "youtube"
    youtube.mkdir()
    (youtube / "videos.jsonl").write_text(
        json.dumps({"query": "demo", "videos": [{"video_id": "a"}, {"video_id": "b"}]}) + "\n",
        encoding="utf-8",
    )
    yt_transcripts = youtube / "transcripts"
    yt_transcripts.mkdir()
    (yt_transcripts / "a.txt").write_text("x", encoding="utf-8")

    (archive / f"{name}-index.md").write_text("# Archive", encoding="utf-8")
    return run_dir


def test_find_run_dirs_from_root(tmp_path) -> None:
    run_a = create_run(tmp_path, "20260104_demo")
    run_b = create_run(tmp_path, "20260105_demo")
    assert find_run_dirs(tmp_path) == [run_a, run_b]


def test_collect_run_summary_counts(tmp_path) -> None:
    run_dir = create_run(tmp_path, "20260104_demo")
    summary = collect_run_summary(run_dir)
    assert summary.query_id == "20260104_demo"
    assert summary.date == "2026-01-04"
    assert summary.tavily_search is True
    assert summary.tavily_extract_count == 1
    assert summary.arxiv_papers is True
    assert summary.arxiv_pdf_count == 1
    assert summary.arxiv_text_count == 1
    assert summary.openalex_works is True
    assert summary.openalex_pdf_count == 1
    assert summary.openalex_text_count == 1
    assert summary.local_raw_count == 1
    assert summary.local_text_count == 1
    assert summary.web_pdf_count == 1
    assert summary.web_text_count == 1
    assert summary.youtube_video_count == 2
    assert summary.youtube_transcript_count == 1
    assert summary.index_path and summary.index_path.name == "20260104_demo-index.md"

    listing = format_run_list([summary])
    assert "20260104_demo" in listing
    assert "S+E1" in listing

    payload = json.loads(render_review_json(run_dir))
    assert payload["query_id"] == "20260104_demo"
    assert payload["index_text"] == "# Archive"


def test_render_jsonl_review_tavily(tmp_path) -> None:
    path = tmp_path / "tavily_search.jsonl"
    payload = {
        "query": "oled",
        "result": {
            "results": [
                {"url": "https://arxiv.org/abs/2401.01234", "summary": "arxiv summary", "score": 0.9},
                {"url": "https://example.com/paper.pdf", "summary": "pdf summary", "score": 0.8},
                {"url": "https://example.com/page", "summary": "web summary", "score": 0.7},
            ]
        },
        "query_summary": "query summary text",
    }
    path.write_text(json.dumps(payload) + "\n", encoding="utf-8")
    output = render_jsonl_review(path)
    assert "Tavily search summary" in output
    assert "oled" in output
    assert "Results" in output
    assert "pdf=1" in output
    assert "arxiv=1" in output
