from __future__ import annotations

import datetime as dt
import json
from pathlib import Path
from typing import Optional


def write_workflow_summary(
    *,
    stage_status: dict[str, dict[str, str]],
    stage_order: list[str],
    notes_dir: Path,
    run_dir: Path,
    template_adjustment_path: Optional[Path],
) -> tuple[list[str], Path]:
    workflow_summary: list[str] = []
    for idx, name in enumerate(stage_order, start=1):
        entry = stage_status.get(name, {})
        status = entry.get("status", "unknown")
        detail = entry.get("detail", "")
        line = f"{idx}. {name}: {status}"
        if detail:
            line = f"{line} ({detail})"
        workflow_summary.append(line)
    workflow_path = notes_dir / "report_workflow.md"
    workflow_lines = ["# Report Workflow", "", "## Stages", *workflow_summary, ""]
    artifact_sections: dict[str, list[tuple[str, Path]]] = {
        "scout": [("Scout notes", notes_dir / "scout_notes.md")],
        "plan": [("Plan update", notes_dir / "report_plan.md")],
        "evidence": [
            ("Evidence notes", notes_dir / "evidence_notes.md"),
            ("Source triage", notes_dir / "source_triage.md"),
            ("Source index", notes_dir / "source_index.jsonl"),
            ("Claim map", notes_dir / "claim_map.md"),
            ("Gap report", notes_dir / "gap_finder.md"),
        ],
        "alignment": [
            ("Alignment (scout)", notes_dir / "alignment_scout.md"),
            ("Alignment (plan)", notes_dir / "alignment_plan.md"),
            ("Alignment (evidence)", notes_dir / "alignment_evidence.md"),
            ("Alignment (draft)", notes_dir / "alignment_draft.md"),
            ("Alignment (final)", notes_dir / "alignment_final.md"),
        ],
        "quality": [
            ("Quality evaluations", notes_dir / "quality_evals.jsonl"),
            ("Quality pairwise", notes_dir / "quality_pairwise.jsonl"),
        ],
        "template_adjust": [],
    }
    if template_adjustment_path:
        artifact_sections["template_adjust"].append(("Template adjustment", template_adjustment_path))

    artifact_lines: list[str] = []
    for stage_name in stage_order:
        items = artifact_sections.get(stage_name) or []
        existing = [
            (label, path)
            for label, path in items
            if isinstance(path, Path) and path.exists()
        ]
        if not existing:
            continue
        artifact_lines.append(f"### {stage_name}")
        for label, path in existing:
            try:
                rel = f"./{path.relative_to(run_dir).as_posix()}"
            except Exception:
                rel = path.as_posix()
            artifact_lines.append(f"- {label}: {rel}")
        artifact_lines.append("")
    if artifact_lines:
        workflow_lines.extend(["## Artifacts", *artifact_lines])
    workflow_path.write_text("\n".join(workflow_lines).strip() + "\n", encoding="utf-8")
    workflow_json_path = notes_dir / "report_workflow.json"
    workflow_payload = {
        "created_at": dt.datetime.now().isoformat(),
        "stages": stage_status,
        "order": list(stage_order),
    }
    workflow_json_path.write_text(
        json.dumps(workflow_payload, ensure_ascii=False, indent=2), encoding="utf-8"
    )
    return workflow_summary, workflow_path
