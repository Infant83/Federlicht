from __future__ import annotations

import argparse
import os
import shutil
import sys
from typing import Optional

from .report import (
    DEFAULT_CHECK_MODEL,
    DEFAULT_MODEL,
    DEFAULT_TEMPLATE_RIGIDITY,
    DEFAULT_TEMPERATURE_LEVEL,
    MAX_INPUT_TOKENS_ENV,
    STAGE_ORDER,
    TEMPLATE_RIGIDITY_POLICIES,
    TEMPERATURE_LEVELS,
    list_builtin_templates,
    parse_max_input_tokens,
)

class CleanHelpFormatter(argparse.RawDescriptionHelpFormatter):
    def __init__(self, prog: str) -> None:
        width = shutil.get_terminal_size((120, 20)).columns
        super().__init__(prog, width=width, max_help_position=32)


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




