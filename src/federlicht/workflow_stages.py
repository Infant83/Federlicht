from __future__ import annotations

from typing import Optional


STAGE_DEPENDENCIES: dict[str, tuple[str, ...]] = {
    "clarifier": ("scout",),
    "template_adjust": ("scout",),
    "plan": ("scout",),
    "web": ("scout", "plan"),
    "evidence": ("scout", "plan"),
    "plan_check": ("plan", "evidence"),
    "writer": ("scout", "plan", "evidence"),
    "quality": ("writer",),
}

TOP_LEVEL_STAGES: tuple[str, ...] = (
    "scout",
    "plan",
    "evidence",
    "writer",
    "quality",
)

TOP_LEVEL_DEPENDENCIES: dict[str, tuple[str, ...]] = {
    "plan": ("scout",),
    "evidence": ("scout", "plan"),
    "writer": ("evidence",),
    "quality": ("writer",),
}

TOP_LEVEL_STAGE_BUNDLES: dict[str, tuple[str, ...]] = {
    "scout": ("scout", "clarifier", "template_adjust"),
    "plan": ("plan",),
    "evidence": ("web", "evidence", "plan_check"),
    "writer": ("writer",),
    "quality": ("quality",),
}


def parse_stage_list(raw: Optional[str]) -> list[str]:
    if not raw:
        return []
    tokens: list[str] = []
    seen: set[str] = set()
    for part in raw.replace(";", ",").replace("|", ",").split(","):
        cleaned = part.strip().lower()
        if cleaned and cleaned not in seen:
            seen.add(cleaned)
            tokens.append(cleaned)
    return tokens


def resolve_stage_order(
    *,
    all_stages: set[str],
    default_stage_order: list[str],
    stages_raw: Optional[str],
) -> list[str]:
    requested = [name for name in parse_stage_list(stages_raw) if name in all_stages]
    base = [name for name in default_stage_order if name in all_stages]
    if not requested:
        return base
    seen = set(requested)
    remaining = [name for name in base if name not in seen]
    return [*requested, *remaining]


def resolve_stage_set(
    *,
    all_stages: set[str],
    stages_raw: Optional[str],
    skip_stages_raw: Optional[str],
) -> set[str]:
    stage_set = set(parse_stage_list(stages_raw))
    skip_set = set(parse_stage_list(skip_stages_raw))
    if stage_set:
        stage_set = {stage for stage in stage_set if stage in all_stages}
        if skip_set:
            stage_set -= skip_set
        return stage_set
    if skip_set:
        return {stage for stage in all_stages if stage not in skip_set}
    return set()


def expand_stage_dependencies(
    *,
    stage_set: set[str],
    all_stages: set[str],
    dependencies: Optional[dict[str, tuple[str, ...]]] = None,
) -> tuple[set[str], dict[str, list[str]]]:
    """Expand selected stages with required dependencies.

    Returns:
      - expanded set
      - auto-added mapping (required_stage -> list[trigger_stage, ...])
    """
    if not stage_set:
        return stage_set, {}
    dependency_map = dependencies or STAGE_DEPENDENCIES
    originally_selected = set(stage_set)
    expanded = set(stage_set)
    trigger_map: dict[str, set[str]] = {name: {name} for name in expanded}

    changed = True
    while changed:
        changed = False
        current = sorted(expanded)
        for stage in current:
            stage_triggers = trigger_map.get(stage, set())
            for dep in dependency_map.get(stage, ()):
                if dep not in all_stages:
                    continue
                if dep not in expanded:
                    expanded.add(dep)
                    changed = True
                dep_triggers = trigger_map.setdefault(dep, set())
                before = len(dep_triggers)
                dep_triggers.update(stage_triggers)
                if len(dep_triggers) != before:
                    changed = True
    added_by: dict[str, list[str]] = {}
    for dep, triggers in trigger_map.items():
        if dep in originally_selected:
            continue
        ordered = sorted(triggers)
        if ordered:
            added_by[dep] = ordered
    return expanded, added_by


def stage_enabled(stage_set: set[str], name: str) -> bool:
    return True if not stage_set else name in stage_set


def initialize_stage_status(
    *,
    stage_order: list[str],
    stage_set: set[str],
) -> dict[str, dict[str, str]]:
    stage_status: dict[str, dict[str, str]] = {}
    for name in stage_order:
        if stage_enabled(stage_set, name):
            stage_status[name] = {"status": "pending", "detail": ""}
        else:
            stage_status[name] = {"status": "disabled", "detail": ""}
    return stage_status


def record_stage(
    stage_status: dict[str, dict[str, str]],
    *,
    name: str,
    status: str,
    detail: str = "",
) -> None:
    if name not in stage_status:
        return
    stage_status[name]["status"] = status
    if detail:
        stage_status[name]["detail"] = detail


def parse_top_level_stages(
    *,
    stages_raw: Optional[str],
    skip_stages_raw: Optional[str] = None,
) -> list[str]:
    skip_set = set(parse_stage_list(skip_stages_raw))
    selected: list[str] = []
    seen: set[str] = set()
    allowed = set(TOP_LEVEL_STAGES)
    for name in parse_stage_list(stages_raw):
        if name not in allowed:
            continue
        if name in skip_set:
            continue
        if name in seen:
            continue
        seen.add(name)
        selected.append(name)
    return selected


def canonical_top_level_order(selected: list[str]) -> list[str]:
    selected_set = set(selected)
    return [name for name in TOP_LEVEL_STAGES if name in selected_set]


def resolve_top_level_execution_plan(
    selected: list[str],
    dependencies: Optional[dict[str, tuple[str, ...]]] = None,
) -> list[str]:
    if not selected:
        return []
    dependency_map = dependencies or TOP_LEVEL_DEPENDENCIES
    plan: list[str] = []
    added: set[str] = set()

    def add_stage(name: str) -> None:
        if name in added:
            return
        for dep in dependency_map.get(name, ()):
            add_stage(dep)
        if name not in added:
            added.add(name)
            plan.append(name)

    for stage_name in selected:
        add_stage(stage_name)
    return plan


def top_level_stage_bundle(stage_name: str) -> tuple[str, ...]:
    return TOP_LEVEL_STAGE_BUNDLES.get(stage_name, (stage_name,))
