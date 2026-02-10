from __future__ import annotations

import argparse
import json
from types import SimpleNamespace


def test_reordered_pipeline_fixture_emits_metrics_and_writes_workflow(monkeypatch, tmp_path, capsys) -> None:
    import federlicht.pipeline_runner_impl as runner

    run_dir = tmp_path / "run_case"
    (run_dir / "archive").mkdir(parents=True, exist_ok=True)
    (run_dir / "instruction").mkdir(parents=True, exist_ok=True)
    (run_dir / "instruction" / "prompt.txt").write_text("demo prompt", encoding="utf-8")

    class FakeOrchestrator:
        def __init__(self, context, _helpers, _overrides, _create) -> None:
            self._args = context.args

        def run(self, state=None, allow_partial=False):  # noqa: ARG002
            stages = [token.strip() for token in str(self._args.stages or "").split(",") if token.strip()]
            summary = []
            for idx, stage_name in enumerate(stages, start=1):
                status = "cached" if idx == 1 else "ran"
                summary.append(f"{idx}. {stage_name}: {status}")
            notes_dir = run_dir / "report_notes"
            notes_dir.mkdir(parents=True, exist_ok=True)
            report_text = "Draft output" if "writer" in stages or "quality" in stages else ""
            return SimpleNamespace(
                report=report_text,
                scout_notes="scout notes",
                plan_text="plan notes",
                plan_context="plan context",
                evidence_notes="evidence notes",
                align_draft=None,
                align_final=None,
                align_scout=None,
                align_plan=None,
                align_evidence=None,
                template_spec=SimpleNamespace(name="default"),
                template_guidance_text="",
                template_adjustment_path=None,
                required_sections=[],
                report_prompt=None,
                clarification_questions=None,
                clarification_answers=None,
                output_format="md",
                language="en",
                run_dir=run_dir,
                archive_dir=run_dir / "archive",
                notes_dir=notes_dir,
                supporting_dir=None,
                supporting_summary=None,
                source_triage_text="",
                claim_map_text="",
                gap_text="",
                context_lines=[],
                depth="normal",
                style_hint="",
                overview_path=None,
                index_file=None,
                instruction_file=run_dir / "instruction" / "prompt.txt",
                quality_model="gpt-4o",
                query_id="run_case",
                workflow_summary=summary,
                workflow_path=None,
            )

    monkeypatch.setattr(runner, "resolve_agent_overrides_from_config", lambda _args, explicit_overrides=None: (explicit_overrides or {}, {}))
    monkeypatch.setattr(runner, "prepare_runtime", lambda _args, _cfg: ("md", "gpt-4o"))
    monkeypatch.setattr(runner, "resolve_create_deep_agent", lambda value: value)
    monkeypatch.setattr(runner, "load_report_prompt", lambda _prompt, _path: "")
    monkeypatch.setattr(runner, "expand_update_prompt_with_base", lambda raw, _run: raw)
    monkeypatch.setattr(runner, "ReportOrchestrator", FakeOrchestrator)

    args = argparse.Namespace(
        run=str(run_dir),
        stages="quality,plan",
        skip_stages=None,
        _state_only=True,
        prompt=None,
        prompt_file=None,
    )
    output = runner.run_pipeline(args, state_only=True)
    assert output.meta["state_only"] is True

    stdout = capsys.readouterr().out
    assert "[workflow] stage=scout status=ran detail=pass=1" in stdout
    assert "elapsed_ms=" in stdout
    assert "est_tokens=" in stdout
    assert "cache_hits=" in stdout

    workflow_path = run_dir / "report_notes" / "report_workflow.md"
    workflow_json = run_dir / "report_notes" / "report_workflow.json"
    assert workflow_path.exists()
    assert workflow_json.exists()
    markdown = workflow_path.read_text(encoding="utf-8")
    assert "# Report Workflow" in markdown
    payload = json.loads(workflow_json.read_text(encoding="utf-8"))
    assert "order" in payload and isinstance(payload["order"], list)
    assert "writer" in payload["order"]
    assert "quality" in payload["order"]
