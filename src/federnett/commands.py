from __future__ import annotations

import sys
from typing import Any

from .utils import extra_args, expand_env_reference, parse_bool, resolve_under_root
from .config import FedernettConfig


def _build_feather_cmd(cfg: FedernettConfig, payload: dict[str, Any]) -> list[str]:
    input_path = payload.get("input")
    query = payload.get("query")
    output_root = payload.get("output")
    if not output_root:
        raise ValueError("Feather requires an output path.")
    if not input_path and not query:
        raise ValueError("Feather requires either input or query.")

    cmd: list[str] = [sys.executable, "-m", "feather"]
    if input_path:
        resolved_input = resolve_under_root(cfg.root, str(input_path))
        cmd.extend(["--input", str(resolved_input)])
    elif query:
        cmd.extend(["--query", str(query)])
    resolved_output = resolve_under_root(cfg.root, str(output_root))
    cmd.extend(["--output", str(resolved_output)])
    if payload.get("lang"):
        cmd.extend(["--lang", str(payload.get("lang"))])
    if payload.get("days") is not None and str(payload.get("days")) != "":
        cmd.extend(["--days", str(payload.get("days"))])
    if payload.get("max_results") is not None and str(payload.get("max_results")) != "":
        cmd.extend(["--max-results", str(payload.get("max_results"))])
    if parse_bool(payload, "agentic_search"):
        cmd.append("--agentic-search")
        model = expand_env_reference(payload.get("model"))
        if model:
            cmd.extend(["--model", str(model)])
        if payload.get("max_iter") is not None and str(payload.get("max_iter")) != "":
            cmd.extend(["--max-iter", str(payload.get("max_iter"))])
    if parse_bool(payload, "download_pdf"):
        cmd.append("--download-pdf")
    if parse_bool(payload, "arxiv_src"):
        cmd.append("--arxiv-src")
    if parse_bool(payload, "openalex"):
        cmd.append("--openalex")
    if parse_bool(payload, "no_openalex"):
        cmd.append("--no-openalex")
    if payload.get("oa_max_results") is not None and str(payload.get("oa_max_results")) != "":
        cmd.extend(["--oa-max-results", str(payload.get("oa_max_results"))])
    if parse_bool(payload, "youtube"):
        cmd.append("--youtube")
    if parse_bool(payload, "no_youtube"):
        cmd.append("--no-youtube")
    if payload.get("yt_max_results") is not None and str(payload.get("yt_max_results")) != "":
        cmd.extend(["--yt-max-results", str(payload.get("yt_max_results"))])
    if payload.get("yt_order"):
        cmd.extend(["--yt-order", str(payload.get("yt_order"))])
    if parse_bool(payload, "yt_transcript"):
        cmd.append("--yt-transcript")
    if parse_bool(payload, "no_stdout_log"):
        cmd.append("--no-stdout-log")
    if parse_bool(payload, "no_citations"):
        cmd.append("--no-citations")
    if parse_bool(payload, "update_run"):
        cmd.append("--update-run")
    cmd.extend(extra_args(payload.get("extra_args")))
    return cmd


def _build_federlicht_cmd(cfg: FedernettConfig, payload: dict[str, Any]) -> list[str]:
    run_dir = payload.get("run")
    if not run_dir:
        raise ValueError("Federlicht requires a run path.")
    resolved_run = resolve_under_root(cfg.root, str(run_dir))

    cmd: list[str] = [sys.executable, "-m", "federlicht.report", "--run", str(resolved_run)]
    output_path = payload.get("output")
    if output_path:
        resolved_output = resolve_under_root(cfg.root, str(output_path))
        cmd.extend(["--output", str(resolved_output)])
    template = payload.get("template")
    if template:
        cmd.extend(["--template", str(template)])
    lang = payload.get("lang")
    if lang:
        cmd.extend(["--lang", str(lang)])
    depth = payload.get("depth")
    if depth:
        cmd.extend(["--depth", str(depth)])
    template_rigidity = payload.get("template_rigidity")
    if template_rigidity:
        cmd.extend(["--template-rigidity", str(template_rigidity)])
    prompt = payload.get("prompt")
    if prompt:
        cmd.extend(["--prompt", str(prompt)])
    prompt_file = payload.get("prompt_file")
    if prompt_file:
        resolved_prompt = resolve_under_root(cfg.root, str(prompt_file))
        cmd.extend(["--prompt-file", str(resolved_prompt)])
    stages = payload.get("stages")
    if stages:
        cmd.extend(["--stages", str(stages)])
    skip_stages = payload.get("skip_stages")
    if skip_stages:
        cmd.extend(["--skip-stages", str(skip_stages)])
    model = expand_env_reference(payload.get("model"))
    if model:
        cmd.extend(["--model", str(model)])
    check_model = expand_env_reference(payload.get("check_model"))
    if check_model:
        cmd.extend(["--check-model", str(check_model)])
    model_vision = expand_env_reference(payload.get("model_vision"))
    if model_vision:
        cmd.extend(["--model-vision", str(model_vision)])
    temperature_level = payload.get("temperature_level")
    if temperature_level:
        cmd.extend(["--temperature-level", str(temperature_level)])
    temperature = payload.get("temperature")
    if temperature is not None and str(temperature) != "":
        cmd.extend(["--temperature", str(temperature)])
    quality_iterations = payload.get("quality_iterations")
    if quality_iterations is not None and str(quality_iterations) != "":
        cmd.extend(["--quality-iterations", str(quality_iterations)])
    quality_strategy = payload.get("quality_strategy")
    if quality_strategy:
        cmd.extend(["--quality-strategy", str(quality_strategy)])
    max_chars = payload.get("max_chars")
    if max_chars:
        cmd.extend(["--max-chars", str(max_chars)])
    max_tool_chars = payload.get("max_tool_chars")
    if max_tool_chars is not None and str(max_tool_chars) != "":
        cmd.extend(["--max-tool-chars", str(max_tool_chars)])
    max_pdf_pages = payload.get("max_pdf_pages")
    if max_pdf_pages is not None and str(max_pdf_pages) != "":
        cmd.extend(["--max-pdf-pages", str(max_pdf_pages)])
    tags = payload.get("tags")
    if tags:
        cmd.extend(["--tags", str(tags)])
    if parse_bool(payload, "no_tags"):
        cmd.append("--no-tags")
    if parse_bool(payload, "figures"):
        cmd.append("--figures")
    if parse_bool(payload, "no_figures"):
        cmd.append("--no-figures")
    figures_mode = payload.get("figures_mode")
    if figures_mode:
        cmd.extend(["--figures-mode", str(figures_mode)])
    figures_select = payload.get("figures_select")
    if figures_select:
        resolved_select = resolve_under_root(cfg.root, str(figures_select))
        cmd.extend(["--figures-select", str(resolved_select)])
    if parse_bool(payload, "web_search"):
        cmd.append("--web-search")
    agent_profile = payload.get("agent_profile")
    if agent_profile:
        cmd.extend(["--agent-profile", str(agent_profile)])
    agent_profile_dir = payload.get("agent_profile_dir")
    if agent_profile_dir:
        resolved_dir = resolve_under_root(cfg.root, str(agent_profile_dir))
        cmd.extend(["--agent-profile-dir", str(resolved_dir)])
    site_output = payload.get("site_output")
    if site_output:
        resolved_site = resolve_under_root(cfg.root, str(site_output))
        cmd.extend(["--site-output", str(resolved_site)])

    cmd.extend(extra_args(payload.get("extra_args")))
    return cmd


def _build_generate_prompt_cmd(cfg: FedernettConfig, payload: dict[str, Any]) -> list[str]:
    run_dir = payload.get("run")
    if not run_dir:
        raise ValueError("Prompt generation requires a run path.")
    resolved_run = resolve_under_root(cfg.root, str(run_dir))

    cmd: list[str] = [
        sys.executable,
        "-m",
        "federlicht.report",
        "--run",
        str(resolved_run),
        "--generate-prompt",
    ]
    output_path = payload.get("output")
    if output_path:
        resolved_output = resolve_under_root(cfg.root, str(output_path))
        cmd.extend(["--output", str(resolved_output)])
    template = payload.get("template")
    if template:
        cmd.extend(["--template", str(template)])
    lang = payload.get("lang")
    if lang:
        cmd.extend(["--lang", str(lang)])
    depth = payload.get("depth")
    if depth:
        cmd.extend(["--depth", str(depth)])
    template_rigidity = payload.get("template_rigidity")
    if template_rigidity:
        cmd.extend(["--template-rigidity", str(template_rigidity)])
    model = expand_env_reference(payload.get("model"))
    if model:
        cmd.extend(["--model", str(model)])
    check_model = expand_env_reference(payload.get("check_model"))
    if check_model:
        cmd.extend(["--check-model", str(check_model)])
    temperature_level = payload.get("temperature_level")
    if temperature_level:
        cmd.extend(["--temperature-level", str(temperature_level)])
    temperature = payload.get("temperature")
    if temperature is not None and str(temperature) != "":
        cmd.extend(["--temperature", str(temperature)])
    cmd.extend(extra_args(payload.get("extra_args")))
    return cmd


def _build_generate_template_cmd(cfg: FedernettConfig, payload: dict[str, Any]) -> list[str]:
    prompt = payload.get("prompt")
    name = payload.get("name")
    if not prompt:
        raise ValueError("Template generation requires a prompt.")
    if not name:
        raise ValueError("Template generation requires a template name.")
    store = payload.get("store") or "run"
    cmd: list[str] = [sys.executable, "-m", "federlicht.report", "--generate-template"]
    if payload.get("run"):
        resolved_run = resolve_under_root(cfg.root, str(payload.get("run")))
        if resolved_run:
            cmd.extend(["--run", str(resolved_run)])
    cmd.extend(["--template-name", str(name)])
    cmd.extend(["--template-prompt", str(prompt)])
    cmd.extend(["--template-store", str(store)])
    model = expand_env_reference(payload.get("model"))
    if model:
        cmd.extend(["--model", str(model)])
    lang = payload.get("lang")
    if lang:
        cmd.extend(["--lang", str(lang)])
    site_output = payload.get("site_output")
    if site_output:
        resolved_site = resolve_under_root(cfg.root, str(site_output))
        if resolved_site:
            cmd.extend(["--site-output", str(resolved_site)])
    cmd.extend(extra_args(payload.get("extra_args")))
    return cmd
