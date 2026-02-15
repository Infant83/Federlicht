from __future__ import annotations

from federlicht import artwork


def test_build_mermaid_flowchart_basic() -> None:
    snippet = artwork.build_mermaid_flowchart(
        "start|Start;writer|Writer;result|Result",
        "start->writer|draft;writer->result|publish",
        direction="LR",
        title="Workflow",
    )
    assert "```mermaid" in snippet
    assert "flowchart LR" in snippet
    assert 'start["Start"]' in snippet
    assert "start -->|draft| writer" in snippet
    assert "Figure: Workflow" in snippet


def test_build_mermaid_timeline_basic() -> None:
    snippet = artwork.build_mermaid_timeline("2026-Q1|kickoff;2026-Q2|draft")
    assert "```mermaid" in snippet
    assert "timeline" in snippet
    assert "2026-Q1 : kickoff" in snippet
    assert "2026-Q2 : draft" in snippet


def test_render_d2_svg_missing_cli(tmp_path, monkeypatch) -> None:
    monkeypatch.setattr(artwork, "_resolve_d2_command", lambda: [])
    result = artwork.render_d2_svg(tmp_path, "a -> b")
    assert result["ok"] == "false"
    assert result["error"] == "d2_cli_missing"


def test_render_diagrams_missing_package(tmp_path, monkeypatch) -> None:
    monkeypatch.setattr(artwork, "_has_diagrams_package", lambda: False)
    result = artwork.render_diagrams_architecture(tmp_path, "a|A;b|B", "a->b")
    assert result["ok"] == "false"
    assert result["error"] == "diagrams_missing"


def test_render_diagrams_missing_dot(tmp_path, monkeypatch) -> None:
    monkeypatch.setattr(artwork, "_has_diagrams_package", lambda: True)
    monkeypatch.setattr(artwork, "_resolve_dot_command", lambda: None)
    result = artwork.render_diagrams_architecture(tmp_path, "a|A;b|B", "a->b")
    assert result["ok"] == "false"
    assert result["error"] == "graphviz_dot_missing"
