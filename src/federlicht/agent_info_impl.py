from __future__ import annotations

# ruff: noqa: F401,F403,F405

from . import report as core
from .agent_runtime import AgentRuntime
from .report import *  # noqa: F401,F403

STAGE_AGENT_MAP = {
    "scout": ["scout", "clarifier", "alignment", "template_adjuster"],
    "plan": ["planner", "alignment"],
    "web": ["web_query"],
    "evidence": ["evidence", "plan_check", "alignment", "reducer"],
    "writer": ["writer", "structural_editor"],
    "quality": ["critic", "reviser", "evaluator", "pairwise_compare", "synthesizer"],
    "figures": ["image_analyst"],
}


def build_agent_info(
    args: argparse.Namespace,
    output_format: str,
    language: str,
    report_prompt: Optional[str],
    template_spec: TemplateSpec,
    template_guidance_text: str,
    required_sections: list[str],
    free_format: bool = False,
    agent_overrides: Optional[dict] = None,
) -> dict:
    profile = resolve_active_profile(args)
    profiles_dir = resolve_profiles_dir(getattr(args, "agent_profile_dir", None))
    if not required_sections and not free_format:
        required_sections = list(DEFAULT_SECTIONS)
    if not template_guidance_text:
        template_guidance_text = build_template_guidance_text(template_spec)
    overrides = normalize_agent_overrides(agent_overrides)
    runtime = AgentRuntime(args=args, helpers=core, overrides=overrides)
    quality_model = args.quality_model or args.check_model or args.model
    format_instructions = build_format_instructions(
        output_format,
        required_sections,
        free_form=args.free_format,
        language=language,
        template_rigidity=args.template_rigidity,
    )
    metrics = ", ".join(QUALITY_WEIGHTS.keys())
    depth = getattr(args, "depth", None)

    def build_agent_entry(
        name: str,
        *,
        default_model: str,
        default_prompt: str,
        default_enabled: Optional[bool] = None,
        include_tokens: bool = True,
    ) -> dict:
        payload = {
            "model": runtime.model(name, default_model, overrides),
            "system_prompt": runtime.prompt(name, default_prompt, overrides),
        }
        if include_tokens:
            max_input_tokens, _source = runtime.max_input_tokens(name, overrides)
            payload["max_input_tokens"] = max_input_tokens
        if default_enabled is not None:
            payload["enabled"] = runtime.enabled(name, default_enabled, overrides)
        return payload

    writer_default_prompt = prompts.build_writer_prompt(
        format_instructions,
        template_guidance_text,
        template_spec,
        required_sections,
        output_format,
        language,
        depth,
        template_rigidity=args.template_rigidity,
        figures_enabled=bool(getattr(args, "extract_figures", False)),
        figures_mode=getattr(args, "figures_mode", "auto"),
    )
    repair_default_prompt = prompts.build_repair_prompt(
        format_instructions,
        output_format,
        language,
        free_form=args.free_format,
        template_rigidity=args.template_rigidity,
    )
    quality_enabled = bool(args.quality_iterations > 0)
    agents = {
        "scout": build_agent_entry(
            "scout",
            default_model=args.model,
            default_prompt=prompts.build_scout_prompt(language),
        ),
        "clarifier": build_agent_entry(
            "clarifier",
            default_model=args.model,
            default_prompt=prompts.build_clarifier_prompt(language),
            default_enabled=bool(args.interactive or args.answers or args.answers_file),
        ),
        "alignment": build_agent_entry(
            "alignment",
            default_model=args.check_model or args.model,
            default_prompt=prompts.build_alignment_prompt(language),
            default_enabled=bool(args.alignment_check),
        ),
        "planner": build_agent_entry(
            "planner",
            default_model=args.model,
            default_prompt=prompts.build_plan_prompt(language),
        ),
        "plan_check": build_agent_entry(
            "plan_check",
            default_model=args.check_model or args.model,
            default_prompt=prompts.build_plan_check_prompt(language),
        ),
        "web_query": build_agent_entry(
            "web_query",
            default_model=args.model,
            default_prompt=prompts.build_web_prompt(),
            default_enabled=bool(args.web_search),
        ),
        "evidence": build_agent_entry(
            "evidence",
            default_model=args.model,
            default_prompt=prompts.build_evidence_prompt(language),
        ),
        "reducer": build_agent_entry(
            "reducer",
            default_model=args.check_model or args.model,
            default_prompt=prompts.build_reducer_prompt(language),
        ),
        "writer": build_agent_entry(
            "writer",
            default_model=args.model,
            default_prompt=writer_default_prompt,
        ),
        "structural_editor": build_agent_entry(
            "structural_editor",
            default_model=args.model,
            default_prompt=repair_default_prompt,
        ),
        "critic": build_agent_entry(
            "critic",
            default_model=quality_model,
            default_prompt=prompts.build_critic_prompt(language, required_sections),
            default_enabled=quality_enabled,
        ),
        "reviser": build_agent_entry(
            "reviser",
            default_model=quality_model,
            default_prompt=prompts.build_revise_prompt(format_instructions, output_format, language),
            default_enabled=quality_enabled,
        ),
        "evaluator": build_agent_entry(
            "evaluator",
            default_model=quality_model,
            default_prompt=prompts.build_evaluate_prompt(metrics, depth=depth),
            default_enabled=quality_enabled,
        ),
        "pairwise_compare": build_agent_entry(
            "pairwise_compare",
            default_model=quality_model,
            default_prompt=prompts.build_compare_prompt(),
            default_enabled=bool(quality_enabled and args.quality_strategy == "pairwise"),
        ),
        "synthesizer": build_agent_entry(
            "synthesizer",
            default_model=quality_model,
            default_prompt=prompts.build_synthesize_prompt(format_instructions, template_guidance_text, language),
            default_enabled=quality_enabled,
        ),
        "template_adjuster": build_agent_entry(
            "template_adjuster",
            default_model=args.model,
            default_prompt=prompts.build_template_adjuster_prompt(output_format),
            default_enabled=bool(args.template_adjust),
        ),
        "image_analyst": build_agent_entry(
            "image_analyst",
            default_model=args.model_vision or "(not set)",
            default_prompt=prompts.build_image_prompt(),
            default_enabled=bool(args.model_vision and args.extract_figures),
            include_tokens=False,
        ),
    }
    if free_format:
        agents["template_adjuster"]["enabled"] = False
    template_adjust_enabled = bool(agents["template_adjuster"].get("enabled"))
    return {
        "config": {
            "language": language,
            "output_format": output_format,
            "model": args.model,
            "temperature_level": args.temperature_level,
            "quality_model": quality_model,
            "model_vision": args.model_vision,
            "template": template_spec.name,
            "template_rigidity": args.template_rigidity,
            "template_rigidity_effective": getattr(args, "template_rigidity_effective", {}),
            "template_adjust": template_adjust_enabled,
            "template_adjust_mode": args.template_adjust_mode,
            "repair_mode": args.repair_mode,
            "free_format": args.free_format,
            "max_input_tokens": args.max_input_tokens,
            "quality_iterations": args.quality_iterations,
            "quality_strategy": args.quality_strategy,
            "web_search": args.web_search,
            "alignment_check": args.alignment_check,
            "interactive": args.interactive,
            "cache": args.cache,
            "agent_profile": profile_summary(profile) if profile else None,
            "agent_profile_dir": str(profiles_dir),
        },
        "agent_profiles": list_profiles(profiles_dir),
        "stages": get_stage_info(["all"]),
        "stage_agent_map": STAGE_AGENT_MAP,
        "agents": agents,
    }


