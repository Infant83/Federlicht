from __future__ import annotations

import json
from pathlib import Path

from federlicht.workflow_trace import write_workflow_summary


def test_write_workflow_summary_writes_stage_and_artifact_outputs(tmp_path: Path) -> None:
    run_dir = tmp_path
    notes_dir = run_dir / "report_notes"
    notes_dir.mkdir(parents=True, exist_ok=True)
    (notes_dir / "scout_notes.md").write_text("# scout", encoding="utf-8")
    template_adjustment_path = notes_dir / "template_adjustment.md"
    template_adjustment_path.write_text("adjustment", encoding="utf-8")

    stage_order = ["scout", "template_adjust", "quality"]
    stage_status = {
        "scout": {"status": "ran", "detail": "ok"},
        "template_adjust": {"status": "ran", "detail": ""},
        "quality": {"status": "skipped", "detail": "state_only"},
    }

    workflow_summary, workflow_path = write_workflow_summary(
        stage_status=stage_status,
        stage_order=stage_order,
        notes_dir=notes_dir,
        run_dir=run_dir,
        template_adjustment_path=template_adjustment_path,
    )

    assert workflow_summary == [
        "1. scout: ran (ok)",
        "2. template_adjust: ran",
        "3. quality: skipped (state_only)",
    ]
    assert workflow_path == notes_dir / "report_workflow.md"

    markdown = workflow_path.read_text(encoding="utf-8")
    assert "## Stages" in markdown
    assert "1. scout: ran (ok)" in markdown
    assert "## Artifacts" in markdown
    assert "- Scout notes: ./report_notes/scout_notes.md" in markdown
    assert "- Template adjustment: ./report_notes/template_adjustment.md" in markdown

    workflow_json_path = notes_dir / "report_workflow.json"
    payload = json.loads(workflow_json_path.read_text(encoding="utf-8"))
    assert payload["stages"] == stage_status
    assert payload["order"] == stage_order
    assert isinstance(payload.get("created_at"), str) and payload["created_at"]
