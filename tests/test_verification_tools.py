from __future__ import annotations

from federlicht.verification_tools import parse_verification_requests


def test_parse_verification_requests_requires_artifact_context() -> None:
    text = "NEEDS_VERIFICATION: check [chunk_001]"
    assert parse_verification_requests(text) == []


def test_parse_verification_requests_uses_latest_artifact() -> None:
    text = "\n".join(
        [
            "[artifact] Original chunks: report_notes/tool_cache/read_old",
            "NEEDS_VERIFICATION: prior [chunk_001]",
            "[artifact] Original chunks: report_notes/tool_cache/read_new",
            "NEEDS_VERIFICATION: first [chunk_002] and [chunk_003]",
        ]
    )
    assert parse_verification_requests(text) == [
        ("report_notes/tool_cache/read_old", "chunk_001.txt"),
        ("report_notes/tool_cache/read_new", "chunk_002.txt"),
        ("report_notes/tool_cache/read_new", "chunk_003.txt"),
    ]


def test_parse_verification_requests_ignores_non_matching_lines() -> None:
    text = "\n".join(
        [
            "[artifact] Original chunks: report_notes/tool_cache/read_x",
            "notes: maybe chunk_001",
            "NEEDS_VERIFICATION: no bracket chunk_001",
            "NEEDS_VERIFICATION: verify [chunk_004]",
        ]
    )
    assert parse_verification_requests(text) == [
        ("report_notes/tool_cache/read_x", "chunk_004.txt")
    ]

