from federlicht import workflow_stages


def test_parse_stage_list_normalizes_tokens() -> None:
    parsed = workflow_stages.parse_stage_list(" Scout ;PLAN| evidence, , ")
    assert parsed == ["scout", "plan", "evidence"]


def test_resolve_stage_order_prioritizes_requested_order() -> None:
    order = workflow_stages.resolve_stage_order(
        all_stages={"scout", "plan", "evidence", "writer"},
        default_stage_order=["scout", "plan", "evidence", "writer"],
        stages_raw="writer,scout",
    )
    assert order == ["writer", "scout", "plan", "evidence"]


def test_resolve_stage_set_applies_filter_and_skip() -> None:
    all_stages = {"scout", "plan", "evidence", "writer"}
    stage_set = workflow_stages.resolve_stage_set(
        all_stages=all_stages,
        stages_raw="scout,writer,unknown",
        skip_stages_raw="writer",
    )
    assert stage_set == {"scout"}


def test_initialize_and_record_stage() -> None:
    stage_status = workflow_stages.initialize_stage_status(
        stage_order=["scout", "plan"],
        stage_set={"scout"},
    )
    assert stage_status["scout"]["status"] == "pending"
    assert stage_status["plan"]["status"] == "disabled"

    workflow_stages.record_stage(stage_status, name="scout", status="ran", detail="ok")
    assert stage_status["scout"] == {"status": "ran", "detail": "ok"}


def test_expand_stage_dependencies_adds_required_stages() -> None:
    expanded, added_by = workflow_stages.expand_stage_dependencies(
        stage_set={"writer"},
        all_stages={"scout", "plan", "evidence", "writer"},
    )
    assert expanded == {"scout", "plan", "evidence", "writer"}
    assert added_by == {
        "evidence": ["writer"],
        "plan": ["writer"],
        "scout": ["writer"],
    }


def test_expand_stage_dependencies_records_multi_stage_triggers() -> None:
    expanded, added_by = workflow_stages.expand_stage_dependencies(
        stage_set={"web", "evidence"},
        all_stages={"scout", "plan", "web", "evidence"},
    )
    assert expanded == {"scout", "plan", "web", "evidence"}
    assert added_by["scout"] == ["evidence", "web"]
    assert added_by["plan"] == ["evidence", "web"]


def test_expand_stage_dependencies_tracks_transitive_root_stage() -> None:
    expanded, added_by = workflow_stages.expand_stage_dependencies(
        stage_set={"quality"},
        all_stages={"scout", "plan", "evidence", "writer", "quality"},
    )
    assert expanded == {"scout", "plan", "evidence", "writer", "quality"}
    assert added_by["writer"] == ["quality"]
    assert added_by["evidence"] == ["quality"]
    assert added_by["plan"] == ["quality"]
    assert added_by["scout"] == ["quality"]


def test_parse_top_level_stages_applies_skip_and_filters_non_top_level() -> None:
    parsed = workflow_stages.parse_top_level_stages(
        stages_raw="scout,template_adjust,quality,plan_check,writer",
        skip_stages_raw="quality",
    )
    assert parsed == ["scout", "writer"]


def test_resolve_top_level_execution_plan_inserts_required_dependencies() -> None:
    plan = workflow_stages.resolve_top_level_execution_plan(["quality", "plan"])
    assert plan == ["scout", "plan", "evidence", "writer", "quality"]


def test_top_level_stage_bundle_maps_to_runtime_stages() -> None:
    assert workflow_stages.top_level_stage_bundle("evidence") == ("web", "evidence", "plan_check")
