from __future__ import annotations

from dataclasses import dataclass
from typing import Optional
import copy

from . import report as report_mod


REPORTER_INPUT_SCHEMA = {
    "type": "object",
    "required": ["run"],
    "properties": {
        "run": {"type": "string", "description": "Path to the run folder."},
        "output": {"type": "string", "description": "Output path (extension selects format)."},
        "template": {"type": "string", "description": "Template name or template path."},
        "lang": {"type": "string", "description": "Language preference (e.g., ko, en)."},
        "prompt": {"type": "string", "description": "Inline report focus prompt."},
        "prompt_file": {"type": "string", "description": "Path to prompt file."},
        "tags": {"type": "string", "description": "Comma-separated tags to include (or 'auto')."},
        "no_tags": {"type": "boolean", "description": "Disable tags (also disables auto tags)."},
        "no_figures": {"type": "boolean", "description": "Disable figure extraction."},
        "figures": {"type": "boolean", "description": "Enable figure extraction."},
        "figures_mode": {"type": "string", "description": "Figure insertion mode: select|auto."},
        "figures_select": {"type": "string", "description": "Path to a figure selection file."},
        "web_search": {"type": "boolean", "description": "Enable web research."},
        "supporting_dir": {"type": "string", "description": "Supporting folder for web research."},
        "free_format": {"type": "boolean", "description": "Free-form report structure."},
        "stages": {"type": "string", "description": "Comma-separated stages to run."},
        "skip_stages": {"type": "string", "description": "Comma-separated stages to skip."},
        "model": {"type": "string", "description": "Primary model name."},
        "check_model": {"type": "string", "description": "Check/quality model name."},
        "quality_model": {"type": "string", "description": "Quality model name."},
        "quality_iterations": {"type": "integer", "description": "Number of quality iterations."},
        "quality_strategy": {"type": "string", "description": "Quality strategy (pairwise/single)."},
        "max_input_tokens": {"type": "integer", "description": "Fallback max input tokens."},
        "depth": {"type": "string", "description": "Depth preference (brief|normal|deep|exhaustive)."},
        "notes_dir": {"type": "string", "description": "Notes output directory."},
        "overwrite_output": {"type": "boolean", "description": "Overwrite output file if exists."},
        "stream": {"type": "boolean", "description": "Enable streaming output."},
        "progress": {"type": "boolean", "description": "Enable progress snippets."},
        "echo_markdown": {"type": "boolean", "description": "Echo markdown to stdout when output is set."},
        "max_refs": {"type": "integer", "description": "Max references to append."},
        "max_chars": {"type": "integer", "description": "Max chars returned by read tool."},
        "max_tool_chars": {
            "type": "integer",
            "description": "Max cumulative chars returned by read tool across a run.",
        },
        "max_pdf_pages": {"type": "integer", "description": "Max PDF pages to extract."},
        "pdf_extend_pages": {"type": "integer", "description": "Auto-read next N PDF pages when text is short."},
        "pdf_extend_min_chars": {"type": "integer", "description": "Minimum chars before PDF auto-extension triggers."},
    },
    "additionalProperties": True,
}


def _mark_cli_flag(args, flag: str) -> None:
    argv_flags = list(getattr(args, "_cli_argv", []) or ["federlicht"])
    if flag not in argv_flags:
        argv_flags.append(flag)
    args._cli_argv = argv_flags


def _apply_arg_overrides(args, overrides: dict) -> None:
    for key, value in overrides.items():
        if key in {"no_figures", "no-figures"}:
            args.extract_figures = False
            continue
        if key in {"figures", "with_figures"}:
            if value is not None:
                args.extract_figures = bool(value)
            continue
        attr = key.replace("-", "_")
        if hasattr(args, attr):
            setattr(args, attr, value)
            if attr == "model" and value:
                _mark_cli_flag(args, "--model")
            elif attr == "check_model" and value:
                _mark_cli_flag(args, "--check-model")
            elif attr == "quality_model" and value:
                _mark_cli_flag(args, "--quality-model")
            elif attr == "max_input_tokens" and value:
                args.max_input_tokens_source = "cli"
                _mark_cli_flag(args, "--max-input-tokens")
            continue
        raise ValueError(f"Unknown reporter option: {key}")


@dataclass
class Reporter:
    args: object
    agent_overrides: Optional[dict] = None
    config_overrides: Optional[dict] = None
    create_deep_agent: Optional[object] = None

    def run(self, return_state: bool = False, **overrides):
        args = copy.deepcopy(self.args)
        if overrides:
            _apply_arg_overrides(args, overrides)
        state_only = False
        stage_override = overrides.get("stages") if overrides else None
        requested = stage_override or getattr(args, "stages", None)
        if requested:
            tokens = {token.strip().lower() for token in str(requested).split(",") if token.strip()}
            if "writer" not in tokens:
                args._state_only = True
                state_only = True
                return_state = True
        output = report_mod.run_pipeline(
            args,
            create_deep_agent=self.create_deep_agent,
            agent_overrides=self.agent_overrides,
            config_overrides=self.config_overrides,
            state_only=state_only,
        )
        if return_state:
            if isinstance(output, report_mod.ReportOutput):
                if not output.state:
                    raise RuntimeError("Pipeline state not available.")
                return output.state
            return output
        return output

    def invoke(self, payload: dict) -> str:
        output = self.run(**payload)
        if isinstance(output, report_mod.ReportOutput):
            if output.output_path:
                return str(output.output_path)
            return output.rendered
        return str(output)

    def run_state(self, **overrides) -> report_mod.PipelineState:
        output = self.run(return_state=True, **overrides)
        if isinstance(output, report_mod.ReportOutput):
            if not output.state:
                raise RuntimeError("Pipeline state not available.")
            return output.state
        if isinstance(output, report_mod.PipelineState):
            return output
        raise RuntimeError("Unexpected reporter output type.")

    def stage_info(self, stages: Optional[object] = None) -> dict:
        return report_mod.get_stage_info(stages if stages is not None else ["all"])

    def write(self, state: object, **overrides) -> report_mod.ReportOutput:
        args = copy.deepcopy(self.args)
        if overrides:
            _apply_arg_overrides(args, overrides)
        if not getattr(args, "stages", None):
            args.stages = "writer,quality"
        else:
            tokens = {token.strip().lower() for token in str(args.stages).split(",") if token.strip()}
            if "writer" not in tokens:
                raise ValueError("Reporter.write requires the writer stage. Include 'writer' in stages.")
        pipeline_state = report_mod.coerce_pipeline_state(state)
        pipeline_state = report_mod.normalize_state_for_writer(pipeline_state)
        missing = report_mod.validate_state_for_writer(pipeline_state)
        if missing:
            raise ValueError(f"State is missing required fields for writer: {', '.join(missing)}")
        return report_mod.run_pipeline(
            args,
            create_deep_agent=self.create_deep_agent,
            agent_overrides=self.agent_overrides,
            config_overrides=self.config_overrides,
            state=pipeline_state,
        )

    def as_tool(
        self,
        name: str = "federlicht_reporter",
        description: str = "Generate a report from a federlicht run folder.",
    ) -> "ReporterTool":
        return ReporterTool(
            reporter=self,
            name=name,
            description=description,
            input_schema=REPORTER_INPUT_SCHEMA,
        )


@dataclass
class ReporterTool:
    reporter: Reporter
    name: str
    description: str
    input_schema: dict

    def invoke(self, payload: dict) -> str:
        return self.reporter.invoke(payload)

    def __call__(self, payload: dict) -> str:
        return self.invoke(payload)


def create_reporter(
    *,
    run: Optional[str] = None,
    output: Optional[str] = None,
    template: Optional[str] = None,
    lang: Optional[str] = None,
    prompt: Optional[str] = None,
    prompt_file: Optional[str] = None,
    agent_config: Optional[str] = None,
    agent_overrides: Optional[dict] = None,
    create_deep_agent: Optional[object] = None,
    **kwargs,
) -> Reporter:
    args = report_mod.parse_args([])
    args._cli_argv = ["federlicht"]
    if run is not None:
        args.run = run
    if output is not None:
        args.output = output
    if template is not None:
        args.template = template
        _mark_cli_flag(args, "--template")
    if lang is not None:
        args.lang = lang
        _mark_cli_flag(args, "--lang")
    if prompt is not None:
        args.prompt = prompt
        _mark_cli_flag(args, "--prompt")
    if prompt_file is not None:
        args.prompt_file = prompt_file
        _mark_cli_flag(args, "--prompt-file")
    if agent_config is not None:
        args.agent_config = agent_config
        _mark_cli_flag(args, "--agent-config")

    _apply_arg_overrides(args, kwargs)

    if args.max_input_tokens and getattr(args, "max_input_tokens_source", "none") == "none":
        args.max_input_tokens_source = "cli"

    return Reporter(
        args=args,
        agent_overrides=agent_overrides,
        config_overrides=None,
        create_deep_agent=create_deep_agent,
    )
