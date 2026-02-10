from federlicht.pipeline_runner_impl import (
    _count_cached_stage_hits,
    _estimate_pass_tokens,
    _flatten_execution_stage_order,
    _merge_workflow_stage_status,
)


def test_flatten_execution_stage_order_expands_runtime_stage_bundles() -> None:
    ordered = _flatten_execution_stage_order(["evidence", "writer"])
    assert ordered[:4] == ["web", "evidence", "plan_check", "writer"]
    assert "scout" in ordered
    assert "quality" in ordered


def test_merge_workflow_stage_status_prefers_non_disabled_updates() -> None:
    merged = _merge_workflow_stage_status(
        [
            [
                "1. scout: ran",
                "2. plan: disabled",
            ],
            [
                "1. plan: ran (cached)",
                "2. scout: disabled",
            ],
        ]
    )
    assert merged["scout"] == {"status": "ran", "detail": ""}
    assert merged["plan"] == {"status": "ran", "detail": "cached"}


def test_count_cached_stage_hits_only_counts_selected_runtime_stages() -> None:
    summary = [
        "1. scout: cached",
        "2. plan: ran",
        "3. evidence: cached",
        "4. quality: skipped",
    ]
    hits = _count_cached_stage_hits(summary, ("scout", "plan", "writer"))
    assert hits == 1


def test_estimate_pass_tokens_uses_delta_from_previous_state() -> None:
    from types import SimpleNamespace

    result = SimpleNamespace(
        language="en",
        scout_notes="abcd" * 40,
        plan_text="",
        evidence_notes="",
        claim_map_text="",
        gap_text="",
        report="",
    )
    previous = SimpleNamespace(
        scout_notes="abcd" * 10,
        plan_text="",
        evidence_notes="",
        claim_map_text="",
        gap_text="",
        report="",
    )
    # Delta chars = 120, en ratio=4 -> 30 tokens
    assert _estimate_pass_tokens(result, previous) == 30


def test_reordered_pipeline_runs_multipass_with_dependency_expansion_disabled(monkeypatch, tmp_path) -> None:
    import argparse
    from pathlib import Path
    from types import SimpleNamespace

    import federlicht.pipeline_runner_impl as runner
    from federlicht import workflow_stages

    run_dir = tmp_path / "run"
    (run_dir / "archive").mkdir(parents=True, exist_ok=True)

    calls: list[tuple[str, bool, bool]] = []
    merged_orders: list[list[str]] = []

    class FakeOrchestrator:
        def __init__(self, context, _helpers, _overrides, _create) -> None:
            self._args = context.args

        def run(self, state=None, allow_partial=False):
            calls.append(
                (
                    str(getattr(self._args, "stages", "") or ""),
                    bool(getattr(self._args, "_disable_stage_dependency_expansion", False)),
                    bool(allow_partial),
                )
            )
            stages = [token.strip() for token in str(self._args.stages or "").split(",") if token.strip()]
            summary = [f"{idx}. {name}: ran" for idx, name in enumerate(stages, start=1)] or ["1. scout: skipped"]
            return SimpleNamespace(
                report="",
                scout_notes="",
                plan_text="",
                plan_context="",
                evidence_notes="",
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
                notes_dir=run_dir / "report_notes",
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
                instruction_file=None,
                quality_model="gpt-4o",
                query_id="q",
                workflow_summary=summary,
                workflow_path=None,
            )

    def fake_write_workflow_summary(**kwargs):
        merged_orders.append(list(kwargs.get("stage_order") or []))
        return (["1. scout: ran"], Path(run_dir / "report_notes" / "report_workflow.md"))

    monkeypatch.setattr(runner, "resolve_archive", lambda path: (run_dir / "archive", run_dir, "q"))
    monkeypatch.setattr(runner, "load_report_prompt", lambda _prompt, _file: "")
    monkeypatch.setattr(runner, "expand_update_prompt_with_base", lambda raw, _run: raw)
    monkeypatch.setattr(runner, "resolve_agent_overrides_from_config", lambda _args, explicit_overrides=None: (explicit_overrides or {}, {}))
    monkeypatch.setattr(runner, "prepare_runtime", lambda _args, _cfg: ("md", "gpt-4o"))
    monkeypatch.setattr(runner, "resolve_create_deep_agent", lambda value: value)
    monkeypatch.setattr(runner, "ReportOrchestrator", FakeOrchestrator)
    monkeypatch.setattr(runner, "write_workflow_summary", fake_write_workflow_summary)
    monkeypatch.setattr(runner, "build_pipeline_state", lambda _result: None)

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

    requested = workflow_stages.parse_top_level_stages(stages_raw="quality,plan", skip_stages_raw=None)
    execution_plan = workflow_stages.resolve_top_level_execution_plan(requested)
    expected_passes = [",".join(workflow_stages.top_level_stage_bundle(stage)) for stage in execution_plan]
    assert [stage for stage, _flag, _partial in calls] == expected_passes
    assert all(flag for _stage, flag, _partial in calls)
    assert all(partial for _stage, _flag, partial in calls)
    assert merged_orders and merged_orders[-1] == _flatten_execution_stage_order(execution_plan)
