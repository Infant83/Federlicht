#!/usr/bin/env python3
# -*- coding: utf-8 -*-

"""
In-depth, multi-step report generator for a Feather run (Federlicht).

Usage:
  federlicht --run ./examples/runs/20260109_sectioned --output ./examples/runs/20260109_sectioned/report_full.md
  federlicht --run ./examples/runs/20260109_sectioned --notes-dir ./examples/runs/20260109_sectioned/report_notes
  federlicht --run ./examples/runs/20260104_oled --output ./examples/runs/20260104_oled/report_full.html --web-search
  federlicht --run ./examples/runs/20260104_oled --output ./examples/runs/20260104_oled/report_full.tex --template prl_manuscript
"""

from __future__ import annotations

import argparse
import datetime as dt
import html as html_lib
import os
import re
import shutil
import subprocess
from dataclasses import dataclass, field
from html.parser import HTMLParser
import json
import sys
import time
import urllib.parse
from pathlib import Path
from typing import Iterable, Optional

from . import tools as feder_tools
from . import prompts
from .profiles import (
    AgentProfile,
    build_profile_context,
    load_profile,
    list_profiles,
    profile_applies_to,
    profile_summary,
    resolve_profiles_dir,
)
from .orchestrator import (
    PipelineContext,
    PipelineResult,
    PipelineState,
    ReportOrchestrator,
    STAGE_INFO,
    STAGE_ORDER,
)
from feather.web_research import run_supporting_web_research
from .render.html import (
    html_to_text,
    markdown_to_html,
    render_viewer_html,
    transform_mermaid_code_blocks,
    wrap_html,
)
from .utils.json_tools import extract_json_object
from .utils.strings import slugify_label, slugify_url
from .readers.pdf import (
    analyze_figure_with_vision,
    extract_pdf_images,
    read_pdf_with_fitz,
    render_pdf_pages,
)
from .readers.pptx import extract_pptx_images


DEFAULT_MODEL = "gpt-5.2"
DEFAULT_CHECK_MODEL = "gpt-4o"
STREAMING_ENABLED = False
DEFAULT_AUTHOR = "Federlicht Writer"
DEFAULT_TEMPLATE_NAME = "default"
FEDERLICHT_LOG_PATH: Optional[Path] = None
DEFAULT_SECTIONS = [
    "Executive Summary",
    "Scope & Methodology",
    "Key Findings",
    "Trends & Implications",
    "Risks & Gaps",
    "Critics",
    "Appendix",
]
FREE_FORMAT_REQUIRED_SECTIONS = ["Risks & Gaps", "Critics"]
DEFAULT_LATEX_TEMPLATE = r"""\documentclass[11pt]{article}
\usepackage[margin=1in]{geometry}
\usepackage{hyperref}
\usepackage{amsmath,amssymb}
\usepackage{braket}
\usepackage{graphicx}
\usepackage{booktabs}
\usepackage{enumitem}
\title{ {{title}} }
\author{ {{author}} }
\date{ {{date}} }
\begin{document}
\maketitle
{{abstract}}
{{body}}
\end{document}
"""

ARXIV_ID_RE = re.compile(r"^\d{4}\.\d{4,5}(?:v\d+)?$")
REPORT_PLACEHOLDER_RE = re.compile(
    r"(보고서 내용을 완성했습니다|수정.*?(하겠습니다|할 예정|예정)|업데이트.*?(하겠습니다|할 예정)|"
    r"다시 작성|작업을 마친 후|I will update|I will revise|I will finalize|will update the report)",
    re.IGNORECASE,
)
MAX_INPUT_TOKENS_ENV = "FEDERLICHT_MAX_INPUT_TOKENS"
DEFAULT_MAX_INPUT_TOKENS: Optional[int] = None
DEFAULT_MAX_INPUT_TOKENS_SOURCE = "none"
TEMPLATE_RIGIDITY_POLICIES = {
    "strict": {
        "template_adjust": True,
        "template_adjust_mode": "replace",
        "repair_mode": "replace",
    },
    "balanced": {
        "template_adjust": True,
        "template_adjust_mode": "extend",
        "repair_mode": "append",
    },
    "relaxed": {
        "template_adjust": True,
        "template_adjust_mode": "risk_only",
        "repair_mode": "append",
    },
    "loose": {
        "template_adjust": False,
        "template_adjust_mode": "risk_only",
        "repair_mode": "append",
    },
    "off": {
        "template_adjust": False,
        "template_adjust_mode": "risk_only",
        "repair_mode": "off",
    },
}
DEFAULT_TEMPLATE_RIGIDITY = "balanced"
TEMPERATURE_LEVELS = {
    "very_low": 0.0,
    "low": 0.1,
    "balanced": 0.2,
    "high": 0.4,
    "very_high": 0.7,
}
DEFAULT_TEMPERATURE_LEVEL = "balanced"
ACTIVE_AGENT_TEMPERATURE = TEMPERATURE_LEVELS[DEFAULT_TEMPERATURE_LEVEL]
ACTIVE_AGENT_PROFILE: Optional[AgentProfile] = None
ACTIVE_AGENT_PROFILE_CONTEXT = ""


class CleanHelpFormatter(argparse.RawDescriptionHelpFormatter):
    def __init__(self, prog: str) -> None:
        width = shutil.get_terminal_size((120, 20)).columns
        super().__init__(prog, width=width, max_help_position=32)


def templates_dir() -> Path:
    env = os.getenv("FEDERLICHT_TEMPLATES_DIR") or os.getenv("FEATHER_TEMPLATES_DIR")
    if env:
        path = Path(env).expanduser()
        if path.exists():
            return path
    here = Path(__file__).resolve()
    package_templates = here.parent / "templates"
    if package_templates.exists():
        return package_templates
    return package_templates


def list_builtin_templates() -> list[str]:
    root = templates_dir()
    if not root.exists():
        return [DEFAULT_TEMPLATE_NAME]
    names = sorted({path.stem for path in root.glob("*.md") if path.is_file()})
    if DEFAULT_TEMPLATE_NAME not in names:
        names.insert(0, DEFAULT_TEMPLATE_NAME)
    return names


def parse_args(argv: Optional[list[str]] = None) -> argparse.Namespace:
    templates = list_builtin_templates()
    template_lines = "\n".join(f"  - {name}" for name in templates) if templates else "  (none found)"
    epilog = (
        "Template selection:\n"
        "  --template/--templates auto|<name>|<path>\n"
        "  If --template is 'auto', a 'Template: <name>' line in the report prompt is used.\n"
        "  Otherwise the default template is applied.\n\n"
        "Output format:\n"
        "  Inferred from --output extension (.md, .html, .tex).\n\n"
        "Built-in templates:\n"
        f"{template_lines}\n\n"
        "Preview mode:\n"
        "  --preview-template <name|path|all> [--preview-output <path|dir>]\n"
        "  Generates HTML previews without reading sources.\n\n"
        "Quality selection:\n"
        "  --quality-strategy pairwise|best_of (default: pairwise)\n\n"
        "Examples:\n"
        "  federlicht --run ./examples/runs/20260104_oled --output ./examples/runs/20260104_oled/report_full.html\n"
        "  federlicht --run ./examples/runs/20260104_oled --output ./examples/runs/20260104_oled/report_full.html --template executive_brief\n"
        "  federlicht --run ./examples/runs/20260104_oled --output ./examples/runs/20260104_oled/report_full.tex --template prl_manuscript\n"
    )
    ap = argparse.ArgumentParser(
        description="Federlicht report engine: agentic evidence synthesis and publication-grade report generation.",
        formatter_class=CleanHelpFormatter,
        epilog=epilog,
    )
    env_max_input_tokens = parse_max_input_tokens(os.getenv(MAX_INPUT_TOKENS_ENV))
    ap.add_argument("--run", help="Path to run folder (or its archive/ subfolder).")
    ap.add_argument(
        "--output",
        help="Write report to this path (default: print to stdout). Extension selects format (.md/.html/.tex).",
    )
    ap.add_argument(
        "--site-output",
        default="site",
        help=(
            "Write/update a static report index in this directory (default: site). "
            "Use 'none' to disable."
        ),
    )
    ap.add_argument(
        "--site-refresh",
        nargs="?",
        const="site",
        help=(
            "Rebuild the site manifest/index by scanning <site>/runs for report*.html. "
            "Optionally pass the site root path (default: site)."
        ),
    )
    ap.add_argument(
        "--echo-markdown",
        action=argparse.BooleanOptionalAction,
        default=False,
        help="When --output is set, also print the markdown report to stdout (default: disabled).",
    )
    ap.add_argument(
        "--max-input-tokens",
        dest="max_input_tokens",
        type=int,
        default=env_max_input_tokens,
        help=(
            "Fallback max input tokens for models missing profile limits (default: "
            f"{env_max_input_tokens if env_max_input_tokens else 'unset'}; "
            f"env: {MAX_INPUT_TOKENS_ENV}). "
            "If set in --agent-config config.max_input_tokens, it overrides the CLI/env value. "
            "Per-agent overrides (agents.<name>.max_input_tokens) take precedence."
        ),
    )
    ap.add_argument(
        "--max_input_tokens",
        dest="max_input_tokens",
        type=int,
        default=argparse.SUPPRESS,
        help=argparse.SUPPRESS,
    )
    ap.add_argument(
        "--pdf",
        dest="pdf",
        action="store_true",
        default=True,
        help="Compile PDF when output is .tex (default: enabled).",
    )
    ap.add_argument(
        "--no-pdf",
        dest="pdf",
        action="store_false",
        help="Skip PDF compilation for .tex output.",
    )
    ap.add_argument(
        "--lang",
        default="ko",
        help=(
            "Report language preference (default: ko). Aliases: ko/kor/korean/kr -> Korean; "
            "en/eng/english -> English. Other values are passed through as-is."
        ),
    )
    ap.add_argument(
        "--depth",
        help=(
            "Report depth preference (brief|normal|deep|exhaustive). "
            "Aliases: deepest/ultra map to exhaustive. "
            "If omitted, the orchestrator infers depth from the prompt/context."
        ),
    )
    ap.add_argument("--prompt", help="Inline report focus prompt.")
    ap.add_argument("--prompt-file", help="Path to a text file containing a report focus prompt.")
    ap.add_argument(
        "--generate-prompt",
        action="store_true",
        default=False,
        help=(
            "Generate a report focus prompt by scouting the run and template. "
            "Writes to --output if provided, otherwise to <run>/instruction/generated_prompt_<run>.txt."
        ),
    )
    ap.add_argument(
        "--tags",
        help=(
            "Comma-separated tags to include in the report metadata (e.g., qc,oled,tadf). "
            "Use 'auto' to force auto-tagging. "
            "If omitted, up to 5 auto tags are generated unless --no-tags is set."
        ),
    )
    ap.add_argument(
        "--no-tags",
        action="store_true",
        default=False,
        help="Disable tags (also disables auto tags).",
    )
    ap.add_argument(
        "--template",
        "--templates",
        dest="template",
        default="auto",
        help="Report template name or .md template path (default: auto).",
    )
    ap.add_argument(
        "--free-format",
        action=argparse.BooleanOptionalAction,
        default=False,
        help="Use free-form structure without enforcing a section skeleton (default: disabled).",
    )
    ap.add_argument(
        "--agent-info",
        nargs="?",
        const="-",
        help="Print agent registry JSON and exit (optional path to write).",
    )
    ap.add_argument(
        "--agent-profile",
        default=None,
        help="Agent profile id (default: default).",
    )
    ap.add_argument(
        "--agent-profile-dir",
        default=None,
        help="Directory containing agent profile registry and files.",
    )
    ap.add_argument(
        "--agent-config",
        help="Path to agent override JSON (prompts/models/config).",
    )
    ap.add_argument(
        "--template-adjust",
        action=argparse.BooleanOptionalAction,
        default=True,
        help="Ensure required sections are present (default: enabled).",
    )
    ap.add_argument(
        "--template-adjust-mode",
        default="risk_only",
        choices=["risk_only", "extend", "replace"],
        help=(
            "Template adjuster mode: risk_only only adds Risks & Gaps/Critics without touching other sections "
            "(default); extend keeps template sections and adds new ones; replace uses adjusted list."
        ),
    )
    ap.add_argument(
        "--template-rigidity",
        default=DEFAULT_TEMPLATE_RIGIDITY,
        choices=list(TEMPLATE_RIGIDITY_POLICIES.keys()),
        help=(
            "How strongly to enforce template structure. "
            "strict=strong conformance, balanced=adaptive merge (default), relaxed=minimal adjustment, "
            "loose=light template guidance, off=template enforcement off."
        ),
    )
    ap.add_argument(
        "--preview-template",
        help="Generate template preview HTML and exit (name, path, or 'all').",
    )
    ap.add_argument(
        "--preview-output",
        help="Preview output path or directory (default: current templates directory).",
    )
    ap.add_argument(
        "--generate-template",
        action="store_true",
        default=False,
        help="Generate a custom template (md + css) from a prompt and exit.",
    )
    ap.add_argument(
        "--template-prompt",
        help="Prompt describing the desired template style/sections.",
    )
    ap.add_argument(
        "--template-name",
        help="Template name used for output files and frontmatter.",
    )
    ap.add_argument(
        "--template-store",
        default="run",
        choices=["run", "site"],
        help="Where to store generated templates (run/custom_templates or site/custom_templates).",
    )
    ap.add_argument(
        "--template-output-dir",
        help="Explicit output directory for generated templates (overrides --template-store).",
    )
    ap.add_argument(
        "--interactive",
        action=argparse.BooleanOptionalAction,
        default=False,
        help="Ask for clarifications if the agent needs guidance (default: disabled).",
    )
    ap.add_argument("--answers", help="Inline answers to clarification questions.")
    ap.add_argument("--answers-file", help="Path to a text file containing clarification answers.")
    ap.add_argument(
        "--quality-iterations",
        type=int,
        default=0,
        help="Number of critique/revision loops to improve the report (default: 0).",
    )
    ap.add_argument(
        "--quality-strategy",
        default="pairwise",
        choices=["pairwise", "best_of"],
        help=(
            "Quality selection strategy (pairwise: compare candidates and pass top drafts to writer finalizer; "
            "best_of: keep highest score then finalize)."
        ),
    )
    ap.add_argument("--quality-model", help="Optional model name for critique/revision loops.")
    ap.add_argument(
        "--check-model",
        default=DEFAULT_CHECK_MODEL,
        help=f"Model name for alignment/plan checks and quality loops (default: {DEFAULT_CHECK_MODEL}).",
    )
    ap.add_argument(
        "--quality-max-chars",
        type=int,
        default=12000,
        help="Max chars passed to critique/revision (default: 12000).",
    )
    ap.add_argument(
        "--model",
        default=DEFAULT_MODEL,
        help=(
            f"Model name (default: {DEFAULT_MODEL} if supported). "
            "If OPENAI_BASE_URL is set and the model name is not OpenAI (gpt-*/o*), "
            "Federlicht uses ChatOpenAI for OpenAI-compatible endpoints."
        ),
    )
    ap.add_argument(
        "--temperature-level",
        default=DEFAULT_TEMPERATURE_LEVEL,
        choices=list(TEMPERATURE_LEVELS.keys()),
        help=(
            "Agent creativity level (very_low=0.0, low=0.1, balanced=0.2, high=0.4, very_high=0.7). "
            f"Default: {DEFAULT_TEMPERATURE_LEVEL}."
        ),
    )
    ap.add_argument(
        "--temperature",
        type=float,
        help=(
            "Optional explicit temperature override for agents. "
            "If unset, --temperature-level is used."
        ),
    )
    env_model_vision = os.getenv("OPENAI_MODEL_VISION") or None
    ap.add_argument(
        "--model-vision",
        default=env_model_vision,
        help=(
            "Optional vision model name for analyzing extracted figures. "
            "Uses OPENAI_BASE_URL_VISION/OPENAI_API_KEY_VISION when available. "
            f"(default: {env_model_vision or 'unset'}; env: OPENAI_MODEL_VISION)"
        ),
    )
    ap.add_argument(
        "--progress",
        action=argparse.BooleanOptionalAction,
        default=True,
        help="Print intermediate progress snippets (default: enabled).",
    )
    ap.add_argument(
        "--stream",
        action=argparse.BooleanOptionalAction,
        default=True,
        help="Stream agent responses to stdout as they are generated (default: enabled).",
    )
    ap.add_argument(
        "--stream-debug",
        action=argparse.BooleanOptionalAction,
        default=False,
        help="Log streaming event metadata for debugging (default: disabled).",
    )
    ap.add_argument(
        "--cache",
        action=argparse.BooleanOptionalAction,
        default=True,
        help="Reuse per-stage cache under report_notes/cache (default: enabled).",
    )
    ap.add_argument(
        "--alignment-check",
        action=argparse.BooleanOptionalAction,
        default=True,
        help="Check alignment with the report prompt at each stage (default: enabled).",
    )
    ap.add_argument(
        "--repair-mode",
        default="append",
        choices=["append", "replace", "off"],
        help=(
            "Structural repair behavior when sections are missing: "
            "append adds only missing sections, replace rewrites the report, off disables repair "
            "(default: append)."
        ),
    )
    ap.add_argument(
        "--repair-debug",
        action=argparse.BooleanOptionalAction,
        default=False,
        help="Log structural repair diagnostics (default: disabled).",
    )
    ap.add_argument(
        "--progress-chars",
        type=int,
        default=800,
        help="Max chars for progress snippets (default: 800).",
    )
    ap.add_argument(
        "--max-files",
        type=int,
        default=200,
        help="Max files to list in tool output (default: 200).",
    )
    ap.add_argument(
        "--max-chars",
        type=int,
        default=16000,
        help="Max chars returned by read tool (default: 16000).",
    )
    ap.add_argument(
        "--max-tool-chars",
        type=int,
        default=0,
        help=(
            "Max cumulative chars returned by read tool across a run. "
            "Set 0 to use an automatic safety cap derived from stage/model budgets."
        ),
    )
    ap.add_argument(
        "--max_tool_chars",
        dest="max_tool_chars",
        type=int,
        default=argparse.SUPPRESS,
        help=argparse.SUPPRESS,
    )
    ap.add_argument(
        "--max-pdf-pages",
        type=int,
        default=6,
        help=(
            "Max PDF pages to extract when needed (default: 6). "
            "Use 0 to attempt reading all pages."
        ),
    )
    ap.add_argument(
        "--max-pptx-slides",
        type=int,
        default=20,
        help=(
            "Max PPTX slides to extract when needed (default: 20). "
            "Use 0 to attempt reading all slides."
        ),
    )
    ap.add_argument(
        "--pdf-extend-pages",
        type=int,
        default=2,
        help=(
            "Auto-read next N pages when extracted PDF text is too short (default: 2). "
            "Set to 0 to disable."
        ),
    )
    ap.add_argument(
        "--pdf-extend-min-chars",
        type=int,
        default=1200,
        help=(
            "Minimum extracted characters before triggering auto page extension (default: 1200)."
        ),
    )
    ap.add_argument(
        "--figures",
        dest="extract_figures",
        action="store_true",
        default=True,
        help="Extract embedded PDF figures for the report (default: enabled).",
    )
    ap.add_argument(
        "--no-figures",
        dest="extract_figures",
        action="store_false",
        help="Disable embedded PDF figure extraction.",
    )
    ap.add_argument(
        "--figures-max-per-pdf",
        type=int,
        default=4,
        help="Max figures extracted per PDF (default: 4).",
    )
    ap.add_argument(
        "--figures-min-area",
        type=int,
        default=12000,
        help="Min image area (px^2) to keep (default: 12000).",
    )
    ap.add_argument(
        "--figures-renderer",
        default="auto",
        choices=["auto", "pdfium", "poppler", "mupdf", "none"],
        help="Renderer for vector PDF pages when needed (default: auto).",
    )
    ap.add_argument(
        "--figures-dpi",
        type=int,
        default=150,
        help="DPI for rendered PDF pages (default: 150).",
    )
    ap.add_argument(
        "--figures-mode",
        choices=["select", "auto"],
        default="auto",
        help="Figure insertion mode: auto inserts all candidates; select requires a selection file.",
    )
    ap.add_argument(
        "--figures-select",
        help="Path to a figure selection file (default: report_notes/figures_selected.txt).",
    )
    ap.add_argument(
        "--figures-preview",
        action=argparse.BooleanOptionalAction,
        default=False,
        help="Generate figures_preview.html from an existing report and exit.",
    )
    ap.add_argument("--max-refs", type=int, default=200, help="Max references to append (default: 200).")
    ap.add_argument("--notes-dir", help="Optional folder to save intermediate notes (scout/evidence).")
    ap.add_argument("--author", help="Author name shown in the report header.")
    ap.add_argument(
        "--organization",
        help="Optional team/organization shown with the author in the report header.",
    )
    ap.add_argument(
        "--overwrite-output",
        action=argparse.BooleanOptionalAction,
        default=False,
        help="Overwrite the output file if it exists (default: disabled).",
    )
    ap.add_argument(
        "--web-search",
        action=argparse.BooleanOptionalAction,
        default=False,
        help="Enable online web research and store supporting info (default: disabled).",
    )
    stage_list = ", ".join(STAGE_ORDER)
    ap.add_argument(
        "--stages",
        help=(
            "Comma-separated pipeline stages to run (e.g., scout,plan,evidence,writer,quality). "
            f"Available stages: {stage_list}. Omit to run the full pipeline."
        ),
    )
    ap.add_argument(
        "--skip-stages",
        help=f"Comma-separated pipeline stages to skip. Available stages: {stage_list}.",
    )
    ap.add_argument(
        "--stage-info",
        nargs="?",
        const="all",
        help=(
            "Print stage registry JSON and exit. Optionally pass a comma-separated stage list "
            f"or an output path. Available stages: {stage_list}."
        ),
    )
    ap.add_argument("--web-max-queries", type=int, default=4, help="Max web queries to run when enabled.")
    ap.add_argument("--web-max-results", type=int, default=5, help="Max results per web query.")
    ap.add_argument("--web-max-fetch", type=int, default=6, help="Max URLs to fetch across web results.")
    ap.add_argument("--supporting-dir", help="Optional folder for web supporting info.")
    args = ap.parse_args(argv)
    argv_flags = sys.argv if argv is None else ["federlicht", *list(argv)]
    cli_tokens = "--max-input-tokens" in argv_flags or "--max_input_tokens" in argv_flags
    if cli_tokens:
        args.max_input_tokens_source = "cli"
    elif env_max_input_tokens:
        args.max_input_tokens_source = "env"
    else:
        args.max_input_tokens_source = "none"
    args._cli_argv = argv_flags
    return args


def resolve_archive(path: Path) -> tuple[Path, Path, str]:
    path = path.resolve()
    if path.name == "archive":
        archive_dir = path
        run_dir = path.parent
    else:
        run_dir = path
        archive_dir = path / "archive"
    if not archive_dir.exists():
        raise FileNotFoundError(f"Archive folder not found: {archive_dir}")
    query_id = run_dir.name
    return archive_dir, run_dir, query_id


def find_index_file(archive_dir: Path, query_id: str) -> Optional[Path]:
    candidate = archive_dir / f"{query_id}-index.md"
    if candidate.exists():
        return candidate
    legacy = archive_dir / "index.md"
    if legacy.exists():
        return legacy
    matches = sorted(archive_dir.glob("*-index.md"))
    if matches:
        return matches[0]
    return None


def find_instruction_file(run_dir: Path) -> Optional[Path]:
    instr_dir = run_dir / "instruction"
    if not instr_dir.exists():
        return None
    candidates = sorted(instr_dir.glob("*.txt"))
    return candidates[0] if candidates else None


def write_run_overview(
    run_dir: Path,
    instruction_file: Optional[Path],
    index_file: Optional[Path],
) -> Optional[Path]:
    if not instruction_file and not index_file:
        return None
    report_dir = run_dir / "report"
    report_dir.mkdir(parents=True, exist_ok=True)
    overview_path = report_dir / "run_overview.md"
    lines: list[str] = ["# Run Overview", ""]
    if instruction_file and instruction_file.exists():
        rel_instruction = f"./{instruction_file.relative_to(run_dir).as_posix()}"
        lines.extend(["## Instruction", f"Source: {rel_instruction}", ""])
        content = instruction_file.read_text(encoding="utf-8", errors="replace").strip()
        lines.append("```")
        lines.append(content)
        lines.append("```")
        lines.append("")
    if index_file and index_file.exists():
        rel_index = f"./{index_file.relative_to(run_dir).as_posix()}"
        lines.extend(["## Archive Index", f"Source: {rel_index}", ""])
        content = index_file.read_text(encoding="utf-8", errors="replace").strip()
        lines.append(content)
        lines.append("")
    overview_path.write_text("\n".join(lines).strip() + "\n", encoding="utf-8")
    return overview_path


def arxiv_template_id(src_dir: Path) -> str:
    name = src_dir.name
    if ARXIV_ID_RE.match(name):
        return name
    if ARXIV_ID_RE.match(name.replace("_", ".")):
        return name.replace("_", ".")
    if src_dir.parent and ARXIV_ID_RE.match(src_dir.parent.name):
        return src_dir.parent.name
    return slugify_label(name, max_len=64)


def read_arxiv_readme(src_dir: Path) -> Optional[dict]:
    readme_path = src_dir / "00README.json"
    if not readme_path.exists():
        return None
    try:
        return json.loads(readme_path.read_text(encoding="utf-8", errors="replace"))
    except json.JSONDecodeError:
        return None


def strip_tex_comments(line: str) -> str:
    if "%" not in line:
        return line
    parts = line.split("%")
    if not parts:
        return line
    return parts[0]


def select_main_tex(src_dir: Path, readme: Optional[dict]) -> Optional[Path]:
    if readme:
        sources = readme.get("sources") or []
        if isinstance(sources, list):
            toplevel = None
            for entry in sources:
                if not isinstance(entry, dict):
                    continue
                if entry.get("usage") == "toplevel":
                    toplevel = entry
                    break
            choice = toplevel or (sources[0] if sources else None)
            if isinstance(choice, dict):
                filename = choice.get("filename")
                if filename:
                    candidate = src_dir / filename
                    if candidate.exists():
                        return candidate
    tex_files = sorted(src_dir.rglob("*.tex"))
    for tex in tex_files:
        try:
            head = tex.read_text(encoding="utf-8", errors="replace")[:8000]
        except Exception:
            continue
        if "\\documentclass" in head:
            return tex
    return tex_files[0] if tex_files else None


def extract_tex_includes(tex_text: str) -> list[str]:
    includes = []
    for raw in tex_text.splitlines():
        line = strip_tex_comments(raw).strip()
        if not line:
            continue
        for match in re.finditer(r"\\(?:input|include|subfile)\{([^}]+)\}", line):
            path = match.group(1).strip()
            if path:
                includes.append(path)
    return includes


def resolve_tex_path(base: Path, rel: str) -> Optional[Path]:
    candidate = Path(rel)
    if not candidate.suffix:
        candidate = candidate.with_suffix(".tex")
    if not candidate.is_absolute():
        candidate = (base / candidate).resolve()
    if candidate.exists():
        return candidate
    return None


def collect_tex_tree(main_tex: Path) -> list[Path]:
    ordered: list[Path] = []
    seen: set[Path] = set()

    def visit(path: Path) -> None:
        if path in seen or not path.exists():
            return
        seen.add(path)
        ordered.append(path)
        try:
            text = path.read_text(encoding="utf-8", errors="replace")
        except Exception:
            return
        for inc in extract_tex_includes(text):
            resolved = resolve_tex_path(path.parent, inc)
            if resolved:
                visit(resolved)

    visit(main_tex)
    return ordered


def extract_tex_sections(tex_files: list[Path]) -> list[dict]:
    sections: list[dict] = []
    pattern = re.compile(r"\\(section|subsection|subsubsection)\*?\{([^}]+)\}")
    for path in tex_files:
        try:
            text = path.read_text(encoding="utf-8", errors="replace")
        except Exception:
            continue
        for raw in text.splitlines():
            line = strip_tex_comments(raw)
            for match in pattern.finditer(line):
                level = match.group(1)
                title = match.group(2).strip()
                if title:
                    sections.append({"level": level, "title": title, "file": path})
    return sections


def section_list_from_tex(sections: list[dict], main_tex: Optional[Path]) -> list[str]:
    found: list[str] = []
    seen: set[str] = set()
    if main_tex:
        try:
            main_text = main_tex.read_text(encoding="utf-8", errors="replace")
        except Exception:
            main_text = ""
        if re.search(r"\\begin\{abstract\}", main_text):
            found.append("Abstract")
            seen.add("Abstract")
    for sec in sections:
        if sec.get("level") != "section":
            continue
        title = sec.get("title")
        if not title or title in seen:
            continue
        seen.add(title)
        found.append(title)
    return found


def merge_section_lists(primary: list[str], fallback: list[str]) -> list[str]:
    seen: set[str] = set()
    merged: list[str] = []
    for section in primary:
        key = section.strip().lower()
        if not key or key in seen:
            continue
        seen.add(key)
        merged.append(section)
    for section in fallback:
        key = section.strip().lower()
        if not key or key in seen:
            continue
        seen.add(key)
        merged.append(section)
    return merged


def group_section_structure(section_meta: list[dict]) -> list[dict]:
    groups: list[dict] = []
    current: Optional[dict] = None
    for entry in section_meta:
        level = entry.get("level")
        title = entry.get("title")
        if not isinstance(title, str) or not title.strip():
            continue
        if level == "section":
            current = {"title": title.strip(), "subsections": []}
            groups.append(current)
            continue
        if current is None:
            continue
        if level in {"subsection", "subsubsection"}:
            current["subsections"].append((level, title.strip()))
    return groups


def build_arxiv_template_guidance(
    sections: list[str],
    report_prompt: Optional[str],
    language: str,
    model_name: str,
    create_deep_agent,
    backend,
    prompt_override: Optional[str] = None,
) -> tuple[dict[str, str], list[str]]:
    if not sections:
        return {}, []
    prompt = prompt_override or prompts.build_template_designer_prompt()
    user_parts = [
        "Sections:",
        "\n".join(f"- {s}" for s in sections),
        "",
        "Report focus prompt:",
        report_prompt or "(none)",
        "",
        f"Write in {language}.",
    ]
    agent = create_agent_with_fallback(create_deep_agent, model_name, [], prompt, backend)
    result = agent.invoke({"messages": [{"role": "user", "content": "\n".join(user_parts)}]})
    text = extract_agent_text(result)
    parsed = extract_json_object(text) or {}
    section_guidance = parsed.get("section_guidance") if isinstance(parsed, dict) else None
    writer_guidance = parsed.get("writer_guidance") if isinstance(parsed, dict) else None
    if not isinstance(section_guidance, dict):
        section_guidance = {}
    if not isinstance(writer_guidance, list):
        writer_guidance = []
    clean_guidance = {}
    for key, value in section_guidance.items():
        if not key or not isinstance(value, str):
            continue
        clean_guidance[str(key)] = " ".join(value.split())
    clean_writer = [" ".join(str(item).split()) for item in writer_guidance if item]
    return clean_guidance, clean_writer


def fallback_template_guidance(sections: list[str]) -> tuple[dict[str, str], list[str]]:
    guidance = {}
    for section in sections:
        guidance[section] = "Summarize key evidence and implications for this section."
    return guidance, ["Maintain a critical, evidence-based review tone."]


def _normalize_template_name(value: Optional[str]) -> str:
    raw = (value or "").strip()
    if not raw:
        return "custom_template"
    return raw


def generate_template_from_prompt(
    template_prompt: str,
    template_name: str,
    language: str,
    model_name: str,
    create_deep_agent,
    backend,
) -> tuple[TemplateSpec, str]:
    prompt = prompts.build_template_generator_prompt(language)
    user_parts = [
        f"Template name: {template_name}",
        "User request:",
        template_prompt,
        "",
        "JSON only.",
    ]
    agent = create_agent_with_fallback(create_deep_agent, model_name, [], prompt, backend)
    result = agent.invoke({"messages": [{"role": "user", "content": "\n".join(user_parts)}]})
    text = extract_agent_text(result)
    parsed = extract_json_object(text) or {}
    if not isinstance(parsed, dict):
        parsed = {}
    sections = parsed.get("sections") if isinstance(parsed.get("sections"), list) else []
    section_guidance = parsed.get("section_guidance") if isinstance(parsed.get("section_guidance"), dict) else {}
    writer_guidance = parsed.get("writer_guidance") if isinstance(parsed.get("writer_guidance"), list) else []
    layout = parsed.get("layout") if isinstance(parsed.get("layout"), str) else ""
    description = parsed.get("description") if isinstance(parsed.get("description"), str) else ""
    tone = parsed.get("tone") if isinstance(parsed.get("tone"), str) else ""
    audience = parsed.get("audience") if isinstance(parsed.get("audience"), str) else ""
    css_text = parsed.get("css") if isinstance(parsed.get("css"), str) else ""

    clean_sections = [s.strip() for s in sections if isinstance(s, str) and s.strip()]
    if not clean_sections:
        clean_sections = list(DEFAULT_SECTIONS)
    clean_guidance: dict[str, str] = {}
    for key, value in section_guidance.items():
        if not key or not isinstance(value, str):
            continue
        clean_guidance[str(key)] = " ".join(value.split())
    clean_writer = [" ".join(str(item).split()) for item in writer_guidance if item]
    clean_layout = layout.strip().lower()
    if clean_layout not in {"single_column", "sidebar_toc"}:
        clean_layout = ""
    slug = slugify_label(template_name or "custom")
    if not css_text or "body.template-" not in css_text:
        css_text = (
            f"body.template-{slug} {{\n"
            "  --site-ink: var(--ink);\n"
            "  --site-muted: var(--muted);\n"
            "  --ink: #1d1b17;\n"
            "  --muted: #59524a;\n"
            "  --accent: #2563eb;\n"
            "  --page-bg: linear-gradient(135deg, #f3f4f6 0%, #f8fafc 60%, #ffffff 100%);\n"
            "  --masthead-bg: #6f7377;\n"
            "  --masthead-border: rgba(255, 255, 255, 0.35);\n"
            "  --masthead-title: #f8fafc;\n"
            "  --masthead-deck: rgba(248, 250, 252, 0.85);\n"
            "  --masthead-kicker: rgba(248, 250, 252, 0.72);\n"
            "  --masthead-link: rgba(248, 250, 252, 0.88);\n"
            "  --masthead-link-border: rgba(248, 250, 252, 0.3);\n"
            "  --masthead-link-bg: rgba(15, 23, 42, 0.2);\n"
            "  --paper: #ffffff;\n"
            "  --paper-alt: #f3f4f6;\n"
            "  --rule: rgba(15, 23, 42, 0.16);\n"
            "  --shadow: 0 28px 70px rgba(15, 23, 42, 0.18);\n"
            "  --body-font: \"Iowan Old Style\", \"Charter\", \"Palatino Linotype\", Georgia, serif;\n"
            "  --heading-font: \"Avenir Next\", \"Gill Sans\", \"Trebuchet MS\", sans-serif;\n"
            "  --ui-font: \"Avenir Next\", \"Gill Sans\", \"Trebuchet MS\", sans-serif;\n"
            "}\n"
        )
    css_text = css_text.strip() + "\n"
    spec = TemplateSpec(
        name=template_name,
        description=description,
        tone=tone,
        audience=audience,
        sections=clean_sections,
        section_guidance=clean_guidance,
        writer_guidance=clean_writer,
        css=f"{slug}.css",
        latex="default.tex",
        layout=clean_layout or None,
        source=None,
    )
    return spec, css_text


def write_generated_template(
    spec: TemplateSpec,
    css_text: str,
    output_dir: Path,
) -> tuple[Path, Path]:
    output_dir.mkdir(parents=True, exist_ok=True)
    slug = slugify_label(spec.name or "custom")
    css_path = output_dir / f"{slug}.css"
    md_path = output_dir / f"{slug}.md"
    css_path.write_text(css_text, encoding="utf-8")
    header: list[str] = ["---"]
    header.append(f"name: {spec.name}")
    if spec.description:
        header.append(f"description: {spec.description}")
    if spec.tone:
        header.append(f"tone: {spec.tone}")
    if spec.audience:
        header.append(f"audience: {spec.audience}")
    header.append(f"css: {css_path.name}")
    header.append(f"latex: {spec.latex or 'default.tex'}")
    if spec.layout:
        header.append(f"layout: {spec.layout}")
    for section in spec.sections:
        header.append(f"section: {section}")
    for section, guide in spec.section_guidance.items():
        header.append(f"guide {section}: {guide}")
    for note in spec.writer_guidance:
        header.append(f"writer_guidance: {note}")
    header.append("---\n")
    md_path.write_text("\n".join(header), encoding="utf-8")
    return md_path, css_path


def resolve_generated_template_dir(args: argparse.Namespace) -> Path:
    if getattr(args, "template_output_dir", None):
        return Path(args.template_output_dir).resolve()
    store = getattr(args, "template_store", "run")
    if store == "site":
        site_root = resolve_site_output(args.site_output)
        if not site_root:
            raise ValueError("--template-store site requires --site-output.")
        return site_root / "custom_templates"
    if not args.run:
        raise ValueError("--template-store run requires --run.")
    _, run_dir, _ = resolve_archive(Path(args.run))
    return run_dir / "custom_templates"


def generate_template_from_arxiv_src(
    src_dir: Path,
    run_dir: Path,
    report_prompt: Optional[str],
    language: str,
    model_name: str,
    create_deep_agent,
    backend,
    style_spec: TemplateSpec,
    prompt_override: Optional[str] = None,
) -> Optional[Path]:
    if not src_dir.exists():
        print(f"ERROR template source not found: {src_dir}", file=sys.stderr)
        return None
    readme = read_arxiv_readme(src_dir)
    if not readme:
        print(
            "WARN 00README.json not found. Falling back to auto-detect main .tex file.",
            file=sys.stderr,
        )
    main_tex = select_main_tex(src_dir, readme)
    if not main_tex:
        print(f"ERROR no .tex files found in: {src_dir}", file=sys.stderr)
        return None
    tex_files = collect_tex_tree(main_tex)
    section_meta = extract_tex_sections(tex_files)
    source_sections = section_list_from_tex(section_meta, main_tex)
    base_sections = list(style_spec.sections) if style_spec.sections else list(DEFAULT_SECTIONS)
    sections = merge_section_lists(source_sections, base_sections)
    if not sections:
        sections = list(DEFAULT_SECTIONS)

    template_root = run_dir / "template_src" / arxiv_template_id(src_dir)
    template_root.mkdir(parents=True, exist_ok=True)
    sections_dir = template_root / "sections"
    guidance_dir = template_root / "guidance"
    sections_dir.mkdir(parents=True, exist_ok=True)
    guidance_dir.mkdir(parents=True, exist_ok=True)

    try:
        section_guidance, writer_guidance = build_arxiv_template_guidance(
            sections,
            report_prompt,
            language,
            model_name,
            create_deep_agent,
            backend,
            prompt_override=prompt_override,
        )
    except Exception as exc:
        print(f"WARN template guidance generation failed: {exc}", file=sys.stderr)
        section_guidance, writer_guidance = fallback_template_guidance(sections)

    template_md = template_root / "template.md"
    template_tex = template_root / "template_skeleton.tex"
    template_main = template_root / "template_main.tex"
    manifest_path = template_root / "template_manifest.json"
    style_css = style_spec.css or "default.css"
    style_latex = style_spec.latex or "default.tex"
    css_path = resolve_template_css_path(style_spec)
    latex_path = resolve_template_latex_path(style_spec)
    if css_path and css_path.exists():
        target = template_root / css_path.name
        if not target.exists():
            shutil.copy2(css_path, target)
        style_css = target.name
    if latex_path and latex_path.exists():
        target = template_root / latex_path.name
        if not target.exists():
            shutil.copy2(latex_path, target)
        style_latex = target.name
    header = [
        "---",
        f"name: arxiv_{arxiv_template_id(src_dir)}",
        f"description: Generated from arXiv source structure ({arxiv_template_id(src_dir)}).",
        f"tone: {style_spec.tone or 'Technical, evidence-based.'}",
        f"audience: {style_spec.audience or 'Domain experts and technical leaders.'}",
        f"css: {style_css}",
        f"latex: {style_latex}",
    ]
    for section in sections:
        header.append(f"section: {section}")
        guidance = section_guidance.get(section)
        if guidance:
            header.append(f"guide {section}: {guidance}")
    for note in writer_guidance:
        header.append(f"writer_guidance: {note}")
    header.append("---")
    template_md.write_text("\n".join(header) + "\n", encoding="utf-8")

    grouped = group_section_structure(section_meta)
    grouped_map = {g["title"]: g for g in grouped if isinstance(g.get("title"), str)}
    section_files: list[dict] = []
    main_lines = ["% Auto-generated main file from arXiv source", ""]
    skeleton_lines = list(main_lines)
    for idx, section in enumerate(sections, start=1):
        slug = slugify_label(section, max_len=64)
        file_name = f"ch_{idx:02d}_{slug}.tex"
        section_path = sections_dir / file_name
        guidance_path = guidance_dir / f"{file_name}.md"
        file_lines = []
        if section.lower() == "abstract":
            file_lines.append("\\section*{Abstract}")
        else:
            file_lines.append(f"\\section{{{latex_escape(section)}}}")
        file_lines.append("% TODO: write content")
        group = grouped_map.get(section)
        if group:
            for level, title in group.get("subsections", []):
                if level == "subsubsection":
                    file_lines.append(f"\\subsubsection{{{latex_escape(title)}}}")
                else:
                    file_lines.append(f"\\subsection{{{latex_escape(title)}}}")
                file_lines.append("% TODO: write content")
        section_path.write_text("\n".join(file_lines).strip() + "\n", encoding="utf-8")
        guidance_text = section_guidance.get(section) or "Summarize key evidence and implications for this section."
        guidance_path.write_text(f"# {section}\n\n{guidance_text}\n", encoding="utf-8")
        section_files.append(
            {
                "title": section,
                "path": str(section_path),
                "guidance_path": str(guidance_path),
            }
        )
        main_lines.append(f"\\input{{sections/{file_name}}}")
        skeleton_lines.append(f"\\input{{sections/{file_name}}}")
    template_main.write_text("\n".join(main_lines).strip() + "\n", encoding="utf-8")
    template_tex.write_text("\n".join(skeleton_lines).strip() + "\n", encoding="utf-8")

    manifest = {
        "source_dir": str(src_dir),
        "main_tex": str(main_tex),
        "tex_files": [str(path) for path in tex_files],
        "sections": sections,
        "section_files": section_files,
        "readme": readme,
        "generated_at": dt.datetime.now().strftime("%Y-%m-%d %H:%M:%S"),
        "style_template": style_spec.name,
        "template_md": str(template_md),
        "template_skeleton": str(template_tex),
        "template_main": str(template_main),
    }
    manifest_path.write_text(json.dumps(manifest, ensure_ascii=False, indent=2), encoding="utf-8")
    return template_md


def rel_path_or_abs(path: Path, base_dir: Path) -> str:
    try:
        rel = path.relative_to(base_dir).as_posix()
        return f"./{rel}"
    except ValueError:
        return str(path)


def append_report_workflow_outputs(
    workflow_path: Optional[Path],
    run_dir: Path,
    output_path: Optional[Path],
    report_overview_path: Optional[Path],
    meta_path: Optional[Path],
    prompt_copy_path: Optional[Path],
    notes_dir: Path,
    preview_path: Optional[Path],
) -> None:
    if not workflow_path or not workflow_path.exists():
        return
    content = workflow_path.read_text(encoding="utf-8", errors="replace")
    if "## Outputs" in content:
        return
    lines: list[str] = ["", "## Outputs"]
    def add(label: str, path: Optional[Path]) -> None:
        if path and path.exists():
            lines.append(f"- {label}: {rel_path_or_abs(path, run_dir)}")
    add("Report output", output_path)
    add("Report overview", report_overview_path)
    add("Report meta", meta_path)
    add("Report prompt copy", prompt_copy_path)
    add("Figure candidates", preview_path)
    report_template = notes_dir / "report_template.txt"
    add("Template summary", report_template if report_template.exists() else None)
    questions_path = notes_dir / "clarification_questions.txt"
    add("Clarification questions", questions_path if questions_path.exists() else None)
    answers_path = notes_dir / "clarification_answers.txt"
    add("Clarification answers", answers_path if answers_path.exists() else None)
    updated = content.rstrip() + "\n" + "\n".join(lines).strip() + "\n"
    workflow_path.write_text(updated, encoding="utf-8")


def write_report_prompt_copy(
    run_dir: Path,
    report_prompt: Optional[str],
    output_path: Optional[Path],
) -> Optional[Path]:
    instr_dir = run_dir / "instruction"
    instr_dir.mkdir(parents=True, exist_ok=True)
    stem = output_path.stem if output_path else "report"
    prompt_path = instr_dir / f"report_prompt_{stem}.txt"
    text = (report_prompt or "No report prompt provided.").strip()
    prompt_path.write_text(f"{text}\n", encoding="utf-8")
    return prompt_path


def write_report_overview(
    run_dir: Path,
    output_path: Optional[Path],
    report_prompt: Optional[str],
    template_name: str,
    template_adjustment_path: Optional[Path],
    output_format: str,
    language: str,
    quality_iterations: int,
    quality_strategy: str,
    figures_enabled: bool,
    figures_mode: str,
    prompt_path: Optional[Path],
) -> Optional[Path]:
    if not output_path:
        return None
    report_dir = run_dir / "report"
    report_dir.mkdir(parents=True, exist_ok=True)
    overview_path = report_dir / f"run_overview_{output_path.stem}.md"
    lines: list[str] = [
        "# Report Overview",
        "",
        "## Report Output",
        f"Output: {rel_path_or_abs(output_path, run_dir)}",
        f"Template: {template_name}",
        f"Format: {output_format}",
        f"Language: {language}",
        f"Quality iterations: {quality_iterations}",
        f"Quality strategy: {quality_strategy}",
        f"Figures: {'enabled' if figures_enabled else 'disabled'} ({figures_mode})",
        "",
    ]
    if prompt_path:
        lines.extend(["## Report Prompt (Saved)", f"Source: {rel_path_or_abs(prompt_path, run_dir)}", ""])
    if template_adjustment_path:
        lines.extend(
            [
                "## Template Adjustment",
                f"Source: {rel_path_or_abs(template_adjustment_path, run_dir)}",
                "",
            ]
        )
    if report_prompt:
        lines.append("```")
        lines.append(report_prompt.strip())
        lines.append("```")
        lines.append("")
    overview_path.write_text("\n".join(lines).strip() + "\n", encoding="utf-8")
    return overview_path


def resolve_site_output(site_output: Optional[str]) -> Optional[Path]:
    if site_output is None:
        return None
    value = str(site_output).strip()
    if not value or value.lower() in {"none", "off", "disable", "disabled", "false", "0"}:
        return None
    return Path(value).resolve()


def relpath_if_within(path: Optional[Path], root: Path) -> Optional[str]:
    if not path:
        return None
    try:
        rel = path.resolve().relative_to(root.resolve())
    except ValueError:
        return None
    return rel.as_posix()


def derive_report_summary(report: str, output_format: str, limit: int = 220) -> str:
    summary = extract_section_summary(report, output_format)
    if summary:
        return truncate_text_head(summary, limit)
    text = report
    if output_format in {"html", "md"}:
        text = html_to_text(markdown_to_html(report))
    elif output_format == "tex":
        text = re.sub(r"\\[a-zA-Z]+\\*?(?:\[[^\]]*\])?", " ", report)
        text = re.sub(r"[{}$]", " ", text)
    text = re.sub(r"\s+", " ", text).strip()
    if not text:
        return ""
    return truncate_text_head(text, limit)


def extract_section_summary(report: str, output_format: str) -> Optional[str]:
    targets = {
        "abstract",
        "executive summary",
        "lede",
        "hook",
        "synopsis",
        "overview",
        "summary",
        "요약",
        "초록",
        "핵심 요약",
        "개요",
        "개관",
    }
    if output_format == "html":
        summary = extract_section_summary_html(report, targets)
        if summary:
            return summary
        return extract_section_summary_md(report, targets)
    if output_format == "md":
        summary = extract_section_summary_md(report, targets)
        if summary:
            return summary
        return extract_section_summary_html(report, targets)
    return None


def extract_section_summary_html(report: str, targets: set[str]) -> Optional[str]:
    if not report:
        return None
    pattern = re.compile(r"(?is)<h([1-6])[^>]*>(.*?)</h\1>(.*?)(?=<h[1-6]|\Z)")
    for match in pattern.finditer(report):
        title = html_to_text(match.group(2)).strip().lower()
        title = re.sub(r"[^a-z0-9가-힣\\s]", "", title)
        if not title:
            continue
        if title in targets:
            body = match.group(3)
            para = re.search(r"(?is)<p[^>]*>(.*?)</p>", body)
            if para:
                text = html_to_text(para.group(1)).strip()
            else:
                text = html_to_text(body).strip()
            text = re.sub(r"\\s+", " ", text).strip()
            return text or None
    return None


def extract_section_summary_md(report: str, targets: set[str]) -> Optional[str]:
    lines = report.splitlines()
    current_title = None
    buffer: list[str] = []
    def flush() -> Optional[str]:
        if current_title and current_title in targets:
            text = " ".join(buffer).strip()
            text = re.sub(r"\\s+", " ", text).strip()
            return text or None
        return None
    for line in lines + ["## _end_"]:
        heading = re.match(r"^(#{1,6})\\s+(.+)", line)
        if heading:
            summary = flush()
            if summary:
                return summary
            current_title = re.sub(r"[^a-zA-Z0-9가-힣\\s]", "", heading.group(2)).strip().lower()
            buffer = []
        else:
            if line.strip():
                buffer.append(line.strip())
    return None


def build_site_manifest_entry(
    site_root: Path,
    run_dir: Path,
    output_path: Path,
    title: str,
    author: str,
    summary: str,
    output_format: str,
    template_name: str,
    language: str,
    generated_at: dt.datetime,
    report_overview_path: Optional[Path] = None,
    workflow_path: Optional[Path] = None,
    model_name: Optional[str] = None,
    tags: Optional[list[str]] = None,
) -> Optional[dict]:
    report_rel = relpath_if_within(output_path, site_root)
    if not report_rel:
        return None
    paths = {"report": report_rel}
    overview_rel = relpath_if_within(report_overview_path, site_root)
    if overview_rel:
        paths["overview"] = overview_rel
    workflow_rel = relpath_if_within(workflow_path, site_root)
    if workflow_rel:
        paths["workflow"] = workflow_rel
    run_rel = relpath_if_within(run_dir, site_root)
    if run_rel:
        paths["run"] = run_rel
    stat = output_path.stat()
    return {
        "id": run_dir.name,
        "run": run_dir.name,
        "report_stem": output_path.stem,
        "title": title,
        "author": author,
        "summary": summary,
        "lang": language,
        "template": template_name,
        "format": output_format,
        "model": model_name,
        "tags": list(tags or []),
        "date": generated_at.strftime("%Y-%m-%d"),
        "timestamp": generated_at.isoformat(),
        "source_mtime": int(stat.st_mtime),
        "source_size": int(stat.st_size),
        "paths": paths,
    }


def update_site_manifest(site_root: Path, entry: dict) -> dict:
    site_root.mkdir(parents=True, exist_ok=True)
    manifest_path = site_root / "manifest.json"
    manifest: dict
    if manifest_path.exists():
        try:
            manifest = json.loads(manifest_path.read_text(encoding="utf-8"))
        except json.JSONDecodeError:
            manifest = {}
    else:
        manifest = {}
    items = manifest.get("items")
    if isinstance(items, list):
        items = list(items)
    elif isinstance(manifest, list):
        items = list(manifest)
    else:
        items = []
    replaced = False
    for idx, existing in enumerate(items):
        if existing.get("id") == entry.get("id"):
            items[idx] = entry
            replaced = True
            break
    if not replaced:
        items.append(entry)
    def sort_key(item: dict) -> str:
        return str(item.get("timestamp") or item.get("date") or "")
    items.sort(key=sort_key, reverse=True)
    now = dt.datetime.now().isoformat()
    manifest = {
        "revision": now,
        "generated_at": now,
        "items": items,
    }
    manifest_path.write_text(json.dumps(manifest, ensure_ascii=False, indent=2), encoding="utf-8")
    return manifest


def build_site_index_html(manifest: dict, refresh_minutes: int = 10) -> str:
    manifest_json = json.dumps(manifest, ensure_ascii=False)
    manifest_json = manifest_json.replace("</", "<\\/")
    refresh_ms = max(refresh_minutes, 1) * 60 * 1000
    return f"""<!doctype html>
<html lang="ko">
  <head>
    <meta charset="utf-8" />
    <meta name="viewport" content="width=device-width, initial-scale=1" />
    <title>Federlicht Report Hub</title>
    <link rel="preconnect" href="https://fonts.googleapis.com">
    <link rel="preconnect" href="https://fonts.gstatic.com" crossorigin>
    <link href="https://fonts.googleapis.com/css2?family=Fraunces:wght@300;600;700&family=Space+Grotesk:wght@400;500;700&family=Noto+Sans+KR:wght@300;400;500;700&display=swap" rel="stylesheet">
    <style>
      :root {{
        --bg: #0b0f14;
        --bg-2: #121821;
        --card: rgba(255, 255, 255, 0.06);
        --ink: #f5f7fb;
        --muted: rgba(245, 247, 251, 0.65);
        --accent: #4ee0b5;
        --accent-2: #6bd3ff;
        --edge: rgba(255, 255, 255, 0.15);
        --glow: rgba(78, 224, 181, 0.25);
      }}
      :root[data-theme="sky"] {{
        --bg: #0b1220;
        --bg-2: #0f1b2e;
        --card: rgba(255, 255, 255, 0.06);
        --ink: #f4f7ff;
        --muted: rgba(244, 247, 255, 0.62);
        --accent: #64b5ff;
        --accent-2: #8fd1ff;
        --edge: rgba(255, 255, 255, 0.18);
        --glow: rgba(100, 181, 255, 0.28);
      }}
      :root[data-theme="crimson"] {{
        --bg: #120a0d;
        --bg-2: #1c0f16;
        --card: rgba(255, 255, 255, 0.06);
        --ink: #fff5f7;
        --muted: rgba(255, 245, 247, 0.62);
        --accent: #ff6b81;
        --accent-2: #ff9aa9;
        --edge: rgba(255, 255, 255, 0.15);
        --glow: rgba(255, 107, 129, 0.25);
      }}
      * {{ box-sizing: border-box; }}
      body {{
        margin: 0;
        font-family: "Noto Sans KR", "Space Grotesk", sans-serif;
        color: var(--ink);
        background: radial-gradient(circle at 20% 20%, var(--glow), transparent 42%),
                    radial-gradient(circle at 80% 0%, rgba(107, 211, 255, 0.2), transparent 36%),
                    linear-gradient(160deg, #0a0d12 10%, #0f1622 60%, #0b0f14 100%);
        min-height: 100vh;
      }}
      .wrap {{
        max-width: 1200px;
        margin: 0 auto;
        padding: 48px 28px 120px;
      }}
      header.hero {{
        position: relative;
        border: 1px solid var(--edge);
        border-radius: 28px;
        padding: 48px;
        background: linear-gradient(140deg, rgba(255,255,255,0.05), rgba(255,255,255,0.02));
        box-shadow: 0 40px 120px rgba(0,0,0,0.4);
        overflow: hidden;
      }}
      header.hero::after {{
        content: "";
        position: absolute;
        inset: -40% -20%;
        background: radial-gradient(circle, rgba(78, 224, 181, 0.12), transparent 60%);
        opacity: 0.8;
        pointer-events: none;
      }}
      .nav {{
        display: flex;
        justify-content: space-between;
        align-items: center;
        font-family: "Space Grotesk", sans-serif;
        letter-spacing: 0.08em;
        text-transform: uppercase;
        font-size: 12px;
        color: var(--muted);
      }}
      .nav-actions {{
        display: inline-flex;
        align-items: center;
        gap: 12px;
      }}
      #theme-select {{
        background: transparent;
        color: var(--muted);
        border: 1px solid var(--edge);
        border-radius: 999px;
        padding: 6px 12px;
        font-size: 11px;
        font-family: "Space Grotesk", sans-serif;
        letter-spacing: 0.08em;
        text-transform: uppercase;
        cursor: pointer;
      }}
      #theme-select option {{
        color: #0b0f14;
      }}
      .nav .brand {{
        display: inline-flex;
        align-items: center;
        gap: 10px;
      }}
      .pulse {{
        width: 10px;
        height: 10px;
        border-radius: 50%;
        background: var(--accent);
        box-shadow: 0 0 12px var(--glow);
      }}
      .hero-grid {{
        display: grid;
        gap: 32px;
        grid-template-columns: repeat(auto-fit, minmax(240px, 1fr));
        margin-top: 36px;
      }}
      .hero h1 {{
        font-family: "Fraunces", serif;
        font-weight: 700;
        font-size: clamp(32px, 4.8vw, 56px);
        margin: 0 0 14px;
      }}
      .hero p {{
        margin: 0;
        font-size: 16px;
        color: var(--muted);
        line-height: 1.6;
      }}
      .cta {{
        display: flex;
        gap: 12px;
        margin-top: 24px;
        flex-wrap: wrap;
      }}
      .btn {{
        background: var(--accent);
        color: #071016;
        font-weight: 600;
        padding: 12px 18px;
        border-radius: 999px;
        text-decoration: none;
        transition: transform 0.2s ease, box-shadow 0.2s ease;
      }}
      .btn.secondary {{
        background: transparent;
        color: var(--ink);
        border: 1px solid var(--edge);
      }}
      .btn:hover {{
        transform: translateY(-2px);
        box-shadow: 0 16px 32px rgba(78, 224, 181, 0.25);
      }}
      .stats {{
        display: flex;
        gap: 20px;
        flex-wrap: wrap;
        margin-top: 22px;
      }}
      .stat {{
        padding: 14px 18px;
        border-radius: 14px;
        border: 1px solid var(--edge);
        background: rgba(0, 0, 0, 0.25);
        min-width: 140px;
      }}
      .stat span {{
        display: block;
        font-family: "Space Grotesk", sans-serif;
        font-weight: 600;
        font-size: 20px;
      }}
      .section {{
        margin-top: 52px;
      }}
      .section h2 {{
        font-family: "Space Grotesk", sans-serif;
        font-weight: 600;
        font-size: 22px;
        margin: 0 0 10px;
      }}
      .section p {{
        margin: 0 0 24px;
        color: var(--muted);
      }}
      .filter-bar {{
        display: flex;
        flex-wrap: wrap;
        gap: 12px;
        margin-bottom: 18px;
      }}
      .filter-bar input,
      .filter-bar select {{
        background: rgba(0, 0, 0, 0.28);
        color: var(--ink);
        border: 1px solid var(--edge);
        border-radius: 12px;
        padding: 8px 12px;
        font-size: 12px;
        font-family: "Space Grotesk", "Noto Sans KR", sans-serif;
      }}
      .filter-bar select option {{
        color: #0b0f14;
      }}
      .tabs {{
        margin-top: 18px;
        border: 1px solid var(--edge);
        border-radius: 18px;
        padding: 18px;
        background: rgba(0, 0, 0, 0.2);
      }}
      .tab-buttons {{
        display: flex;
        gap: 8px;
        flex-wrap: wrap;
        margin-bottom: 12px;
      }}
      .tab-button {{
        border: 1px solid var(--edge);
        background: transparent;
        color: var(--muted);
        padding: 6px 12px;
        border-radius: 999px;
        font-size: 12px;
        cursor: pointer;
        font-family: "Space Grotesk", "Noto Sans KR", sans-serif;
      }}
      .tab-button.active {{
        background: var(--accent);
        color: #071016;
        border-color: transparent;
      }}
      .tab-panel {{
        display: none;
      }}
      .tab-panel.active {{
        display: block;
      }}
      .chip-list {{
        display: flex;
        flex-wrap: wrap;
        gap: 8px;
      }}
      .chip {{
        border: 1px solid var(--edge);
        background: transparent;
        color: var(--muted);
        border-radius: 999px;
        padding: 6px 12px;
        font-size: 12px;
        cursor: pointer;
      }}
      .chip strong {{
        color: var(--ink);
        font-weight: 600;
        margin-left: 6px;
      }}
      .insights {{
        display: grid;
        gap: 12px;
        grid-template-columns: repeat(auto-fit, minmax(180px, 1fr));
        margin-top: 14px;
      }}
      .insight-card {{
        border: 1px solid var(--edge);
        border-radius: 14px;
        padding: 14px;
        background: rgba(0, 0, 0, 0.22);
      }}
      .insight-card h4 {{
        margin: 0 0 8px;
        font-size: 12px;
        font-family: "Space Grotesk", sans-serif;
        letter-spacing: 0.08em;
        text-transform: uppercase;
        color: var(--muted);
      }}
      .insight-item {{
        font-size: 13px;
        color: var(--ink);
        display: flex;
        justify-content: space-between;
        margin-bottom: 6px;
      }}
      .word-cloud {{
        margin-top: 18px;
        padding: 18px;
        border-radius: 18px;
        border: 1px solid var(--edge);
        background: rgba(0, 0, 0, 0.24);
        position: relative;
        min-height: 220px;
        overflow: hidden;
      }}
      .word-cloud .word {{
        font-family: "Space Grotesk", "Noto Sans KR", sans-serif;
        font-weight: 600;
        letter-spacing: 0.02em;
        position: absolute;
        white-space: nowrap;
        padding: 4px 10px;
        border-radius: 999px;
        border: 1px solid rgba(255,255,255,0.15);
        background: linear-gradient(120deg, rgba(255,255,255,0.12), rgba(255,255,255,0.04));
        transition: transform 0.25s ease, color 0.25s ease, border-color 0.25s ease, filter 0.25s ease;
        font-size: calc(12px + var(--weight, 0.4) * 20px);
        background-image: var(--cloud-gradient, linear-gradient(120deg, #6bd3ff, #4ee0b5));
        color: transparent;
        -webkit-background-clip: text;
        background-clip: text;
        text-shadow: 0 8px 18px rgba(0, 0, 0, 0.35);
        opacity: var(--cloud-opacity, 0.75);
        animation: cloudFloat var(--cloud-duration, 6s) ease-in-out infinite;
        animation-delay: var(--cloud-delay, 0s);
        transform: translate3d(0, 0, 0) rotate(var(--cloud-tilt, 0deg));
      }}
      .word-cloud .word:hover {{
        transform: translate3d(0, -6px, 0) rotate(var(--cloud-tilt, 0deg));
        filter: drop-shadow(0 12px 18px rgba(78, 224, 181, 0.3));
        border-color: var(--accent);
      }}
      @keyframes cloudFloat {{
        0% {{ transform: translate3d(0, 0, 0) rotate(var(--cloud-tilt, 0deg)); }}
        50% {{ transform: translate3d(0, -10px, 0) rotate(var(--cloud-tilt, 0deg)); }}
        100% {{ transform: translate3d(0, 0, 0) rotate(var(--cloud-tilt, 0deg)); }}
      }}
      .grid {{
        display: grid;
        gap: 18px;
        grid-template-columns: repeat(auto-fit, minmax(260px, 1fr));
      }}
      .card {{
        padding: 20px;
        border-radius: 18px;
        border: 1px solid var(--edge);
        background: var(--card);
        backdrop-filter: blur(6px);
        display: flex;
        flex-direction: column;
        gap: 14px;
        animation: floatIn 0.6s ease both;
      }}
      .card h3 {{
        margin: 0;
        font-size: 18px;
        font-weight: 600;
      }}
      .card h3 a {{
        color: var(--accent-2);
        text-decoration: none;
      }}
      .card h3 a:visited {{
        color: var(--accent-2);
      }}
      .card h3 a:hover {{
        color: var(--accent);
      }}
      .card h3 a:focus-visible {{
        outline: 2px solid var(--accent-2);
        outline-offset: 2px;
        border-radius: 6px;
      }}
      .tags {{
        display: flex;
        flex-wrap: wrap;
        gap: 8px;
      }}
      .tag {{
        font-size: 11px;
        padding: 4px 10px;
        border-radius: 999px;
        border: 1px solid rgba(255, 255, 255, 0.18);
        color: var(--muted);
      }}
      .card .summary {{
        color: var(--muted);
        line-height: 1.5;
        font-size: 14px;
        min-height: 60px;
      }}
      .card .meta {{
        display: flex;
        justify-content: space-between;
        font-size: 12px;
        color: var(--muted);
      }}
      .links {{
        display: flex;
        gap: 12px;
        flex-wrap: wrap;
      }}
      .links a {{
        font-size: 12px;
        color: var(--accent-2);
        text-decoration: none;
      }}
      .load-more {{
        margin-top: 18px;
        display: flex;
        justify-content: center;
      }}
      .load-more button {{
        border: 1px solid var(--edge);
        background: transparent;
        color: var(--ink);
        font-weight: 600;
        padding: 10px 18px;
        border-radius: 999px;
        cursor: pointer;
      }}
      .load-more button:hover {{
        color: var(--accent);
        border-color: var(--accent);
      }}
      .banner {{
        position: fixed;
        left: 50%;
        bottom: 24px;
        transform: translateX(-50%);
        background: #0d131c;
        border: 1px solid var(--edge);
        border-radius: 16px;
        padding: 14px 20px;
        display: flex;
        align-items: center;
        gap: 16px;
        box-shadow: 0 18px 40px rgba(0,0,0,0.35);
        z-index: 50;
      }}
      .banner strong {{
        font-family: "Space Grotesk", sans-serif;
      }}
      .banner button {{
        border: none;
        background: var(--accent);
        color: #071016;
        font-weight: 600;
        padding: 8px 14px;
        border-radius: 999px;
        cursor: pointer;
      }}
      .empty {{
        border: 1px dashed var(--edge);
        border-radius: 18px;
        padding: 26px;
        color: var(--muted);
      }}
      .disclosure-footer {{
        margin-top: 40px;
        padding: 20px 22px;
        border: 1px solid var(--edge);
        border-radius: 16px;
        background: rgba(0, 0, 0, 0.24);
        color: var(--muted);
        font-size: 13px;
        line-height: 1.6;
      }}
      .disclosure-footer strong {{
        color: var(--ink);
        display: block;
        margin-bottom: 8px;
        font-family: "Space Grotesk", "Noto Sans KR", sans-serif;
        letter-spacing: 0.04em;
      }}
      .disclosure-footer ul {{
        margin: 0;
        padding-left: 18px;
      }}
      .disclosure-footer li {{
        margin-bottom: 6px;
      }}
      @keyframes floatIn {{
        from {{
          opacity: 0;
          transform: translateY(14px);
        }}
        to {{
          opacity: 1;
          transform: translateY(0);
        }}
      }}
      @media (max-width: 720px) {{
        header.hero {{ padding: 32px; }}
        .wrap {{ padding: 32px 20px 90px; }}
      }}
    </style>
  </head>
  <body>
    <script id="manifest-data" type="application/json">{manifest_json}</script>
    <div class="wrap">
      <header class="hero">
        <div class="nav">
          <div class="brand"><span class="pulse"></span> Federlicht Report Hub</div>
          <div class="nav-actions">
            <div id="last-updated"></div>
            <select id="theme-select" aria-label="Theme">
              <option value="">Default</option>
              <option value="sky">Sky</option>
              <option value="crimson">Crimson</option>
            </select>
          </div>
        </div>
        <div class="hero-grid">
          <div>
            <h1>Enlighten your Technology Insight.</h1>
            <p>Federlicht가 생성한 기술 리포트를 모아둔 허브입니다. 최신 실행 결과를 자동으로 받아오며, 공유 가능한 HTML 리포트를 바로 열람할 수 있습니다.</p>
            <div class="cta">
              <a class="btn" href="#latest">최신 리포트 보기</a>
              <a class="btn secondary" href="#archive">전체 목록</a>
            </div>
            <div class="stats">
              <div class="stat"><small>Reports</small><span id="stat-reports">0</span></div>
              <div class="stat"><small>Languages</small><span id="stat-langs">0</span></div>
              <div class="stat"><small>Templates</small><span id="stat-templates">0</span></div>
            </div>
          </div>
          <div class="card" id="latest-card">
            <div class="tags" id="latest-tags"></div>
            <h3><a id="latest-title-link" href="#">보고서를 기다리는 중</a></h3>
            <p class="summary" id="latest-summary">manifest.json에서 최신 리포트를 불러옵니다.</p>
            <div class="meta" id="latest-meta"></div>
            <div class="links" id="latest-links"></div>
          </div>
        </div>
      </header>

      <section class="section" id="latest">
        <h2>Latest Reports</h2>
        <p>최근 생성된 리포트부터 순서대로 정렬됩니다. 새 리포트가 감지되면 배너로 알려드립니다.</p>
        <div class="grid" id="report-grid"></div>
        <div class="load-more"><button id="report-more">더 보기</button></div>
      </section>

      <section class="section" id="explore">
        <h2>Explore</h2>
        <p>태그/템플릿/작성자 기준으로 빠르게 탐색합니다.</p>
        <div class="tabs">
          <div class="tab-buttons">
            <button class="tab-button active" data-tab="topics">Topics</button>
            <button class="tab-button" data-tab="templates">Templates</button>
            <button class="tab-button" data-tab="authors">Authors</button>
          </div>
          <div class="tab-panel active" id="tab-topics"></div>
          <div class="tab-panel" id="tab-templates"></div>
          <div class="tab-panel" id="tab-authors"></div>
        </div>
        <div class="insights" id="trend-insights"></div>
        <div class="word-cloud" id="word-cloud"></div>
      </section>

      <section class="section" id="archive">
        <h2>Archive</h2>
        <p>모든 리포트를 한 번에 탐색하거나, 템플릿/언어/형식을 기준으로 비교할 수 있습니다.</p>
        <div class="filter-bar">
          <input id="search-input" type="search" placeholder="Search title, summary, author" />
          <select id="filter-template">
            <option value="">All templates</option>
          </select>
          <select id="filter-lang">
            <option value="">All languages</option>
          </select>
          <select id="filter-tag">
            <option value="">All tags</option>
          </select>
          <select id="filter-author">
            <option value="">All authors</option>
          </select>
        </div>
        <div class="grid" id="archive-grid"></div>
        <div class="load-more"><button id="archive-more">더 보기</button></div>
      </section>
      <footer class="disclosure-footer">
        <strong>AI Transparency and Source Notice</strong>
        <ul>
          <li>이 허브의 게시물은 Federlicht 기반 AI 보조 생성물이며, 최종 책임은 사용자/조직에 있습니다.</li>
          <li>외부 출처의 저작권/라이선스는 원 저작권자에게 있으며, 재배포 전 원문 정책 확인이 필요합니다.</li>
          <li>고위험 의사결정(법률·의료·재무·규제)에는 원문 대조와 추가 검증 절차를 수행하세요.</li>
          <li>EU AI Act 투명성 취지에 따라 AI 생성/보조 작성 콘텐츠임을 명시합니다.</li>
        </ul>
      </footer>
    </div>

    <div class="banner" id="update-banner" style="display:none;">
      <div>
        <strong>새 보고서 있음</strong>
        <div id="update-detail" style="font-size:12px;color:var(--muted);"></div>
      </div>
      <button id="apply-update">새로고침</button>
    </div>

    <script>
      const bootstrap = document.getElementById('manifest-data');
      let currentManifest = bootstrap ? JSON.parse(bootstrap.textContent || '{{}}') : {{ items: [] }};
      let pendingManifest = null;
      const REFRESH_MS = {refresh_ms};

      const escapeHtml = (value) => String(value || '')
        .replace(/&/g, '&amp;')
        .replace(/</g, '&lt;')
        .replace(/>/g, '&gt;')
        .replace(/"/g, '&quot;')
        .replace(/'/g, '&#039;');

      const countBy = (items, getter) => {{
        const counts = new Map();
        items.forEach((item) => {{
          const value = getter(item);
          const values = Array.isArray(value) ? value : [value];
          values.forEach((raw) => {{
            const key = (raw || '').toString().trim();
            if (!key || key === 'unknown') return;
            counts.set(key, (counts.get(key) || 0) + 1);
          }});
        }});
        return Array.from(counts.entries()).sort((a, b) => b[1] - a[1]);
      }};

      const sortItems = (items) => items.slice().sort((a, b) => {{
        const ta = Date.parse(a.timestamp || a.date || 0) || 0;
        const tb = Date.parse(b.timestamp || b.date || 0) || 0;
        return tb - ta;
      }});

      const buildLinks = (paths = {{}}) => {{
        const entries = [];
        if (paths.report) entries.push(['Report', paths.report]);
        if (paths.overview) entries.push(['Overview', paths.overview]);
        if (paths.workflow) entries.push(['Workflow', paths.workflow]);
        return entries.map(([label, href]) => `<a href="${{escapeHtml(href)}}">${{label}}</a>`).join('');
      }};

        const renderLatest = (item) => {{
        if (!item) return;
        const latestLink = document.getElementById('latest-title-link');
        if (latestLink) {{
          latestLink.textContent = item.title || 'Untitled report';
          latestLink.href = (item.paths && item.paths.report) ? item.paths.report : '#';
        }}
        document.getElementById('latest-summary').textContent = item.summary || '요약 정보가 없습니다.';
        document.getElementById('latest-meta').textContent = `${{item.date || ''}} · ${{item.author || 'Unknown'}}`;
        const tags = [item.lang, item.template, item.model, item.format]
          .filter(tag => tag && tag !== 'unknown')
          .map(tag => `<span class="tag">${{escapeHtml(tag)}}</span>`).join('');
        document.getElementById('latest-tags').innerHTML = tags;
        document.getElementById('latest-links').innerHTML = buildLinks(item.paths);
      }};

      const buildCardHtml = (item, idx) => {{
        const delay = (idx % 6) * 0.05;
        const tags = [item.lang, item.template, item.model, item.format]
          .filter(tag => tag && tag !== 'unknown')
          .map(tag => `<span class="tag">${{escapeHtml(tag)}}</span>`).join('');
        const summary = escapeHtml(item.summary || '');
        const meta = `${{escapeHtml(item.date || '')}} · ${{escapeHtml(item.author || 'Unknown')}}`;
        const reportHref = (item.paths && item.paths.report) ? item.paths.report : '#';
        return `
          <article class="card" style="animation-delay:${{delay}}s">
            <div class="tags">${{tags}}</div>
            <h3><a href="${{escapeHtml(reportHref)}}">${{escapeHtml(item.title || 'Untitled')}}</a></h3>
            <p class="summary">${{summary || '요약 정보가 없습니다.'}}</p>
            <div class="meta">${{meta}}</div>
            <div class="links">${{buildLinks(item.paths)}}</div>
          </article>
        `;
      }};

      const createPager = (targetId, buttonId, pageSize) => {{
        let items = [];
        let index = 0;
        const target = document.getElementById(targetId);
        const button = document.getElementById(buttonId);
        const renderNext = () => {{
          if (!target) return;
          if (!items.length) {{
            target.innerHTML = '<div class="empty">아직 등록된 리포트가 없습니다.</div>';
            if (button) button.style.display = 'none';
            return;
          }}
          const slice = items.slice(index, index + pageSize);
          slice.forEach((item, idx) => {{
            target.insertAdjacentHTML('beforeend', buildCardHtml(item, index + idx));
          }});
          index += slice.length;
          if (button) {{
            button.style.display = index >= items.length ? 'none' : 'inline-flex';
          }}
        }};
        if (button) {{
          button.addEventListener('click', renderNext);
        }}
        const reset = (nextItems) => {{
          items = nextItems || [];
          index = 0;
          if (target) target.innerHTML = '';
          renderNext();
        }};
        return {{ reset }};
      }};

      const renderStats = (items) => {{
        const langCount = new Set(items.map(item => item.lang).filter(Boolean)).size;
        const templateCount = new Set(items.map(item => item.template).filter(Boolean)).size;
        document.getElementById('stat-reports').textContent = items.length;
        document.getElementById('stat-langs').textContent = langCount;
        document.getElementById('stat-templates').textContent = templateCount;
      }};

      const withinDays = (items, days) => {{
        const cutoff = Date.now() - days * 24 * 60 * 60 * 1000;
        return items.filter(item => {{
          const stamp = item.timestamp || item.date;
          if (!stamp) return false;
          const time = Date.parse(stamp);
          return !Number.isNaN(time) && time >= cutoff;
        }});
      }};

      const buildKeywordStats = (items) => {{
        const counts = new Map();
        items.forEach(item => {{
          (item.keywords || []).forEach((entry) => {{
            if (!entry) return;
            let term = '';
            let count = 1;
            if (Array.isArray(entry)) {{
              term = String(entry[0] || '').trim();
              count = Number(entry[1] || 1);
            }} else {{
              term = String(entry || '').trim();
            }}
            if (!term) return;
            counts.set(term, (counts.get(term) || 0) + (Number.isFinite(count) ? count : 1));
          }});
        }});
        return Array.from(counts.entries()).sort((a, b) => b[1] - a[1]);
      }};

      const layoutWordCloud = (container) => {{
        if (!container) return;
        const words = Array.from(container.querySelectorAll('.word'));
        if (!words.length) return;
        const width = container.clientWidth;
        const height = container.clientHeight;
        const placed = [];
        const center = {{ x: width / 2, y: height / 2 }};
        const overlaps = (rect) => {{
          return placed.some((p) =>
            rect.x < p.x + p.w && rect.x + rect.w > p.x &&
            rect.y < p.y + p.h && rect.y + rect.h > p.y
          );
        }};
        words.forEach((word) => {{
          const w = word.offsetWidth;
          const h = word.offsetHeight;
          let angle = Math.random() * Math.PI * 2;
          let radius = 0;
          let found = null;
          for (let i = 0; i < 220; i++) {{
            const x = center.x + Math.cos(angle) * radius - w / 2;
            const y = center.y + Math.sin(angle) * radius - h / 2;
            const rect = {{ x, y, w, h }};
            if (x >= 0 && y >= 0 && x + w <= width && y + h <= height && !overlaps(rect)) {{
              found = rect;
              break;
            }}
            angle += 0.35;
            radius += 2.2;
          }}
          if (!found) {{
            const x = Math.max(0, Math.random() * Math.max(1, width - w));
            const y = Math.max(0, Math.random() * Math.max(1, height - h));
            found = {{ x, y, w, h }};
          }}
          placed.push(found);
          word.style.left = `${{found.x.toFixed(1)}}px`;
          word.style.top = `${{found.y.toFixed(1)}}px`;
        }});
      }};

      const latestPager = createPager('report-grid', 'report-more', 6);
      const archivePager = createPager('archive-grid', 'archive-more', 12);

      const populateFilters = (items) => {{
        const templateSelect = document.getElementById('filter-template');
        const langSelect = document.getElementById('filter-lang');
        const tagSelect = document.getElementById('filter-tag');
        const authorSelect = document.getElementById('filter-author');
        if (!templateSelect || !langSelect || !tagSelect || !authorSelect) return;
        const templates = Array.from(new Set(items.map(item => item.template).filter(Boolean))).sort();
        const langs = Array.from(new Set(items.map(item => item.lang).filter(Boolean))).sort();
        const tags = Array.from(new Set(items.flatMap(item => item.tags || []))).sort();
        const authors = Array.from(new Set(items.map(item => item.author).filter(Boolean))).sort();
        const fill = (select, values, label) => {{
          const current = select.value;
          select.innerHTML = `<option value="">${{label}}</option>` +
            values.map(value => `<option value="${{escapeHtml(value)}}">${{escapeHtml(value)}}</option>`).join('');
          select.value = current;
        }};
        fill(templateSelect, templates, 'All templates');
        fill(langSelect, langs, 'All languages');
        fill(tagSelect, tags, 'All tags');
        fill(authorSelect, authors, 'All authors');
      }};

      const applyFilters = (items) => {{
        const query = (document.getElementById('search-input')?.value || '').toLowerCase().trim();
        const template = document.getElementById('filter-template')?.value || '';
        const lang = document.getElementById('filter-lang')?.value || '';
        const tag = document.getElementById('filter-tag')?.value || '';
        const author = document.getElementById('filter-author')?.value || '';
        return items.filter(item => {{
          if (template && item.template !== template) return false;
          if (lang && item.lang !== lang) return false;
          if (tag && !(item.tags || []).includes(tag)) return false;
          if (author && item.author !== author) return false;
          if (!query) return true;
          const haystack = `${{item.title || ''}} ${{item.summary || ''}} ${{item.author || ''}}`.toLowerCase();
          return haystack.includes(query);
        }});
      }};

      const renderTabs = (items) => {{
        const tabTopics = document.getElementById('tab-topics');
        const tabTemplates = document.getElementById('tab-templates');
        const tabAuthors = document.getElementById('tab-authors');
        if (!tabTopics || !tabTemplates || !tabAuthors) return;
        const topTags = countBy(items, item => item.tags || []).slice(0, 20);
        const topTemplates = countBy(items, item => item.template).slice(0, 20);
        const topAuthors = countBy(items, item => item.author).slice(0, 20);
        const chipHtml = (list, type) => {{
          if (!list.length) return '<div class="empty">데이터가 없습니다.</div>';
          return `<div class="chip-list">` + list.map(([value, count]) =>
            `<button class="chip" data-type="${{type}}" data-value="${{escapeHtml(value)}}">${{escapeHtml(value)}} <strong>${{count}}</strong></button>`
          ).join('') + `</div>`;
        }};
        tabTopics.innerHTML = chipHtml(topTags, 'tag');
        tabTemplates.innerHTML = chipHtml(topTemplates, 'template');
        tabAuthors.innerHTML = chipHtml(topAuthors, 'author');
      }};

      const renderTrends = (items) => {{
        const target = document.getElementById('trend-insights');
        if (!target) return;
        const scoped = withinDays(items, 30);
        const pool = scoped.length ? scoped : items;
        const topTags = countBy(pool, item => item.tags || []).slice(0, 3);
        const topTemplates = countBy(pool, item => item.template).slice(0, 3);
        const topAuthors = countBy(pool, item => item.author).slice(0, 3);
        const block = (title, list) => {{
          const rows = list.length
            ? list.map(([value, count]) => `<div class="insight-item"><span>${{escapeHtml(value)}}</span><strong>${{count}}</strong></div>`).join('')
            : '<div class="insight-item"><span>데이터 없음</span><strong>-</strong></div>';
          return `<div class="insight-card"><h4>${{title}}</h4>${{rows}}</div>`;
        }};
        target.innerHTML = block('Top Tags', topTags) + block('Top Templates', topTemplates) + block('Top Authors', topAuthors);
      }};

      const renderWordCloud = (items) => {{
        const target = document.getElementById('word-cloud');
        if (!target) return;
        const scoped = withinDays(items, 30);
        const pool = scoped.length ? scoped : items;
        const stats = buildKeywordStats(pool).slice(0, 40);
        if (!stats.length) {{
          target.innerHTML = '<div class="empty">최근 30일 키워드가 없습니다.</div>';
          return;
        }}
        const max = stats[0][1] || 1;
        const gradients = [
          'linear-gradient(120deg, #6bd3ff, #4ee0b5)',
          'linear-gradient(120deg, #ff8c96, #ffd36b)',
          'linear-gradient(120deg, #c6b7ff, #7df0ff)',
          'linear-gradient(120deg, #4ee0b5, #8fd1ff)',
          'linear-gradient(120deg, #ff9aa9, #ff6b81)',
        ];
        target.innerHTML = stats.map(([term, count], idx) => {{
          const ratio = count / max;
          const weight = Math.max(0.25, Math.min(1, Math.pow(ratio, 0.6)));
          const opacity = Math.max(0.45, Math.min(1, 0.35 + Math.pow(ratio, 0.5) * 0.65));
          const gradient = gradients[idx % gradients.length];
          const delay = (Math.random() * 2).toFixed(2);
          const duration = (5 + Math.random() * 4).toFixed(2);
          const tilt = ((Math.random() * 6) - 3).toFixed(2);
          return `<span class="word" style="--weight:${{weight.toFixed(2)}};--cloud-opacity:${{opacity.toFixed(2)}};--cloud-gradient:${{gradient}};--cloud-delay:${{delay}}s;--cloud-duration:${{duration}}s;--cloud-tilt:${{tilt}}deg;">${{escapeHtml(term)}}</span>`;
        }}).join('');
        requestAnimationFrame(() => layoutWordCloud(target));
      }};

      const setFilterValue = (type, value) => {{
        if (!value) return;
        if (type === 'tag') {{
          const tagSelect = document.getElementById('filter-tag');
          if (tagSelect) tagSelect.value = value;
        }} else if (type === 'template') {{
          const templateSelect = document.getElementById('filter-template');
          if (templateSelect) templateSelect.value = value;
        }} else if (type === 'author') {{
          const authorSelect = document.getElementById('filter-author');
          if (authorSelect) authorSelect.value = value;
        }}
        const items = sortItems(currentManifest.items || []);
        const filtered = applyFilters(items);
        archivePager.reset(filtered);
        renderTrends(filtered);
        renderWordCloud(filtered);
      }};

      const renderAll = (manifest) => {{
        const items = sortItems(manifest.items || []);
        renderLatest(items[0]);
        latestPager.reset(items);
        populateFilters(items);
        renderTabs(items);
        renderTrends(items);
        renderWordCloud(items);
        const filtered = applyFilters(items);
        archivePager.reset(filtered);
        renderStats(items);
        const updated = manifest.generated_at ? new Date(manifest.generated_at).toLocaleString() : '';
        document.getElementById('last-updated').textContent = updated ? `Updated ${{updated}}` : '';
      }};

      const showUpdateBanner = (manifest) => {{
        const banner = document.getElementById('update-banner');
        const detail = document.getElementById('update-detail');
        const items = sortItems(manifest.items || []);
        const latest = items[0];
        if (!latest) return;
        detail.textContent = `${{latest.title || 'Untitled'}} · ${{latest.author || 'Unknown'}}`;
        banner.style.display = 'flex';
      }};

      const applyUpdate = () => {{
        if (!pendingManifest) return;
        currentManifest = pendingManifest;
        pendingManifest = null;
        renderAll(currentManifest);
        document.getElementById('update-banner').style.display = 'none';
        try {{
          localStorage.setItem('federlicht.manifest.revision', currentManifest.revision || '');
        }} catch (err) {{}}
      }};

      document.getElementById('apply-update').addEventListener('click', applyUpdate);

      const pollManifest = () => {{
        fetch(`manifest.json?ts=${{Date.now()}}`, {{ cache: 'no-store' }})
          .then((resp) => resp.json())
          .then((data) => {{
            if (!data || !data.revision) return;
            if (currentManifest.revision && data.revision === currentManifest.revision) return;
            pendingManifest = data;
            showUpdateBanner(data);
          }})
          .catch(() => {{}});
      }};

      const filterInputs = ['search-input', 'filter-template', 'filter-lang', 'filter-tag', 'filter-author'];
      filterInputs.forEach((id) => {{
        const el = document.getElementById(id);
        if (!el) return;
        el.addEventListener('input', () => {{
          const items = sortItems(currentManifest.items || []);
          const filtered = applyFilters(items);
          archivePager.reset(filtered);
          renderTrends(filtered);
          renderWordCloud(filtered);
        }});
        el.addEventListener('change', () => {{
          const items = sortItems(currentManifest.items || []);
          const filtered = applyFilters(items);
          archivePager.reset(filtered);
          renderTrends(filtered);
          renderWordCloud(filtered);
        }});
      }});

      window.addEventListener('resize', () => {{
        const items = sortItems(currentManifest.items || []);
        const filtered = applyFilters(items);
        renderWordCloud(filtered);
      }});

      document.querySelectorAll('.tab-button').forEach((button) => {{
        button.addEventListener('click', () => {{
          document.querySelectorAll('.tab-button').forEach((btn) => btn.classList.remove('active'));
          document.querySelectorAll('.tab-panel').forEach((panel) => panel.classList.remove('active'));
          button.classList.add('active');
          const tabId = button.dataset.tab;
          const panel = document.getElementById(`tab-${{tabId}}`);
          if (panel) panel.classList.add('active');
        }});
      }});

      document.addEventListener('click', (event) => {{
        const target = event.target;
        if (!(target instanceof HTMLElement)) return;
        if (!target.classList.contains('chip')) return;
        const type = target.dataset.type;
        const value = target.dataset.value;
        if (!type || !value) return;
        setFilterValue(type, value);
        document.getElementById('archive')?.scrollIntoView({{ behavior: 'smooth' }});
      }});

      document.addEventListener('click', (event) => {{
        const target = event.target;
        if (!(target instanceof HTMLElement)) return;
        if (!target.classList.contains('word')) return;
        const term = target.textContent || '';
        if (!term) return;
        const tagSelect = document.getElementById('filter-tag');
        if (tagSelect) {{
          tagSelect.value = '';
        }}
        const searchInput = document.getElementById('search-input');
        if (searchInput) {{
          searchInput.value = term;
        }}
        const items = sortItems(currentManifest.items || []);
        const filtered = applyFilters(items);
        archivePager.reset(filtered);
        renderTrends(filtered);
        renderWordCloud(filtered);
        document.getElementById('archive')?.scrollIntoView({{ behavior: 'smooth' }});
      }});

      renderAll(currentManifest);
      try {{
        localStorage.setItem('federlicht.manifest.revision', currentManifest.revision || '');
      }} catch (err) {{}}
      const params = new URLSearchParams(window.location.search);
      const themeParam = params.get('theme');
      const storedTheme = localStorage.getItem('federlicht.theme');
      const theme = themeParam || storedTheme;
      if (theme) {{
        document.documentElement.dataset.theme = theme;
        localStorage.setItem('federlicht.theme', theme);
      }}
      const themeSelect = document.getElementById('theme-select');
      if (themeSelect) {{
        themeSelect.value = theme || '';
        themeSelect.addEventListener('change', (event) => {{
          const selected = event.target.value;
          if (selected) {{
            document.documentElement.dataset.theme = selected;
            localStorage.setItem('federlicht.theme', selected);
          }} else {{
            document.documentElement.removeAttribute('data-theme');
            localStorage.removeItem('federlicht.theme');
          }}
        }});
      }}
      setInterval(pollManifest, REFRESH_MS);
    </script>
  </body>
</html>
"""


def write_site_index(site_root: Path, manifest: dict, refresh_minutes: int = 10) -> Path:
    site_root.mkdir(parents=True, exist_ok=True)
    index_path = site_root / "index.html"
    index_path.write_text(build_site_index_html(manifest, refresh_minutes), encoding="utf-8")
    return index_path


def write_site_manifest(site_root: Path, entries: list[dict]) -> dict:
    site_root.mkdir(parents=True, exist_ok=True)
    manifest_path = site_root / "manifest.json"
    entries = list(entries)
    entries.sort(key=lambda item: str(item.get("timestamp") or item.get("date") or ""), reverse=True)
    now = dt.datetime.now().isoformat()
    manifest = {
        "revision": now,
        "generated_at": now,
        "items": entries,
    }
    manifest_path.write_text(json.dumps(manifest, ensure_ascii=False, indent=2), encoding="utf-8")
    return manifest


def find_baseline_report(run_dir: Path) -> Optional[Path]:
    candidate = run_dir / "report.md"
    return candidate if candidate.exists() else None


def parse_tags(value: Optional[str]) -> list[str]:
    if not value:
        return []
    raw = [part.strip() for part in value.split(",")]
    return [part for part in raw if part]


def build_auto_tags(
    prompt: Optional[str],
    title: Optional[str],
    summary: Optional[str] = None,
    max_tags: int = 5,
) -> list[str]:
    text = " ".join(part for part in [title, prompt, summary] if part).strip()
    if not text:
        return []
    english_stop = {
        "report",
        "analysis",
        "review",
        "survey",
        "summary",
        "overview",
        "study",
        "based",
        "using",
        "about",
        "with",
        "from",
        "this",
        "that",
        "which",
        "their",
        "your",
        "into",
        "between",
        "within",
        "without",
        "recent",
        "latest",
        "federlicht",
    }
    korean_stop = {
        "보고서",
        "리포트",
        "요약",
        "분석",
        "동향",
        "연구",
        "기반",
        "사용",
        "작성",
        "설명",
        "프롬프트",
        "최근",
    }
    tokens = re.findall(r"[A-Za-z][A-Za-z0-9_-]{2,}", text)
    tokens.extend(re.findall(r"[가-힣]{2,}", text))
    if not tokens:
        return []
    counts: dict[str, dict[str, object]] = {}
    for idx, token in enumerate(tokens):
        if re.fullmatch(r"[A-Za-z0-9_-]+", token):
            key = token.lower()
            if key in english_stop:
                continue
            display = token if token.isupper() and 2 <= len(token) <= 6 else key
        else:
            key = token
            if key in korean_stop:
                continue
            display = token
        if key not in counts:
            counts[key] = {"count": 0, "index": idx, "display": display}
        entry = counts[key]
        entry["count"] = int(entry["count"]) + 1
        if isinstance(display, str) and display.isupper() and display != entry["display"]:
            entry["display"] = display
    ranked = sorted(
        counts.values(),
        key=lambda item: (-int(item["count"]), int(item["index"])),
    )
    tags: list[str] = []
    for item in ranked:
        display = str(item["display"]).strip()
        if display and display not in tags:
            tags.append(display)
        if len(tags) >= max_tags:
            break
    return tags


def extract_agent_text(result: object) -> str:
    if isinstance(result, dict):
        messages = result.get("messages")
        if messages:
            last = messages[-1]
            content = getattr(last, "content", None)
            if content is None and isinstance(last, dict):
                content = last.get("content")
            if content is not None:
                return str(content)
    return str(result)


def normalize_lang(value: str) -> str:
    text = value.strip().lower()
    if text in {"ko", "kor", "korean", "kr"}:
        return "Korean"
    if text in {"en", "eng", "english"}:
        return "English"
    return value.strip()


def is_korean_language(value: str) -> bool:
    return normalize_lang(value) == "Korean"


def load_report_prompt(prompt_text: Optional[str], prompt_file: Optional[str]) -> Optional[str]:
    parts: list[str] = []
    seen: set[str] = set()

    def _add_part(text: str) -> None:
        normalized = re.sub(r"\s+", " ", text).strip()
        if not normalized:
            return
        if normalized in seen:
            return
        seen.add(normalized)
        parts.append(text)

    if prompt_file:
        path = Path(prompt_file)
        content = path.read_text(encoding="utf-8", errors="replace").strip()
        if content:
            _add_part(content)
    if prompt_text:
        text = prompt_text.strip()
        if text:
            _add_part(text)
    if not parts:
        return None
    return "\n\n".join(parts)


def load_user_answers(answer_text: Optional[str], answer_file: Optional[str]) -> Optional[str]:
    parts: list[str] = []
    if answer_file:
        path = Path(answer_file)
        content = path.read_text(encoding="utf-8", errors="replace").strip()
        if content:
            parts.append(content)
    if answer_text:
        text = answer_text.strip()
        if text:
            parts.append(text)
    if not parts:
        return None
    return "\n\n".join(parts)


def read_user_answers() -> str:
    print("\n[Clarification Answers]\nEnter your answers. Submit an empty line to finish.\n")
    lines: list[str] = []
    while True:
        try:
            line = input()
        except EOFError:
            break
        if not line.strip():
            break
        lines.append(line)
    return "\n".join(lines).strip()


def truncate_text_middle(text: str, max_chars: int) -> str:
    if max_chars <= 0 or len(text) <= max_chars:
        return text
    head = text[: max_chars // 2]
    tail = text[-max_chars // 2 :]
    return f"{head}\n... [truncated] ...\n{tail}"


def parse_max_input_tokens(value: object) -> Optional[int]:
    if value is None:
        return None
    if isinstance(value, bool):
        return None
    if isinstance(value, int):
        return value if value > 0 else None
    if isinstance(value, str):
        text = value.strip()
        if not text:
            return None
        try:
            parsed = int(text)
        except ValueError:
            return None
        return parsed if parsed > 0 else None
    return None


def parse_temperature(value: object) -> Optional[float]:
    if value is None:
        return None
    if isinstance(value, bool):
        return None
    if isinstance(value, (int, float)):
        parsed = float(value)
    elif isinstance(value, str):
        text = value.strip()
        if not text:
            return None
        try:
            parsed = float(text)
        except ValueError:
            return None
    else:
        return None
    if parsed < 0.0:
        parsed = 0.0
    if parsed > 2.0:
        parsed = 2.0
    return round(parsed, 4)


def choose_format(output: Optional[str]) -> str:
    if output and output.lower().endswith((".html", ".htm")):
        return "html"
    if output and output.lower().endswith(".tex"):
        return "tex"
    return "md"


def escape_latex_heading(text: str) -> str:
    # Keep LaTeX math/commands intact; only escape characters that break headings.
    return text.replace("&", "\\&").replace("%", "\\%").replace("#", "\\#")


def build_report_skeleton(sections: list[str], output_format: str) -> str:
    if output_format == "tex":
        return "\n".join(f"\\section{{{escape_latex_heading(section)}}}" for section in sections)
    return "\n".join(f"## {section}" for section in sections)


_LATEX_ESCAPE_TABLE = {
    "\\": r"\textbackslash{}",
    "{": r"\{",
    "}": r"\}",
    "&": r"\&",
    "%": r"\%",
    "$": r"\$",
    "#": r"\#",
    "_": r"\_",
    "~": r"\textasciitilde{}",
    "^": r"\textasciicircum{}",
}


def latex_escape(text: str) -> str:
    return "".join(_LATEX_ESCAPE_TABLE.get(ch, ch) for ch in text)


def latex_link(target: str, label: str) -> str:
    return f"\\href{{{latex_escape(target)}}}{{{label}}}"


def format_byline(byline: str, output_format: str) -> str:
    if output_format == "tex":
        return f"\\noindent\\textit{{{latex_escape(byline)}}}"
    return byline


_TITLE_LINE_RE = re.compile(r"^(?:title|제목)\s*:\s*(.+)$", re.IGNORECASE)
_TITLE_PREFIX_RE = re.compile(r"^(?:report|보고서|리포트|title|제목)\s*[:\-]\s*", re.IGNORECASE)
_TITLE_REQUEST_SUFFIX_RE = re.compile(
    r"(해줘|해주세요|해 주세요|부탁해|부탁드립니다|알려줘|알려주세요|작성해줘|작성해주세요|정리해줘|정리해주세요|요약해줘|요약해주세요|분석해줘|분석해주세요)\s*$"
)
_TITLE_SECTION_HINTS = (
    "abstract",
    "executive summary",
    "summary",
    "개요",
    "요약",
    "초록",
    "서론",
)


def extract_prompt_title(report_prompt: Optional[str]) -> Optional[str]:
    if not report_prompt:
        return None
    for line in report_prompt.splitlines():
        cleaned = line.strip()
        if not cleaned:
            continue
        match = _TITLE_LINE_RE.match(cleaned)
        if match:
            return match.group(1).strip()
    for line in report_prompt.splitlines():
        cleaned = line.strip()
        if cleaned.startswith("#"):
            title = cleaned.lstrip("#").strip()
            if title:
                return title
    return None


def resolve_report_title(
    report_prompt: Optional[str],
    template_spec: Optional["TemplateSpec"],
    query_id: str,
    language: str = "English",
) -> str:
    title = extract_prompt_title(report_prompt)
    if title:
        title = title.strip().strip('"').strip("'")
    title = normalize_title_candidate(title or "")
    title = enforce_concise_title(title, language)
    if not title:
        title = f"Federlicht Report - {query_id}"
    return title


def title_constraints(language: str) -> tuple[int, Optional[int]]:
    if is_korean_language(language):
        return 48, None
    return 72, 12


def normalize_title_candidate(title: str) -> str:
    cleaned = title.strip().strip("`").strip('"').strip("'")
    cleaned = cleaned.lstrip("#").strip()
    cleaned = _TITLE_PREFIX_RE.sub("", cleaned)
    for prefix in (
        "본 보고서는",
        "이 보고서는",
        "본 문서는",
        "이 문서는",
        "본 리뷰는",
        "이 리뷰는",
    ):
        if cleaned.startswith(prefix):
            cleaned = cleaned[len(prefix) :].strip()
            break
    cleaned = _TITLE_REQUEST_SUFFIX_RE.sub("", cleaned).strip()
    cleaned = cleaned.strip().rstrip(" .:-")
    return cleaned


def enforce_concise_title(title: str, language: str) -> str:
    if not title:
        return title
    is_korean = is_korean_language(language)
    max_chars, max_words = title_constraints(language)
    separators = (" — ", " – ", " - ", " —", " –", " -", ":", "：", "|")
    if "관점에서" in title:
        title = title.split("관점에서", 1)[0].strip()
    if "에 대한" in title:
        title = title.split("에 대한", 1)[0].strip()
    if not is_korean:
        words = title.split()
        if max_words and len(words) > max_words:
            title = " ".join(words[:max_words]).strip()
    if len(title) > max_chars:
        for sep in separators:
            if sep in title:
                title = title.split(sep, 1)[0].strip()
                break
    if len(title) > max_chars:
        title = title[:max_chars].rstrip()
        title = f"{title}..." if title else title
    return title


def strip_latex_commands(text: str) -> str:
    if not text:
        return text
    cleaned = re.sub(r"\\[a-zA-Z]+\*?(?:\\[[^\\]]*\\])?\\{([^}]*)\\}", r"\\1", text)
    cleaned = re.sub(r"\\[a-zA-Z]+", " ", cleaned)
    return re.sub(r"\s+", " ", cleaned).strip()


def extract_title_seed(report_text: str, output_format: str, language: str) -> str:
    if not report_text:
        return ""
    text = report_text.strip()
    if output_format == "html":
        text = html_to_text(text)
    elif output_format == "tex":
        text = strip_latex_commands(text)
    text = text.replace("Report Prompt", "").replace("Clarifications", "").strip()
    paragraphs = [p.strip() for p in re.split(r"\n{2,}", text) if p.strip()]
    min_len = 40 if is_korean_language(language) else 80
    for para in paragraphs:
        lower = para.lower()
        if any(lower.startswith(hint) for hint in _TITLE_SECTION_HINTS):
            continue
        if lower.startswith(("generated at:", "duration:", "model:", "miscellaneous")):
            continue
        if len(para) < min_len:
            continue
        return para[:600]
    return paragraphs[0][:600] if paragraphs else text[:600]


def build_title_prompt(language: str) -> str:
    max_chars, max_words = title_constraints(language)
    lines = [
        "You are a report title generator.",
        f"Write the title in {language}.",
        "Return only the title text on a single line.",
        "Use a concise noun phrase.",
        "Do not include quotes, Markdown, or trailing punctuation.",
        "Do not use request phrasing such as '해줘/해주세요' or 'please'.",
    ]
    if max_words:
        lines.append(f"Limit to {max_words} words.")
    lines.append(f"Limit to {max_chars} characters.")
    return "\n".join(lines)


def generate_title_with_llm(
    report_text: str,
    output_format: str,
    language: str,
    model_name: str,
    create_deep_agent,
    backend,
) -> Optional[str]:
    seed = extract_title_seed(report_text, output_format, language)
    if not seed:
        return None
    prompt = build_title_prompt(language)
    agent = create_agent_with_fallback(create_deep_agent, model_name, [], prompt, backend)
    user_text = "\n".join(["Report snippet:", seed])
    try:
        result = agent.invoke({"messages": [{"role": "user", "content": user_text}]})
    except Exception:
        return None
    raw = extract_agent_text(result).strip()
    if not raw:
        return None
    cleaned = normalize_title_candidate(raw)
    cleaned = enforce_concise_title(cleaned, language)
    return cleaned or None


def normalize_depth_choice(value: Optional[str]) -> str:
    if not value:
        return "normal"
    token = str(value).strip().lower()
    if token in {"brief", "short", "summary", "요약", "간단"}:
        return "brief"
    if token in {"normal", "default", "standard", "일반", "보통"}:
        return "normal"
    if token in {"deep", "long-form", "comprehensive", "학술", "리뷰", "journal", "심층"}:
        return "deep"
    if token in {
        "exhaustive",
        "deepest",
        "ultra",
        "ultra-deep",
        "very deep",
        "극심",
        "매우심층",
        "최심층",
    }:
        return "exhaustive"
    return "normal"


def strip_code_fences(text: str) -> str:
    stripped = text.strip()
    if stripped.startswith("```"):
        stripped = re.sub(r"^```[a-zA-Z0-9_-]*\\s*", "", stripped)
        stripped = re.sub(r"\\s*```$", "", stripped)
    return stripped.strip()


def ensure_prompt_headers(text: str, template_name: str, depth: str, language: str) -> str:
    lower = text.lower()
    lines = text.splitlines()
    header_lines: list[str] = []
    if "template:" not in lower:
        header_lines.append(f"Template: {template_name}")
    if "depth:" not in lower:
        header_lines.append(f"Depth: {depth}")
    if "language:" not in lower and "언어:" not in lower:
        header_lines.append(f"Language: {language}")
    if header_lines:
        header_lines.append("")
        return "\n".join(header_lines + lines).strip()
    return text.strip()


def build_prompt_generator_input(
    template_spec: "TemplateSpec",
    required_sections: list[str],
    depth: str,
    language: str,
    query_id: str,
    scout_notes: str,
    instruction_text: str,
    seed_prompt: str,
    template_guidance_text: str,
) -> str:
    lines = [
        f"Template name: {template_spec.name}",
        f"Template description: {template_spec.description or '-'}",
        f"Template tone: {template_spec.tone or '-'}",
        f"Template audience: {template_spec.audience or '-'}",
        f"Requested depth: {depth}",
        f"Language: {language}",
        f"Run ID: {query_id}",
        "",
    ]
    if required_sections:
        lines.append("Required sections:")
        lines.extend([f"- {section}" for section in required_sections])
        lines.append("")
    if template_guidance_text:
        lines.extend(["Template guidance (summary):", truncate_text_middle(template_guidance_text, 2000), ""])
    if instruction_text:
        lines.extend(["Instruction snippet:", truncate_text_middle(instruction_text, 2000), ""])
    if seed_prompt:
        lines.extend(["Seed prompt (if any):", truncate_text_middle(seed_prompt, 2000), ""])
    if scout_notes:
        lines.extend(["Scout notes:", truncate_text_middle(scout_notes, 6000), ""])
    return "\n".join(lines).strip()


def resolve_prompt_output_path(args: argparse.Namespace, run_dir: Path, query_id: str) -> Path:
    if args.output:
        output_path = Path(args.output)
        if output_path.exists() and output_path.is_dir():
            output_path = output_path / f"generated_prompt_{query_id}.txt"
    else:
        instr_dir = run_dir / "instruction"
        instr_dir.mkdir(parents=True, exist_ok=True)
        output_path = instr_dir / f"generated_prompt_{query_id}.txt"
    return resolve_output_path(output_path, args.overwrite_output)


def generate_prompt_from_scout(
    result: PipelineResult,
    args: argparse.Namespace,
    agent_overrides: dict,
    create_deep_agent,
) -> str:
    template_spec = result.template_spec
    required_sections = result.required_sections or list(DEFAULT_SECTIONS)
    language = result.language
    depth = normalize_depth_choice(getattr(args, "depth", None) or result.depth)
    seed_prompt = load_report_prompt(args.prompt, args.prompt_file) or ""
    instruction_text = ""
    if result.instruction_file and result.instruction_file.exists():
        instruction_text = result.instruction_file.read_text(encoding="utf-8", errors="replace").strip()
    template_guidance_text = result.template_guidance_text or build_template_guidance_text(template_spec)

    user_text = build_prompt_generator_input(
        template_spec,
        required_sections,
        depth,
        language,
        result.query_id,
        result.scout_notes,
        instruction_text,
        seed_prompt,
        template_guidance_text,
    )
    system_prompt = prompts.build_prompt_generator_prompt(language)
    prompt_model = resolve_agent_model("prompt_generator", args.model, agent_overrides)
    prompt_max, prompt_max_source = resolve_agent_max_input_tokens("prompt_generator", args, agent_overrides)
    backend = SafeFilesystemBackend(root_dir=result.run_dir)
    agent = create_agent_with_fallback(
        create_deep_agent,
        prompt_model,
        [],
        system_prompt,
        backend,
        max_input_tokens=prompt_max,
        max_input_tokens_source=prompt_max_source,
    )
    try:
        response = agent.invoke({"messages": [{"role": "user", "content": user_text}]})
        generated = extract_agent_text(response).strip()
    except Exception:
        generated = ""
    if not generated:
        generated = (
            f"Template: {template_spec.name}\n"
            f"Depth: {depth}\n"
            f"Language: {language}\n\n"
            f"보고서 주제: {result.query_id}\n"
            "아카이브를 기반으로 핵심 동향, 근거, 한계, 시사점을 구조화해 정리하세요.\n"
            "근거는 논문/리뷰/공식 발표를 우선하고, 웹 자료는 supporting으로 구분하세요.\n"
            "근거가 부족한 영역은 공개정보 한계를 명시하세요.\n"
        )
    generated = strip_code_fences(generated)
    generated = ensure_prompt_headers(generated, template_spec.name, depth, language)
    return generated.strip() + "\n"

def format_report_title(title: str, output_format: str) -> str:
    if output_format == "tex":
        return ""
    return f"# {title}"


def format_report_prompt_block(report_prompt: Optional[str], output_format: str) -> str:
    if not report_prompt:
        return ""
    if output_format == "tex":
        return (
            "\n\n\\section*{Report Prompt}\n"
            "\\begin{verbatim}\n"
            f"{report_prompt}\n"
            "\\end{verbatim}\n"
        )
    return f"\n\n## Report Prompt\n{report_prompt}\n"


def format_clarifications_block(
    clarification_questions: Optional[str],
    clarification_answers: Optional[str],
    output_format: str,
) -> str:
    if not clarification_questions or "no_questions" in clarification_questions.lower():
        return ""
    if output_format == "tex":
        block = (
            "\n\n\\section*{Clarifications}\n"
            "\\subsection*{Questions}\n"
            "\\begin{verbatim}\n"
            f"{clarification_questions}\n"
            "\\end{verbatim}\n"
        )
        if clarification_answers:
            block += (
                "\n\\subsection*{Answers}\n"
                "\\begin{verbatim}\n"
                f"{clarification_answers}\n"
                "\\end{verbatim}\n"
            )
        return block
    block = f"\n\n## Clarifications\n\n### Questions\n{clarification_questions}\n"
    if clarification_answers:
        block = f"{block.rstrip()}\n\n### Answers\n{clarification_answers}\n"
    return block


def extract_latex_abstract(body: str) -> tuple[str, str]:
    match = re.search(r"\\begin\\{abstract\\}.*?\\end\\{abstract\\}", body, re.DOTALL)
    if not match:
        return "", body.strip()
    abstract_block = match.group(0).strip()
    cleaned = (body[: match.start()] + body[match.end() :]).strip()
    return abstract_block, cleaned


def render_latex_document(
    template_text: Optional[str],
    title: str,
    author: str,
    date: str,
    body: str,
) -> str:
    abstract_block, body_clean = extract_latex_abstract(body)
    text = template_text or DEFAULT_LATEX_TEMPLATE
    replacements = {
        "title": latex_escape(title),
        "author": latex_escape(author),
        "date": latex_escape(date),
        "abstract": abstract_block,
        "body": body_clean,
    }
    for key, value in replacements.items():
        text = text.replace(f"{{{{{key}}}}}", value)
    return text


def close_unbalanced_lists(text: str) -> str:
    for env in ("itemize", "enumerate"):
        begin = text.count(f"\\begin{{{env}}}")
        end = text.count(f"\\end{{{env}}}")
        if end < begin:
            text = text.rstrip() + "\n" + "\n".join([f"\\end{{{env}}}"] * (begin - end)) + "\n"
    return text


def sanitize_latex_headings(text: str) -> str:
    pattern = re.compile(r"(\\(?:sub)*section\\*?\\{)([^}]+)\\}")

    def repl(match: re.Match[str]) -> str:
        title = escape_latex_heading(match.group(2))
        return f"{match.group(1)}{title}}}"

    return pattern.sub(repl, text)


def ensure_korean_package(template_text: str) -> str:
    if "kotex" in template_text:
        return template_text
    lines = template_text.splitlines()
    for idx, line in enumerate(lines):
        if line.strip().startswith("\\documentclass"):
            lines.insert(idx + 1, "\\usepackage{kotex}")
            return "\n".join(lines)
    return "\\usepackage{kotex}\n" + template_text


QUALITY_WEIGHTS = {
    "alignment": 0.2,
    "evidence_grounding": 0.15,
    "groundedness": 0.2,
    "tone_fit": 0.07,
    "format_fit": 0.08,
    "structure": 0.1,
    "readability": 0.1,
    "insight": 0.08,
    "aesthetic": 0.02,
}


def normalize_score(value: object) -> float:
    try:
        score = float(value)  # type: ignore[arg-type]
    except (TypeError, ValueError):
        return 0.0
    if score < 0:
        return 0.0
    if score > 100:
        return 100.0
    return score


def compute_overall_score(evaluation: dict) -> float:
    total = 0.0
    for key, weight in QUALITY_WEIGHTS.items():
        total += normalize_score(evaluation.get(key)) * weight
    return round(total, 2)


def format_duration(seconds: float) -> str:
    total = int(seconds)
    hours, remainder = divmod(total, 3600)
    minutes, secs = divmod(remainder, 60)
    return f"{hours:02d}:{minutes:02d}:{secs:02d}"


def _is_korean_lang(language: object) -> bool:
    token = str(language or "").strip().lower()
    return token in {"korean", "ko", "kor", "kr"}


def transparency_notice_lines(language: object) -> list[str]:
    if _is_korean_lang(language):
        return [
            "AI 투명성 고지: 본 문서는 Federlicht 에이전트 파이프라인을 통해 생성되었으며, 최종 책임과 배포 판단은 사용자/조직에 있습니다.",
            "출처·저작권 고지: 외부 소스의 저작권/라이선스는 원 저작권자 정책을 따르며, 본문 인용은 분석 목적의 요약/재서술을 원칙으로 합니다.",
            "검증 고지: 고위험 의사결정(법률·의료·재무·규제)에는 원문 대조 및 추가 검증을 수행하세요.",
            "EU AI Act 정합성 참고: 본 산출물은 AI 보조 생성물임을 명시하며, 인간 검토를 전제로 사용해야 합니다.",
        ]
    return [
        "AI transparency notice: this document is generated with the Federlicht agent pipeline; final accountability remains with the user/organization.",
        "Source and copyright notice: external-source rights remain with original owners; quotations should stay minimal and analysis should rely on paraphrased synthesis.",
        "Verification notice: for high-stakes use (legal, medical, finance, regulation), perform primary-source verification before relying on this report.",
        "EU AI Act alignment note: this output is explicitly disclosed as AI-assisted/generated content and is intended for human-reviewed use.",
    ]


def format_metadata_block(meta: dict, output_format: str) -> str:
    lines = [
        f"Generated at: {meta.get('generated_at', '-')}",
        f"Duration: {meta.get('duration_hms', '-')} ({meta.get('duration_seconds', '-')}s)",
        f"Model: {meta.get('model', '-')}",
    ]
    if meta.get("model_vision"):
        lines.append(f"Vision model: {meta.get('model_vision')}")
    if meta.get("quality_model"):
        lines.append(f"Quality model: {meta.get('quality_model')}")
    lines.append(f"Quality strategy: {meta.get('quality_strategy', '-')}")
    lines.append(f"Quality iterations: {meta.get('quality_iterations', '-')}")
    lines.append(f"Template: {meta.get('template', '-')}")
    if meta.get("language"):
        lines.append(f"Language: {meta.get('language', '-')}")
    if meta.get("tags"):
        tags_value = meta.get("tags")
        if isinstance(tags_value, (list, tuple)):
            tags_text = ", ".join(str(tag) for tag in tags_value if tag)
        else:
            tags_text = str(tags_value)
        if tags_text:
            lines.append(f"Tags: {tags_text}")
    lines.append(f"Output format: {meta.get('output_format', '-')}")
    if meta.get("pdf_status"):
        lines.append(f"PDF compile: {meta.get('pdf_status')}")
    if output_format != "html":
        if meta.get("run_overview_path"):
            lines.append(f"Run overview: {meta.get('run_overview_path')}")
        if meta.get("report_overview_path"):
            lines.append(f"Report overview: {meta.get('report_overview_path')}")
        if meta.get("report_workflow_path"):
            lines.append(f"Report workflow: {meta.get('report_workflow_path')}")
        if meta.get("archive_index_path"):
            lines.append(f"Archive index: {meta.get('archive_index_path')}")
        if meta.get("instruction_path"):
            lines.append(f"Instruction file: {meta.get('instruction_path')}")
        if meta.get("report_prompt_path"):
            lines.append(f"Report prompt: {meta.get('report_prompt_path')}")
        if meta.get("figures_preview_path"):
            lines.append(f"Figure candidates: {meta.get('figures_preview_path')}")
    notice_lines = transparency_notice_lines(meta.get("language"))
    if output_format == "tex":
        block = ["", "\\section*{Miscellaneous}", "\\small", "\\begin{itemize}"]
        block.extend([f"\\item {latex_escape(line)}" for line in lines])
        block.append("\\item \\textbf{AI Transparency and Source Notice}")
        block.extend([f"\\item {latex_escape(line)}" for line in notice_lines])
        block.extend(["\\end{itemize}", "\\normalsize"])
        return "\n".join(block)
    if output_format == "html":
        items_list: list[str] = [f"<li>{html_lib.escape(line)}</li>" for line in lines]
        def add_link(label: str, value: Optional[str]) -> None:
            if not value:
                return
            safe = html_lib.escape(value)
            items_list.append(f"<li>{html_lib.escape(label)}: <a href=\"{safe}\">{safe}</a></li>")

        add_link("Run overview", meta.get("run_overview_path"))
        add_link("Report overview", meta.get("report_overview_path"))
        add_link("Report workflow", meta.get("report_workflow_path"))
        add_link("Archive index", meta.get("archive_index_path"))
        add_link("Instruction file", meta.get("instruction_path"))
        add_link("Report prompt", meta.get("report_prompt_path"))
        add_link("Figure candidates", meta.get("figures_preview_path"))
        notice_items = "\n".join(f"<li>{html_lib.escape(line)}</li>" for line in notice_lines)
        items = "\n".join(items_list)
        return "\n".join(
            [
                "",
                "<h2>Miscellaneous</h2>",
                "<div class=\"misc-block\">",
                "<ul>",
                items,
                "</ul>",
                "</div>",
                "<div class=\"misc-block ai-disclosure\">",
                "<p><strong>AI Transparency and Source Notice</strong></p>",
                "<ul>",
                notice_items,
                "</ul>",
                "</div>",
            ]
        )
    block = ["", "## Miscellaneous"]
    block.extend([f"- {line}" for line in lines])
    block.extend(["", "### AI Transparency and Source Notice"])
    block.extend([f"- {line}" for line in notice_lines])
    return "\n".join(block)


def append_jsonl(path: Path, payload: dict) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    with path.open("a", encoding="utf-8") as handle:
        handle.write(json.dumps(payload, ensure_ascii=False) + "\n")


def summarize_evaluation(evaluation: dict) -> str:
    overall = normalize_score(evaluation.get("overall"))
    strengths = evaluation.get("strengths") or []
    weaknesses = evaluation.get("weaknesses") or []
    fixes = evaluation.get("fixes") or []
    lines = [
        f"overall={overall:.1f}",
        f"strengths: {', '.join(str(s) for s in strengths[:3])}" if strengths else "strengths: (none)",
        f"weaknesses: {', '.join(str(s) for s in weaknesses[:3])}" if weaknesses else "weaknesses: (none)",
        f"fixes: {', '.join(str(s) for s in fixes[:3])}" if fixes else "fixes: (none)",
    ]
    return "\n".join(lines)


def evaluate_report(
    report_text: str,
    evidence_notes: str,
    report_prompt: Optional[str],
    template_guidance_text: str,
    required_sections: list[str],
    output_format: str,
    language: str,
    model_name: str,
    create_deep_agent,
    tools,
    backend,
    max_chars: int,
    max_input_tokens: Optional[int] = None,
    max_input_tokens_source: str = "none",
) -> dict:
    metrics = ", ".join(QUALITY_WEIGHTS.keys())
    evaluator_prompt = prompts.build_evaluate_prompt(metrics)
    evaluator_agent = create_agent_with_fallback(
        create_deep_agent,
        model_name,
        tools,
        evaluator_prompt,
        backend,
        max_input_tokens=max_input_tokens,
        max_input_tokens_source=max_input_tokens_source,
    )
    format_note = "LaTeX" if output_format == "tex" else "Markdown/HTML"
    evaluator_input = "\n".join(
        [
            "Required sections:",
            ", ".join(required_sections),
            "",
            f"Output format: {format_note}",
            "",
            "Template guidance:",
            template_guidance_text or "(none)",
            "",
            "Report focus prompt:",
            report_prompt or "(none)",
            "",
            "Evidence notes:",
            truncate_text_middle(evidence_notes, max_chars),
            "",
            "Report:",
            truncate_text_middle(report_text, max_chars),
            "",
            f"Write in {language}. Return JSON only.",
        ]
    )
    result = evaluator_agent.invoke({"messages": [{"role": "user", "content": evaluator_input}]})
    raw = extract_agent_text(result)
    parsed = extract_json_object(raw) or {}
    evaluation: dict = {"raw": raw}
    for key in QUALITY_WEIGHTS.keys():
        evaluation[key] = normalize_score(parsed.get(key))
    evaluation["overall"] = normalize_score(parsed.get("overall")) if parsed else 0.0
    if evaluation["overall"] <= 0:
        evaluation["overall"] = compute_overall_score(evaluation)
    for key in ("strengths", "weaknesses", "fixes"):
        value = parsed.get(key, [])
        if isinstance(value, list):
            evaluation[key] = [str(item) for item in value]
        elif value:
            evaluation[key] = [str(value)]
        else:
            evaluation[key] = []
    return evaluation


def compare_reports_pairwise(
    report_a: str,
    report_b: str,
    eval_a: dict,
    eval_b: dict,
    evidence_notes: str,
    report_prompt: Optional[str],
    required_sections: list[str],
    output_format: str,
    language: str,
    model_name: str,
    create_deep_agent,
    tools,
    backend,
    max_chars: int,
    max_input_tokens: Optional[int] = None,
    max_input_tokens_source: str = "none",
) -> dict:
    judge_prompt = prompts.build_compare_prompt()
    judge_agent = create_agent_with_fallback(
        create_deep_agent,
        model_name,
        tools,
        judge_prompt,
        backend,
        max_input_tokens=max_input_tokens,
        max_input_tokens_source=max_input_tokens_source,
    )
    format_note = "LaTeX" if output_format == "tex" else "Markdown/HTML"
    judge_input = "\n".join(
        [
            f"Output format: {format_note}",
            "Required sections:",
            ", ".join(required_sections),
            "",
            "Report focus prompt:",
            report_prompt or "(none)",
            "",
            "Evidence notes:",
            truncate_text_middle(evidence_notes, max_chars),
            "",
            "Report A evaluation summary:",
            summarize_evaluation(eval_a),
            "",
            "Report A:",
            truncate_text_middle(report_a, max_chars),
            "",
            "Report B evaluation summary:",
            summarize_evaluation(eval_b),
            "",
            "Report B:",
            truncate_text_middle(report_b, max_chars),
            "",
            f"Write in {language}. Return JSON only.",
        ]
    )
    result = judge_agent.invoke({"messages": [{"role": "user", "content": judge_input}]})
    raw = extract_agent_text(result)
    parsed = extract_json_object(raw) or {}
    winner = str(parsed.get("winner", "")).strip().upper()
    if winner not in {"A", "B", "TIE"}:
        winner = "TIE"
    return {
        "winner": winner,
        "reason": str(parsed.get("reason", "")).strip() or "(no reason)",
        "focus_improvements": [str(item) for item in parsed.get("focus_improvements", [])]
        if isinstance(parsed.get("focus_improvements"), list)
        else [],
        "raw": raw,
    }


def synthesize_reports(
    report_a: str,
    report_b: str,
    eval_a: dict,
    eval_b: dict,
    pairwise_notes: list[dict],
    evidence_notes: str,
    report_prompt: Optional[str],
    template_guidance_text: str,
    required_sections: list[str],
    output_format: str,
    language: str,
    model_name: str,
    create_deep_agent,
    tools,
    backend,
    max_chars: int,
    free_form: bool = False,
    template_rigidity: str = DEFAULT_TEMPLATE_RIGIDITY,
    max_input_tokens: Optional[int] = None,
    max_input_tokens_source: str = "none",
) -> str:
    format_instructions = build_format_instructions(
        output_format,
        required_sections,
        free_form=free_form,
        language=language,
        template_rigidity=template_rigidity,
    )
    synthesis_prompt = prompts.build_synthesize_prompt(format_instructions, template_guidance_text, language)
    synthesis_agent = create_agent_with_fallback(
        create_deep_agent,
        model_name,
        tools,
        synthesis_prompt,
        backend,
        max_input_tokens=max_input_tokens,
        max_input_tokens_source=max_input_tokens_source,
    )
    notes = "\n".join(
        f"- {note.get('reason', '')} (winner={note.get('winner')})"
        for note in pairwise_notes
        if note.get("reason")
    )
    synthesis_input = "\n".join(
        [
            "Report focus prompt:",
            report_prompt or "(none)",
            "",
            "Evidence notes:",
            truncate_text_middle(evidence_notes, max_chars),
            "",
            "Report A evaluation summary:",
            summarize_evaluation(eval_a),
            "",
            "Report B evaluation summary:",
            summarize_evaluation(eval_b),
            "",
            "Pairwise selection notes:",
            notes or "(none)",
            "",
            "Report A:",
            truncate_text_middle(report_a, max_chars),
            "",
            "Report B:",
            truncate_text_middle(report_b, max_chars),
        ]
    )
    result = synthesis_agent.invoke({"messages": [{"role": "user", "content": synthesis_input}]})
    return extract_agent_text(result)


def resolve_notes_dir(run_dir: Path, notes_dir: Optional[str]) -> Path:
    if notes_dir:
        raw = Path(notes_dir)
        path = raw if raw.is_absolute() else (run_dir / raw)
        path = path.resolve()
    else:
        path = run_dir / "report_notes"
    path.mkdir(parents=True, exist_ok=True)
    return path


def resolve_supporting_dir(run_dir: Path, supporting_dir: Optional[str]) -> Path:
    if supporting_dir:
        raw = Path(supporting_dir)
        path = raw if raw.is_absolute() else (run_dir / raw)
        resolved = path.resolve()
        if run_dir not in resolved.parents and resolved != run_dir:
            raise ValueError(f"Supporting dir must be inside run folder: {supporting_dir}")
    else:
        stamp = dt.datetime.now().strftime("%Y%m%d_%H%M%S")
        path = run_dir / "supporting" / stamp
    path.mkdir(parents=True, exist_ok=True)
    return path


def resolve_output_path(
    output_path: Path,
    overwrite: bool,
    companion_suffixes: Optional[list[str]] = None,
) -> Path:
    if overwrite or not output_path.exists():
        if overwrite or not companion_suffixes:
            return output_path
        for suffix in companion_suffixes:
            if output_path.with_suffix(suffix).exists():
                break
        else:
            return output_path
    parent = output_path.parent
    suffix = output_path.suffix
    stem = output_path.stem
    counter = 1
    while True:
        candidate = parent / f"{stem}_{counter}{suffix}"
        if candidate.exists():
            counter += 1
            continue
        if companion_suffixes and not overwrite:
            conflict = False
            for suffix_value in companion_suffixes:
                if candidate.with_suffix(suffix_value).exists():
                    conflict = True
                    break
            if conflict:
                counter += 1
                continue
        return candidate


def compile_latex_to_pdf(tex_path: Path) -> tuple[bool, str]:
    workdir = tex_path.parent
    if shutil.which("latexmk"):
        cmd = ["latexmk", "-pdf", "-interaction=nonstopmode", "-halt-on-error", tex_path.name]
        result = subprocess.run(
            cmd,
            cwd=workdir,
            capture_output=True,
            text=True,
            encoding="utf-8",
            errors="replace",
        )
        if result.returncode == 0:
            cleanup_latex_artifacts(tex_path)
            return True, ""
        last_error = result.stderr or result.stdout or "latexmk failed."
    else:
        last_error = None
    if shutil.which("pdflatex"):
        cmd = ["pdflatex", "-interaction=nonstopmode", "-halt-on-error", tex_path.name]
        for _ in range(2):
            result = subprocess.run(
                cmd,
                cwd=workdir,
                capture_output=True,
                text=True,
                encoding="utf-8",
                errors="replace",
            )
            if result.returncode != 0:
                return False, (result.stderr or result.stdout or "pdflatex failed.")
        cleanup_latex_artifacts(tex_path)
        return True, ""
    if last_error:
        return False, last_error
    return False, "No LaTeX compiler found (latexmk or pdflatex)."


def cleanup_latex_artifacts(tex_path: Path) -> None:
    base = tex_path.with_suffix("")
    candidates = [
        tex_path.with_suffix(".aux"),
        tex_path.with_suffix(".log"),
        tex_path.with_suffix(".out"),
        tex_path.with_suffix(".toc"),
        tex_path.with_suffix(".bbl"),
        tex_path.with_suffix(".blg"),
        tex_path.with_suffix(".lof"),
        tex_path.with_suffix(".lot"),
        tex_path.with_suffix(".fls"),
        tex_path.with_suffix(".fdb_latexmk"),
        tex_path.with_suffix(".synctex.gz"),
    ]
    for path in candidates:
        try:
            if path.exists():
                path.unlink()
        except Exception:
            pass
    for extra in ["-blx.bib", "-run.xml"]:
        candidate = Path(f"{base}{extra}")
        try:
            if candidate.exists():
                candidate.unlink()
        except Exception:
            pass


def coerce_rel_path(value: Optional[str], run_dir: Path) -> Optional[str]:
    if not value:
        return None
    raw = value.strip()
    if not raw:
        return None
    if raw.startswith("./"):
        return raw
    candidate = Path(raw)
    if candidate.is_absolute():
        try:
            rel = candidate.resolve().relative_to(run_dir)
        except ValueError:
            return None
        return f"./{rel.as_posix()}"
    return f"./{raw.lstrip('./')}"


@dataclass
class TemplateSpec:
    name: str
    sections: list[str] = field(default_factory=list)
    section_guidance: dict[str, str] = field(default_factory=dict)
    writer_guidance: list[str] = field(default_factory=list)
    description: Optional[str] = None
    tone: Optional[str] = None
    audience: Optional[str] = None
    css: Optional[str] = None
    latex: Optional[str] = None
    layout: Optional[str] = None
    source: Optional[str] = None


def normalize_section_list(sections: Iterable[str]) -> list[str]:
    seen: set[str] = set()
    normalized: list[str] = []
    for section in sections:
        text = " ".join(str(section).split()).strip()
        if not text:
            continue
        key = text.lower()
        if key in seen:
            continue
        seen.add(key)
        normalized.append(text)
    return normalized


def match_section_by_keywords(sections: list[str], keywords: list[str]) -> Optional[str]:
    for section in sections:
        lowered = section.lower()
        if any(keyword in lowered for keyword in keywords):
            return section
    return None


def infer_required_sections_from_prompt(report_prompt: Optional[str], template_sections: list[str]) -> list[str]:
    if not report_prompt:
        return []
    text = report_prompt.lower()
    canonical = {
        "summary": "Executive Summary",
        "scope": "Scope & Methodology",
        "method": "Scope & Methodology",
        "findings": "Key Findings",
        "trend": "Trends & Implications",
        "risk": "Risks & Gaps",
        "critic": "Critics",
        "appendix": "Appendix",
        "conclusion": "Conclusion",
    }
    keyword_map = {
        "summary": ["executive summary", "summary", "요약", "서문 요약"],
        "scope": ["scope", "범위"],
        "method": ["method", "methodology", "방법", "방법론"],
        "findings": ["key findings", "findings", "핵심 발견", "핵심 내용"],
        "trend": ["trend", "trends", "implication", "implications", "추세", "시사점"],
        "risk": ["risk", "risks", "gap", "gaps", "limitation", "limitations", "위험", "리스크", "한계", "공백"],
        "critic": ["critic", "critique", "비판", "비평", "사설"],
        "appendix": ["appendix", "부록"],
        "conclusion": ["conclusion", "결론", "종합"],
    }
    required: list[str] = []
    for key, keywords in keyword_map.items():
        if not any(keyword in text for keyword in keywords):
            continue
        match = match_section_by_keywords(template_sections, keywords)
        required.append(match or canonical[key])
    return normalize_section_list(required)


def merge_required_sections(
    adjusted_sections: list[str],
    required_sections: list[str],
    template_sections: list[str],
) -> list[str]:
    final = normalize_section_list(adjusted_sections) or normalize_section_list(template_sections)
    for required in required_sections:
        if required in final:
            continue
        inserted = False
        if required in template_sections:
            idx = template_sections.index(required)
            insert_at = len(final)
            for prev in reversed(template_sections[:idx]):
                if prev in final:
                    insert_at = final.index(prev) + 1
                    break
            final.insert(insert_at, required)
            inserted = True
        if not inserted:
            final.append(required)
    return final


def adjust_template_spec(
    template_spec: TemplateSpec,
    report_prompt: Optional[str],
    scout_notes: str,
    align_scout: Optional[str],
    clarification_answers: Optional[str],
    language: str,
    output_format: str,
    model_name: str,
    create_deep_agent,
    backend,
    adjust_mode: str = "extend",
    prompt_override: Optional[str] = None,
    model_override: Optional[str] = None,
    max_input_tokens: Optional[int] = None,
    max_input_tokens_source: str = "none",
) -> tuple[TemplateSpec, Optional[dict]]:
    if not report_prompt and not scout_notes:
        return template_spec, None
    base_sections = normalize_section_list(template_spec.sections) or list(DEFAULT_SECTIONS)
    required_sections = infer_required_sections_from_prompt(report_prompt, base_sections)
    if adjust_mode == "risk_only":
        ensure_sections = ["Risks & Gaps", "Critics"]
        adjusted_sections = list(base_sections)
        added_sections: list[str] = []
        for section in ensure_sections:
            if section in adjusted_sections:
                continue
            insert_at = adjusted_sections.index("Appendix") if "Appendix" in adjusted_sections else len(adjusted_sections)
            adjusted_sections.insert(insert_at, section)
            added_sections.append(section)
        if not added_sections:
            return template_spec, None
        merged_guidance = dict(template_spec.section_guidance)
        fallback_writer: list[str] = []
        if added_sections:
            fallback_guidance, fallback_writer = fallback_template_guidance(added_sections)
            merged_guidance.update(fallback_guidance)
        merged_writer = list(template_spec.writer_guidance)
        for item in fallback_writer:
            if item and item not in merged_writer:
                merged_writer.append(item)
        adjusted_spec = TemplateSpec(
            name=template_spec.name,
            sections=adjusted_sections,
            section_guidance=merged_guidance,
            writer_guidance=merged_writer,
            description=template_spec.description,
            tone=template_spec.tone,
            audience=template_spec.audience,
            css=template_spec.css,
            latex=template_spec.latex,
            source=template_spec.source,
        )
        adjustment = {
            "rationale": "risk_only",
            "sections": adjusted_sections,
            "section_guidance": {k: merged_guidance[k] for k in added_sections if k in merged_guidance},
            "writer_guidance": fallback_writer,
            "required_sections": ensure_sections,
            "adjust_mode": adjust_mode,
        }
        return adjusted_spec, adjustment
    template_guidance = "\n".join(f"- {key}: {value}" for key, value in template_spec.section_guidance.items())
    writer_guidance = "\n".join(f"- {item}" for item in template_spec.writer_guidance)
    prompt = prompt_override or prompts.build_template_adjuster_prompt(output_format)
    user_parts = [
        f"Output format: {output_format}",
        f"Language: {language}",
        "",
        "Required sections (must include):",
        "\n".join(f"- {section}" for section in required_sections) or "(none)",
        "",
        "Template sections:",
        "\n".join(f"- {section}" for section in base_sections),
        "",
        "Template guidance:",
        template_guidance or "(none)",
        "",
        "Template writer guidance:",
        writer_guidance or "(none)",
        "",
        "Report focus prompt:",
        report_prompt or "(none)",
        "",
        "Scout notes:",
        truncate_text_middle(scout_notes, 4000),
    ]
    if align_scout:
        user_parts.extend(["", "Alignment notes (scout):", truncate_text_middle(align_scout, 2000)])
    if clarification_answers:
        user_parts.extend(["", "User clarifications:", truncate_text_middle(clarification_answers, 1200)])
    agent_model = model_override or model_name
    agent = create_agent_with_fallback(
        create_deep_agent,
        agent_model,
        [],
        prompt,
        backend,
        max_input_tokens=max_input_tokens,
        max_input_tokens_source=max_input_tokens_source,
    )
    result = agent.invoke({"messages": [{"role": "user", "content": "\n".join(user_parts)}]})
    text = extract_agent_text(result)
    parsed = extract_json_object(text)
    if not isinstance(parsed, dict):
        return template_spec, None
    sections = parsed.get("sections") if isinstance(parsed.get("sections"), list) else base_sections
    adjusted_sections = normalize_section_list(sections)
    if adjust_mode == "extend":
        extras = [section for section in adjusted_sections if section not in base_sections]
        adjusted_sections = normalize_section_list(list(base_sections) + extras)
    adjusted_sections = merge_required_sections(adjusted_sections, required_sections, base_sections)
    section_guidance = parsed.get("section_guidance") if isinstance(parsed.get("section_guidance"), dict) else {}
    writer_guidance = parsed.get("writer_guidance") if isinstance(parsed.get("writer_guidance"), list) else []
    clean_guidance = {
        str(key): " ".join(str(value).split())
        for key, value in section_guidance.items()
        if key and isinstance(value, str)
    }
    clean_writer_guidance = [" ".join(str(item).split()) for item in writer_guidance if item]
    merged_guidance = dict(template_spec.section_guidance)
    merged_guidance.update({k: v for k, v in clean_guidance.items() if k in adjusted_sections})
    missing_guidance = [section for section in adjusted_sections if section not in merged_guidance]
    if missing_guidance:
        fallback_guidance, fallback_writer = fallback_template_guidance(missing_guidance)
        merged_guidance.update(fallback_guidance)
        clean_writer_guidance.extend(fallback_writer)
    merged_writer = list(template_spec.writer_guidance)
    for item in clean_writer_guidance:
        if item and item not in merged_writer:
            merged_writer.append(item)
    adjusted_spec = TemplateSpec(
        name=template_spec.name,
        sections=adjusted_sections,
        section_guidance=merged_guidance,
        writer_guidance=merged_writer,
        description=template_spec.description,
        tone=template_spec.tone,
        audience=template_spec.audience,
        css=template_spec.css,
        latex=template_spec.latex,
        source=template_spec.source,
    )
    adjustment = {
        "rationale": str(parsed.get("rationale", "")).strip(),
        "sections": adjusted_sections,
        "section_guidance": clean_guidance,
        "writer_guidance": clean_writer_guidance,
        "required_sections": required_sections,
        "adjust_mode": adjust_mode,
    }
    return adjusted_spec, adjustment


def write_template_adjustment_note(
    notes_dir: Path,
    template_spec: TemplateSpec,
    adjusted_spec: TemplateSpec,
    adjustment: dict,
    output_format: str,
    language: str,
) -> Optional[Path]:
    if not adjustment:
        return None
    notes_dir.mkdir(parents=True, exist_ok=True)
    original_sections = normalize_section_list(template_spec.sections)
    adjusted_sections = normalize_section_list(adjusted_spec.sections)
    added = [section for section in adjusted_sections if section not in original_sections]
    removed = [section for section in original_sections if section not in adjusted_sections]
    rationale = adjustment.get("rationale") or "(none)"
    path = notes_dir / "template_adjustment.md"
    lines = [
        "# Template Adjustment",
        "",
        f"Template: {template_spec.name}",
        f"Format: {output_format}",
        f"Language: {language}",
        f"Adjust mode: {adjustment.get('adjust_mode', 'unknown')}",
        "",
        "## Rationale",
        rationale or "(none)",
        "",
        "## Required Sections (prompt-derived)",
        "\n".join(f"- {section}" for section in adjustment.get("required_sections", [])) or "(none)",
        "",
        "## Sections (original)",
        "\n".join(f"- {section}" for section in original_sections) or "(none)",
        "",
        "## Sections (adjusted)",
        "\n".join(f"- {section}" for section in adjusted_sections) or "(none)",
        "",
        "## Added Sections",
        "\n".join(f"- {section}" for section in added) or "(none)",
        "",
        "## Removed Sections",
        "\n".join(f"- {section}" for section in removed) or "(none)",
        "",
    ]
    guidance = adjustment.get("section_guidance") if isinstance(adjustment.get("section_guidance"), dict) else {}
    if guidance:
        lines.extend(
            [
                "## Guidance Overrides",
                "\n".join(f"- {section}: {text}" for section, text in guidance.items()),
                "",
            ]
        )
    writer_guidance = adjustment.get("writer_guidance") if isinstance(adjustment.get("writer_guidance"), list) else []
    if writer_guidance:
        lines.extend(["## Writer Guidance Additions", "\n".join(f"- {item}" for item in writer_guidance), ""])
    path.write_text("\n".join(lines).strip() + "\n", encoding="utf-8")
    return path


def build_template_guidance_text(template_spec: TemplateSpec) -> str:
    lines: list[str] = []
    if template_spec.description:
        lines.append(f"Template description: {template_spec.description}")
    if template_spec.tone:
        lines.append(f"Template tone: {template_spec.tone}")
    if template_spec.audience:
        lines.append(f"Template audience: {template_spec.audience}")
    if template_spec.section_guidance:
        section_lines = [f"- {key}: {value}" for key, value in template_spec.section_guidance.items()]
        lines.append("Section guidance:\n" + "\n".join(section_lines))
    if template_spec.writer_guidance:
        lines.append("Template writing guidance:\n" + "\n".join(template_spec.writer_guidance))
    return "\n\n".join(lines) if lines else ""


@dataclass
class FormatInstructions:
    report_skeleton: str
    section_heading_instruction: str
    latex_safety_instruction: str
    format_instruction: str
    citation_instruction: str


@dataclass
class ReportOutput:
    result: PipelineResult
    report: str
    rendered: str
    output_path: Optional[Path]
    meta: dict
    preview_text: str
    state: Optional[PipelineState] = None


def build_pipeline_state(result: PipelineResult) -> PipelineState:
    return PipelineState(
        run_dir=result.run_dir,
        archive_dir=result.archive_dir,
        notes_dir=result.notes_dir,
        supporting_dir=result.supporting_dir,
        output_format=result.output_format,
        language=result.language,
        report_prompt=result.report_prompt,
        template_spec=result.template_spec,
        template_guidance_text=result.template_guidance_text,
        required_sections=list(result.required_sections),
        context_lines=list(result.context_lines),
        source_triage_text=result.source_triage_text,
        scout_notes=result.scout_notes,
        plan_text=result.plan_text,
        plan_context=result.plan_context,
        evidence_notes=result.evidence_notes,
        claim_map_text=result.claim_map_text,
        gap_text=result.gap_text,
        supporting_summary=result.supporting_summary,
        clarification_questions=result.clarification_questions,
        clarification_answers=result.clarification_answers,
        align_scout=result.align_scout,
        align_plan=result.align_plan,
        align_evidence=result.align_evidence,
        depth=result.depth,
        style_hint=result.style_hint,
        query_id=result.query_id,
        report=result.report,
    )


def pipeline_state_to_dict(state: PipelineState) -> dict:
    def to_path(value: Optional[Path]) -> Optional[str]:
        return value.as_posix() if isinstance(value, Path) else None

    return {
        "run_dir": state.run_dir.as_posix(),
        "archive_dir": state.archive_dir.as_posix(),
        "notes_dir": state.notes_dir.as_posix(),
        "supporting_dir": to_path(state.supporting_dir),
        "output_format": state.output_format,
        "language": state.language,
        "report_prompt": state.report_prompt,
        "template_spec": getattr(state.template_spec, "__dict__", state.template_spec),
        "template_guidance_text": state.template_guidance_text,
        "required_sections": list(state.required_sections),
        "context_lines": list(state.context_lines),
        "source_triage_text": state.source_triage_text,
        "scout_notes": state.scout_notes,
        "plan_text": state.plan_text,
        "plan_context": state.plan_context,
        "evidence_notes": state.evidence_notes,
        "claim_map_text": state.claim_map_text,
        "gap_text": state.gap_text,
        "supporting_summary": state.supporting_summary,
        "clarification_questions": state.clarification_questions,
        "clarification_answers": state.clarification_answers,
        "align_scout": state.align_scout,
        "align_plan": state.align_plan,
        "align_evidence": state.align_evidence,
        "depth": state.depth,
        "style_hint": state.style_hint,
        "query_id": state.query_id,
        "report": state.report,
    }


def coerce_pipeline_state(value: object) -> PipelineState:
    if isinstance(value, PipelineState):
        return value
    if isinstance(value, ReportOutput):
        if value.state:
            return value.state
        return build_pipeline_state(value.result)
    if isinstance(value, PipelineResult):
        return build_pipeline_state(value)
    raise TypeError("Unsupported state type. Use PipelineState, PipelineResult, or ReportOutput.")


def get_stage_info(names: Optional[Iterable[str]] = None) -> dict:
    if not names:
        names = ["all"]
    tokens: list[str] = []
    for name in names:
        if name is None:
            continue
        for token in str(name).replace(";", ",").replace("|", ",").split(","):
            cleaned = token.strip().lower()
            if cleaned:
                tokens.append(cleaned)
    if not tokens or "all" in tokens:
        return {"stages": list(STAGE_ORDER), "details": dict(STAGE_INFO)}
    selected = [name for name in STAGE_ORDER if name in tokens]
    return {"stages": selected, "details": {name: STAGE_INFO[name] for name in selected}}


def parse_stage_info_arg(raw: Optional[str]) -> tuple[list[str], Optional[str]]:
    if raw is None or raw == "-" or raw.strip().lower() == "all":
        return ["all"], None
    cleaned = raw.strip()
    lowered = cleaned.lower()
    if any(sep in cleaned for sep in (",", ";", "|")):
        tokens = cleaned.replace(";", ",").replace("|", ",").split(",")
        return [token.strip() for token in tokens if token.strip()], None
    if lowered in STAGE_INFO:
        return [lowered], None
    if lowered == "all":
        return ["all"], None
    return ["all"], cleaned


def write_stage_info(payload: dict, target: Optional[str]) -> None:
    text = json.dumps(payload, ensure_ascii=False, indent=2)
    if target and target != "-":
        path = Path(target)
        path.write_text(text + "\n", encoding="utf-8")
        print(f"Wrote stage info: {path}")
    else:
        print(text)


def normalize_state_for_writer(state: PipelineState) -> PipelineState:
    if not state.evidence_notes and state.scout_notes:
        state.evidence_notes = state.scout_notes
    if not state.plan_context and state.plan_text:
        state.plan_context = state.plan_text
    return state


def validate_state_for_writer(state: PipelineState) -> list[str]:
    missing: list[str] = []
    if not state.plan_text:
        missing.append("plan_text")
    if not state.evidence_notes and not state.scout_notes:
        missing.append("evidence_notes")
    if not state.required_sections:
        missing.append("required_sections")
    if not state.template_spec:
        missing.append("template_spec")
    if not state.output_format:
        missing.append("output_format")
    if not state.language:
        missing.append("language")
    return missing


def build_format_instructions(
    output_format: str,
    required_sections: list[str],
    free_form: bool = False,
    language: str = "English",
    template_rigidity: str = DEFAULT_TEMPLATE_RIGIDITY,
) -> FormatInstructions:
    is_korean = is_korean_language(language)
    rigidity = str(template_rigidity or DEFAULT_TEMPLATE_RIGIDITY).strip().lower()
    if rigidity not in TEMPLATE_RIGIDITY_POLICIES:
        rigidity = DEFAULT_TEMPLATE_RIGIDITY

    def pick(korean_text: str, english_text: str) -> str:
        return korean_text if is_korean else english_text

    report_skeleton = ""
    if free_form:
        required_list = "\n".join(f"- {section}" for section in required_sections)
        if required_sections:
            if output_format != "tex":
                section_heading_instruction = pick(
                    "섹션 구조는 H2 제목으로 명확히 구성하고(하위 항목은 H3), "
                    "아래에 나열된 필수 섹션은 해당 H2 제목을 그대로 사용해 보고서 본문 끝에 배치하세요. "
                    "최상위 섹션에 H3를 쓰지 마세요.\n",
                    "Choose a clear section structure using H2 headings (use H3 for subpoints). "
                    "Include the required sections listed below using these exact H2 headings and place them at the end "
                    "of the report body. Do not use H3 for top-level sections.\n",
                )
            else:
                section_heading_instruction = pick(
                    "섹션 구조는 \\section 제목으로 명확히 구성하고(하위 항목은 \\subsection), "
                    "아래에 나열된 필수 섹션은 해당 \\section 제목을 그대로 사용해 보고서 본문 끝에 배치하세요.\n",
                    "Choose a clear section structure using \\section headings (use \\subsection for subpoints). "
                    "Include the required sections listed below using these exact \\section headings and place them at the end "
                    "of the report body.\n",
                )
            report_skeleton = required_list
        else:
            if output_format != "tex":
                section_heading_instruction = pick(
                    "섹션 구조는 H2 제목으로 명확히 구성하고(하위 항목은 H3), "
                    "보고서 프롬프트가 제목이나 순서를 지정하면 그대로 따르세요.\n",
                    "Choose a clear section structure using H2 headings (use H3 for subpoints). "
                    "If the report prompt specifies headings or ordering, follow it exactly.\n",
                )
            else:
                section_heading_instruction = pick(
                    "섹션 구조는 \\section 제목으로 명확히 구성하고(하위 항목은 \\subsection), "
                    "보고서 프롬프트가 제목이나 순서를 지정하면 그대로 따르세요.\n",
                    "Choose a clear section structure using \\section headings (use \\subsection for subpoints). "
                    "If the report prompt specifies headings or ordering, follow it exactly.\n",
                )
    else:
        report_skeleton = build_report_skeleton(required_sections, output_format)
        if rigidity == "strict":
            if output_format != "tex":
                section_heading_instruction = pick(
                    "아래의 H2 제목을 이 순서대로 정확히 사용하세요(이름 변경 금지; H2 추가 금지):\n",
                    "Use the following exact H2 headings in this order (do not rename; do not add extra H2 headings):\n",
                )
            else:
                section_heading_instruction = pick(
                    "아래의 \\section 제목을 이 순서대로 정확히 사용하세요(이름 변경 금지; \\section 추가 금지):\n",
                    "Use the following exact \\section headings in this order (do not rename; do not add extra \\section headings):\n",
                )
        elif rigidity in {"relaxed", "loose", "off"}:
            if output_format != "tex":
                section_heading_instruction = pick(
                    "아래 필수 H2 제목은 반드시 포함하되, 순서는 필요 시 조정할 수 있습니다. "
                    "추가 H2는 꼭 필요할 때만 제한적으로 사용하세요(필수 제목 이름은 변경 금지):\n",
                    "Include all required H2 headings below, but you may adjust ordering when needed. "
                    "Add extra H2 headings only when necessary (do not rename required headings):\n",
                )
            else:
                section_heading_instruction = pick(
                    "아래 필수 \\section 제목은 반드시 포함하되, 순서는 필요 시 조정할 수 있습니다. "
                    "추가 \\section은 꼭 필요할 때만 제한적으로 사용하세요(필수 제목 이름은 변경 금지):\n",
                    "Include all required \\section headings below, but you may adjust ordering when needed. "
                    "Add extra \\section headings only when necessary (do not rename required headings):\n",
                )
        else:
            if output_format != "tex":
                section_heading_instruction = pick(
                    "아래 H2 제목을 기본 골격으로 사용하세요. 순서는 가능한 유지하되, 근거 흐름상 필요하면 제한적으로 H2를 추가할 수 있습니다 "
                    "(필수 제목 이름은 변경 금지):\n",
                    "Use the following H2 headings as the primary scaffold. Keep the order when practical, but you may add limited H2 headings "
                    "when evidence flow requires it (do not rename required headings):\n",
                )
            else:
                section_heading_instruction = pick(
                    "아래 \\section 제목을 기본 골격으로 사용하세요. 순서는 가능한 유지하되, 근거 흐름상 필요하면 제한적으로 \\section을 추가할 수 있습니다 "
                    "(필수 제목 이름은 변경 금지):\n",
                    "Use the following \\section headings as the primary scaffold. Keep the order when practical, but you may add limited \\section headings "
                    "when evidence flow requires it (do not rename required headings):\n",
                )
    if output_format != "tex":
        citation_instruction = pick(
            "본문에 전체 URL을 그대로 출력하지 말고 [source], [paper] 같은 짧은 링크 라벨을 사용하세요. "
            "파일 경로는 클릭 가능하도록 마크다운 링크를 우선 사용하세요. "
            "./archive/... 같은 파일 경로를 본문에 그대로 쓰지 말고 인용만 남기세요. "
            "인용은 문장 끝에 inline으로 붙이고, 인용만 단독 줄이나 단독 리스트 항목으로 두지 마세요. ",
            "Avoid printing full URLs in the body; use short link labels like [source] or [paper] instead. "
            "Prefer markdown links for file paths so they are clickable. "
            "Do not print archive file paths verbatim in the prose; keep only the citation. "
            "Keep citations inline at the end of the sentence; do not place citations on their own line or as standalone list items. ",
        )
    else:
        citation_instruction = pick(
            "출처 인용 시 원문 URL 또는 파일 경로를 대괄호 안에 직접 넣으세요"
            "(예: [https://example.com], [./archive/path.txt]). 마크다운 링크는 사용하지 마세요. "
            "본문 다른 곳에 전체 URL을 출력하지 마세요. ",
            "When citing sources, include the raw URL or file path inside square brackets "
            "(e.g., [https://example.com], [./archive/path.txt]). Do not use Markdown links. "
            "Avoid printing full URLs elsewhere in the body. ",
        )
    latex_safety_instruction = ""
    format_instruction = ""
    if output_format == "html":
        format_instruction = pick(
            "본문은 Markdown으로 작성하고, Markdown으로 부족할 때만 최소한의 HTML 태그(예: 표/줄바꿈)를 "
            "사용하세요. 전체 출력에 ```html 코드펜스를 감싸지 말고 <html>, <head>, <body> 같은 전체 문서도 "
            "출력하지 마세요. ",
            "Write the report body in Markdown. You may use minimal HTML tags (e.g., tables/line breaks) "
            "only when Markdown is insufficient. Do not wrap the entire output in ```html fences and do not "
            "output a full HTML document (<html>, <head>, <body>). ",
        )
    elif output_format == "md":
        format_instruction = pick(
            "본문은 Markdown으로 작성하되 전체 출력을 코드펜스로 감싸지 마세요. ",
            "Write the report body in Markdown without wrapping the entire output in code fences. ",
        )
    if output_format == "tex":
        latex_safety_instruction = pick(
            "LaTeX 안전 규칙: 본문/제목에서 특수문자는 이스케이프하세요(&는 \\&, %는 \\%, #은 \\#). "
            "&는 tabular/align 환경에서만 사용하세요. "
            "밑줄(_)은 수식 안에서만 사용하고, 텍스트에서는 \\_로 이스케이프하세요. ",
            "LaTeX safety: escape special characters in text/headings (use \\& for &, \\% for %, \\# for #). "
            "Only use & inside tabular/align environments. "
            "Use underscores only inside math; otherwise escape as \\_. ",
        )
        section_rule = pick(
            "각 필수 섹션은 \\section{...}로 작성하고 하위 항목은 \\subsection을 사용하세요. "
            if not free_form
            else "필요한 섹션은 \\section{...}로 작성하고 하위 항목은 \\subsection을 사용하세요. ",
            "Use \\section{...} headings for each required section and \\subsection for subpoints. "
            if not free_form
            else "Use \\section{...} headings as needed and \\subsection for subpoints. ",
        )
        format_instruction = pick(
            "LaTeX 본문만 작성하세요(\\documentclass/서문 금지). "
            f"{section_rule}"
            "마크다운 형식은 사용하지 마세요. "
            "출처 인용을 제외하고 대괄호 사용을 피하세요. "
            f"{latex_safety_instruction}",
            "Write LaTeX body only (no documentclass/preamble). "
            f"{section_rule}"
            "Do not use Markdown formatting. "
            "Avoid square brackets except for raw source citations. "
            f"{latex_safety_instruction}",
        )
    return FormatInstructions(
        report_skeleton=report_skeleton,
        section_heading_instruction=section_heading_instruction,
        latex_safety_instruction=latex_safety_instruction,
        format_instruction=format_instruction,
        citation_instruction=citation_instruction,
    )


def load_agent_config(path: Optional[str]) -> tuple[dict, dict]:
    if not path:
        return {}, {}
    config_path = Path(path)
    if not config_path.exists():
        raise FileNotFoundError(f"Agent config not found: {config_path}")
    raw = json.loads(config_path.read_text(encoding="utf-8"))
    if not isinstance(raw, dict):
        raise ValueError("Agent config must be a JSON object.")
    config = raw.get("config") if isinstance(raw.get("config"), dict) else {}
    agents = raw.get("agents") if isinstance(raw.get("agents"), dict) else {}
    return config, agents


def normalize_config_overrides(raw: dict) -> dict:
    if not isinstance(raw, dict):
        return {}
    overrides: dict[str, object] = {}
    for key in (
        "model",
        "check_model",
        "quality_model",
        "model_vision",
        "template_rigidity",
        "template_adjust",
        "template_adjust_mode",
        "temperature_level",
        "temperature",
        "quality_iterations",
        "quality_strategy",
        "web_search",
        "alignment_check",
        "stream",
        "stream_debug",
        "cache",
        "repair_mode",
        "repair_debug",
        "interactive",
        "free_format",
        "max_input_tokens",
        "language",
        "lang",
    ):
        if key in raw:
            overrides[key] = raw[key]
    return overrides


def apply_config_overrides(args: argparse.Namespace, config: dict) -> None:
    if not config:
        return
    if isinstance(config.get("model"), str) and config["model"].strip():
        args.model = config["model"].strip()
    if isinstance(config.get("check_model"), str) and config["check_model"].strip():
        args.check_model = config["check_model"].strip()
    if isinstance(config.get("quality_model"), str) and config["quality_model"].strip():
        args.quality_model = config["quality_model"].strip()
    if isinstance(config.get("model_vision"), str) and config["model_vision"].strip():
        args.model_vision = config["model_vision"].strip()
    if isinstance(config.get("template_rigidity"), str):
        token = config["template_rigidity"].strip().lower()
        if token in TEMPLATE_RIGIDITY_POLICIES:
            args.template_rigidity = token
    if isinstance(config.get("template_adjust"), bool):
        args.template_adjust = config["template_adjust"]
    if isinstance(config.get("template_adjust_mode"), str) and config["template_adjust_mode"] in {
        "risk_only",
        "extend",
        "replace",
    }:
        args.template_adjust_mode = config["template_adjust_mode"]
    if isinstance(config.get("quality_iterations"), int) and config["quality_iterations"] >= 0:
        args.quality_iterations = config["quality_iterations"]
    if isinstance(config.get("quality_strategy"), str) and config["quality_strategy"] in {"pairwise", "best_of"}:
        args.quality_strategy = config["quality_strategy"]
    if isinstance(config.get("web_search"), bool):
        args.web_search = config["web_search"]
    if isinstance(config.get("alignment_check"), bool):
        args.alignment_check = config["alignment_check"]
    if isinstance(config.get("stream"), bool):
        args.stream = config["stream"]
    if isinstance(config.get("stream_debug"), bool):
        args.stream_debug = config["stream_debug"]
    if isinstance(config.get("cache"), bool):
        args.cache = config["cache"]
    if isinstance(config.get("repair_mode"), str) and config["repair_mode"] in {"append", "replace", "off"}:
        args.repair_mode = config["repair_mode"]
    if isinstance(config.get("repair_debug"), bool):
        args.repair_debug = config["repair_debug"]
    if isinstance(config.get("interactive"), bool):
        args.interactive = config["interactive"]
    if isinstance(config.get("free_format"), bool):
        args.free_format = config["free_format"]
    if isinstance(config.get("temperature_level"), str):
        token = config["temperature_level"].strip().lower()
        if token in TEMPERATURE_LEVELS:
            args.temperature_level = token
    parsed_temperature = parse_temperature(config.get("temperature"))
    if parsed_temperature is not None:
        args.temperature = parsed_temperature
    config_max_input = parse_max_input_tokens(config.get("max_input_tokens"))
    if config_max_input:
        args.max_input_tokens = config_max_input
        args.max_input_tokens_source = "config"
    if isinstance(config.get("language"), str) and config["language"].strip():
        args.lang = config["language"].strip()
    if isinstance(config.get("lang"), str) and config["lang"].strip():
        args.lang = config["lang"].strip()


def normalize_agent_overrides(raw: Optional[dict]) -> dict:
    if not isinstance(raw, dict):
        return {}
    overrides: dict[str, dict] = {}
    for name, entry in raw.items():
        if not isinstance(entry, dict):
            continue
        payload: dict[str, object] = {}
        if isinstance(entry.get("model"), str) and entry["model"].strip():
            payload["model"] = entry["model"].strip()
        if isinstance(entry.get("system_prompt"), str) and entry["system_prompt"].strip():
            payload["system_prompt"] = entry["system_prompt"].strip()
        if isinstance(entry.get("enabled"), bool):
            payload["enabled"] = entry["enabled"]
        max_input = parse_max_input_tokens(entry.get("max_input_tokens"))
        if max_input:
            payload["max_input_tokens"] = max_input
        if payload:
            overrides[str(name)] = payload
    return overrides


def merge_agent_overrides(base: dict, extra: Optional[dict]) -> dict:
    if not extra:
        return base
    merged = dict(base)
    for name, entry in extra.items():
        merged[name] = entry
    return merged


def resolve_agent_overrides_from_config(
    args: argparse.Namespace, explicit_overrides: Optional[dict] = None
) -> tuple[dict, dict]:
    agent_overrides: dict = {}
    config_overrides: dict = {}
    if args.agent_config:
        config_overrides, raw_overrides = load_agent_config(args.agent_config)
        apply_config_overrides(args, normalize_config_overrides(config_overrides))
        agent_overrides = normalize_agent_overrides(raw_overrides)
        if args.quality_iterations > 0:
            disabled_quality = any(
                resolve_agent_enabled(name, True, agent_overrides) is False
                for name in ("critic", "reviser", "evaluator")
            )
            if disabled_quality:
                print(
                    "WARN: agent-config disabled quality agents; skipping quality iterations.",
                    file=sys.stderr,
                )
                args.quality_iterations = 0
    if explicit_overrides:
        agent_overrides = merge_agent_overrides(
            agent_overrides, normalize_agent_overrides(explicit_overrides)
        )
    return agent_overrides, config_overrides


def apply_template_rigidity_policy(
    args: argparse.Namespace,
    config_overrides: Optional[dict] = None,
    argv_flags: Optional[list[str]] = None,
) -> None:
    config_overrides = config_overrides or {}
    argv_flags = argv_flags or getattr(args, "_cli_argv", None) or sys.argv
    rigidity = str(getattr(args, "template_rigidity", DEFAULT_TEMPLATE_RIGIDITY) or "").strip().lower()
    if rigidity not in TEMPLATE_RIGIDITY_POLICIES:
        rigidity = DEFAULT_TEMPLATE_RIGIDITY
    args.template_rigidity = rigidity
    policy = TEMPLATE_RIGIDITY_POLICIES[rigidity]
    cli_tokens = set(str(token) for token in argv_flags)
    explicit_adjust = (
        "--template-adjust" in cli_tokens
        or "--no-template-adjust" in cli_tokens
        or "template_adjust" in config_overrides
    )
    explicit_adjust_mode = "--template-adjust-mode" in cli_tokens or "template_adjust_mode" in config_overrides
    explicit_repair = "--repair-mode" in cli_tokens or "repair_mode" in config_overrides
    if not explicit_adjust:
        args.template_adjust = bool(policy["template_adjust"])
    if not explicit_adjust_mode:
        args.template_adjust_mode = str(policy["template_adjust_mode"])
    if not explicit_repair:
        args.repair_mode = str(policy["repair_mode"])
    if args.free_format:
        args.template_adjust = False
    args.template_rigidity_effective = {
        "template_adjust": bool(args.template_adjust),
        "template_adjust_mode": str(args.template_adjust_mode),
        "repair_mode": str(args.repair_mode),
    }


def resolve_effective_temperature(args: argparse.Namespace) -> float:
    level = str(getattr(args, "temperature_level", DEFAULT_TEMPERATURE_LEVEL) or "").strip().lower()
    if level not in TEMPERATURE_LEVELS:
        level = DEFAULT_TEMPERATURE_LEVEL
    explicit = parse_temperature(getattr(args, "temperature", None))
    effective = explicit if explicit is not None else float(TEMPERATURE_LEVELS[level])
    args.temperature_level = level
    args.temperature = effective
    return effective


def prepare_runtime(
    args: argparse.Namespace,
    config_overrides: Optional[dict] = None,
    argv_flags: Optional[list[str]] = None,
) -> tuple[str, str]:
    config_overrides = config_overrides or {}
    argv_flags = argv_flags or getattr(args, "_cli_argv", None) or sys.argv
    model_cli = "--model" in argv_flags
    check_model_cli = "--check-model" in argv_flags
    quality_model_cli = "--quality-model" in argv_flags
    model_config = "model" in config_overrides
    check_model_config = "check_model" in config_overrides
    quality_model_config = "quality_model" in config_overrides
    if (model_cli or model_config) and not check_model_cli and not check_model_config:
        args.check_model = args.model
    if (model_cli or model_config) and not quality_model_cli and not quality_model_config:
        if not args.quality_model:
            args.quality_model = args.model
    apply_template_rigidity_policy(args, config_overrides=config_overrides, argv_flags=argv_flags)
    effective_temperature = resolve_effective_temperature(args)
    check_model = args.check_model.strip() if args.check_model else ""
    if not check_model:
        check_model = args.model
    global STREAMING_ENABLED
    STREAMING_ENABLED = bool(args.stream)
    global DEFAULT_MAX_INPUT_TOKENS
    global DEFAULT_MAX_INPUT_TOKENS_SOURCE
    global ACTIVE_AGENT_TEMPERATURE
    DEFAULT_MAX_INPUT_TOKENS = parse_max_input_tokens(args.max_input_tokens)
    DEFAULT_MAX_INPUT_TOKENS_SOURCE = getattr(args, "max_input_tokens_source", "none")
    ACTIVE_AGENT_TEMPERATURE = effective_temperature
    output_format = choose_format(args.output)
    args.output_format = output_format
    resolve_active_profile(args)
    return output_format, check_model


def resolve_create_deep_agent(create_deep_agent):
    if create_deep_agent is not None:
        return create_deep_agent
    try:
        from deepagents import create_deep_agent as deep_agent  # type: ignore
    except Exception as exc:
        raise RuntimeError("deepagents is required. Install with: python -m pip install deepagents") from exc
    return deep_agent


def resolve_agent_enabled(name: str, default: bool, overrides: dict) -> bool:
    entry = overrides.get(name)
    if not isinstance(entry, dict):
        return default
    enabled = entry.get("enabled")
    return enabled if isinstance(enabled, bool) else default


def resolve_agent_prompt(name: str, default_prompt: str, overrides: dict) -> str:
    entry = overrides.get(name)
    prompt = default_prompt
    if isinstance(entry, dict):
        override = entry.get("system_prompt")
        if isinstance(override, str) and override.strip():
            prompt = override
    profile = ACTIVE_AGENT_PROFILE
    if profile and profile_applies_to(profile, name):
        if isinstance(entry, dict) and entry.get("profile") is False:
            return prompt
        if ACTIVE_AGENT_PROFILE_CONTEXT:
            return f"{ACTIVE_AGENT_PROFILE_CONTEXT}\n\n{prompt}".strip()
    return prompt


def resolve_active_profile(args: argparse.Namespace) -> Optional[AgentProfile]:
    global ACTIVE_AGENT_PROFILE
    global ACTIVE_AGENT_PROFILE_CONTEXT
    profile = load_profile(getattr(args, "agent_profile", None), getattr(args, "agent_profile_dir", None))
    ACTIVE_AGENT_PROFILE = profile
    ACTIVE_AGENT_PROFILE_CONTEXT = build_profile_context(profile) if profile else ""
    return profile


def resolve_agent_model(name: str, default_model: str, overrides: dict) -> str:
    entry = overrides.get(name)
    if not isinstance(entry, dict):
        return default_model
    model = entry.get("model")
    return model if isinstance(model, str) and model.strip() else default_model


def resolve_agent_max_input_tokens(
    name: str,
    args: argparse.Namespace,
    overrides: dict,
) -> tuple[Optional[int], str]:
    entry = overrides.get(name)
    if isinstance(entry, dict):
        agent_max = parse_max_input_tokens(entry.get("max_input_tokens"))
        if agent_max:
            return agent_max, "agent"
    cli_max = parse_max_input_tokens(getattr(args, "max_input_tokens", None))
    if cli_max:
        source = getattr(args, "max_input_tokens_source", "cli")
        return cli_max, source
    return None, "none"


def apply_model_profile_max_input_tokens(
    model: object,
    max_input_tokens: Optional[int],
    force: bool = False,
) -> Optional[int]:
    if not max_input_tokens:
        return None
    try:
        profile = getattr(model, "profile", None)
    except Exception:
        profile = None
    if isinstance(profile, dict) and "max_input_tokens" in profile and isinstance(profile["max_input_tokens"], int):
        if not force:
            return profile["max_input_tokens"]
    new_profile = dict(profile) if isinstance(profile, dict) else {}
    new_profile["max_input_tokens"] = int(max_input_tokens)
    try:
        setattr(model, "profile", new_profile)
    except Exception:
        return None
    return new_profile["max_input_tokens"]


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
    writer_prompt = resolve_agent_prompt(
        "writer",
        prompts.build_writer_prompt(
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
        ),
        overrides,
    )
    scout_prompt = resolve_agent_prompt("scout", prompts.build_scout_prompt(language), overrides)
    clarifier_prompt = resolve_agent_prompt("clarifier", prompts.build_clarifier_prompt(language), overrides)
    align_prompt = resolve_agent_prompt("alignment", prompts.build_alignment_prompt(language), overrides)
    plan_prompt = resolve_agent_prompt("planner", prompts.build_plan_prompt(language), overrides)
    plan_check_prompt = resolve_agent_prompt("plan_check", prompts.build_plan_check_prompt(language), overrides)
    web_prompt = resolve_agent_prompt("web_query", prompts.build_web_prompt(), overrides)
    evidence_prompt = resolve_agent_prompt("evidence", prompts.build_evidence_prompt(language), overrides)
    repair_prompt = resolve_agent_prompt(
        "structural_editor",
        prompts.build_repair_prompt(
            format_instructions,
            output_format,
            language,
            free_form=args.free_format,
            template_rigidity=args.template_rigidity,
        ),
        overrides,
    )
    critic_prompt = resolve_agent_prompt("critic", prompts.build_critic_prompt(language, required_sections), overrides)
    revise_prompt = resolve_agent_prompt(
        "reviser",
        prompts.build_revise_prompt(format_instructions, output_format, language),
        overrides,
    )
    evaluate_prompt = resolve_agent_prompt("evaluator", prompts.build_evaluate_prompt(metrics), overrides)
    compare_prompt = resolve_agent_prompt("pairwise_compare", prompts.build_compare_prompt(), overrides)
    synthesize_prompt = resolve_agent_prompt(
        "synthesizer",
        prompts.build_synthesize_prompt(format_instructions, template_guidance_text, language),
        overrides,
    )
    template_adjuster_prompt = resolve_agent_prompt(
        "template_adjuster",
        prompts.build_template_adjuster_prompt(output_format),
        overrides,
    )
    image_prompt = resolve_agent_prompt("image_analyst", prompts.build_image_prompt(), overrides)
    scout_max, _ = resolve_agent_max_input_tokens("scout", args, overrides)
    clarifier_max, _ = resolve_agent_max_input_tokens("clarifier", args, overrides)
    alignment_max, _ = resolve_agent_max_input_tokens("alignment", args, overrides)
    planner_max, _ = resolve_agent_max_input_tokens("planner", args, overrides)
    plan_check_max, _ = resolve_agent_max_input_tokens("plan_check", args, overrides)
    web_max, _ = resolve_agent_max_input_tokens("web_query", args, overrides)
    evidence_max, _ = resolve_agent_max_input_tokens("evidence", args, overrides)
    writer_max, _ = resolve_agent_max_input_tokens("writer", args, overrides)
    structural_max, _ = resolve_agent_max_input_tokens("structural_editor", args, overrides)
    critic_max, _ = resolve_agent_max_input_tokens("critic", args, overrides)
    reviser_max, _ = resolve_agent_max_input_tokens("reviser", args, overrides)
    evaluator_max, _ = resolve_agent_max_input_tokens("evaluator", args, overrides)
    compare_max, _ = resolve_agent_max_input_tokens("pairwise_compare", args, overrides)
    synth_max, _ = resolve_agent_max_input_tokens("synthesizer", args, overrides)
    template_adjust_max, _ = resolve_agent_max_input_tokens("template_adjuster", args, overrides)
    scout_model = resolve_agent_model("scout", args.model, overrides)
    clarifier_model = resolve_agent_model("clarifier", args.model, overrides)
    alignment_model = resolve_agent_model("alignment", args.check_model or args.model, overrides)
    planner_model = resolve_agent_model("planner", args.model, overrides)
    plan_check_model = resolve_agent_model("plan_check", args.check_model or args.model, overrides)
    web_model = resolve_agent_model("web_query", args.model, overrides)
    evidence_model = resolve_agent_model("evidence", args.model, overrides)
    writer_model = resolve_agent_model("writer", args.model, overrides)
    structural_model = resolve_agent_model("structural_editor", args.model, overrides)
    critic_model = resolve_agent_model("critic", quality_model, overrides)
    reviser_model = resolve_agent_model("reviser", quality_model, overrides)
    evaluator_model = resolve_agent_model("evaluator", quality_model, overrides)
    compare_model = resolve_agent_model("pairwise_compare", quality_model, overrides)
    synth_model = resolve_agent_model("synthesizer", quality_model, overrides)
    template_adjuster_model = resolve_agent_model("template_adjuster", args.model, overrides)
    image_model = resolve_agent_model("image_analyst", args.model_vision or "(not set)", overrides)
    clarifier_enabled = resolve_agent_enabled(
        "clarifier",
        bool(args.interactive or args.answers or args.answers_file),
        overrides,
    )
    alignment_enabled = resolve_agent_enabled("alignment", bool(args.alignment_check), overrides)
    web_enabled = resolve_agent_enabled("web_query", bool(args.web_search), overrides)
    template_adjust_enabled = resolve_agent_enabled("template_adjuster", bool(args.template_adjust), overrides)
    if free_format:
        template_adjust_enabled = False
    quality_enabled = bool(args.quality_iterations > 0)
    critic_enabled = resolve_agent_enabled("critic", quality_enabled, overrides)
    reviser_enabled = resolve_agent_enabled("reviser", quality_enabled, overrides)
    evaluator_enabled = resolve_agent_enabled("evaluator", quality_enabled, overrides)
    pairwise_enabled = resolve_agent_enabled(
        "pairwise_compare",
        bool(quality_enabled and args.quality_strategy == "pairwise"),
        overrides,
    )
    synth_enabled = resolve_agent_enabled("synthesizer", quality_enabled, overrides)
    agents = {
        "scout": {
            "model": scout_model,
            "system_prompt": scout_prompt,
            "max_input_tokens": scout_max,
        },
        "clarifier": {
            "model": clarifier_model,
            "enabled": clarifier_enabled,
            "system_prompt": clarifier_prompt,
            "max_input_tokens": clarifier_max,
        },
        "alignment": {
            "model": alignment_model,
            "enabled": alignment_enabled,
            "system_prompt": align_prompt,
            "max_input_tokens": alignment_max,
        },
        "planner": {
            "model": planner_model,
            "system_prompt": plan_prompt,
            "max_input_tokens": planner_max,
        },
        "plan_check": {
            "model": plan_check_model,
            "system_prompt": plan_check_prompt,
            "max_input_tokens": plan_check_max,
        },
        "web_query": {
            "model": web_model,
            "enabled": web_enabled,
            "system_prompt": web_prompt,
            "max_input_tokens": web_max,
        },
        "evidence": {
            "model": evidence_model,
            "system_prompt": evidence_prompt,
            "max_input_tokens": evidence_max,
        },
        "writer": {
            "model": writer_model,
            "system_prompt": writer_prompt,
            "max_input_tokens": writer_max,
        },
        "structural_editor": {
            "model": structural_model,
            "system_prompt": repair_prompt,
            "max_input_tokens": structural_max,
        },
        "critic": {
            "model": critic_model,
            "enabled": critic_enabled,
            "system_prompt": critic_prompt,
            "max_input_tokens": critic_max,
        },
        "reviser": {
            "model": reviser_model,
            "enabled": reviser_enabled,
            "system_prompt": revise_prompt,
            "max_input_tokens": reviser_max,
        },
        "evaluator": {
            "model": evaluator_model,
            "enabled": evaluator_enabled,
            "system_prompt": evaluate_prompt,
            "max_input_tokens": evaluator_max,
        },
        "pairwise_compare": {
            "model": compare_model,
            "enabled": pairwise_enabled,
            "system_prompt": compare_prompt,
            "max_input_tokens": compare_max,
        },
        "synthesizer": {
            "model": synth_model,
            "enabled": synth_enabled,
            "system_prompt": synthesize_prompt,
            "max_input_tokens": synth_max,
        },
        "template_adjuster": {
            "model": template_adjuster_model,
            "enabled": template_adjust_enabled,
            "system_prompt": template_adjuster_prompt,
            "max_input_tokens": template_adjust_max,
        },
        "image_analyst": {
            "model": image_model,
            "enabled": bool(args.model_vision and args.extract_figures),
            "system_prompt": image_prompt,
        },
    }
    return {
        "config": {
            "language": language,
            "output_format": output_format,
            "model": args.model,
            "temperature": args.temperature,
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
        "agents": agents,
    }


def write_agent_info(payload: dict, target: Optional[str]) -> None:
    text = json.dumps(payload, ensure_ascii=False, indent=2)
    if target and target != "-":
        path = Path(target)
        path.write_text(text + "\n", encoding="utf-8")
        print(f"Wrote agent info: {path}")
    else:
        print(text)


def template_from_prompt(report_prompt: Optional[str]) -> Optional[str]:
    if not report_prompt:
        return None
    for line in report_prompt.splitlines():
        match = _TEMPLATE_LINE_RE.match(line)
        if match:
            value = match.group(1).strip()
            return value or None
    return None


def parse_template_text(text: str, source: Optional[str] = None) -> TemplateSpec:
    lines = text.splitlines()
    header_start = None
    header_end = None
    for idx, line in enumerate(lines):
        if line.strip() == "---":
            if header_start is None:
                header_start = idx + 1
            else:
                header_end = idx
                break
    header_lines: list[str] = []
    body_lines: list[str] = []
    if header_start is not None and header_end is not None:
        header_lines = lines[header_start:header_end]
        body_lines = lines[header_end + 1 :]
    else:
        body_lines = lines

    spec = TemplateSpec(name=DEFAULT_TEMPLATE_NAME, source=source)
    for raw in header_lines:
        line = raw.strip()
        if not line or line.startswith("#"):
            continue
        if line.lower().startswith("section:"):
            section = line.split(":", 1)[1].strip()
            if section:
                spec.sections.append(section)
            continue
        if line.lower().startswith("guide "):
            rest = line[6:]
            if ":" in rest:
                section, guidance = rest.split(":", 1)
                section = section.strip()
                guidance = guidance.strip()
                if section and guidance:
                    spec.section_guidance[section] = guidance
            continue
        if ":" in line:
            key, value = line.split(":", 1)
            key = key.strip().lower()
            value = value.strip()
            if not value:
                continue
            if key == "name":
                spec.name = value
            elif key == "description":
                spec.description = value
            elif key == "tone":
                spec.tone = value
            elif key == "audience":
                spec.audience = value
            elif key == "css":
                spec.css = value
            elif key == "latex":
                spec.latex = value
            elif key == "layout":
                spec.layout = value
            elif key in {"writer_guidance", "guidance"}:
                spec.writer_guidance.append(value)
    body_text = "\n".join(line.rstrip() for line in body_lines).strip()
    if body_text:
        spec.writer_guidance.append(body_text)
    if not spec.sections:
        spec.sections = list(DEFAULT_SECTIONS)
    return spec


def load_template_spec(template_value: Optional[str], report_prompt: Optional[str]) -> TemplateSpec:
    choice = (template_value or "auto").strip()
    if choice.lower() == "auto":
        prompt_choice = template_from_prompt(report_prompt)
        choice = prompt_choice or DEFAULT_TEMPLATE_NAME
    if choice.lower() == DEFAULT_TEMPLATE_NAME:
        default_path = templates_dir() / f"{DEFAULT_TEMPLATE_NAME}.md"
        if default_path.exists():
            return parse_template_text(default_path.read_text(encoding="utf-8", errors="replace"), str(default_path))
        return TemplateSpec(
            name=DEFAULT_TEMPLATE_NAME,
            sections=list(DEFAULT_SECTIONS),
            description="Default journal-style review.",
            tone="Academic, evidence-based, critical.",
            audience="Technical leaders and researchers.",
            css="default.css",
            latex="default.tex",
            source="builtin-default",
        )
    path = Path(choice)
    if path.exists():
        return parse_template_text(path.read_text(encoding="utf-8", errors="replace"), str(path))
    template_root = templates_dir()
    # If a path was given but doesn't exist, fallback to template root using the stem.
    if path.suffix.lower() == ".md" or path.parent != Path("."):
        fallback_name = path.stem if path.suffix else path.name
        candidate = template_root / f"{fallback_name}.md"
        if candidate.exists():
            return parse_template_text(candidate.read_text(encoding="utf-8", errors="replace"), str(candidate))
    # Name-only lookup (accepts "name" or "name.md").
    candidate = template_root / f"{path.stem}.md"
    if candidate.exists():
        return parse_template_text(candidate.read_text(encoding="utf-8", errors="replace"), str(candidate))
    return TemplateSpec(
        name=DEFAULT_TEMPLATE_NAME,
        sections=list(DEFAULT_SECTIONS),
        description=f"Unknown template '{choice}'. Falling back to default.",
        tone="Academic, evidence-based, critical.",
        audience="Technical leaders and researchers.",
        css="default.css",
        latex="default.tex",
        source="fallback-default",
    )


def resolve_template_css_path(spec: TemplateSpec) -> Optional[Path]:
    if not spec.css:
        return None
    css_value = spec.css.strip()
    if not css_value:
        return None
    candidate = Path(css_value)
    if not candidate.suffix:
        candidate = candidate.with_suffix(".css")
    if candidate.is_absolute() and candidate.exists():
        return candidate
    if spec.source:
        source_dir = Path(str(spec.source)).parent
        local = (source_dir / candidate).resolve()
        if local.exists():
            return local
    template_styles = templates_dir() / "styles"
    local = (template_styles / candidate.name).resolve()
    if local.exists():
        return local
    return None


def load_template_css(spec: TemplateSpec) -> Optional[str]:
    path = resolve_template_css_path(spec)
    if not path or not path.exists():
        return None
    return path.read_text(encoding="utf-8", errors="replace")


def resolve_template_latex_path(spec: TemplateSpec) -> Optional[Path]:
    if not spec.latex:
        return None
    latex_value = spec.latex.strip()
    if not latex_value:
        return None
    candidate = Path(latex_value)
    if not candidate.suffix:
        candidate = candidate.with_suffix(".tex")
    if candidate.is_absolute() and candidate.exists():
        return candidate
    if spec.source:
        source_dir = Path(str(spec.source)).parent
        local = (source_dir / candidate).resolve()
        if local.exists():
            return local
    template_root = templates_dir()
    local = (template_root / candidate.name).resolve()
    if local.exists():
        return local
    return None


def load_template_latex(spec: TemplateSpec) -> Optional[str]:
    path = resolve_template_latex_path(spec)
    if not path or not path.exists():
        return None
    return path.read_text(encoding="utf-8", errors="replace")


def build_template_preview_markdown(template_spec: TemplateSpec) -> str:
    lines = [f"# Template Preview: {template_spec.name}", ""]
    meta_bits = []
    if template_spec.description:
        meta_bits.append(f"**Description:** {template_spec.description}")
    if template_spec.tone:
        meta_bits.append(f"**Tone:** {template_spec.tone}")
    if template_spec.audience:
        meta_bits.append(f"**Audience:** {template_spec.audience}")
    if template_spec.source:
        meta_bits.append(f"**Source:** {template_spec.source}")
    if meta_bits:
        lines.extend(meta_bits)
        lines.append("")
    for section in template_spec.sections:
        lines.append(f"## {section}")
        guidance = template_spec.section_guidance.get(section)
        if guidance:
            lines.append(f"*Guidance:* {guidance}")
        lines.append(
            "This is placeholder content to visualize section flow and expected narrative density."
        )
        lines.append("- Placeholder point A")
        lines.append("- Placeholder point B")
        lines.append("")
    if template_spec.writer_guidance:
        lines.append("## Template Notes")
        lines.extend([f"- {note}" for note in template_spec.writer_guidance])
        lines.append("")
    return "\n".join(lines).strip() + "\n"


def _css_href_for_output(css_path: Path, output_path: Path) -> str:
    rel = os.path.relpath(css_path, output_path.parent).replace("\\", "/")
    return rel


def materialize_template_css(spec: TemplateSpec, output_path: Path) -> Optional[str]:
    css_path = resolve_template_css_path(spec)
    if not css_path or not css_path.exists():
        return None
    report_dir = output_path.parent
    report_styles = report_dir / "report_styles"
    report_styles.mkdir(parents=True, exist_ok=True)
    name = slugify_label(spec.name or "template")
    target = report_styles / f"{name}.css"
    target.write_text(css_path.read_text(encoding="utf-8", errors="replace"), encoding="utf-8")
    return _css_href_for_output(target, output_path)


def load_template_css_content(spec: TemplateSpec) -> Optional[str]:
    css_path = resolve_template_css_path(spec)
    if not css_path or not css_path.exists():
        return None
    return css_path.read_text(encoding="utf-8", errors="replace")


def write_template_preview(template_spec: TemplateSpec, output_path: Path) -> None:
    markdown = build_template_preview_markdown(template_spec)
    body_html = markdown_to_html(markdown)
    body_html = linkify_html(body_html)
    theme_href = None
    extra_body_class = None
    css_path = resolve_template_css_path(template_spec)
    if css_path and css_path.exists():
        preview_dir = output_path.parent
        preview_styles = preview_dir / "styles"
        preview_styles.mkdir(parents=True, exist_ok=True)
        source_path = css_path
        canonical = Path(__file__).resolve().parent / "templates" / "styles" / css_path.name
        if canonical.exists():
            source_path = canonical
        target = preview_styles / css_path.name
        target.write_text(source_path.read_text(encoding="utf-8", errors="replace"), encoding="utf-8")
        theme_href = _css_href_for_output(target, output_path)
        css_slug = slugify_label(css_path.stem)
        template_slug = slugify_label(template_spec.name or "")
        if css_slug and css_slug != template_slug:
            extra_body_class = f"template-{css_slug}"
        rendered = wrap_html(
            f"Template Preview - {template_spec.name}",
            body_html,
            template_name=template_spec.name,
            theme_href=theme_href,
            extra_body_class=extra_body_class,
            layout=template_spec.layout,
        )
    output_path.parent.mkdir(parents=True, exist_ok=True)
    output_path.write_text(rendered, encoding="utf-8")


def resolve_preview_output(
    template_spec: TemplateSpec,
    preview_template: str,
    preview_output: Optional[str],
) -> Path:
    if preview_output:
        path = Path(preview_output)
        if path.suffix.lower() in {".html", ".htm"}:
            return path
        return path / f"preview_{template_spec.name}.html"
    if template_spec.source and Path(str(template_spec.source)).exists():
        base = Path(str(template_spec.source)).parent
    else:
        base = templates_dir()
    return base / f"preview_{template_spec.name}.html"


def truncate_for_view(text: str, max_chars: int) -> tuple[str, bool]:
    if max_chars <= 0 or len(text) <= max_chars:
        return text, False
    return text[:max_chars], True


_FENCED_BLOCK_RE = re.compile(
    r"^\s*```(?P<lang>[\w+-]*)\s*\n(?P<body>.*)\n```\s*$",
    re.DOTALL,
)


def unwrap_single_fenced_block(text: str) -> tuple[Optional[str], str]:
    match = _FENCED_BLOCK_RE.match(text.strip())
    if not match:
        return None, text
    lang = (match.group("lang") or "").strip().lower()
    body = match.group("body").strip()
    return lang, body


def normalize_report_for_format(report_text: str, output_format: str) -> str:
    cleaned = report_text.strip()
    lang, body = unwrap_single_fenced_block(cleaned)
    if lang is not None:
        if output_format == "html" and lang in {"", "html", "htm", "markdown", "md"}:
            cleaned = body
        elif output_format == "tex" and lang in {"", "tex", "latex"}:
            cleaned = body
        elif output_format == "md" and lang in {"", "markdown", "md"}:
            cleaned = body
    if output_format == "html":
        if re.search(r"<!doctype|<html", cleaned, re.IGNORECASE):
            body_match = re.search(r"(?is)<body[^>]*>(.*?)</body>", cleaned)
            if body_match:
                cleaned = body_match.group(1).strip()
            else:
                cleaned = re.sub(r"(?is)<!doctype.*?>", "", cleaned)
                cleaned = re.sub(r"(?is)<head[^>]*>.*?</head>", "", cleaned)
                cleaned = re.sub(r"(?is)</?html[^>]*>", "", cleaned)
                cleaned = re.sub(r"(?is)</?body[^>]*>", "", cleaned)
                cleaned = cleaned.strip()
    if output_format == "tex" and re.search(r"\\begin\{document\}", cleaned):
        doc_match = re.search(r"(?is)\\begin\{document\}(.*)\\end\{document\}", cleaned)
        if doc_match:
            cleaned = doc_match.group(1).strip()
        else:
            cleaned = re.sub(r"(?is)^.*?\\begin\{document\}", "", cleaned).strip()
    return cleaned


_URL_RE = re.compile(r"(https?://[^\s<]+)")
_REL_PATH_RE = re.compile(r"(?<![\w/])(\./[A-Za-z0-9_./-]+)")
_ARCHIVE_PATH_RE = re.compile(r"(/archive/[A-Za-z0-9_./-]+)")
_BARE_PATH_RE = re.compile(
    r"(?<![\w./])((?:archive|instruction|report_notes|report|supporting)/[A-Za-z0-9_./-]+)"
)
_WINDOWS_ABS_RE = re.compile(r"^(?:\\\\\\?\\\\)?[A-Za-z]:/")
_CODE_LINK_RE = re.compile(
    r"^(https?://\S+|\.?/archive/\S+|\.?/instruction/\S+|\.?/report_notes/\S+|\.?/report/\S+|"
    r"\.?/supporting/\S+|archive/\S+|instruction/\S+|report_notes/\S+|report/\S+|supporting/\S+|[A-Za-z]:/\S+)$"
)
_CITED_PATH_RE = re.compile(
    r"(?<![\w./])((?:\./)?(?:archive|instruction|report_notes|report|supporting)/[A-Za-z0-9_./-]+)"
)
_CITATION_LINK_PATTERN = r"\[(?:\\\[)?\d+(?:\\\])?\]\([^)]+\)"
_CITATION_LINK_RE = re.compile(_CITATION_LINK_PATTERN)
_CITATION_LINE_RE = re.compile(
    rf"^[\s\(\[]*(?:{_CITATION_LINK_PATTERN})(?:[\s,;]*(?:{_CITATION_LINK_PATTERN}))*[\s\)\].,:;]*$"
)
_AUTHOR_LINE_RE = re.compile(r"^\s*(?:author|작성자|prompted by|byline)\s*:\s*(.+)$", re.IGNORECASE)
_TEMPLATE_LINE_RE = re.compile(r"^\s*(?:template|템플릿)\s*:\s*(.+)$", re.IGNORECASE)
_FIGURE_CAPTION_RE = re.compile(r"^(?:figure|fig\\.?)[\\s:]*\\d+", re.IGNORECASE)
INDEX_JSONL_HINTS = {
    "tavily_search.jsonl": "Tavily search index",
    "openalex/works.jsonl": "OpenAlex works index",
    "arxiv/papers.jsonl": "arXiv papers index",
    "youtube/videos.jsonl": "YouTube videos index",
    "local/manifest.jsonl": "Local documents index",
    "supporting/web_search.jsonl": "Supporting web search index",
    "supporting/web_fetch.jsonl": "Supporting web fetch index",
}


def _linkify_text(text: str) -> str:
    def replace_url(match: re.Match[str]) -> str:
        url = match.group(1)
        trimmed = url.rstrip(").,;")
        suffix = url[len(trimmed) :]
        return f'<a href="{html_lib.escape(trimmed)}">{html_lib.escape(trimmed)}</a>{suffix}'

    def replace_rel(match: re.Match[str]) -> str:
        path = match.group(1)
        return f'<a href="{html_lib.escape(path)}">{html_lib.escape(path)}</a>'

    def replace_archive(match: re.Match[str]) -> str:
        path = match.group(1)
        href = f".{path}"
        return f'<a href="{html_lib.escape(href)}">{html_lib.escape(path)}</a>'

    def replace_bare(match: re.Match[str]) -> str:
        path = match.group(1)
        href = f"./{path}"
        return f'<a href="{html_lib.escape(href)}">{html_lib.escape(path)}</a>'

    text = _URL_RE.sub(replace_url, text)
    text = _REL_PATH_RE.sub(replace_rel, text)
    text = _ARCHIVE_PATH_RE.sub(replace_archive, text)
    text = _BARE_PATH_RE.sub(replace_bare, text)
    return text


def linkify_plain_text(text: str) -> str:
    parts: list[str] = []
    last = 0
    for match in _URL_RE.finditer(text):
        start, end = match.span(1)
        parts.append(html_lib.escape(text[last:start]))
        url = match.group(1)
        trimmed = url.rstrip(").,;")
        suffix = url[len(trimmed) :]
        safe = html_lib.escape(trimmed)
        parts.append(f'<a href="{safe}">{safe}</a>')
        if suffix:
            parts.append(html_lib.escape(suffix))
        last = end
    parts.append(html_lib.escape(text[last:]))
    return "".join(parts)


class _LinkifyHTMLParser(HTMLParser):
    def __init__(self) -> None:
        super().__init__(convert_charrefs=False)
        self._parts: list[str] = []
        self._stack: list[str] = []

    def handle_starttag(self, tag: str, attrs: list[tuple[str, Optional[str]]]) -> None:
        self._stack.append(tag)
        self._parts.append(self._rebuild_tag(tag, attrs, closed=False))

    def handle_startendtag(self, tag: str, attrs: list[tuple[str, Optional[str]]]) -> None:
        self._parts.append(self._rebuild_tag(tag, attrs, closed=True))

    def handle_endtag(self, tag: str) -> None:
        if self._stack and self._stack[-1] == tag:
            self._stack.pop()
        self._parts.append(f"</{tag}>")

    def handle_data(self, data: str) -> None:
        if any(t in {"a", "pre"} for t in self._stack):
            self._parts.append(data)
            return
        if "code" in self._stack:
            snippet = data.strip()
            if snippet and not any(ch.isspace() for ch in snippet) and _CODE_LINK_RE.match(snippet):
                self._parts.append(_linkify_text(data))
            else:
                self._parts.append(data)
            return
        self._parts.append(_linkify_text(data))

    def handle_entityref(self, name: str) -> None:
        self._parts.append(f"&{name};")

    def handle_charref(self, name: str) -> None:
        self._parts.append(f"&#{name};")

    def handle_comment(self, data: str) -> None:
        self._parts.append(f"<!--{data}-->")

    def _rebuild_tag(self, tag: str, attrs: list[tuple[str, Optional[str]]], closed: bool) -> str:
        if not attrs:
            return f"<{tag}{' /' if closed else ''}>"
        parts = []
        for key, value in attrs:
            if value is None:
                parts.append(key)
            else:
                parts.append(f'{key}="{html_lib.escape(value, quote=True)}"')
        attrs_str = " ".join(parts)
        return f"<{tag} {attrs_str}{' /' if closed else ''}>"

    def get_html(self) -> str:
        return "".join(self._parts)


def linkify_html(html_text: str) -> str:
    parser = _LinkifyHTMLParser()
    parser.feed(html_text)
    return parser.get_html()


_VIEWER_HREF_RE = re.compile(r'href="([^"]+)"')


def rewrite_viewer_links(html_text: str, run_dir: Path, viewer_dir: Path) -> str:
    base = os.path.relpath(run_dir, viewer_dir).replace("\\", "/")

    def replace(match: re.Match[str]) -> str:
        raw = html_lib.unescape(match.group(1))
        if not raw:
            return match.group(0)
        if raw.startswith(("http://", "https://", "#")):
            return match.group(0)
        if _WINDOWS_ABS_RE.match(raw):
            return match.group(0)
        normalized = raw[2:] if raw.startswith("./") else raw
        if normalized.startswith(("archive/", "instruction/", "report_notes/", "report/", "supporting/", "report_views/")):
            fixed = f"{base}/{normalized}"
            return f'href="{html_lib.escape(fixed, quote=True)}"'
        return match.group(0)

    return _VIEWER_HREF_RE.sub(replace, html_text)


class _ViewerLinkParser(HTMLParser):
    def __init__(self, viewer_map: dict[str, dict[str, str]]) -> None:
        super().__init__(convert_charrefs=False)
        self._parts: list[str] = []
        self._viewer_map = viewer_map

    def handle_starttag(self, tag: str, attrs: list[tuple[str, Optional[str]]]) -> None:
        if tag != "a":
            self._parts.append(self._rebuild_tag(tag, attrs, closed=False))
            return
        attr_map = {key: value for key, value in attrs}
        href = attr_map.get("href") or ""
        normalized = href
        if href.startswith("./"):
            normalized = href
        elif href.startswith("archive/") or href.startswith("instruction/") or href.startswith("report/"):
            normalized = f"./{href}"
        elif href.startswith("report_notes/") or href.startswith("supporting/"):
            normalized = f"./{href}"
        if normalized in self._viewer_map:
            viewer = self._viewer_map[normalized]["viewer"]
            raw = self._viewer_map[normalized]["raw"]
            attr_map["href"] = viewer
            attr_map["data-viewer"] = viewer
            attr_map["data-raw"] = raw
            classes = attr_map.get("class") or ""
            attr_map["class"] = (classes + " viewer-link").strip()
        elif href.startswith("http://") or href.startswith("https://"):
            attr_map.setdefault("target", "_blank")
            attr_map.setdefault("rel", "noopener")
        self._parts.append(self._rebuild_tag(tag, list(attr_map.items()), closed=False))

    def handle_startendtag(self, tag: str, attrs: list[tuple[str, Optional[str]]]) -> None:
        self._parts.append(self._rebuild_tag(tag, attrs, closed=True))

    def handle_endtag(self, tag: str) -> None:
        self._parts.append(f"</{tag}>")

    def handle_data(self, data: str) -> None:
        self._parts.append(data)

    def handle_entityref(self, name: str) -> None:
        self._parts.append(f"&{name};")

    def handle_charref(self, name: str) -> None:
        self._parts.append(f"&#{name};")

    def handle_comment(self, data: str) -> None:
        self._parts.append(f"<!--{data}-->")

    def _rebuild_tag(self, tag: str, attrs: list[tuple[str, Optional[str]]], closed: bool) -> str:
        if not attrs:
            return f"<{tag}{' /' if closed else ''}>"
        parts = []
        for key, value in attrs:
            if value is None:
                parts.append(key)
            else:
                parts.append(f'{key}=\"{html_lib.escape(value, quote=True)}\"')
        attrs_str = " ".join(parts)
        return f"<{tag} {attrs_str}{' /' if closed else ''}>"

    def get_html(self) -> str:
        return "".join(self._parts)


def inject_viewer_links(html_text: str, viewer_map: dict[str, dict[str, str]]) -> str:
    if not viewer_map:
        return html_text
    parser = _ViewerLinkParser(viewer_map)
    parser.feed(html_text)
    return parser.get_html()


def clean_citation_labels(html_text: str) -> str:
    pattern = re.compile(r'(<a\b[^>]*>)\\\[(\d+)\\\](</a>)')
    return pattern.sub(r'\1[\2]\3', html_text)


def build_text_meta_index(
    run_dir: Path,
    archive_dir: Path,
    supporting_dir: Optional[Path],
) -> dict[str, dict]:
    meta_map: dict[str, dict] = {}

    def merge_meta(existing: dict, incoming: dict) -> dict:
        merged = dict(existing)
        for key, value in incoming.items():
            if value and not merged.get(key):
                merged[key] = value
        return merged

    def add_meta(rel_path: Optional[str], payload: dict) -> None:
        if not rel_path:
            return
        for variant in {rel_path, rel_path.lstrip("./")}:
            if variant in meta_map:
                meta_map[variant] = merge_meta(meta_map[variant], payload)
            else:
                meta_map[variant] = payload

    arxiv = archive_dir / "arxiv" / "papers.jsonl"
    if arxiv.exists():
        for entry in iter_jsonl(arxiv):
            arxiv_id = entry.get("arxiv_id")
            if not arxiv_id:
                continue
            text_path = archive_dir / "arxiv" / "text" / f"{arxiv_id}.txt"
            if not text_path.exists():
                continue
            rel_text = f"./{text_path.relative_to(run_dir).as_posix()}"
            pdf_path = archive_dir / "arxiv" / "pdf" / f"{arxiv_id}.pdf"
            payload = {
                "title": entry.get("title"),
                "summary": entry.get("summary"),
                "source_url": entry.get("entry_id") or entry.get("pdf_url"),
                "pdf_path": f"./{pdf_path.relative_to(run_dir).as_posix()}" if pdf_path.exists() else None,
                "authors": normalize_author_list(entry.get("authors")),
                "published": entry.get("published") or entry.get("updated"),
                "source": "arxiv",
            }
            add_meta(rel_text, payload)

    openalex = archive_dir / "openalex" / "works.jsonl"
    if openalex.exists():
        for entry in iter_jsonl(openalex):
            work = entry.get("work") or entry
            short_id = work.get("openalex_id_short")
            if not short_id:
                continue
            text_path = archive_dir / "openalex" / "text" / f"{short_id}.txt"
            if not text_path.exists():
                continue
            rel_text = f"./{text_path.relative_to(run_dir).as_posix()}"
            pdf_path = archive_dir / "openalex" / "pdf" / f"{short_id}.pdf"
            payload = {
                "title": work.get("title"),
                "summary": work.get("abstract"),
                "source_url": work.get("landing_page_url") or work.get("doi") or work.get("pdf_url"),
                "pdf_path": f"./{pdf_path.relative_to(run_dir).as_posix()}" if pdf_path.exists() else None,
                "authors": extract_openalex_authors(work),
                "published": resolve_openalex_published(work),
                "journal": resolve_openalex_journal(work),
                "cited_by_count": work.get("cited_by_count"),
                "source": "openalex",
            }
            add_meta(rel_text, payload)

    youtube = archive_dir / "youtube" / "videos.jsonl"
    if youtube.exists():
        for entry in iter_jsonl(youtube):
            video = entry.get("video") or entry
            rel_text = coerce_rel_path(video.get("transcript_path") or entry.get("transcript_path"), run_dir)
            if not rel_text:
                continue
            payload = {
                "title": video.get("title"),
                "summary": video.get("summary"),
                "source_url": video.get("url") or entry.get("direct_url"),
                "published": video.get("published_at"),
                "channel": video.get("channel_title"),
                "source": "youtube",
            }
            add_meta(rel_text, payload)

    tavily_search = archive_dir / "tavily_search.jsonl"
    tavily_extract_dir = archive_dir / "tavily_extract"
    if tavily_search.exists() and tavily_extract_dir.exists():
        for entry in iter_jsonl(tavily_search):
            results = entry.get("result", {}).get("results") or entry.get("results") or []
            for item in results:
                url = feder_tools.normalize_url(item.get("url"))
                if not url:
                    continue
                safe = feder_tools.safe_filename(url)
                for text_path in tavily_extract_dir.glob(f"*_{safe}.txt"):
                    rel_text = f"./{text_path.relative_to(run_dir).as_posix()}"
                    payload = {
                        "title": item.get("title"),
                        "source_url": url,
                        "source": "tavily",
                    }
                    add_meta(rel_text, payload)

    web_text_dir = archive_dir / "web" / "text"
    if web_text_dir.exists():
        for text_path in web_text_dir.glob("*.txt"):
            rel_text = f"./{text_path.relative_to(run_dir).as_posix()}"
            pdf_path = archive_dir / "web" / "pdf" / f"{text_path.stem}.pdf"
            payload = {
                "pdf_path": f"./{pdf_path.relative_to(run_dir).as_posix()}" if pdf_path.exists() else None,
                "source": "web",
            }
            add_meta(rel_text, payload)

    if supporting_dir and supporting_dir.exists():
        fetch = supporting_dir / "web_fetch.jsonl"
        if fetch.exists():
            for entry in iter_jsonl(fetch):
                rel_text = coerce_rel_path(entry.get("text_path") or entry.get("extract_path"), run_dir)
                if not rel_text:
                    continue
                payload = {
                    "title": entry.get("title"),
                    "source_url": entry.get("url"),
                    "pdf_path": coerce_rel_path(entry.get("pdf_path"), run_dir),
                    "source": "supporting_web",
                }
                add_meta(rel_text, payload)
        support_text_dir = supporting_dir / "web_text"
        if support_text_dir.exists():
            for text_path in support_text_dir.glob("*.txt"):
                rel_text = f"./{text_path.relative_to(run_dir).as_posix()}"
                pdf_path = supporting_dir / "web_pdf" / f"{text_path.stem}.pdf"
                payload = {
                    "pdf_path": f"./{pdf_path.relative_to(run_dir).as_posix()}" if pdf_path.exists() else None,
                    "source": "supporting_web",
                }
                add_meta(rel_text, payload)

    local_manifest = archive_dir / "local" / "manifest.jsonl"
    if local_manifest.exists():
        for entry in iter_jsonl(local_manifest):
            rel_text = coerce_rel_path(entry.get("content_path"), run_dir)
            if not rel_text:
                continue
            title = entry.get("title") or entry.get("file_name") or Path(entry.get("source_path") or "").name
            file_ext = str(entry.get("file_ext") or "").lower()
            raw_path = coerce_rel_path(entry.get("raw_path"), run_dir)
            payload = {
                "title": title,
                "source_url": entry.get("source_path"),
                "published": entry.get("modified"),
                "source": "local",
                "extra": entry.get("file_ext"),
            }
            if raw_path:
                payload["raw_path"] = raw_path
            if file_ext == ".pptx":
                payload["pptx_path"] = raw_path or coerce_rel_path(entry.get("raw_path"), run_dir)
            add_meta(rel_text, payload)

    return meta_map


def build_viewer_map(
    report_text: str,
    run_dir: Path,
    archive_dir: Path,
    supporting_dir: Optional[Path],
    report_dir: Path,
    viewer_dir: Path,
    max_chars: int,
) -> dict[str, dict[str, str]]:
    viewer_dir.mkdir(parents=True, exist_ok=True)
    mapping: dict[str, dict[str, str]] = {}
    rel_paths = sorted(set(extract_cited_paths(report_text)))
    meta_index = build_text_meta_index(run_dir, archive_dir, supporting_dir)
    summary_max = min(1600, max_chars)
    for rel in rel_paths:
        rel_clean = rel.lstrip("./")
        path = (run_dir / rel_clean).resolve()
        if not path.exists() or run_dir not in path.parents and path != run_dir:
            continue
        if path.is_dir():
            continue
        slug = slugify_url(rel_clean)
        viewer_path = viewer_dir / f"{slug}.html"
        body_html = ""
        truncated = False
        suffix = path.suffix.lower()
        if suffix in {".pptx", ".ppt", ".docx", ".doc", ".xlsx", ".xls"}:
            continue
        if suffix in {".md", ".markdown"}:
            text = path.read_text(encoding="utf-8", errors="replace")
            text, truncated = truncate_for_view(text, max_chars)
            body_html = linkify_html(markdown_to_html(text))
        elif suffix in {".json", ".jsonl"}:
            if suffix == ".json":
                try:
                    data = json.loads(path.read_text(encoding="utf-8", errors="replace"))
                except Exception:
                    data = path.read_text(encoding="utf-8", errors="replace")
                payload = json.dumps(data, ensure_ascii=False, indent=2) if isinstance(data, (dict, list)) else str(data)
            else:
                lines = path.read_text(encoding="utf-8", errors="replace").splitlines()
                items = []
                truncated_items = False
                for line in lines:
                    if not line.strip():
                        continue
                    try:
                        items.append(json.loads(line))
                    except json.JSONDecodeError:
                        items.append(line)
                    if len(items) >= 200:
                        truncated_items = True
                        break
                payload = json.dumps(items, ensure_ascii=False, indent=2)
                if truncated_items:
                    payload = "[showing first 200 entries]\n" + payload
            payload, truncated = truncate_for_view(payload, max_chars)
            body_html = f"<pre>{linkify_plain_text(payload)}</pre>"
        elif suffix == ".pdf":
            rel_pdf = os.path.relpath(path, viewer_dir).replace("\\", "/")
            body_html = f'<iframe src="{html_lib.escape(rel_pdf)}" style="width:100%; height:80vh; border:0;"></iframe>'
        else:
            text = path.read_text(encoding="utf-8", errors="replace")
            text, truncated = truncate_for_view(text, max_chars)
            body_html = f"<pre>{linkify_plain_text(text)}</pre>"
            meta = meta_index.get(rel) or meta_index.get(rel_clean) or meta_index.get(f"./{rel_clean}")
            if meta:
                meta_lines = []
                title = meta.get("title")
                if title:
                    meta_lines.append(f"<p><strong>Title:</strong> {html_lib.escape(title)}</p>")
                authors = meta.get("authors")
                if authors:
                    meta_lines.append(f"<p><strong>Authors:</strong> {html_lib.escape(str(authors))}</p>")
                journal = meta.get("journal")
                if journal:
                    meta_lines.append(f"<p><strong>Journal:</strong> {html_lib.escape(str(journal))}</p>")
                published = meta.get("published")
                if published:
                    meta_lines.append(f"<p><strong>Published:</strong> {html_lib.escape(str(published))}</p>")
                channel = meta.get("channel")
                if channel:
                    meta_lines.append(f"<p><strong>Channel:</strong> {html_lib.escape(str(channel))}</p>")
                source_url = meta.get("source_url")
                if source_url:
                    safe = html_lib.escape(str(source_url))
                    meta_lines.append(f"<p><strong>Source:</strong> <a href=\"{safe}\">{safe}</a></p>")
                pdf_path = meta.get("pdf_path")
                if pdf_path:
                    pdf_abs = (run_dir / pdf_path.lstrip("./")).resolve()
                    if pdf_abs.exists():
                        pdf_href = os.path.relpath(pdf_abs, viewer_dir).replace("\\", "/")
                        meta_lines.append(
                            f"<p><strong>PDF:</strong> <a href=\"{html_lib.escape(pdf_href)}\">{html_lib.escape(pdf_path)}</a></p>"
                        )
                    else:
                        meta_lines.append(f"<p><strong>PDF:</strong> {html_lib.escape(pdf_path)}</p>")
                summary = meta.get("summary")
                if summary:
                    summary_text, summary_truncated = truncate_for_view(str(summary), summary_max)
                    summary_html = linkify_plain_text(summary_text)
                    if summary_truncated:
                        summary_html += " <em>[truncated]</em>"
                    meta_lines.append(f"<p><strong>Summary:</strong><br />{summary_html}</p>")
                if meta_lines:
                    meta_html = "<div class=\"meta-block\">" + "".join(meta_lines) + "</div>"
                    body_html = f"{meta_html}{body_html}"
        if truncated:
            body_html = f"<p><em>Truncated view for readability.</em></p>{body_html}"
        body_html = rewrite_viewer_links(body_html, run_dir, viewer_dir)
        viewer_html = render_viewer_html(rel_clean, body_html)
        viewer_path.write_text(viewer_html, encoding="utf-8")
        viewer_href = os.path.relpath(viewer_path, report_dir).replace("\\", "/")
        raw_href = os.path.relpath(path, report_dir).replace("\\", "/")
        for variant in {rel, f"./{rel_clean}", rel_clean}:
            mapping[variant] = {"viewer": viewer_href, "raw": raw_href}
    return mapping


def parse_query_lines(text: str, max_queries: int) -> list[str]:
    queries: list[str] = []
    candidate = text.strip()
    if candidate.startswith("[") or candidate.startswith("{"):
        try:
            payload = json.loads(candidate)
            if isinstance(payload, list):
                for item in payload:
                    if isinstance(item, str) and item.strip():
                        queries.append(item.strip())
        except Exception:
            pass
    if not queries:
        for line in text.splitlines():
            cleaned = line.strip().lstrip("-*").strip()
            if not cleaned:
                continue
            if cleaned.lower().startswith("query"):
                cleaned = cleaned.split(":", 1)[-1].strip()
            if cleaned and cleaned not in queries:
                queries.append(cleaned)
            if len(queries) >= max_queries:
                break
    return queries[:max_queries]


def run_web_research(
    supporting_dir: Path,
    queries: list[str],
    max_results: int,
    max_fetch: int,
    max_chars: int,
    max_pdf_pages: int,
) -> tuple[str, list[dict]]:
    return run_supporting_web_research(
        supporting_dir,
        queries,
        max_results,
        max_fetch,
        max_chars,
        max_pdf_pages,
        pdf_text_reader=read_pdf_with_fitz,
    )


class SafeFilesystemBackend:
    def __init__(
        self,
        root_dir: Path,
        max_read_chars: int = 6000,
        max_total_chars: int = 20000,
        max_list_entries: int = 300,
        max_grep_matches: int = 200,
    ) -> None:
        from deepagents.backends import FilesystemBackend  # type: ignore
        from deepagents.backends.protocol import EditResult, WriteResult  # type: ignore

        class _Backend(FilesystemBackend):
            def __init__(
                self,
                root_dir: Path,
                virtual_mode: bool = True,
                max_file_size_mb: int = 10,
                max_read_chars: int = 6000,
                max_total_chars: int = 20000,
                max_list_entries: int = 300,
                max_grep_matches: int = 200,
            ) -> None:
                super().__init__(root_dir=root_dir, virtual_mode=virtual_mode, max_file_size_mb=max_file_size_mb)
                self._max_read_chars = max(1000, int(max_read_chars))
                self._max_total_chars = max(4000, int(max_total_chars))
                self._used_chars = 0
                self._max_list_entries = max(50, int(max_list_entries))
                self._max_grep_matches = max(20, int(max_grep_matches))

            def _map_windows_path(self, normalized: str) -> Optional[str]:
                root_norm = str(self.cwd).replace("\\", "/")
                if normalized.lower().startswith(root_norm.lower()):
                    rel = normalized[len(root_norm) :].lstrip("/")
                    return f"/{rel}" if rel else "/"
                for marker in ("/archive", "/instruction", "/report", "/report_notes", "/supporting", "/report_views"):
                    idx = normalized.lower().find(marker)
                    if idx != -1:
                        rel = normalized[idx + 1 :]
                        return f"/{rel}"
                return None

            def _resolve_path(self, key: str) -> Path:  # type: ignore[override]
                if self.virtual_mode:
                    raw = os.fspath(key) if isinstance(key, (str, os.PathLike)) else None
                    if isinstance(raw, str) and raw:
                        normalized = raw.strip().replace("\\", "/")
                        if normalized.startswith("//?/"):
                            normalized = normalized[4:]
                        if _WINDOWS_ABS_RE.match(normalized):
                            mapped = self._map_windows_path(normalized)
                            if mapped is not None:
                                return super()._resolve_path(mapped)
                return super()._resolve_path(key)

            def _apply_total_budget(self, text: str) -> str:
                if not isinstance(text, str) or not text:
                    return text
                remaining = self._max_total_chars - self._used_chars
                if remaining <= 0:
                    return (
                        "[error] filesystem tool read budget exhausted for this stage. "
                        "Narrow scope or continue with listed/indexed sources."
                    )
                if len(text) > remaining:
                    text = truncate_text_middle(text, remaining)
                self._used_chars += len(text)
                return text

            def read(self, file_path: str, offset: int = 0, limit: int = 2000) -> str:  # type: ignore[override]
                # Keep default filesystem-tool reads bounded to avoid exploding model context.
                bounded_limit = min(max(1, int(limit or 1)), 240)
                try:
                    content = super().read(file_path, offset=offset, limit=bounded_limit)
                except Exception as exc:
                    # Do not hard-fail the whole stage when one malformed file (e.g., broken PDF) is read.
                    return (
                        f"[error] Failed to read '{file_path}': {exc}. "
                        "Skip this file and continue with other sources."
                    )
                if isinstance(content, str) and len(content) > self._max_read_chars:
                    content = truncate_text_middle(content, self._max_read_chars)
                return self._apply_total_budget(content)

            def ls_info(self, path: str):  # type: ignore[override]
                info = super().ls_info(path)
                if len(info) <= self._max_list_entries:
                    return info
                return info[: self._max_list_entries]

            def grep_raw(self, pattern: str, path: str | None = None, glob: str | None = None):  # type: ignore[override]
                result = super().grep_raw(pattern, path=path, glob=glob)
                if isinstance(result, list) and len(result) > self._max_grep_matches:
                    return result[: self._max_grep_matches]
                return result

            def write(self, file_path: str, content: str) -> WriteResult:  # type: ignore[override]
                # The report pipeline manages artifacts itself; disable ad-hoc writes from model tools.
                return WriteResult(error="write_file is disabled in this pipeline. Return content in the agent response.")

            def edit(
                self,
                file_path: str,
                old_string: str,
                new_string: str,
                replace_all: bool = False,
            ) -> EditResult:  # type: ignore[override]
                # Prevent large in-memory replace operations from model tool misuse.
                if len(old_string or "") > 20000 or len(new_string or "") > 20000:
                    return EditResult(error="edit_file payload too large; use structured response instead.")
                return EditResult(error="edit_file is disabled in this pipeline. Return revised content in agent response.")

        self._backend = _Backend(
            root_dir=root_dir,
            virtual_mode=True,
            max_read_chars=max_read_chars,
            max_total_chars=max_total_chars,
            max_list_entries=max_list_entries,
            max_grep_matches=max_grep_matches,
        )

    def __getattr__(self, name: str):
        return getattr(self._backend, name)


def iter_jsonl(path: Path):
    with path.open("r", encoding="utf-8", errors="replace") as handle:
        for line in handle:
            line = line.strip()
            if not line:
                continue
            try:
                yield json.loads(line)
            except json.JSONDecodeError:
                continue


def extract_openalex_authors(work: dict) -> Optional[str]:
    authors = work.get("authors")
    if isinstance(authors, list):
        names: list[str] = []
        for entry in authors:
            if isinstance(entry, dict):
                name = entry.get("display_name") or entry.get("name")
                if name:
                    names.append(name)
            elif entry:
                names.append(str(entry))
        normalized = normalize_author_list(names)
    else:
        normalized = normalize_author_list(authors)
    if normalized:
        return normalized
    names: list[str] = []
    for entry in work.get("authorships") or []:
        author = entry.get("author") or {}
        name = author.get("display_name") or author.get("name")
        if name:
            names.append(name)
    return normalize_author_list(names)


def resolve_openalex_journal(work: dict) -> Optional[str]:
    journal = work.get("journal")
    if journal:
        if isinstance(journal, dict):
            name = journal.get("display_name") or journal.get("name")
            if name:
                return name
        elif isinstance(journal, str):
            return journal
    host = work.get("host_venue") or {}
    name = host.get("display_name")
    if name:
        return name
    primary = work.get("primary_location") or {}
    source = primary.get("source") or {}
    if isinstance(source, dict):
        name = source.get("display_name")
        if name:
            return name
    return None


def resolve_openalex_published(work: dict) -> Optional[str]:
    return work.get("publication_date") or work.get("publication_year") or work.get("published")


def load_openalex_meta(archive_dir: Path) -> dict[str, dict]:
    meta: dict[str, dict] = {}
    openalex = archive_dir / "openalex" / "works.jsonl"
    if not openalex.exists():
        return meta
    for entry in iter_jsonl(openalex):
        work = entry.get("work") or entry
        short_id = work.get("openalex_id_short")
        if not short_id:
            continue
        meta[short_id] = work
    return meta


def collect_references(
    archive_dir: Path,
    run_dir: Path,
    max_refs: int,
    supporting_dir: Optional[Path] = None,
) -> list[dict]:
    refs: list[dict] = []
    seen: set[str] = set()

    def add_ref(
        url: Optional[str],
        title: Optional[str],
        source: str,
        archive_path: Path,
        extra: Optional[str] = None,
        meta: Optional[dict] = None,
    ) -> None:
        if not url:
            return
        url = url.strip()
        if not url or url in seen:
            return
        seen.add(url)
        payload = {
            "title": title or url,
            "url": url,
            "source": source,
            "archive": f"./{archive_path.relative_to(run_dir).as_posix()}",
            "extra": extra,
        }
        if meta:
            payload.update(
                {
                    "cited_by_count": meta.get("cited_by_count"),
                    "journal": meta.get("journal"),
                    "published": meta.get("published"),
                    "openalex_id_short": meta.get("openalex_id_short"),
                    "authors": meta.get("authors"),
                    "doi": meta.get("doi"),
                    "source_label": meta.get("source_label"),
                }
            )
        refs.append(payload)

    def limit_reached() -> bool:
        return max_refs > 0 and len(refs) >= max_refs

    tavily = archive_dir / "tavily_search.jsonl"
    if tavily.exists():
        for entry in iter_jsonl(tavily):
            results = entry.get("result", {}).get("results") or entry.get("results") or []
            for item in results:
                add_ref(item.get("url"), item.get("title"), "tavily", tavily)
                if limit_reached():
                    return refs

    openalex = archive_dir / "openalex" / "works.jsonl"
    if openalex.exists():
        for entry in iter_jsonl(openalex):
            work = entry.get("work") or entry
            url = work.get("landing_page_url") or work.get("doi") or work.get("pdf_url")
            title = work.get("title")
            meta = {
                "cited_by_count": work.get("cited_by_count"),
                "journal": resolve_openalex_journal(work),
                "published": resolve_openalex_published(work),
                "openalex_id_short": work.get("openalex_id_short"),
                "authors": extract_openalex_authors(work),
                "doi": work.get("doi"),
            }
            add_ref(url, title, "openalex", openalex, meta=meta)
            if limit_reached():
                return refs

    arxiv = archive_dir / "arxiv" / "papers.jsonl"
    if arxiv.exists():
        for entry in iter_jsonl(arxiv):
            url = entry.get("entry_id") or entry.get("pdf_url")
            title = entry.get("title")
            meta = {
                "authors": normalize_author_list(entry.get("authors")),
                "published": entry.get("published") or entry.get("updated"),
            }
            add_ref(url, title, "arxiv", arxiv, meta=meta)
            if limit_reached():
                return refs

    youtube = archive_dir / "youtube" / "videos.jsonl"
    if youtube.exists():
        for entry in iter_jsonl(youtube):
            video = entry.get("video") or {}
            url = video.get("url") or entry.get("direct_url")
            title = video.get("title") or entry.get("title")
            extra = None
            channel = video.get("channel_title")
            if channel:
                extra = f"channel: {channel}"
            add_ref(url, title, "youtube", youtube, extra=extra)
            if limit_reached():
                return refs

    local = archive_dir / "local" / "manifest.jsonl"
    if local.exists():
        for entry in iter_jsonl(local):
            source_path = entry.get("source_path") or entry.get("path")
            title = entry.get("title") or source_path
            add_ref(source_path, title, "local", local)
            if limit_reached():
                return refs

    if supporting_dir and supporting_dir.exists():
        support_search = supporting_dir / "web_search.jsonl"
        if support_search.exists():
            for entry in iter_jsonl(support_search):
                results = entry.get("result", {}).get("results") or entry.get("results") or []
                for item in results:
                    add_ref(item.get("url"), item.get("title"), "supporting_web", support_search)
                    if limit_reached():
                        return refs
        support_fetch = supporting_dir / "web_fetch.jsonl"
        if support_fetch.exists():
            for entry in iter_jsonl(support_fetch):
                add_ref(entry.get("url"), entry.get("title"), "supporting_web", support_fetch)
                if limit_reached():
                    return refs

    return refs


def render_references_md(refs: list[dict]) -> str:
    if not refs:
        return ""
    lines = ["", "## Source Index (Auto)", ""]
    for ref in refs:
        extra = f" ({ref['extra']})" if ref.get("extra") else ""
        title = ref["title"]
        url = ref["url"]
        archive = ref["archive"]
        lines.append(
            f"- [{title}]({url}){extra} [source: {ref['source']}; archive: [{archive}]({archive})]"
        )
    return "\n".join(lines)


def extract_keywords(text: Optional[str]) -> list[str]:
    if not text:
        return []
    tokens = re.findall(r"[A-Za-z]{3,}|[가-힣]{2,}", text)
    stop = {
        "focus",
        "insight",
        "insights",
        "trend",
        "trends",
        "implication",
        "implications",
        "analysis",
        "review",
        "report",
        "paper",
        "papers",
        "research",
        "technical",
        "technology",
        "applications",
    }
    cleaned = []
    for token in tokens:
        low = token.lower()
        if low in stop:
            continue
        cleaned.append(low)
    return sorted(set(cleaned))


def extract_urls(text: Optional[str]) -> list[str]:
    if not text:
        return []
    return _URL_RE.findall(text)


def extract_cited_paths(text: Optional[str]) -> list[str]:
    if not text:
        return []
    paths = []
    for match in _CITED_PATH_RE.finditer(text):
        paths.append(match.group(1))
    return paths


def resolve_related_pdf_path(
    rel_path: str,
    run_dir: Path,
    meta_index: dict[str, dict],
) -> Optional[str]:
    rel_clean = rel_path.lstrip("./")
    if rel_clean.lower().endswith(".pdf"):
        pdf_abs = (run_dir / rel_clean).resolve()
        if pdf_abs.exists():
            return f"./{pdf_abs.relative_to(run_dir).as_posix()}"
        return None
    meta = meta_index.get(rel_path) or meta_index.get(rel_clean) or meta_index.get(f"./{rel_clean}")
    if meta:
        pdf_path = meta.get("pdf_path")
        if pdf_path:
            pdf_abs = (run_dir / pdf_path.lstrip("./")).resolve()
            if pdf_abs.exists():
                return f"./{pdf_abs.relative_to(run_dir).as_posix()}"
    path = (run_dir / rel_clean).resolve()
    if path.exists():
        if path.parent.name == "text":
            candidate = path.parent.parent / "pdf" / f"{path.stem}.pdf"
        elif path.parent.name == "web_text":
            candidate = path.parent.parent / "web_pdf" / f"{path.stem}.pdf"
        else:
            candidate = None
        if candidate and candidate.exists():
            return f"./{candidate.relative_to(run_dir).as_posix()}"
    return None


def resolve_related_pptx_path(
    rel_path: str,
    run_dir: Path,
    meta_index: dict[str, dict],
) -> Optional[str]:
    rel_clean = rel_path.lstrip("./")
    if rel_clean.lower().endswith(".pptx"):
        pptx_abs = (run_dir / rel_clean).resolve()
        if pptx_abs.exists():
            return f"./{pptx_abs.relative_to(run_dir).as_posix()}"
        return None
    meta = meta_index.get(rel_path) or meta_index.get(rel_clean) or meta_index.get(f"./{rel_clean}")
    if meta:
        pptx_path = meta.get("pptx_path")
        if pptx_path:
            pptx_abs = (run_dir / pptx_path.lstrip("./")).resolve()
            if pptx_abs.exists():
                return f"./{pptx_abs.relative_to(run_dir).as_posix()}"
    return None


def find_section_spans(text: str, output_format: str) -> list[tuple[str, int, int]]:
    if output_format == "tex":
        pattern = re.compile(r"^\\section\\*?\\{([^}]+)\\}", re.MULTILINE)
    else:
        pattern = re.compile(r"^##\\s+(.+)$", re.MULTILINE)
    matches = list(pattern.finditer(text))
    spans: list[tuple[str, int, int]] = []
    for idx, match in enumerate(matches):
        start = match.start()
        end = matches[idx + 1].start() if idx + 1 < len(matches) else len(text)
        spans.append((match.group(1).strip(), start, end))
    return spans


def extract_pdf_captions(
    pdf_path: Path,
    max_pages: int,
    pages: Optional[Iterable[int]] = None,
) -> dict[int, list[str]]:
    try:
        import pdfplumber  # type: ignore
    except Exception:
        return {}
    captions: dict[int, list[str]] = {}
    try:
        with pdfplumber.open(pdf_path) as pdf:
            if pages:
                page_indices = sorted({page - 1 for page in pages if page > 0})
                if max_pages > 0:
                    page_indices = page_indices[:max_pages]
            else:
                page_count = min(len(pdf.pages), max_pages) if max_pages > 0 else len(pdf.pages)
                page_indices = list(range(page_count))
            for page_index in page_indices:
                if page_index < 0 or page_index >= len(pdf.pages):
                    continue
                try:
                    text = pdf.pages[page_index].extract_text() or ""
                except Exception:
                    continue
                lines = [line.strip() for line in text.splitlines() if line.strip()]
                if not lines:
                    continue
                found: list[str] = []
                for idx, line in enumerate(lines):
                    if not _FIGURE_CAPTION_RE.match(line):
                        continue
                    caption = line
                    if idx + 1 < len(lines) and len(caption) < 140:
                        follow = lines[idx + 1]
                        if follow and not _FIGURE_CAPTION_RE.match(follow):
                            caption = f"{caption} {follow}"
                    found.append(caption)
                if found:
                    captions[page_index + 1] = found
    except Exception:
        return {}
    return captions


def should_expand_appendix(section_text: str, output_format: str) -> bool:
    if not section_text:
        return True
    if output_format == "tex":
        body = re.sub(r"^\\section\\*?\\{[^}]+\\}", "", section_text, flags=re.MULTILINE).strip()
        sub_count = len(re.findall(r"^\\subsection\\*?\\{", body, flags=re.MULTILINE))
    else:
        body = re.sub(r"^##\\s+.+$", "", section_text, count=1, flags=re.MULTILINE).strip()
        sub_count = len(re.findall(r"^###\\s+.+$", body, flags=re.MULTILINE))
    if len(body) < 300:
        return True
    if sub_count < 2:
        return True
    return False


def build_appendix_block(
    output_format: str,
    refs: list[dict],
    run_dir: Path,
    notes_dir: Path,
    language: str,
) -> str:
    key_refs = refs[:6]
    artifacts = [
        ("Source index", notes_dir / "source_index.jsonl"),
        ("Source triage", notes_dir / "source_triage.md"),
        ("Evidence notes", notes_dir / "evidence_notes.md"),
        ("Report workflow", notes_dir / "report_workflow.md"),
    ]
    checklist = [
        "원문 링크/파일 경로를 확인했는가?",
        "근거 유형(primary/supporting)을 명확히 구분했는가?",
        "핵심 주장마다 출처가 연결되어 있는가?",
        "재현성에 필요한 입력/설정이 기록되었는가?",
        "범위/한계가 명시되었는가?",
    ]
    if output_format == "tex":
        lines = [
            "",
            "\\subsection*{Key Sources}",
            "\\begin{itemize}",
        ]
        for ref in key_refs:
            title = latex_escape(str(ref.get("title") or ref.get("url") or "source"))
            url = latex_escape(str(ref.get("url") or ""))
            archive = latex_escape(str(ref.get("archive") or ""))
            lines.append(f"\\item {title} [{url}] (archive: {archive})")
        lines.extend(["\\end{itemize}", "", "\\subsection*{Artifacts}", "\\begin{itemize}"])
        for label, path in artifacts:
            if path.exists():
                lines.append(f"\\item {latex_escape(label)} [{latex_escape(rel_path_or_abs(path, run_dir))}]")
        lines.extend(["\\end{itemize}", "", "\\subsection*{Checklist}", "\\begin{itemize}"])
        for item in checklist:
            lines.append(f"\\item {latex_escape(item)}")
        lines.append("\\end{itemize}")
        return "\n".join(lines).strip()
    lines = [
        "",
        "### Key Sources",
    ]
    for ref in key_refs:
        title = str(ref.get("title") or ref.get("url") or "source")
        url = str(ref.get("url") or "")
        archive = str(ref.get("archive") or "")
        if url and archive:
            lines.append(f"- {title} — [source]({url}) / [archive]({archive})")
        elif url:
            lines.append(f"- {title} — [source]({url})")
        elif archive:
            lines.append(f"- {title} — [archive]({archive})")
        else:
            lines.append(f"- {title}")
    lines.extend(["", "### Artifacts"])
    for label, path in artifacts:
        if path.exists():
            lines.append(f"- {label}: {rel_path_or_abs(path, run_dir)}")
    lines.extend(["", "### Checklist"])
    for item in checklist:
        lines.append(f"- {item}")
    return "\n".join(lines).strip()


def ensure_appendix_contents(
    report_text: str,
    output_format: str,
    refs: list[dict],
    run_dir: Path,
    notes_dir: Path,
    language: str,
) -> str:
    spans = find_section_spans(report_text, output_format)
    target_titles = {"appendix", "부록"}
    for title, start, end in spans:
        if title.strip().lower() not in target_titles:
            continue
        section_text = report_text[start:end]
        if not should_expand_appendix(section_text, output_format):
            return report_text
        if output_format == "tex":
            header_match = re.search(r"^\\section\\*?\\{[^}]+\\}", section_text, re.MULTILINE)
            header = header_match.group(0) if header_match else f"\\section*{{{title}}}"
            body = section_text[len(header) :].strip() if header_match else section_text.strip()
        else:
            header_line = section_text.splitlines()[0]
            header = header_line.strip()
            body = section_text[len(header_line) :].strip()
        appendix_block = build_appendix_block(output_format, refs, run_dir, notes_dir, language)
        merged_body = "\n\n".join(part for part in [body, appendix_block] if part)
        new_section = f"{header}\n\n{merged_body}\n"
        return report_text[:start] + new_section + report_text[end:]
    return report_text


def build_figure_plan(
    report_text: str,
    run_dir: Path,
    archive_dir: Path,
    supporting_dir: Optional[Path],
    output_format: str,
    max_per_pdf: int,
    min_area: int,
    renderer: str,
    dpi: int,
    notes_dir: Path,
    vision_model_name: Optional[str],
) -> list[dict]:
    meta_index = build_text_meta_index(run_dir, archive_dir, supporting_dir)
    spans = find_section_spans(report_text, output_format)
    cited_paths = extract_cited_paths(report_text)
    positions: dict[str, int] = {}
    for path in cited_paths:
        pos = report_text.find(path)
        if pos == -1:
            continue
        if path not in positions or pos < positions[path]:
            positions[path] = pos

    def find_section_title(pos: int) -> Optional[str]:
        for title, start, end in spans:
            if start <= pos < end:
                return title
        return None

    ordered = sorted(positions.items(), key=lambda item: item[1])
    pdf_targets: dict[str, dict] = {}
    pptx_targets: dict[str, dict] = {}
    for rel_path, pos in ordered:
        pdf_path = resolve_related_pdf_path(rel_path, run_dir, meta_index)
        if not pdf_path:
            pdf_path = None
        if pdf_path and pdf_path not in pdf_targets:
            pdf_targets[pdf_path] = {"source_path": rel_path, "section": find_section_title(pos), "position": pos}
        pptx_path = resolve_related_pptx_path(rel_path, run_dir, meta_index)
        if not pptx_path:
            continue
        if pptx_path in pptx_targets:
            continue
        pptx_targets[pptx_path] = {"source_path": rel_path, "section": find_section_title(pos), "position": pos}

    if not pdf_targets and not pptx_targets:
        return []

    figures_dir = run_dir / "report_assets" / "figures"
    entries: list[dict] = []
    for pdf_path, info in pdf_targets.items():
        pdf_abs = (run_dir / pdf_path.lstrip("./")).resolve()
        if not pdf_abs.exists():
            continue
        images = extract_pdf_images(pdf_abs, figures_dir, run_dir, max_per_pdf, min_area)
        render_limit = max_per_pdf - len(images)
        if renderer != "none" and render_limit > 0:
            rendered = render_pdf_pages(pdf_abs, figures_dir, run_dir, renderer, dpi, render_limit, min_area)
            if rendered:
                images.extend(rendered)
        if not images:
            continue
        pages = {img.get("page") for img in images if img.get("page")}
        captions = extract_pdf_captions(pdf_abs, max_per_pdf, pages)
        caption_index: dict[int, int] = {page: 0 for page in captions}
        for image in images:
            caption = None
            page_caps = captions.get(image.get("page", 0))
            if page_caps:
                idx = caption_index.get(image["page"], 0)
                if idx < len(page_caps):
                    caption = page_caps[idx]
                    caption_index[image["page"]] = idx + 1
            entry = {
                "pdf_path": image["pdf_path"],
                "image_path": image["image_path"],
                "page": image["page"],
                "width": image["width"],
                "height": image["height"],
                "area": int(image["width"]) * int(image["height"]),
                "method": image.get("method"),
                "caption": caption,
                "source_kind": "pdf",
                "source_file": image["pdf_path"],
                "source_path": info["source_path"],
                "section": info["section"],
                "position": info["position"],
            }
            entries.append(entry)

    for pptx_path, info in pptx_targets.items():
        pptx_abs = (run_dir / pptx_path.lstrip("./")).resolve()
        if not pptx_abs.exists():
            continue
        images = extract_pptx_images(pptx_abs, figures_dir, run_dir, max_per_pdf, min_area)
        if not images:
            continue
        for image in images:
            caption = image.get("slide_title") or None
            entry = {
                "pptx_path": image["pptx_path"],
                "image_path": image["image_path"],
                "slide": image["slide"],
                "page": image["slide"],
                "width": image["width"],
                "height": image["height"],
                "area": int(image["width"]) * int(image["height"]),
                "method": image.get("method"),
                "caption": caption,
                "source_kind": "pptx",
                "source_file": image["pptx_path"],
                "source_path": info["source_path"],
                "section": info["section"],
                "position": info["position"],
            }
            entries.append(entry)

    if entries:
        entries.sort(
            key=lambda item: (
                item.get("position", 1_000_000),
                item.get("page") or 0,
                -(item.get("area") or 0),
            )
        )
        if vision_model_name:
            vision_model = build_vision_model(vision_model_name)
            if vision_model is None:
                print("Vision model unavailable; skipping figure analysis.", file=sys.stderr)
            else:
                for entry in entries:
                    img_abs = (run_dir / entry["image_path"].lstrip("./")).resolve()
                    if not img_abs.exists():
                        continue
                    analysis = analyze_figure_with_vision(vision_model, img_abs)
                    if not analysis:
                        continue
                    entry["vision_summary"] = analysis.get("summary")
                    entry["vision_type"] = analysis.get("type")
                    entry["vision_relevance"] = analysis.get("relevance")
                    entry["vision_recommended"] = analysis.get("recommended")
                    if not entry.get("caption") and analysis.get("summary"):
                        entry["caption"] = str(analysis.get("summary"))
        for idx, entry in enumerate(entries, start=1):
            entry["candidate_id"] = f"fig-{idx:03d}"
    return entries


def truncate_text_head(text: str, limit: int = 140) -> str:
    if len(text) <= limit:
        return text
    return text[: limit - 1].rstrip() + "…"


def render_figure_callouts(
    entries: list[dict],
    output_format: str,
    report_dir: Path,
    run_dir: Path,
) -> str:
    items: list[str] = []
    for entry in entries:
        number = entry.get("figure_number")
        if not number:
            continue
        caption = entry.get("caption")
        if not caption:
            source_file = entry.get("source_file") or entry.get("pdf_path") or entry.get("pptx_path") or ""
            source_kind = entry.get("source_kind") or ("pptx" if str(source_file).lower().endswith(".pptx") else "pdf")
            source_name = Path(source_file).name if source_file else ""
            source_label = "PPTX" if source_kind == "pptx" else "PDF"
            caption = f"Source {source_label}: {source_name}" if source_name else f"Source {source_label} figure"
        caption = truncate_text_head(caption, 120)
        if output_format == "tex":
            items.append(f"Figure~\\ref{{fig:{number}}}: {latex_escape(caption)}")
        else:
            safe_caption = html_lib.escape(caption)
            items.append(f'<a href="#fig-{number}">Figure {number}</a>: {safe_caption}')
    if not items:
        return ""
    if output_format == "tex":
        return "\\paragraph{Figures referenced.} " + " ".join(items)
    return '<p class="figure-callout">Figures referenced: ' + "; ".join(items) + "</p>"


def write_figure_candidates(
    entries: list[dict],
    notes_dir: Path,
    run_dir: Path,
    report_dir: Path,
    viewer_dir: Path,
    max_preview: int = 32,
) -> Optional[Path]:
    if not entries:
        return None
    notes_dir.mkdir(parents=True, exist_ok=True)
    candidates_path = notes_dir / "figures_candidates.jsonl"
    with candidates_path.open("w", encoding="utf-8") as handle:
        for entry in entries:
            handle.write(json.dumps(entry, ensure_ascii=False) + "\n")
    select_path = notes_dir / "figures_selected.txt"
    if not select_path.exists():
        select_path.write_text(
            "# Add one candidate_id per line (e.g., fig-001)\n"
            "# Optional: add a custom caption after | (e.g., fig-001 | My caption)\n"
            "# Lines starting with '#' are ignored.\n",
            encoding="utf-8",
        )

    viewer_dir.mkdir(parents=True, exist_ok=True)
    cards: list[str] = [
        "<h1>Figure Candidates</h1>",
        "<p>Review candidates and add their IDs to "
        f"<code>{html_lib.escape(select_path.relative_to(run_dir).as_posix())}</code>, "
        "then rerun Federlicht to insert selected figures.</p>",
    ]
    for entry in entries[:max_preview]:
        candidate_id = entry.get("candidate_id") or "fig"
        img_abs = (run_dir / entry["image_path"].lstrip("./")).resolve()
        source_file = entry.get("source_file") or entry.get("pdf_path") or entry.get("pptx_path") or ""
        source_kind = entry.get("source_kind") or ("pptx" if str(source_file).lower().endswith(".pptx") else "pdf")
        source_abs = (run_dir / str(source_file).lstrip("./")).resolve()
        img_href = os.path.relpath(img_abs, viewer_dir).replace("\\", "/")
        source_href = os.path.relpath(source_abs, viewer_dir).replace("\\", "/")
        page_label = "slide" if source_kind == "pptx" else "p."
        page_value = entry.get("slide") or entry.get("page")
        caption = html_lib.escape(entry.get("caption") or "")
        vision_summary_raw = entry.get("vision_summary") or ""
        vision_summary = html_lib.escape(truncate_text_head(str(vision_summary_raw), 200)) if vision_summary_raw else ""
        vision_type = html_lib.escape(str(entry.get("vision_type") or "")).strip()
        vision_relevance = entry.get("vision_relevance")
        vision_recommended = str(entry.get("vision_recommended") or "").strip().lower()
        vision_line = ""
        if vision_summary:
            parts = [vision_summary]
            if vision_type:
                parts.append(f"type: {vision_type}")
            if vision_relevance is not None:
                parts.append(f"relevance: {vision_relevance}")
            if vision_recommended:
                parts.append(f"recommended: {vision_recommended}")
            vision_line = html_lib.escape(" | ".join(parts))
        cards.append(
            "\n".join(
                [
                    "<div class=\"report-figure\">",
                    f"<p><strong>{candidate_id}</strong> — {html_lib.escape(str(source_file))} ({page_label}{page_value})</p>",
                    f"<img src=\"{html_lib.escape(img_href)}\" alt=\"{candidate_id}\" />",
                    f"<p>{caption}</p>" if caption else "",
                    f"<p><em>Vision:</em> {vision_line}</p>" if vision_line else "",
                    f"<p>Source: <a href=\"{html_lib.escape(source_href)}\">{html_lib.escape(str(source_file))}</a></p>",
                    "</div>",
                ]
            )
        )
    if len(entries) > max_preview:
        cards.append(f"<p><em>Showing first {max_preview} candidates.</em></p>")
    preview_html = render_viewer_html("Figure Candidates", "\n".join(cards))
    preview_path = viewer_dir / "figures_preview.html"
    preview_path.write_text(preview_html, encoding="utf-8")
    return preview_path


def select_figures(
    entries: list[dict],
    selection_path: Path,
) -> list[dict]:
    if not selection_path.exists():
        return []
    raw = selection_path.read_text(encoding="utf-8", errors="replace").splitlines()
    tokens: set[str] = set()
    captions: dict[str, str] = {}
    for line in raw:
        if not line.strip() or line.lstrip().startswith("#"):
            continue
        parts = [part.strip() for part in line.split("|", 1)]
        cleaned = parts[0]
        if not cleaned:
            continue
        tokens.add(cleaned)
        if len(parts) > 1 and parts[1]:
            captions[cleaned] = parts[1]
    if not tokens:
        return []
    selected: list[dict] = []
    for entry in entries:
        candidate_id = entry.get("candidate_id")
        img_path = entry.get("image_path")
        if candidate_id in tokens:
            override = captions.get(candidate_id)
            if override:
                entry["caption"] = override
            selected.append(entry)
            continue
        if img_path in tokens or (isinstance(img_path, str) and img_path.lstrip("./") in tokens):
            override = captions.get(img_path) or captions.get(img_path.lstrip("./")) if isinstance(img_path, str) else None
            if override:
                entry["caption"] = override
            selected.append(entry)
    return selected


def auto_select_figures(entries: list[dict], prefer_recommended: bool = False) -> list[dict]:
    if not entries:
        return []
    if prefer_recommended:
        recommended = [
            entry
            for entry in entries
            if str(entry.get("vision_recommended") or "").strip().lower() == "yes"
        ]
        if recommended:
            return recommended
    return entries


def render_figure_block(
    entries: list[dict],
    output_format: str,
    report_dir: Path,
    run_dir: Path,
) -> str:
    blocks: list[str] = []
    for entry in entries:
        source_file = entry.get("source_file") or entry.get("pdf_path") or entry.get("pptx_path") or ""
        source_kind = entry.get("source_kind") or ("pptx" if str(source_file).lower().endswith(".pptx") else "pdf")
        page_label = "slide" if source_kind == "pptx" else "page"
        page = entry.get("slide") or entry.get("page")
        pdf_abs = (run_dir / str(source_file).lstrip("./")).resolve()
        img_abs = (run_dir / entry["image_path"].lstrip("./")).resolve()
        pdf_href = os.path.relpath(pdf_abs, report_dir).replace("\\", "/")
        img_href = os.path.relpath(img_abs, report_dir).replace("\\", "/")
        caption = entry.get("caption")
        number = entry.get("figure_number")
        figure_label = f"{number}" if number else ""
        if output_format == "tex":
            if caption:
                caption_text = (
                    f"{latex_escape(caption)}. Source: \\\\texttt{{{latex_escape(str(source_file))}}}, {page_label} {page}."
                )
            else:
                caption_text = f"Source: \\\\texttt{{{latex_escape(str(source_file))}}}, {page_label} {page}."
            blocks.append(
                "\n".join(
                    [
                        "\\begin{figure}[htbp]",
                        "\\centering",
                        f"\\includegraphics[width=\\linewidth]{{{latex_escape(img_href)}}}",
                        f"\\caption{{{caption_text}}}",
                        f"\\label{{fig:{figure_label}}}" if figure_label else "",
                        "\\end{figure}",
                    ]
                )
            )
        else:
            safe_img = html_lib.escape(img_href)
            safe_pdf = html_lib.escape(pdf_href)
            safe_label = html_lib.escape(str(source_file))
            safe_alt = html_lib.escape(f"Figure from {source_file} ({page_label} {page})")
            safe_caption = html_lib.escape(caption) if caption else ""
            fig_id = f' id="fig-{figure_label}"' if figure_label else ""
            figure_prefix = f"Figure {figure_label}" if figure_label else "Figure"
            if safe_caption:
                fig_caption = (
                    f"{figure_prefix}: {safe_caption} (Source: <a href=\"{safe_pdf}\">{safe_label}</a>, "
                    f"{page_label} {page})"
                )
            else:
                fig_caption = f"{figure_prefix}: <a href=\"{safe_pdf}\">{safe_label}</a> ({page_label} {page})"
            blocks.append(
                "\n".join(
                    [
                        f'<figure class="report-figure"{fig_id}>',
                        f'  <img src="{safe_img}" alt="{safe_alt}" />',
                        f"  <figcaption>{fig_caption}</figcaption>",
                        "</figure>",
                    ]
                )
            )
    return "\n\n".join(blocks)


def insert_figures_by_section(
    report_text: str,
    figure_entries: list[dict],
    output_format: str,
    report_dir: Path,
    run_dir: Path,
) -> str:
    if not figure_entries:
        return report_text
    spans = find_section_spans(report_text, output_format)
    blocks: dict[str, list[dict]] = {}
    orphan: list[dict] = []
    for entry in figure_entries:
        title = entry.get("section")
        if title:
            blocks.setdefault(title.lower(), []).append(entry)
        else:
            orphan.append(entry)

    if not spans:
        block = render_figure_block(figure_entries, output_format, report_dir, run_dir)
        callout = render_figure_callouts(figure_entries, output_format, report_dir, run_dir)
        if output_format == "tex":
            callout_block = f"{callout}\n\n" if callout else ""
            return report_text.rstrip() + "\n\n\\section*{Figures}\n" + callout_block + block + "\n"
        callout_block = f"{callout}\n\n" if callout else ""
        return report_text.rstrip() + "\n\n## Figures\n" + callout_block + block + "\n"

    rebuilt = report_text[: spans[0][1]]
    for idx, (title, start, end) in enumerate(spans):
        section_text = report_text[start:end]
        entries = blocks.get(title.lower())
        if entries:
            callout = render_figure_callouts(entries, output_format, report_dir, run_dir)
            block = render_figure_block(entries, output_format, report_dir, run_dir)
            section_text = section_text.rstrip()
            if callout:
                section_text += "\n\n" + callout
            section_text += "\n\n" + block + "\n\n"
        rebuilt += section_text

    if orphan:
        callout = render_figure_callouts(orphan, output_format, report_dir, run_dir)
        block = render_figure_block(orphan, output_format, report_dir, run_dir)
        if output_format == "tex":
            callout_block = f"{callout}\n\n" if callout else ""
            rebuilt = rebuilt.rstrip() + "\n\n\\section*{Figures}\n" + callout_block + block + "\n"
        else:
            callout_block = f"{callout}\n\n" if callout else ""
            rebuilt = rebuilt.rstrip() + "\n\n## Figures\n" + callout_block + block + "\n"
    return rebuilt


def generate_figures_preview(
    report_path: Path,
    run_dir: Path,
    archive_dir: Path,
    supporting_dir: Optional[Path],
    notes_dir: Path,
    output_format: str,
    max_per_pdf: int,
    min_area: int,
    renderer: str,
    dpi: int,
    vision_model_name: Optional[str],
) -> Optional[Path]:
    report_text = report_path.read_text(encoding="utf-8", errors="replace")
    report_dir = report_path.resolve().parent
    candidates = build_figure_plan(
        report_text,
        run_dir,
        archive_dir,
        supporting_dir,
        output_format,
        max_per_pdf,
        min_area,
        renderer,
        dpi,
        notes_dir,
        vision_model_name,
    )
    viewer_dir = run_dir / "report_views"
    return write_figure_candidates(candidates, notes_dir, run_dir, report_dir, viewer_dir)


def extract_used_sources(text: Optional[str]) -> set[str]:
    used: set[str] = set()
    for path in extract_cited_paths(text):
        normalized = path.lstrip("./")
        if not normalized.startswith("archive/"):
            if normalized.startswith("supporting/"):
                used.add("supporting")
            continue
        parts = normalized.split("/")
        if len(parts) < 2:
            continue
        base = parts[1]
        if base.startswith("tavily"):
            base = "tavily"
        used.add(base)
    return used


def filter_references(
    refs: list[dict],
    prompt_text: Optional[str],
    evidence_text: Optional[str],
    max_refs: int,
) -> list[dict]:
    if not refs:
        return []
    urls = set(extract_urls(evidence_text))
    selected = [ref for ref in refs if ref["url"] in urls]
    if not selected:
        used_sources = extract_used_sources(evidence_text)
        if used_sources:
            selected = [
                ref
                for ref in refs
                if ref["source"] in used_sources
                or any(ref["source"].startswith(src) for src in used_sources)
            ]
    if not selected:
        keywords = extract_keywords(prompt_text)
        if evidence_text:
            keywords.extend(extract_keywords(evidence_text))
        keywords = sorted(set(keywords))
        if keywords:
            filtered = []
            for ref in refs:
                hay = f"{ref['title']} {ref['url']}".lower()
                if any(key in hay for key in keywords):
                    filtered.append(ref)
            selected = filtered
    if not selected:
        selected = refs
    if max_refs > 0:
        selected = selected[:max_refs]
    return selected


def rewrite_citations(report_text: str, output_format: str = "md") -> tuple[str, list[dict]]:
    ref_map: dict[str, int] = {}
    refs: list[dict] = []
    citation_re = re.compile(r"\[([^\]]+)\]")
    md_link_re = re.compile(r"\[([^\]]+)\]\(([^)]+)\)")

    def normalize_target(value: str, kind: str) -> str:
        if kind == "url":
            return value
        if value.startswith("./"):
            return value
        return f"./{value}"

    def add_ref(target: str, kind: str) -> int:
        key = f"{kind}:{target}"
        if key in ref_map:
            return ref_map[key]
        idx = len(refs) + 1
        ref_map[key] = idx
        refs.append({"index": idx, "kind": kind, "target": target})
        return idx

    def should_anchor_citation(target: str) -> bool:
        lowered = target.lower()
        if lowered.endswith((".pptx", ".ppt", ".docx", ".doc", ".xlsx", ".xls")):
            return True
        if lowered.endswith(".txt"):
            extract_hints = (
                "/archive/web/text/",
                "/archive/openalex/text/",
                "/archive/arxiv/text/",
                "/archive/local/text/",
                "/archive/supporting/web_text/",
                "/supporting/web_text/",
            )
            return any(hint in lowered for hint in extract_hints)
        return False

    def format_inline_citation(idx: int, target: str) -> str:
        if output_format == "tex":
            return latex_link(target, f"[{idx}]")
        if should_anchor_citation(target):
            return f"[\\[{idx}\\]](#ref-{idx})"
        return f"[\\[{idx}\\]]({target})"

    def replace_md_link(match: re.Match[str]) -> str:
        target = match.group(2).strip()
        kind = None
        if target.startswith(("http://", "https://")):
            kind = "url"
        elif _CITED_PATH_RE.match(target):
            kind = "path"
        if not kind:
            return match.group(0)
        norm_target = normalize_target(target, kind)
        idx = add_ref(norm_target, kind)
        if output_format == "tex":
            return format_inline_citation(idx, norm_target)
        return f"[\\[{idx}\\]]({norm_target})"

    def replace_block(match: re.Match[str]) -> str:
        content = match.group(1)
        candidates: list[tuple[int, str, str]] = []
        for m in _URL_RE.finditer(content):
            candidates.append((m.start(), m.group(1), "url"))
        for m in _CITED_PATH_RE.finditer(content):
            candidates.append((m.start(), m.group(1), "path"))
        if not candidates:
            return match.group(0)
        candidates.sort(key=lambda item: item[0])
        seen: set[str] = set()
        parts: list[str] = []
        for _, raw, kind in candidates:
            target = normalize_target(raw.strip(), kind)
            key = f"{kind}:{target}"
            if key in seen:
                continue
            seen.add(key)
            idx = add_ref(target, kind)
            parts.append(format_inline_citation(idx, target))
        return ", ".join(parts) if parts else match.group(0)

    updated = md_link_re.sub(replace_md_link, report_text)
    updated = citation_re.sub(replace_block, updated)
    if output_format != "tex":
        raw_url_re = re.compile(r"(?<!\]\()https?://[^\s<]+")

        def replace_naked_url(match: re.Match[str]) -> str:
            raw = match.group(0)
            trimmed = raw.rstrip(".,;:!?)]")
            suffix = raw[len(trimmed) :]
            if not trimmed:
                return raw
            idx = add_ref(trimmed, "url")
            return f"{format_inline_citation(idx, trimmed)}{suffix}"

        updated = raw_url_re.sub(replace_naked_url, updated)
    if output_format != "tex":
        updated = re.sub(
            r"(\[\[\d+\]\]\([^)]+\))\s*\((https?://[^)]+)\)",
            r"\1",
            updated,
        )
        updated = re.sub(
            r"(\[\[\d+\]\]\([^)]+\))\s*\((\./(?:archive|instruction|report_notes|report|supporting)[^)]+)\)",
            r"\1",
            updated,
        )
        raw_path_re = re.compile(
            r"(?<!\]\()(?<![\w./])((?:\./)?(?:archive|instruction|report_notes|report|supporting)/[A-Za-z0-9_./-]+)"
        )

        def replace_naked_path(match: re.Match[str]) -> str:
            raw = match.group(1)
            trimmed = raw.rstrip(".,;:!?)]")
            suffix = raw[len(trimmed) :]
            if not trimmed:
                return raw
            norm_target = normalize_target(trimmed, "path")
            idx = add_ref(norm_target, "path")
            return f"{format_inline_citation(idx, norm_target)}{suffix}"

        updated = raw_path_re.sub(replace_naked_path, updated)
    return updated, refs


def merge_orphan_citations(report_text: str) -> str:
    if not report_text:
        return report_text
    lines = report_text.splitlines()
    merged: list[str] = []
    bullet_re = re.compile(r"^\s*(?:[-*•]|\d+\.)\s+")
    bare_cite_re = re.compile(r"^\[?\s*\d+\s*\]?$")
    for line in lines:
        stripped = line.strip()
        candidate = bullet_re.sub("", stripped)
        is_citation_line = False
        if candidate:
            if _CITATION_LINE_RE.fullmatch(candidate):
                is_citation_line = True
            elif bare_cite_re.fullmatch(candidate):
                is_citation_line = True
        if stripped and is_citation_line:
            if merged:
                idx = len(merged) - 1
                while idx >= 0 and not merged[idx].strip():
                    idx -= 1
                if idx >= 0:
                    prefix = merged[idx].rstrip()
                    joiner = "" if prefix.endswith(("(", "[", "{")) else " "
                    merged[idx] = prefix + joiner + candidate
                    if idx < len(merged) - 1:
                        del merged[idx + 1 :]
                else:
                    merged.append(candidate)
            else:
                merged.append(candidate)
            continue
        merged.append(line)
    return "\n".join(merged)


def index_label_for_path(target: str) -> Optional[str]:
    trimmed = target.lstrip("./")
    for key, label in INDEX_JSONL_HINTS.items():
        if trimmed.endswith(key):
            return label
    return None


def shorten_url_label(url: str, max_len: int = 64) -> str:
    if not url:
        return "link"
    parsed = urllib.parse.urlparse(url)
    label = f"{parsed.netloc}{parsed.path}" if parsed.netloc else url
    if len(label) > max_len:
        label = label[: max_len - 3] + "..."
    return label or "link"


def display_title(title: Optional[str], url: Optional[str]) -> str:
    cleaned = (title or "").strip()
    if cleaned:
        if url and cleaned == url:
            return shorten_url_label(url)
        return cleaned
    if url:
        return shorten_url_label(url)
    return "Untitled source"


_AUTHOR_SPLIT_RE = re.compile(r"[;,]")
_YEAR_RE = re.compile(r"(19|20)\d{2}")
_SOURCE_LABELS = {
    "local": "Local file",
    "web": "Web",
    "supporting_web": "Supporting web",
    "youtube": "YouTube",
}


def normalize_author_list(authors: object, max_names: int = 4) -> Optional[str]:
    if not authors:
        return None
    names: list[str] = []
    if isinstance(authors, str):
        parts = [part.strip() for part in _AUTHOR_SPLIT_RE.split(authors) if part.strip()]
        if len(parts) <= 1:
            return authors.strip()
        names = parts
    elif isinstance(authors, (list, tuple, set)):
        for item in authors:
            if not item:
                continue
            text = str(item).strip()
            if text:
                names.append(text)
    else:
        return None
    seen: set[str] = set()
    cleaned: list[str] = []
    for name in names:
        if name in seen:
            continue
        seen.add(name)
        cleaned.append(name)
    if not cleaned:
        return None
    if len(cleaned) > max_names:
        return f"{cleaned[0]} et al."
    return ", ".join(cleaned)


def extract_year(value: object) -> Optional[str]:
    if value is None:
        return None
    match = _YEAR_RE.search(str(value))
    return match.group(0) if match else None


def normalize_reference_url(value: object) -> Optional[str]:
    if not value:
        return None
    url = str(value).strip()
    if url.startswith(("http://", "https://")):
        return url
    return None


def normalize_source_label(value: object) -> Optional[str]:
    if not value:
        return None
    key = str(value).strip().lower()
    return _SOURCE_LABELS.get(key)


def clean_reference_tail(value: object) -> Optional[str]:
    if not value:
        return None
    text = " ".join(str(value).split())
    return text.strip().strip(".")


def format_reference_item(ref: dict, output_format: str = "md") -> str:
    url = normalize_reference_url(ref.get("url") or ref.get("source_url"))
    title = display_title(ref.get("title"), url)
    authors = normalize_author_list(ref.get("authors"))
    published = ref.get("published")
    year = extract_year(published)
    venue = ref.get("journal") or ref.get("publisher") or ref.get("channel")
    source_label = normalize_source_label(ref.get("source") or ref.get("source_label"))
    cite_note = ""
    if ref.get("cited_by_count") is not None:
        if output_format == "tex":
            cite_note = f" \\textit{{citations: {ref['cited_by_count']}}}"
        else:
            cite_note = f" <small>citations: {ref['cited_by_count']}</small>"
    main = ""
    if authors and year:
        main = f"{authors} ({year}). {title}"
    elif authors:
        main = f"{authors}. {title}"
    elif year:
        main = f"{title} ({year})"
    else:
        main = f"{title}"
    tail_bits: list[str] = []
    if venue:
        tail_bits.append(clean_reference_tail(venue) or "")
    if not year and published:
        tail_bits.append(clean_reference_tail(published) or "")
    if ref.get("extra"):
        tail_bits.append(clean_reference_tail(ref["extra"]) or "")
    if source_label:
        tail_bits.append(source_label)
    tail_bits = [bit for bit in tail_bits if bit]
    if tail_bits:
        main = f"{main}. {'; '.join(tail_bits)}"
    if output_format == "tex":
        safe_title = latex_escape(str(main))
        if url and isinstance(url, str):
            return f"{safe_title} --- {latex_link(url, 'link')}{cite_note}"
        return f"{safe_title}{cite_note}"
    if url and isinstance(url, str):
        return f"{main} — [link]({url}){cite_note}"
    return f"{main}{cite_note}"


def render_reference_section(
    citations: list[dict],
    refs_meta: list[dict],
    openalex_meta: dict[str, dict],
    output_format: str = "md",
    text_meta_index: Optional[dict[str, dict]] = None,
) -> str:
    if not citations:
        return ""
    by_archive = {ref.get("archive", "").lstrip("./"): ref for ref in refs_meta}
    by_url = {ref.get("url"): ref for ref in refs_meta if ref.get("url")}
    text_meta_index = text_meta_index or {}
    extract_hints = (
        "/archive/tavily_extract/",
        "/archive/web/text/",
        "/archive/openalex/text/",
        "/archive/arxiv/text/",
        "/archive/local/text/",
        "/supporting/web_text/",
        "/archive/supporting/web_text/",
    )
    if output_format == "tex":
        lines = [
            "",
            "\\section*{References}",
            "\\noindent\\textit{Citation policy: inline numeric citations; rights remain with original source owners; verify primary sources for high-stakes use.}",
            "\\renewcommand{\\labelenumi}{[\\arabic{enumi}]}",
            "\\begin{enumerate}",
        ]
    else:
        lines = [
            "",
            "## References",
            "",
            "> Citation policy: keep citations inline as `[n]`; source rights belong to original publishers/authors. Validate primary sources before high-stakes use.",
            "",
        ]
    for entry in citations:
        idx = entry["index"]
        kind = entry["kind"]
        target = entry["target"]
        anchor = "" if output_format == "tex" else f"<span id=\"ref-{idx}\"></span>"
        if kind == "path":
            norm = target.lstrip("./")
            index_label = index_label_for_path(norm)
            if index_label:
                items = [ref for ref in refs_meta if ref.get("archive", "").lstrip("./") == norm]
                if items:
                    if output_format == "tex":
                        label = latex_escape(index_label)
                        file_link = latex_link(target, f"\\texttt{{{latex_escape(target)}}}")
                        lines.append(f"\\item {label} ({file_link}) --- selected sources:")
                        lines.append("\\begin{itemize}")
                        for item in items[:6]:
                            lines.append(f"\\item {format_reference_item(item, output_format)}")
                        lines.append("\\end{itemize}")
                    else:
                        lines.append(f"{idx}. {anchor} {index_label} ({target}) — selected sources:")
                        for item in items[:6]:
                            lines.append(f"   - {format_reference_item(item, output_format)}")
                    continue
            meta = text_meta_index.get(norm) or text_meta_index.get(f"./{norm}") or by_archive.get(norm)
            path_name = Path(norm).name
            short_id = Path(norm).stem if path_name.startswith("W") else None
            oa_meta = openalex_meta.get(short_id) if short_id else None
            url = None
            if meta:
                url = meta.get("source_url") or meta.get("url")
            if not url and oa_meta:
                url = oa_meta.get("landing_page_url") or oa_meta.get("doi") or oa_meta.get("pdf_url")
            title = display_title(
                (meta.get("title") if meta else None) or (oa_meta.get("title") if oa_meta else None),
                url,
            )
            if title == "Untitled source":
                title = path_name
            ref_payload: dict = {}
            if meta:
                ref_payload.update(meta)
            if oa_meta:
                ref_payload.setdefault("authors", extract_openalex_authors(oa_meta))
                ref_payload.setdefault("journal", resolve_openalex_journal(oa_meta))
                ref_payload.setdefault("published", resolve_openalex_published(oa_meta))
                ref_payload.setdefault("cited_by_count", oa_meta.get("cited_by_count"))
            ref_payload.setdefault("title", title)
            if url:
                ref_payload["url"] = url
            item_text = format_reference_item(ref_payload, output_format)
            pdf_path = ref_payload.get("pdf_path") if isinstance(ref_payload, dict) else None
            raw_path = ref_payload.get("raw_path") if isinstance(ref_payload, dict) else None
            pptx_path = ref_payload.get("pptx_path") if isinstance(ref_payload, dict) else None
            primary_path = raw_path or pdf_path or pptx_path or target
            hide_primary = False
            if url and isinstance(primary_path, str) and primary_path == target:
                lowered = primary_path.lower()
                if any(hint in lowered for hint in extract_hints):
                    hide_primary = True
            if output_format == "tex":
                parts = [item_text]
                if not hide_primary:
                    file_link = latex_link(primary_path, f"\\texttt{{{latex_escape(primary_path)}}}")
                    parts.append(file_link)
                if pdf_path and pdf_path != target:
                    parts.append(latex_link(pdf_path, "pdf"))
                lines.append("\\item " + " --- ".join(parts))
            else:
                parts = [item_text]
                if not hide_primary:
                    parts.append(f"[file]({primary_path})")
                if pdf_path and pdf_path not in {primary_path, target}:
                    parts.append(f"[pdf]({pdf_path})")
                lines.append(f"{idx}. {anchor} " + " — ".join(parts))
        else:
            meta = by_url.get(target)
            payload = {"title": meta.get("title") if meta else None, "url": target}
            if meta:
                payload.update(meta)
            item_text = format_reference_item(payload, output_format)
            if output_format == "tex":
                lines.append(f"\\item {item_text}")
            else:
                lines.append(f"{idx}. {anchor} {item_text}")
    if output_format == "tex":
        lines.append("\\end{enumerate}")
    return "\n".join(lines)


def normalize_report_paths(text: str, run_dir: Path) -> str:
    variants = [str(run_dir), str(run_dir).replace("\\", "/")]
    for variant in variants:
        if not variant:
            continue
        text = text.replace(variant, ".")
        text = text.replace("/" + variant, ".")
        text = text.replace("\\" + variant, ".")
    for name in ("archive", "instruction", "report_notes", "report", "supporting"):
        text = re.sub(rf"(?<![\w./]){name}/", f"./{name}/", text)
    return text


def find_missing_sections(report_text: str, required_sections: list[str], output_format: str) -> list[str]:
    if output_format == "tex":
        headings = [
            match.group(1).strip()
            for match in re.finditer(r"^\\section\\*?\\{([^}]+)\\}", report_text, re.MULTILINE)
        ]
    else:
        headings = [match.group(1).strip() for match in re.finditer(r"^##\s+(.+)$", report_text, re.MULTILINE)]
    missing = []
    for section in required_sections:
        if not any(heading.lower().startswith(section.lower()) for heading in headings):
            missing.append(section)
    return missing


def compose_author_label(name: str, organization: Optional[str]) -> str:
    cleaned_name = (name or "").strip()
    cleaned_org = (organization or "").strip()
    if not cleaned_name:
        return ""
    if not cleaned_org:
        return cleaned_name
    if cleaned_org.lower() in cleaned_name.lower():
        return cleaned_name
    return f"{cleaned_name} / {cleaned_org}"


def _resolve_profile_author(profile: Optional[AgentProfile]) -> tuple[str, str]:
    if not profile:
        return "", ""
    author_name = (getattr(profile, "author_name", "") or "").strip()
    organization = (getattr(profile, "organization", "") or "").strip()
    return author_name, organization


def resolve_author_identity(
    author_cli: Optional[str],
    organization_cli: Optional[str],
    report_prompt: Optional[str],
    profile: Optional[AgentProfile] = None,
) -> tuple[str, str]:
    cli_name = (author_cli or "").strip()
    cli_org = (organization_cli or "").strip()
    if cli_name:
        return cli_name, cli_org

    profile_name, profile_org = _resolve_profile_author(profile)
    if profile_name:
        effective_org = cli_org or profile_org
        return profile_name, effective_org

    if report_prompt:
        for line in report_prompt.splitlines():
            match = _AUTHOR_LINE_RE.match(line)
            if match:
                name = match.group(1).strip()
                if name:
                    return name, cli_org

    return DEFAULT_AUTHOR, cli_org


def build_byline(agent_name: str, prompter: str, organization: Optional[str] = None) -> str:
    stamp = dt.datetime.now().strftime("%Y-%m-%d %H:%M")
    agent = (agent_name or "Federlicht").strip()
    person = (prompter or DEFAULT_AUTHOR).strip()
    org = (organization or "").strip()
    if org:
        return f'{agent} assisted and prompted by "{person}" ({org}) — {stamp}'
    return f'{agent} assisted and prompted by "{person}" — {stamp}'

def set_federlicht_log_path(run_dir: Path) -> None:
    global FEDERLICHT_LOG_PATH
    FEDERLICHT_LOG_PATH = run_dir / "_federlicht_log.txt"
    _append_federlicht_log("JOB START")


def _append_federlicht_log(message: str) -> None:
    if FEDERLICHT_LOG_PATH is None:
        return
    try:
        stamp = dt.datetime.now().strftime("%Y-%m-%d %H:%M:%S")
        line = f"[{stamp}] {message}"
        FEDERLICHT_LOG_PATH.parent.mkdir(parents=True, exist_ok=True)
        with FEDERLICHT_LOG_PATH.open("a", encoding="utf-8") as handle:
            handle.write(line + "\n")
    except Exception:
        return

def finish_federlicht_log(status: str = "JOB END") -> None:
    _append_federlicht_log(status)


def parse_update_prompt(report_prompt: Optional[str]) -> tuple[Optional[str], Optional[str]]:
    if not report_prompt:
        return None, None
    base = None
    notes_lines: list[str] = []
    in_update = False
    for line in report_prompt.splitlines():
        stripped = line.strip()
        if stripped.lower().startswith("base report:"):
            base = stripped.split(":", 1)[-1].strip()
            continue
        if stripped.lower().startswith("update request"):
            in_update = True
            continue
        if in_update:
            if stripped.lower().startswith("second prompt") or stripped.lower().startswith("instructions"):
                in_update = False
                continue
            if stripped:
                notes_lines.append(stripped)
    notes = "\n".join(notes_lines).strip() if notes_lines else None
    return base, notes


def expand_update_prompt_with_base(
    report_prompt: Optional[str],
    run_dir: Path,
    max_chars: int = 12000,
) -> Optional[str]:
    if not report_prompt:
        return report_prompt
    base_path, _ = parse_update_prompt(report_prompt)
    if not base_path:
        return report_prompt
    rel = base_path.lstrip("./")
    candidate = (run_dir / rel).resolve()
    if not candidate.exists():
        return report_prompt
    try:
        raw = candidate.read_text(encoding="utf-8", errors="replace")
    except Exception:
        return report_prompt
    if candidate.suffix.lower() in {".html", ".htm"}:
        raw = html_to_text(raw)
    raw = raw.strip()
    if max_chars > 0 and len(raw) > max_chars:
        raw = raw[: max_chars - 1].rstrip() + "…"
    if not raw:
        return report_prompt
    return "\n\n".join(
        [
            report_prompt,
            "Base report content (truncated for context):",
            raw,
        ]
    )


def print_progress(label: str, content: str, enabled: bool, max_chars: int) -> None:
    if not enabled:
        return
    snippet = content.strip()
    if max_chars > 0 and len(snippet) > max_chars:
        snippet = f"{snippet[:max_chars]}\n... [truncated]"
    _append_federlicht_log(f"{label}: {snippet}")
    print(f"\n[{label}]\n{snippet}\n")


_OPENAI_COMPAT_RE = re.compile(r"^qwen", re.IGNORECASE)
_OPENAI_MODEL_RE = re.compile(r"^(gpt-|o\\d)", re.IGNORECASE)


def is_openai_compat_model_name(model_name: str) -> bool:
    return bool(_OPENAI_COMPAT_RE.match(model_name.strip()))


def is_openai_model_name(model_name: str) -> bool:
    return bool(_OPENAI_MODEL_RE.match(model_name.strip()))


def build_openai_compat_model(
    model_name: str,
    streaming: bool = False,
    temperature: Optional[float] = None,
):
    try:
        from langchain_openai import ChatOpenAI  # type: ignore
    except Exception:
        return None
    base_url = os.getenv("OPENAI_BASE_URL") or os.getenv("OPENAI_API_BASE")
    kwargs = {"model": model_name}
    if streaming:
        kwargs["streaming"] = True
    if temperature is not None:
        kwargs["temperature"] = temperature
    if base_url:
        try:
            return ChatOpenAI(**kwargs, base_url=base_url)
        except TypeError:
            try:
                return ChatOpenAI(**kwargs, openai_api_base=base_url)
            except TypeError:
                kwargs.pop("streaming", None)
                try:
                    return ChatOpenAI(**kwargs, openai_api_base=base_url)
                except TypeError:
                    kwargs.pop("temperature", None)
                    return ChatOpenAI(**kwargs, openai_api_base=base_url)
    try:
        return ChatOpenAI(**kwargs)
    except TypeError:
        kwargs.pop("streaming", None)
        try:
            return ChatOpenAI(**kwargs)
        except TypeError:
            kwargs.pop("temperature", None)
            return ChatOpenAI(**kwargs)


def build_vision_model(model_name: str):
    try:
        from langchain_openai import ChatOpenAI  # type: ignore
    except Exception:
        print(
            "Vision model requested but langchain-openai is unavailable. "
            "Install with: python -m pip install langchain-openai",
            file=sys.stderr,
        )
        return None
    base_url = (
        os.getenv("OPENAI_BASE_URL_VISION")
        or os.getenv("OPENAI_API_BASE_VISION")
        or os.getenv("OPENAI_BASE_URL")
        or os.getenv("OPENAI_API_BASE")
    )
    api_key = os.getenv("OPENAI_API_KEY_VISION") or os.getenv("OPENAI_API_KEY")
    kwargs = {"model": model_name}
    if api_key:
        kwargs["openai_api_key"] = api_key
    if base_url:
        try:
            return ChatOpenAI(**kwargs, base_url=base_url)
        except TypeError:
            try:
                return ChatOpenAI(**kwargs, openai_api_base=base_url)
            except TypeError:
                return ChatOpenAI(**kwargs)
    try:
        return ChatOpenAI(**kwargs)
    except TypeError:
        if "openai_api_key" in kwargs:
            kwargs.pop("openai_api_key")
            return ChatOpenAI(**kwargs)
        raise


def create_agent_with_fallback(
    create_deep_agent,
    model_name: str,
    tools,
    system_prompt: str,
    backend,
    max_input_tokens: Optional[int] = None,
    max_input_tokens_source: str = "none",
    temperature: Optional[float] = None,
):
    max_input_tokens = max_input_tokens if max_input_tokens is not None else DEFAULT_MAX_INPUT_TOKENS
    if max_input_tokens_source == "none":
        max_input_tokens_source = DEFAULT_MAX_INPUT_TOKENS_SOURCE
    force_override = max_input_tokens_source in {"agent", "cli", "config"}
    effective_temperature = parse_temperature(temperature)
    if effective_temperature is None:
        effective_temperature = parse_temperature(ACTIVE_AGENT_TEMPERATURE)
    kwargs = {"tools": tools, "system_prompt": system_prompt, "backend": backend}
    if effective_temperature is not None:
        kwargs["temperature"] = effective_temperature
    if model_name:
        model_value = model_name
        base_url = os.getenv("OPENAI_BASE_URL") or os.getenv("OPENAI_API_BASE")
        use_compat = False
        if is_openai_model_name(model_name):
            use_compat = False
        elif base_url:
            use_compat = True
        elif is_openai_compat_model_name(model_name):
            use_compat = True
        if use_compat:
            compat_model = build_openai_compat_model(
                model_name,
                streaming=STREAMING_ENABLED,
                temperature=effective_temperature,
            )
            if compat_model is None:
                print(
                    "OpenAI-compatible model requested but langchain-openai is unavailable. "
                    "Install with: python -m pip install langchain-openai "
                    "and set OPENAI_BASE_URL/OPENAI_API_KEY if needed.",
                    file=sys.stderr,
                )
            else:
                apply_model_profile_max_input_tokens(compat_model, max_input_tokens, force=force_override)
                model_value = compat_model
        elif STREAMING_ENABLED and is_openai_model_name(model_name):
            compat_model = build_openai_compat_model(
                model_name,
                streaming=True,
                temperature=effective_temperature,
            )
            if compat_model is not None:
                apply_model_profile_max_input_tokens(compat_model, max_input_tokens, force=force_override)
                model_value = compat_model
        if isinstance(model_value, str) and max_input_tokens:
            try:
                from langchain.chat_models import init_chat_model  # type: ignore
            except Exception:
                init_chat_model = None
            if init_chat_model is not None:
                try:
                    if effective_temperature is not None:
                        model_obj = init_chat_model(model_value, temperature=effective_temperature)
                    else:
                        model_obj = init_chat_model(model_value)
                    apply_model_profile_max_input_tokens(model_obj, max_input_tokens, force=force_override)
                    model_value = model_obj
                except Exception:
                    pass
        if not isinstance(model_value, str):
            apply_model_profile_max_input_tokens(model_value, max_input_tokens, force=force_override)
        try:
            return create_deep_agent(model=model_value, **kwargs)
        except TypeError as exc:
            if "temperature" in kwargs and "temperature" in str(exc).lower():
                retry_kwargs = dict(kwargs)
                retry_kwargs.pop("temperature", None)
                return create_deep_agent(model=model_value, **retry_kwargs)
            raise
        except Exception as exc:  # pragma: no cover - fallback path
            msg = str(exc).lower()
            if model_name == DEFAULT_MODEL and any(token in msg for token in ("model", "unsupported", "unknown")):
                print(
                    f"Model '{DEFAULT_MODEL}' not supported by this deepagents setup. Falling back to default.",
                    file=sys.stderr,
                )
            else:
                raise
    try:
        return create_deep_agent(**kwargs)
    except TypeError as exc:
        if "temperature" in kwargs and "temperature" in str(exc).lower():
            retry_kwargs = dict(kwargs)
            retry_kwargs.pop("temperature", None)
            return create_deep_agent(**retry_kwargs)
        raise


def run_pipeline(
    args: argparse.Namespace,
    create_deep_agent=None,
    agent_overrides: Optional[dict] = None,
    config_overrides: Optional[dict] = None,
    state: Optional[PipelineState] = None,
    state_only: bool = False,
) -> ReportOutput:
    if not args.run:
        raise ValueError("--run is required.")
    try:
        _, pre_run_dir, _ = resolve_archive(Path(args.run))
    except Exception:
        pre_run_dir = None
    if pre_run_dir:
        raw_prompt = load_report_prompt(args.prompt, args.prompt_file)
        expanded_prompt = expand_update_prompt_with_base(raw_prompt, pre_run_dir)
        if expanded_prompt:
            args.prompt = expanded_prompt
            args.prompt_file = None
    if config_overrides is None:
        agent_from_config, config_overrides = resolve_agent_overrides_from_config(
            args, explicit_overrides=agent_overrides
        )
        agent_overrides = agent_from_config
    agent_overrides = agent_overrides or {}
    config_overrides = config_overrides or {}
    output_format, check_model = prepare_runtime(args, config_overrides)
    create_deep_agent = resolve_create_deep_agent(create_deep_agent)

    start_stamp = dt.datetime.now()
    start_timer = time.monotonic()

    helpers = sys.modules[__name__]
    pipeline_context = PipelineContext(args=args, output_format=output_format, check_model=check_model)
    state_only = state_only or bool(getattr(args, "_state_only", False))
    orchestrator = ReportOrchestrator(pipeline_context, helpers, agent_overrides, create_deep_agent)
    result = orchestrator.run(state=state, allow_partial=state_only)
    pipeline_state = build_pipeline_state(result)

    report = result.report
    if state_only:
        meta = {
            "generated_at": dt.datetime.now().strftime("%Y-%m-%d %H:%M:%S"),
            "state_only": True,
            "stages": getattr(args, "stages", None),
        }
        return ReportOutput(
            result=result,
            report="",
            rendered="",
            output_path=None,
            meta=meta,
            preview_text="",
            state=pipeline_state,
        )
    scout_notes = result.scout_notes
    evidence_notes = result.evidence_notes
    report_prompt = result.report_prompt
    clarification_questions = result.clarification_questions
    clarification_answers = result.clarification_answers
    template_spec = result.template_spec
    template_guidance_text = result.template_guidance_text
    template_adjustment_path = result.template_adjustment_path
    required_sections = result.required_sections
    language = result.language
    run_dir = result.run_dir
    archive_dir = result.archive_dir
    notes_dir = result.notes_dir
    supporting_dir = result.supporting_dir
    overview_path = result.overview_path
    index_file = result.index_file
    instruction_file = result.instruction_file
    quality_model = result.quality_model
    query_id = result.query_id
    update_base, update_notes = parse_update_prompt(report_prompt)
    update_prompt_path = args.prompt_file if getattr(args, "prompt_file", None) else None

    report = normalize_report_for_format(report, output_format)
    author_name, author_organization = resolve_author_identity(
        args.author,
        getattr(args, "organization", None),
        report_prompt,
        profile=ACTIVE_AGENT_PROFILE,
    )
    author_label = compose_author_label(author_name, author_organization)
    agent_label = (
        (ACTIVE_AGENT_PROFILE.name or "").strip()
        if ACTIVE_AGENT_PROFILE and getattr(ACTIVE_AGENT_PROFILE, "name", None)
        else "Federlicht"
    )
    byline = build_byline(agent_label, author_name, author_organization)
    backend = SafeFilesystemBackend(root_dir=run_dir)
    title = extract_prompt_title(report_prompt)
    if title:
        title = enforce_concise_title(normalize_title_candidate(title), language)
    else:
        title = generate_title_with_llm(
            report,
            output_format,
            language,
            args.model,
            create_deep_agent,
            backend,
        )
    if not title:
        title = resolve_report_title(report_prompt, template_spec, query_id, language=language)
    title_block = format_report_title(title, output_format)
    byline_block = format_byline(byline, output_format)
    if title_block:
        report = f"{title_block}\n{byline_block}\n\n{report.strip()}"
    else:
        report = f"{byline_block}\n\n{report.strip()}"
    report_dir = run_dir if not args.output else Path(args.output).resolve().parent
    figure_entries: list[dict] = []
    preview_path: Optional[Path] = None
    if args.extract_figures:
        candidates = build_figure_plan(
            report,
            run_dir,
            archive_dir,
            supporting_dir,
            output_format,
            args.figures_max_per_pdf,
            args.figures_min_area,
            args.figures_renderer,
            args.figures_dpi,
            notes_dir,
            args.model_vision,
        )
        viewer_dir = run_dir / "report_views"
        preview_path = write_figure_candidates(candidates, notes_dir, run_dir, report_dir, viewer_dir)
        selection_path = Path(args.figures_select) if args.figures_select else (notes_dir / "figures_selected.txt")
        selection_path = selection_path if selection_path.is_absolute() else (run_dir / selection_path)
        if args.figures_mode == "auto":
            figure_entries = auto_select_figures(candidates)
        else:
            figure_entries = select_figures(candidates, selection_path)
            if not figure_entries:
                argv_flags = set(getattr(args, "_cli_argv", []))
                explicit_figures = "--figures" in argv_flags
                explicit_mode = any(
                    flag.startswith("--figures-mode") or flag.startswith("--figures-select")
                    for flag in argv_flags
                )
                if not candidates:
                    print(
                        "No figure candidates found. Ensure the report cites PDF paths "
                        "(e.g., ./archive/.../pdf/...) and rerun with --figures.",
                        file=sys.stderr,
                    )
                elif explicit_figures and not explicit_mode:
                    figure_entries = auto_select_figures(candidates, prefer_recommended=True)
                    print(
                        "No figures selected; auto-selected candidates because --figures "
                        "was explicitly set. Use --figures-mode select to require manual selection.",
                        file=sys.stderr,
                    )
                else:
                    print(
                        "No figures selected. Add candidate IDs to "
                        f"{selection_path.relative_to(run_dir).as_posix()} and rerun.",
                        file=sys.stderr,
                    )
        if figure_entries:
            for idx, entry in enumerate(figure_entries, start=1):
                entry["figure_number"] = idx
            notes_dir.mkdir(parents=True, exist_ok=True)
            figures_path = notes_dir / "figures.jsonl"
            with figures_path.open("w", encoding="utf-8") as handle:
                for entry in figure_entries:
                    handle.write(json.dumps(entry, ensure_ascii=False) + "\n")
    report = feder_tools.normalize_math_expressions(report)
    report_body, citation_refs = rewrite_citations(report.rstrip(), output_format)
    if output_format != "tex":
        report_body = merge_orphan_citations(report_body)
    if figure_entries:
        report_body = insert_figures_by_section(report_body, figure_entries, output_format, report_dir, run_dir)
    report = report_body
    if report_prompt:
        report = report.rstrip()
    if clarification_questions and "no_questions" not in clarification_questions.lower():
        report = report.rstrip()
    refs = collect_references(archive_dir, run_dir, args.max_refs, supporting_dir)
    refs = filter_references(refs, report_prompt, evidence_notes, args.max_refs)
    openalex_meta = load_openalex_meta(archive_dir)
    text_meta_index = build_text_meta_index(run_dir, archive_dir, supporting_dir)
    report = ensure_appendix_contents(report, output_format, refs, run_dir, notes_dir, language)
    if report_prompt:
        report = f"{report.rstrip()}{format_report_prompt_block(report_prompt, output_format)}"
    if clarification_questions and "no_questions" not in clarification_questions.lower():
        report = f"{report.rstrip()}{format_clarifications_block(clarification_questions, clarification_answers, output_format)}"
    report = f"{report.rstrip()}{render_reference_section(citation_refs, refs, openalex_meta, output_format, text_meta_index)}"
    out_path = Path(args.output) if args.output else None
    final_path: Optional[Path] = None
    if out_path:
        out_path.parent.mkdir(parents=True, exist_ok=True)
        companion_suffixes = [".pdf"] if output_format == "tex" else None
        final_path = resolve_output_path(out_path, args.overwrite_output, companion_suffixes)
    prompt_copy_path = write_report_prompt_copy(run_dir, report_prompt, final_path or out_path)
    report_overview_path = write_report_overview(
        run_dir,
        final_path,
        report_prompt,
        template_spec.name,
        template_adjustment_path,
        output_format,
        language,
        args.quality_iterations,
        args.quality_strategy,
        args.extract_figures,
        args.figures_mode,
        prompt_copy_path,
    )
    end_stamp = dt.datetime.now()
    elapsed = time.monotonic() - start_timer
    meta_path = notes_dir / "report_meta.json"
    report_summary = derive_report_summary(report, output_format)
    auto_tags_enabled = False
    if args.no_tags:
        tags_list = []
    else:
        raw_tags = (args.tags or "").strip()
        if raw_tags.lower() == "auto":
            auto_tags_enabled = True
            tags_list = []
        else:
            tags_list = parse_tags(args.tags)
            auto_tags_enabled = not tags_list
    if auto_tags_enabled:
        tags_list = build_auto_tags(report_prompt, title, report_summary, max_tags=5)
    meta = {
        "generated_at": end_stamp.strftime("%Y-%m-%d %H:%M:%S"),
        "started_at": start_stamp.strftime("%Y-%m-%d %H:%M:%S"),
        "duration_seconds": round(elapsed, 2),
        "duration_hms": format_duration(elapsed),
        "model": args.model,
        "temperature": args.temperature,
        "temperature_level": args.temperature_level,
        "model_vision": args.model_vision,
        "quality_model": quality_model if args.quality_iterations > 0 else None,
        "quality_iterations": args.quality_iterations,
        "quality_strategy": args.quality_strategy if args.quality_iterations > 0 else "none",
        "template": template_spec.name,
        "template_rigidity": args.template_rigidity,
        "template_rigidity_effective": getattr(args, "template_rigidity_effective", {}),
        "template_adjust_mode": args.template_adjust_mode,
        "repair_mode": args.repair_mode,
        "title": title,
        "summary": report_summary,
        "output_format": output_format,
        "language": language,
        "author": author_label,
        "organization": author_organization or None,
        "tags": tags_list,
        "free_format": args.free_format,
        "pdf_status": "enabled" if output_format == "tex" and args.pdf else "disabled",
    }
    if ACTIVE_AGENT_PROFILE:
        meta["agent_profile"] = {
            "id": ACTIVE_AGENT_PROFILE.profile_id,
            "name": ACTIVE_AGENT_PROFILE.name,
            "tagline": ACTIVE_AGENT_PROFILE.tagline,
            "author_name": ACTIVE_AGENT_PROFILE.author_name,
            "organization": ACTIVE_AGENT_PROFILE.organization,
            "version": ACTIVE_AGENT_PROFILE.version,
            "apply_to": list(ACTIVE_AGENT_PROFILE.apply_to),
        }
    if final_path:
        meta["report_stem"] = final_path.stem
    elif out_path:
        meta["report_stem"] = out_path.stem
    if result.workflow_summary:
        meta["stage_workflow"] = list(result.workflow_summary)
    if result.workflow_path:
        meta["report_workflow_path"] = rel_path_or_abs(result.workflow_path, run_dir)
    if overview_path:
        meta["run_overview_path"] = rel_path_or_abs(overview_path, run_dir)
    if report_overview_path:
        meta["report_overview_path"] = rel_path_or_abs(report_overview_path, run_dir)
    if index_file:
        meta["archive_index_path"] = rel_path_or_abs(index_file, run_dir)
    if instruction_file:
        meta["instruction_path"] = rel_path_or_abs(instruction_file, run_dir)
    if prompt_copy_path:
        meta["report_prompt_path"] = rel_path_or_abs(prompt_copy_path, run_dir)
    if template_adjustment_path:
        meta["template_adjustment_path"] = rel_path_or_abs(template_adjustment_path, run_dir)
    if preview_path:
        meta["figures_preview_path"] = rel_path_or_abs(preview_path, run_dir)
    append_report_workflow_outputs(
        result.workflow_path,
        run_dir,
        final_path,
        report_overview_path,
        meta_path,
        prompt_copy_path,
        notes_dir,
        preview_path,
    )
    report = f"{report.rstrip()}{format_metadata_block(meta, output_format)}"
    preview_text = report
    if output_format == "html":
        preview_text = html_to_text(markdown_to_html(report))
    print_progress("Report Preview", preview_text, args.progress, args.progress_chars)

    (notes_dir / "scout_notes.md").write_text(scout_notes, encoding="utf-8")
    template_lines = [
        f"Template: {template_spec.name}",
        f"Source: {template_spec.source or 'builtin/default'}",
        f"Latex: {template_spec.latex or 'default.tex'}",
        f"Layout: {template_spec.layout or 'single_column'}",
        "Sections:",
        *([f"- {section}" for section in required_sections] if required_sections else ["- (free-form)"]),
    ]
    if template_adjustment_path:
        template_lines.extend(["", f"Adjustment: {rel_path_or_abs(template_adjustment_path, run_dir)}"])
    if template_guidance_text:
        template_lines.extend(["", "Guidance:", template_guidance_text])
    (notes_dir / "report_template.txt").write_text("\n".join(template_lines), encoding="utf-8")
    if report_prompt:
        (notes_dir / "report_prompt.txt").write_text(report_prompt, encoding="utf-8")
    if clarification_questions and "no_questions" not in clarification_questions.lower():
        (notes_dir / "clarification_questions.txt").write_text(clarification_questions, encoding="utf-8")
    if clarification_answers:
        (notes_dir / "clarification_answers.txt").write_text(clarification_answers, encoding="utf-8")
    meta_path.write_text(json.dumps(meta, ensure_ascii=False, indent=2), encoding="utf-8")

    theme_css = None
    extra_body_class = None
    if output_format == "html":
        css_path = resolve_template_css_path(template_spec)
        if css_path and css_path.exists():
            theme_css = css_path.read_text(encoding="utf-8", errors="replace")
            css_slug = slugify_label(css_path.stem)
            template_slug = slugify_label(template_spec.name or "")
            if css_slug and css_slug != template_slug:
                extra_body_class = f"template-{css_slug}"
    rendered = report
    if output_format == "html":
        viewer_dir = run_dir / "report_views"
        viewer_map = build_viewer_map(report, run_dir, archive_dir, supporting_dir, report_dir, viewer_dir, args.max_chars)
        body_html = markdown_to_html(report)
        body_html = linkify_html(body_html)
        body_html, has_mermaid = transform_mermaid_code_blocks(body_html)
        body_html = inject_viewer_links(body_html, viewer_map)
        body_html = clean_citation_labels(body_html)
        rendered = wrap_html(
            title,
            body_html,
            template_name=template_spec.name,
            theme_css=theme_css,
            extra_body_class=extra_body_class,
            with_mermaid=has_mermaid,
            layout=template_spec.layout,
        )
    elif output_format == "tex":
        latex_template = load_template_latex(template_spec)
        if language == "Korean":
            latex_template = ensure_korean_package(latex_template or DEFAULT_LATEX_TEMPLATE)
        report = close_unbalanced_lists(report)
        report = sanitize_latex_headings(report)
        rendered = render_latex_document(
            latex_template,
            title,
            author_name,
            dt.datetime.now().strftime("%Y-%m-%d"),
            report,
        )

    if args.output:
        if not final_path:
            raise RuntimeError("Output path resolution failed.")
        final_path.write_text(rendered, encoding="utf-8")
        print(f"Wrote report: {final_path}")
        site_root = resolve_site_output(args.site_output)
        site_index_path: Optional[Path] = None
        if site_root:
            entry = build_site_manifest_entry(
                site_root,
                run_dir,
                final_path,
                title,
                author_name,
                report_summary,
                output_format,
                template_spec.name,
                language,
                end_stamp,
                report_overview_path=report_overview_path,
                workflow_path=result.workflow_path,
                model_name=args.model,
                tags=tags_list,
            )
            if entry:
                manifest = update_site_manifest(site_root, entry)
                site_index_path = write_site_index(site_root, manifest, refresh_minutes=10)
                meta["site_index_path"] = str(site_index_path)
                meta_path.write_text(json.dumps(meta, ensure_ascii=False, indent=2), encoding="utf-8")
        if args.echo_markdown:
            print(report)
        if output_format == "tex" and args.pdf:
            ok, message = compile_latex_to_pdf(final_path)
            pdf_path = final_path.with_suffix(".pdf")
            if ok and pdf_path.exists():
                print(f"Wrote PDF: {pdf_path}")
                meta["pdf_status"] = "success"
            elif not ok:
                print(f"PDF compile failed: {truncate_text_head(message, 800)}", file=sys.stderr)
                meta["pdf_status"] = "failed"
            meta_path.write_text(json.dumps(meta, ensure_ascii=False, indent=2), encoding="utf-8")
    else:
        print(rendered)

    if update_base or update_notes:
        try:
            notes_dir.mkdir(parents=True, exist_ok=True)
            history_path = notes_dir / "update_history.jsonl"
            entry = {
                "timestamp": dt.datetime.now().isoformat(),
                "base_report": update_base,
                "update_notes": update_notes,
                "prompt_file": update_prompt_path,
                "output_path": f"./{final_path.relative_to(run_dir).as_posix()}" if final_path else None,
            }
            append_jsonl(history_path, entry)
        except Exception:
            pass

    return ReportOutput(
        result=result,
        report=report,
        rendered=rendered,
        output_path=final_path,
        meta=meta,
        preview_text=preview_text,
        state=pipeline_state,
    )

def main() -> int:
    from .cli import main as cli_main

    return cli_main()


if __name__ == "__main__":
    raise SystemExit(main())
