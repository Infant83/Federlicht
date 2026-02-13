from federlicht.report import format_metadata_block


def _base_meta() -> dict:
    return {
        "generated_at": "2026-02-14 12:00:00",
        "duration_hms": "00:00:10",
        "duration_seconds": 10,
        "model": "gpt-5.2",
        "quality_strategy": "pairwise",
        "quality_iterations": 1,
        "template": "default",
        "output_format": "html",
    }


def test_format_metadata_block_includes_artwork_tool_log_in_html() -> None:
    meta = _base_meta()
    meta["artwork_tool_log_path"] = "report_notes/artwork_tool_calls.md"
    rendered = format_metadata_block(meta, "html")
    assert "Artwork tool log" in rendered
    assert "report_notes/artwork_tool_calls.md" in rendered


def test_format_metadata_block_includes_artwork_tool_log_in_markdown() -> None:
    meta = _base_meta()
    meta["artwork_tool_log_path"] = "report_notes/artwork_tool_calls.md"
    rendered = format_metadata_block(meta, "md")
    assert "Artwork tool log: report_notes/artwork_tool_calls.md" in rendered

