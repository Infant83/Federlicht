from __future__ import annotations

import argparse

from federlicht import report


def _args() -> argparse.Namespace:
    return argparse.Namespace(
        model="gpt-5-mini",
        check_model="gpt-4o",
        quality_model="",
        model_vision=None,
        template_rigidity="balanced",
        template_adjust=True,
        template_adjust_mode="risk_only",
        repair_mode="append",
        free_format=False,
        max_input_tokens=None,
        quality_iterations=0,
        quality_strategy="pairwise",
        web_search=False,
        alignment_check=True,
        interactive=False,
        answers=None,
        answers_file=None,
        extract_figures=False,
        figures_mode="auto",
        temperature=0.2,
        temperature_level="balanced",
        cache=True,
        agent_profile=None,
        agent_profile_dir=None,
    )


def test_agent_info_has_consistent_stage_agent_map() -> None:
    args = _args()
    spec = report.TemplateSpec(
        name="default",
        sections=["Executive Summary", "Risks & Gaps", "Critics"],
    )
    payload = report.build_agent_info(
        args=args,
        output_format="md",
        language="Korean",
        report_prompt="test prompt",
        template_spec=spec,
        template_guidance_text="guidance",
        required_sections=list(spec.sections),
        free_format=False,
        agent_overrides={},
    )

    agents = payload["agents"]
    stage_agent_map = payload["stage_agent_map"]
    assert "reducer" in agents
    for _, names in stage_agent_map.items():
        for name in names:
            assert name in agents, f"missing agent '{name}' referenced in stage map"


def test_agent_info_reducer_override_applies() -> None:
    args = _args()
    spec = report.TemplateSpec(name="default", sections=["Executive Summary"])
    payload = report.build_agent_info(
        args=args,
        output_format="md",
        language="Korean",
        report_prompt=None,
        template_spec=spec,
        template_guidance_text="",
        required_sections=list(spec.sections),
        free_format=False,
        agent_overrides={"reducer": {"model": "gpt-5-nano", "max_input_tokens": 12345}},
    )

    reducer = payload["agents"]["reducer"]
    assert reducer["model"] == "gpt-5-nano"
    assert reducer["max_input_tokens"] == 12345

