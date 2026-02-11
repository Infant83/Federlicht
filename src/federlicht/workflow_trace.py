from __future__ import annotations

import datetime as dt
import json
from pathlib import Path
from typing import Optional


def _normalize_stage_events(
    stage_events: Optional[list[dict[str, str]]],
    stage_order: list[str],
    stage_status: dict[str, dict[str, str]],
) -> list[dict[str, str]]:
    if stage_events:
        normalized: list[dict[str, str]] = []
        for idx, event in enumerate(stage_events, start=1):
            stage_name = str(event.get("stage") or "").strip().lower()
            if not stage_name:
                continue
            normalized.append(
                {
                    "index": str(event.get("index") or idx),
                    "timestamp": str(event.get("timestamp") or ""),
                    "stage": stage_name,
                    "status": str(event.get("status") or "").strip().lower() or "unknown",
                    "detail": str(event.get("detail") or "").strip(),
                }
            )
        if normalized:
            return normalized
    inferred: list[dict[str, str]] = []
    for idx, stage_name in enumerate(stage_order, start=1):
        entry = stage_status.get(stage_name, {})
        inferred.append(
            {
                "index": str(idx),
                "timestamp": "",
                "stage": stage_name,
                "status": str(entry.get("status") or "unknown"),
                "detail": str(entry.get("detail") or ""),
            }
        )
    return inferred


def _build_mermaid(
    stage_order: list[str],
    stage_status: dict[str, dict[str, str]],
) -> str:
    order = [name for name in stage_order if name in stage_status]
    if not order:
        return ""
    lines = ["flowchart LR"]
    for stage_name in order:
        status = str((stage_status.get(stage_name) or {}).get("status") or "unknown")
        safe_label = f"{stage_name}\\n{status}".replace('"', "'")
        lines.append(f'    {stage_name}["{safe_label}"]')
    for idx in range(len(order) - 1):
        lines.append(f"    {order[idx]} --> {order[idx + 1]}")
    quality_status = str((stage_status.get("quality") or {}).get("status") or "").lower()
    if "quality" in order and "writer" in order and quality_status in {"ran", "cached", "done"}:
        lines.append("    quality -. feedback .-> writer")
    return "\n".join(lines)


def _artifact_sections(
    stage_order: list[str],
    notes_dir: Path,
    run_dir: Path,
    template_adjustment_path: Optional[Path],
) -> tuple[list[str], dict[str, list[dict[str, str]]]]:
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
    artifact_payload: dict[str, list[dict[str, str]]] = {}
    for stage_name in stage_order:
        items = artifact_sections.get(stage_name) or []
        existing: list[dict[str, str]] = []
        for label, path in items:
            if not isinstance(path, Path) or not path.exists():
                continue
            try:
                rel = f"./{path.relative_to(run_dir).as_posix()}"
            except Exception:
                rel = path.as_posix()
            existing.append({"label": label, "path": rel})
        if not existing:
            continue
        artifact_payload[stage_name] = existing
        artifact_lines.append(f"### {stage_name}")
        for item in existing:
            artifact_lines.append(f"- {item['label']}: {item['path']}")
        artifact_lines.append("")
    return artifact_lines, artifact_payload


def write_workflow_summary(
    *,
    stage_status: dict[str, dict[str, str]],
    stage_order: list[str],
    notes_dir: Path,
    run_dir: Path,
    template_adjustment_path: Optional[Path],
    stage_events: Optional[list[dict[str, str]]] = None,
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
    timeline = _normalize_stage_events(stage_events, stage_order, stage_status)
    if timeline:
        workflow_lines.extend(["## Timeline", ""])
        for idx, event in enumerate(timeline, start=1):
            stamp = f"[{event['timestamp']}] " if event.get("timestamp") else ""
            detail = f" ({event['detail']})" if event.get("detail") else ""
            workflow_lines.append(
                f"{idx}. {stamp}{event['stage']}: {event['status']}{detail}"
            )
        workflow_lines.append("")
    artifact_lines, artifact_payload = _artifact_sections(
        stage_order,
        notes_dir,
        run_dir,
        template_adjustment_path,
    )
    if artifact_lines:
        workflow_lines.extend(["## Artifacts", *artifact_lines])
    mermaid = _build_mermaid(stage_order, stage_status)
    if mermaid:
        workflow_lines.extend(["## Diagram", "", "```mermaid", mermaid, "```", ""])
    workflow_path.write_text("\n".join(workflow_lines).strip() + "\n", encoding="utf-8")
    workflow_json_path = notes_dir / "report_workflow.json"
    workflow_payload = {
        "created_at": dt.datetime.now().isoformat(),
        "stages": stage_status,
        "order": list(stage_order),
        "timeline": timeline,
        "artifacts": artifact_payload,
        "diagram_mermaid": mermaid,
    }
    workflow_json_path.write_text(
        json.dumps(workflow_payload, ensure_ascii=False, indent=2), encoding="utf-8"
    )
    return workflow_summary, workflow_path
