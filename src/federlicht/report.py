#!/usr/bin/env python3
# -*- coding: utf-8 -*-

"""
In-depth, multi-step report generator for a Feather run (Federlicht).

Usage:
  federlicht --run ./examples/runs/20260109_sectioned --output ./examples/runs/20260109_sectioned/report_full.md
  federlicht --run ./examples/runs/20260109_sectioned --notes-dir ./examples/runs/20260109_sectioned/report_notes
  federlicht --run ./examples/runs/20260104_oled --output ./examples/runs/20260104_oled/report_full.html --web-search
  federlicht --run ./examples/runs/20260104_oled --output ./examples/runs/20260104_oled/report_full.tex --template prl_manuscript
  python scripts/federlicht_report.py --run ./examples/runs/20260104_oled --output ./examples/runs/20260104_oled/report_full.html
"""

from __future__ import annotations

import argparse
import base64
import datetime as dt
import io
import html as html_lib
import hashlib
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


DEFAULT_MODEL = "gpt-5.2"
DEFAULT_CHECK_MODEL = "gpt-4o"
STREAMING_ENABLED = False
DEFAULT_AUTHOR = "Hyun-Jung Kim / AI Governance Team"
DEFAULT_TEMPLATE_NAME = "default"
FORMAL_TEMPLATES = {
    "prl_manuscript",
    "prl_perspective",
    "review_of_modern_physics",
    "nature_reviews",
    "nature_journal",
    "arxiv_preprint",
    "acs_review",
}
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


def templates_dir() -> Path:
    env = os.getenv("FEDERLICHT_TEMPLATES_DIR") or os.getenv("FEATHER_TEMPLATES_DIR")
    if env:
        path = Path(env).expanduser()
        if path.exists():
            return path
    here = Path(__file__).resolve()
    for parent in [here.parent, *here.parents]:
        candidate = parent / "scripts" / "templates"
        if candidate.exists():
            return candidate
    return here.parent / "templates"


def list_builtin_templates() -> list[str]:
    root = templates_dir()
    if not root.exists():
        return [DEFAULT_TEMPLATE_NAME]
    names = sorted({path.stem for path in root.glob("*.md") if path.is_file()})
    if DEFAULT_TEMPLATE_NAME not in names:
        names.insert(0, DEFAULT_TEMPLATE_NAME)
    return names


def parse_args() -> argparse.Namespace:
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
        description="Deepagents in-depth report generator.",
        formatter_class=argparse.RawTextHelpFormatter,
        epilog=epilog,
    )
    ap.add_argument("--run", help="Path to run folder (or its archive/ subfolder).")
    ap.add_argument(
        "--output",
        help="Write report to this path (default: print to stdout). Extension selects format (.md/.html/.tex).",
    )
    ap.add_argument(
        "--echo-markdown",
        action=argparse.BooleanOptionalAction,
        default=False,
        help="When --output is set, also print the markdown report to stdout (default: disabled).",
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
    ap.add_argument("--lang", default="ko", help="Report language preference (default: ko).")
    ap.add_argument("--prompt", help="Inline report focus prompt.")
    ap.add_argument("--prompt-file", help="Path to a text file containing a report focus prompt.")
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
        "--preview-template",
        help="Generate template preview HTML and exit (name, path, or 'all').",
    )
    ap.add_argument(
        "--preview-output",
        help="Preview output path or directory (default: templates/ or scripts/templates/).",
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
        help="Quality selection strategy (pairwise: compare candidates then synthesize, best_of: keep highest score).",
    )
    ap.add_argument("--quality-model", help="Optional model name for critique/revision loops.")
    ap.add_argument(
        "--check-model",
        default=DEFAULT_CHECK_MODEL,
        help=f"Model name for alignment/plan checks and quality loops (default: {DEFAULT_CHECK_MODEL}).",
    )
    ap.add_argument("--quality-max-chars", type=int, default=12000, help="Max chars passed to critique/revision.")
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
        "--model-vision",
        help=(
            "Optional vision model name for analyzing extracted figures. "
            "Uses OPENAI_BASE_URL_VISION/OPENAI_API_KEY_VISION when available."
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
    ap.add_argument("--progress-chars", type=int, default=800, help="Max chars for progress snippets.")
    ap.add_argument("--max-files", type=int, default=200, help="Max files to list in tool output.")
    ap.add_argument("--max-chars", type=int, default=16000, help="Max chars returned by read tool.")
    ap.add_argument("--max-pdf-pages", type=int, default=6, help="Max PDF pages to extract when needed.")
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
    ap.add_argument("--figures-max-per-pdf", type=int, default=4, help="Max figures extracted per PDF.")
    ap.add_argument("--figures-min-area", type=int, default=12000, help="Min image area (px^2) to keep.")
    ap.add_argument(
        "--figures-renderer",
        default="auto",
        choices=["auto", "pdfium", "poppler", "mupdf", "none"],
        help="Renderer for vector PDF pages when needed (default: auto).",
    )
    ap.add_argument("--figures-dpi", type=int, default=150, help="DPI for rendered PDF pages.")
    ap.add_argument(
        "--figures-mode",
        choices=["select", "auto"],
        default="select",
        help="Figure insertion mode: select requires a selection file; auto inserts all candidates.",
    )
    ap.add_argument(
        "--figures-select",
        help="Path to a figure selection file (default: report_notes/figures_selected.txt).",
    )
    ap.add_argument("--max-refs", type=int, default=200, help="Max references to append (default: 200).")
    ap.add_argument("--notes-dir", help="Optional folder to save intermediate notes (scout/evidence).")
    ap.add_argument("--author", help="Author name shown in the report header.")
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
    ap.add_argument("--web-max-queries", type=int, default=4, help="Max web queries to run when enabled.")
    ap.add_argument("--web-max-results", type=int, default=5, help="Max results per web query.")
    ap.add_argument("--web-max-fetch", type=int, default=6, help="Max URLs to fetch across web results.")
    ap.add_argument("--supporting-dir", help="Optional folder for web supporting info.")
    return ap.parse_args()


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
    prompt = prompt_override or build_template_designer_prompt()
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


def find_baseline_report(run_dir: Path) -> Optional[Path]:
    candidate = run_dir / "report.md"
    return candidate if candidate.exists() else None


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


def load_report_prompt(prompt_text: Optional[str], prompt_file: Optional[str]) -> Optional[str]:
    parts: list[str] = []
    if prompt_file:
        path = Path(prompt_file)
        content = path.read_text(encoding="utf-8", errors="replace").strip()
        if content:
            parts.append(content)
    if prompt_text:
        text = prompt_text.strip()
        if text:
            parts.append(text)
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


def truncate_text(text: str, max_chars: int) -> str:
    if max_chars <= 0 or len(text) <= max_chars:
        return text
    head = text[: max_chars // 2]
    tail = text[-max_chars // 2 :]
    return f"{head}\n... [truncated] ...\n{tail}"


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


def extract_json_object(text: str) -> Optional[dict]:
    start = text.find("{")
    end = text.rfind("}")
    if start == -1 or end == -1 or end <= start:
        return None
    snippet = text[start : end + 1]
    try:
        return json.loads(snippet)
    except json.JSONDecodeError:
        return None


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
    lines.append(f"Output format: {meta.get('output_format', '-')}")
    if meta.get("pdf_status"):
        lines.append(f"PDF compile: {meta.get('pdf_status')}")
    if output_format != "html":
        if meta.get("run_overview_path"):
            lines.append(f"Run overview: {meta.get('run_overview_path')}")
        if meta.get("report_overview_path"):
            lines.append(f"Report overview: {meta.get('report_overview_path')}")
        if meta.get("archive_index_path"):
            lines.append(f"Archive index: {meta.get('archive_index_path')}")
        if meta.get("instruction_path"):
            lines.append(f"Instruction file: {meta.get('instruction_path')}")
        if meta.get("report_prompt_path"):
            lines.append(f"Report prompt: {meta.get('report_prompt_path')}")
        if meta.get("figures_preview_path"):
            lines.append(f"Figure candidates: {meta.get('figures_preview_path')}")
    if output_format == "tex":
        block = ["", "\\section*{Miscellaneous}", "\\small", "\\begin{itemize}"]
        block.extend([f"\\item {latex_escape(line)}" for line in lines])
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
        add_link("Archive index", meta.get("archive_index_path"))
        add_link("Instruction file", meta.get("instruction_path"))
        add_link("Report prompt", meta.get("report_prompt_path"))
        add_link("Figure candidates", meta.get("figures_preview_path"))
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
            ]
        )
    block = ["", "## Miscellaneous"]
    block.extend([f"- {line}" for line in lines])
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
) -> dict:
    metrics = ", ".join(QUALITY_WEIGHTS.keys())
    evaluator_prompt = build_evaluate_prompt(metrics)
    evaluator_agent = create_agent_with_fallback(create_deep_agent, model_name, tools, evaluator_prompt, backend)
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
            truncate_text(evidence_notes, max_chars),
            "",
            "Report:",
            truncate_text(report_text, max_chars),
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
) -> dict:
    judge_prompt = build_compare_prompt()
    judge_agent = create_agent_with_fallback(create_deep_agent, model_name, tools, judge_prompt, backend)
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
            truncate_text(evidence_notes, max_chars),
            "",
            "Report A evaluation summary:",
            summarize_evaluation(eval_a),
            "",
            "Report A:",
            truncate_text(report_a, max_chars),
            "",
            "Report B evaluation summary:",
            summarize_evaluation(eval_b),
            "",
            "Report B:",
            truncate_text(report_b, max_chars),
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
) -> str:
    format_instructions = build_format_instructions(output_format, required_sections, free_form=args.free_format)
    synthesis_prompt = build_synthesize_prompt(format_instructions, template_guidance_text, language)
    synthesis_agent = create_agent_with_fallback(create_deep_agent, model_name, tools, synthesis_prompt, backend)
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
            truncate_text(evidence_notes, max_chars),
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
            truncate_text(report_a, max_chars),
            "",
            "Report B:",
            truncate_text(report_b, max_chars),
        ]
    )
    result = synthesis_agent.invoke({"messages": [{"role": "user", "content": synthesis_input}]})
    return extract_agent_text(result)


def resolve_notes_dir(run_dir: Path, notes_dir: Optional[str]) -> Path:
    if notes_dir:
        path = Path(notes_dir)
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


def request_headers() -> dict[str, str]:
    return {"User-Agent": "Federlicht/1.0 (+https://example.local)"}


def slugify_url(url: str, max_len: int = 80) -> str:
    parsed = urllib.parse.urlparse(url)
    host = parsed.netloc.replace("www.", "")
    path = parsed.path.strip("/").replace("/", "_")
    base = "_".join([part for part in (host, path) if part])
    cleaned = re.sub(r"[^A-Za-z0-9._-]+", "_", base).strip("_")
    if not cleaned:
        cleaned = "resource"
    digest = hashlib.sha1(url.encode("utf-8")).hexdigest()[:8]
    trimmed = cleaned[:max_len]
    return f"{trimmed}-{digest}"


def slugify_label(label: str, max_len: int = 48) -> str:
    cleaned = re.sub(r"[^A-Za-z0-9._-]+", "_", label.strip().lower()).strip("_")
    if not cleaned:
        cleaned = "stage"
    return cleaned[:max_len]


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
    prompt = prompt_override or build_template_adjuster_prompt(output_format)
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
        truncate_text(scout_notes, 4000),
    ]
    if align_scout:
        user_parts.extend(["", "Alignment notes (scout):", truncate_text(align_scout, 2000)])
    if clarification_answers:
        user_parts.extend(["", "User clarifications:", truncate_text(clarification_answers, 1200)])
    agent_model = model_override or model_name
    agent = create_agent_with_fallback(create_deep_agent, agent_model, [], prompt, backend)
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


def build_format_instructions(
    output_format: str,
    required_sections: list[str],
    free_form: bool = False,
) -> FormatInstructions:
    report_skeleton = ""
    if free_form:
        required_list = "\n".join(f"- {section}" for section in required_sections)
        if required_sections:
            section_heading_instruction = (
                "Choose a clear section structure using H2 headings (use H3 for subpoints). "
                "Include the required sections listed below using these exact H2 headings and place them at the end "
                "of the report body. Do not use H3 for top-level sections.\n"
                if output_format != "tex"
                else "Choose a clear section structure using \\section headings (use \\subsection for subpoints). "
                "Include the required sections listed below using these exact \\section headings and place them at the end "
                "of the report body.\n"
            )
            report_skeleton = required_list
        else:
            section_heading_instruction = (
                "Choose a clear section structure using H2 headings (use H3 for subpoints). "
                "If the report prompt specifies headings or ordering, follow it exactly.\n"
                if output_format != "tex"
                else "Choose a clear section structure using \\section headings (use \\subsection for subpoints). "
                "If the report prompt specifies headings or ordering, follow it exactly.\n"
            )
    else:
        report_skeleton = build_report_skeleton(required_sections, output_format)
        section_heading_instruction = (
            "Use the following exact H2 headings in this order (do not rename; do not add extra H2 headings):\n"
            if output_format != "tex"
            else "Use the following exact \\section headings in this order (do not rename; do not add extra \\section headings):\n"
        )
    citation_instruction = (
        "Avoid printing full URLs in the body; use short link labels like [source] or [paper] instead. "
        "Prefer markdown links for file paths so they are clickable. "
        if output_format != "tex"
        else "When citing sources, include the raw URL or file path inside square brackets "
        "(e.g., [https://example.com], [./archive/path.txt]). Do not use Markdown links. "
        "Avoid printing full URLs elsewhere in the body. "
    )
    latex_safety_instruction = ""
    format_instruction = ""
    if output_format == "tex":
        latex_safety_instruction = (
            "LaTeX safety: escape special characters in text/headings (use \\& for &, \\% for %, \\# for #). "
            "Only use & inside tabular/align environments. "
            "Use underscores only inside math; otherwise escape as \\_. "
        )
        section_rule = (
            "Use \\section{...} headings for each required section and \\subsection for subpoints. "
            if not free_form
            else "Use \\section{...} headings as needed and \\subsection for subpoints. "
        )
        format_instruction = (
            "Write LaTeX body only (no documentclass/preamble). "
            f"{section_rule}"
            "Do not use Markdown formatting. "
            "Avoid square brackets except for raw source citations. "
            f"{latex_safety_instruction}"
        )
    return FormatInstructions(
        report_skeleton=report_skeleton,
        section_heading_instruction=section_heading_instruction,
        latex_safety_instruction=latex_safety_instruction,
        format_instruction=format_instruction,
        citation_instruction=citation_instruction,
    )


def build_scout_prompt(language: str) -> str:
    return (
        "You are a source scout. Map the archive, identify key source files, and propose a reading plan. "
        "Always open JSONL metadata files if present (archive/tavily_search.jsonl, archive/openalex/works.jsonl, "
        "archive/arxiv/papers.jsonl, archive/youtube/videos.jsonl, archive/local/manifest.jsonl) to understand coverage. "
        "Note: the filesystem root '/' is mapped to the run folder. "
        "Treat JSONL files as indices of sources, not as the report output. "
        "Follow any report focus prompt provided in the user input. "
        "Prioritize sources relevant to the report focus and ignore off-topic items. "
        f"Write notes in {language}. Keep proper nouns and source titles in their original language. "
        "Use list_archive_files and read_document as needed. Output a structured inventory and a prioritized "
        "list of files to read (max 12) with rationale."
    )


def build_clarifier_prompt(language: str) -> str:
    return (
        "You are a report planning assistant. Based on the run context, scout notes, and report focus prompt, "
        "decide if you need clarifications from the user. If none are needed, respond with 'NO_QUESTIONS'. "
        f"Otherwise, list up to 5 concise questions in {language}."
    )


def build_alignment_prompt(language: str) -> str:
    normalized = normalize_lang(language)
    if normalized == "Korean":
        return (
            "당신은 정합성 검토자입니다. 단계 산출물이 보고서 포커스 프롬프트 및 사용자 보충 설명과 "
            "정합되는지 평가하세요. 프롬프트/보충 정보가 없으면 런 컨텍스트(쿼리 ID, 지시문 범위, "
            "가용 소스)에 대한 정합성을 판단하세요. 아래 형식을 정확히 지키세요:\n"
            "정합성 점수: <0-100>\n"
            "정합:\n- ...\n"
            "누락/리스크:\n- ...\n"
            "다음 단계 가이드:\n- ...\n"
            "간결하고 실행 가능하게 작성하세요."
        )
    return (
        "You are an alignment auditor. Check whether the stage output aligns with the report focus prompt "
        "and any user clarifications. If no prompt or clarifications exist, judge alignment to the run context "
        "(query ID, instruction scope, and available sources). Return in this exact format:\n"
        "Alignment score: <0-100>\n"
        "Aligned:\n- ...\n"
        "Gaps/Risks:\n- ...\n"
        "Next-step guidance:\n- ...\n"
        "Be concise and actionable."
    )


def build_plan_prompt(language: str) -> str:
    return (
        "You are a report planner. Create a concise, ordered plan (5-9 steps) to produce the final report. "
        "Each step should be one line with a status checkbox. "
        "Use this format:\n"
        "- [ ] Step title — short description\n"
        "Focus on reading the most relevant sources, extracting evidence, and synthesizing insights. "
        "Align the plan with the report focus prompt and clarifications. "
        f"Write in {language}."
    )


def build_plan_check_prompt(language: str) -> str:
    return (
        "You are a plan checker. Update the plan by marking completed steps with [x] and "
        "adding any missing steps needed to finish the report. Keep it concise. "
        f"Write in {language}."
    )


def build_web_prompt() -> str:
    return (
        "You are planning targeted web searches to enrich a research report. "
        "Provide up to 6 concise search queries in English, one per line. "
        "Focus on recent, credible sources and technical specifics. "
        "Avoid broad keywords; include concrete phrases, paper titles, or domains when helpful."
    )


def build_evidence_prompt(language: str) -> str:
    return (
        "You are an evidence extractor. Use the scout notes to read key files and extract salient facts. "
        "Start by reading any JSONL metadata files that exist (tavily_search.jsonl, openalex/works.jsonl, "
        "arxiv/papers.jsonl, youtube/videos.jsonl, local/manifest.jsonl) to identify sources. "
        "Do not cite JSONL index files in your evidence; cite the underlying source URLs and extracted text/PDF files. "
        "If full text files are missing, you may use abstracts/summaries from metadata (e.g., arXiv summary or "
        "OpenAlex abstract) but still cite the original source URL, not the JSONL. "
        "If a supporting folder exists (./supporting/...), also read supporting/web_search.jsonl and "
        "supporting/web_extract or supporting/web_text to incorporate updated web evidence. "
        "Use JSONL to locate the actual content (extracts, PDFs, transcripts) and summarize those sources. "
        "If a source is off-topic relative to the report focus, skip it. "
        "Cite file paths in square brackets. Prefer existing extracted text files; use PDFs only when needed. "
        "Capture original source URLs (not only archive paths) when available. "
        f"Deliver concise bullet lists grouped by source type in {language}. "
        "Keep proper nouns and source titles in their original language."
    )


def build_writer_prompt(
    format_instructions: FormatInstructions,
    template_guidance_text: str,
    template_spec: TemplateSpec,
    required_sections: list[str],
    output_format: str,
    language: str,
) -> str:
    critics_guidance = ""
    if any(section.lower().startswith("critics") for section in required_sections):
        critics_guidance = (
            "For the Critics section, write in a concise editorial tone with a short headline, brief paragraphs, "
            "and a few bullet points highlighting orthogonal or contrarian viewpoints, risks, or overlooked constraints. "
            "If relevant, touch on AI ethics, regulation (e.g., EU AI Act), safety/security, and explainability. "
        )
    risk_gap_guidance = ""
    if any(section.lower().startswith("risks") for section in required_sections):
        risk_gap_guidance = (
            "For the Risks & Gaps section, highlight constraints, missing evidence, and validation needs; "
            "calibrate depth to evidence strength and context. "
        )
    not_applicable_guidance = (
        "If Risks & Gaps or Critics are not applicable for this report, write a brief "
        "'Not applicable' note (Korean: '해당없음') and explain why. "
    )
    tone_instruction = (
        "Use a formal/academic research-journal tone suitable for PRL/Nature/Annual Review-style manuscripts. "
        if template_spec.name in FORMAL_TEMPLATES
        else "Use an explanatory review style (설명형 리뷰) with a professional yet natural narrative tone. "
    )
    return (
        "You are a senior research writer. Using the instruction, baseline report, and evidence notes, "
        "produce a detailed report with citations. "
        f"{tone_instruction}"
        f"{format_instructions.section_heading_instruction}{format_instructions.report_skeleton}\n"
        f"{'Template guidance:\\n' + template_guidance_text + '\\n' if template_guidance_text else ''}"
        f"{format_instructions.format_instruction}"
        "Output the report body directly; do not include status updates or promises. "
        "Math formatting rule: Any formula or symbolic expression must be valid LaTeX and wrapped in $...$ "
        "(inline) or $$...$$ (block). Do not use bare brackets [ ... ] for equations. "
        "Always wrap subscripts/superscripts (e.g., $\\Delta E_{ST}$, $E(S_1)$, $S_1/T_1$). "
        "Synthesize across sources (not a list of summaries), use clear transitions, and surface actionable insights. "
        "Do not dump JSONL contents; focus on analyzing the referenced documents and articles. "
        "Never cite JSONL index files (e.g., tavily_search.jsonl, openalex/works.jsonl). Cite actual source URLs "
        "and extracted text/PDF/transcript files instead. "
        "Do not include a full References list; the script appends a Source Index automatically. "
        "Do not add Report Prompt or Clarifications sections; the script appends them automatically. "
        "Do not add a separate section enumerating figures or page numbers; the script inserts figure callouts. "
        "If you mention a figure, only do so when the source text explicitly explains it. "
        "When citing file paths, use relative paths like ./archive/... or ./instruction/... (avoid absolute paths). "
        f"{format_instructions.citation_instruction}"
        "When formulas are important, render them in LaTeX using $...$ or $$...$$ so they can be rendered in HTML. "
        f"{critics_guidance}"
        f"{risk_gap_guidance}"
        f"{not_applicable_guidance}"
        "If supporting web research exists under ./supporting/..., integrate it as updated evidence and label it as "
        "web-derived support (not primary experimental evidence). "
        f"Write the report in {language}. Keep proper nouns and source titles in their original language. "
        "Avoid speculation and clearly separate facts from interpretation."
    )


def build_repair_prompt(
    format_instructions: FormatInstructions,
    output_format: str,
    language: str,
    mode: str = "replace",
    free_form: bool = False,
) -> str:
    mode_instruction = ""
    if mode == "append":
        mode_instruction = "Return ONLY the missing sections with their headings; do not restate existing sections. "
    elif mode == "replace":
        mode_instruction = "Return the full repaired report with all sections present. "
    if free_form:
        heading_rule = (
            "Use the exact headings for the missing required sections and append them at the end of the report body. "
            "Do not remove or rename any existing sections. "
        )
    else:
        heading_rule = "Use the exact section headings in the required skeleton and keep their order. "
    return (
        "You are a structural editor. The report is missing required sections. "
        "Add the missing sections while preserving all existing content and citations. "
        f"{mode_instruction}"
        f"{heading_rule}"
        "Do not add extra section headings. Do not include status updates or promises. "
        f"{'Prefer markdown links for file paths. ' if output_format != 'tex' else 'Keep LaTeX section commands and avoid Markdown formatting. '}"
        f"{format_instructions.latex_safety_instruction}"
        f"Write in {language}."
    )


def build_critic_prompt(language: str, required_sections: list[str]) -> str:
    required_sections_label = ", ".join(required_sections)
    section_check = (
        f"Confirm all required sections are present ({required_sections_label}) and note any missing. "
        if required_sections
        else "Assess whether the section structure is clear and appropriate. "
    )
    return (
        "You are a rigorous journal editor. Critique the report for clarity, narrative flow, "
        "depth of insight, evidence usage, and alignment with the report focus. "
        "Flag any reliance on JSONL index data instead of source content, including citations that point "
        "to JSONL index files rather than the underlying sources. "
        f"{section_check}"
        "If the report already meets high-quality standards, respond with 'NO_CHANGES'. "
        f"Write in {language}."
    )


def build_revise_prompt(format_instructions: FormatInstructions, output_format: str, language: str) -> str:
    section_rule = (
        "Preserve the required sections and citations. "
        if format_instructions.report_skeleton
        else "Preserve citations and keep the section structure coherent. "
    )
    return (
        "You are a senior editor. Revise the report to address the critique. "
        f"{section_rule}"
        "Improve narrative flow, synthesis, and technical rigor. "
        "Do not add a full References list; the script appends a Source Index automatically. "
        f"{'Keep LaTeX formatting and section commands; do not convert to Markdown. ' if output_format == 'tex' else ''}"
        f"{format_instructions.latex_safety_instruction}"
        f"Write in {language}."
    )


def build_evaluate_prompt(metrics: str) -> str:
    return (
        "You are a rigorous report evaluator. Score the report across multiple dimensions, "
        "including alignment with the report prompt, tone/voice fit, output-format compliance, "
        "structure/readability, evidence grounding, hallucination risk (lower risk = higher score), "
        "insight depth, and aesthetic/visual completeness. "
        "Return JSON only with these keys:\n"
        f"{metrics}, overall, strengths, weaknesses, fixes\n"
        "Each score must be 0-100 (higher is better). "
        "For hallucination risk, output a high score when risk is low (i.e., well-grounded). "
        "Provide strengths/weaknesses/fixes as short bullet strings (array of strings). "
        "Do not include any extra text outside JSON."
    )


def build_compare_prompt() -> str:
    return (
        "You are a senior journal editor. Compare Report A vs Report B and choose the stronger report. "
        "Consider alignment, evidence grounding, hallucination risk, format compliance, clarity, "
        "and narrative strength. Return JSON only:\n"
        "{\"winner\": \"A|B|Tie\", \"reason\": \"...\", \"focus_improvements\": [\"...\"]}\n"
        "Do not include any extra text outside JSON."
    )


def build_synthesize_prompt(
    format_instructions: FormatInstructions,
    template_guidance_text: str,
    language: str,
) -> str:
    return (
        "You are a chief editor. Merge the strongest parts of Report A and Report B, fix weaknesses, "
        "and produce a final report with higher overall quality. "
        "Preserve citations; do not invent sources. "
        "Do not add a full References list; the script appends it automatically. "
        f"{format_instructions.section_heading_instruction}{format_instructions.report_skeleton}\n"
        f"{'Template guidance:\\n' + template_guidance_text + '\\n' if template_guidance_text else ''}"
        f"{format_instructions.format_instruction}"
        f"Write in {language}."
    )


def build_template_adjuster_prompt(output_format: str) -> str:
    heading_rule = (
        'For LaTeX output, avoid &, %, # in headings. Use "and" or plain words instead.'
        if output_format == "tex"
        else "Keep headings concise and consistent."
    )
    return (
        "You are a template adjuster. Adapt the section list and guidance to match the run intent. "
        "Use the template as style reference, but adjust structure if needed. "
        "Keep any required sections listed below. "
        "Do not add a References section. "
        f"{heading_rule} "
        "Return JSON only with keys: sections (ordered list), section_guidance (object), "
        "writer_guidance (list), rationale (string). If no changes are needed, return the original sections "
        "and set rationale to 'no_change'."
    )


def build_template_designer_prompt() -> str:
    return (
        "You are a template designer. Generate guidance for each section of a research-style review.\n"
        "Return JSON with keys:\n"
        "- section_guidance: object mapping section title -> 1-2 sentence guidance\n"
        "- writer_guidance: list of short bullets for overall tone/rigor\n"
        "Keep guidance concise, evidence-focused, and aligned to the report focus prompt.\n"
        "Write in the requested language."
    )


def build_image_prompt() -> str:
    return (
        "You are an image analyst. Describe the figure strictly based on what is visible. "
        "Return JSON only with keys: summary (1-2 sentences), type (chart/diagram/table/screenshot/photo/other), "
        "relevance (0-100), recommended (yes/no). If unclear, use summary='unclear'."
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
        "template_adjust",
        "template_adjust_mode",
        "quality_iterations",
        "quality_strategy",
        "web_search",
        "alignment_check",
        "stream",
        "stream_debug",
        "repair_mode",
        "repair_debug",
        "interactive",
        "free_format",
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
    if isinstance(config.get("repair_mode"), str) and config["repair_mode"] in {"append", "replace", "off"}:
        args.repair_mode = config["repair_mode"]
    if isinstance(config.get("repair_debug"), bool):
        args.repair_debug = config["repair_debug"]
    if isinstance(config.get("interactive"), bool):
        args.interactive = config["interactive"]
    if isinstance(config.get("free_format"), bool):
        args.free_format = config["free_format"]
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
        if payload:
            overrides[str(name)] = payload
    return overrides


def resolve_agent_enabled(name: str, default: bool, overrides: dict) -> bool:
    entry = overrides.get(name)
    if not isinstance(entry, dict):
        return default
    enabled = entry.get("enabled")
    return enabled if isinstance(enabled, bool) else default


def resolve_agent_prompt(name: str, default_prompt: str, overrides: dict) -> str:
    entry = overrides.get(name)
    if not isinstance(entry, dict):
        return default_prompt
    prompt = entry.get("system_prompt")
    return prompt if isinstance(prompt, str) and prompt.strip() else default_prompt


def resolve_agent_model(name: str, default_model: str, overrides: dict) -> str:
    entry = overrides.get(name)
    if not isinstance(entry, dict):
        return default_model
    model = entry.get("model")
    return model if isinstance(model, str) and model.strip() else default_model


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
    if not required_sections and not free_format:
        required_sections = list(DEFAULT_SECTIONS)
    if not template_guidance_text:
        template_guidance_text = build_template_guidance_text(template_spec)
    overrides = normalize_agent_overrides(agent_overrides)
    quality_model = args.quality_model or args.check_model or args.model
    format_instructions = build_format_instructions(output_format, required_sections, free_form=args.free_format)
    metrics = ", ".join(QUALITY_WEIGHTS.keys())
    writer_prompt = resolve_agent_prompt(
        "writer",
        build_writer_prompt(
            format_instructions,
            template_guidance_text,
            template_spec,
            required_sections,
            output_format,
            language,
        ),
        overrides,
    )
    scout_prompt = resolve_agent_prompt("scout", build_scout_prompt(language), overrides)
    clarifier_prompt = resolve_agent_prompt("clarifier", build_clarifier_prompt(language), overrides)
    align_prompt = resolve_agent_prompt("alignment", build_alignment_prompt(language), overrides)
    plan_prompt = resolve_agent_prompt("planner", build_plan_prompt(language), overrides)
    plan_check_prompt = resolve_agent_prompt("plan_check", build_plan_check_prompt(language), overrides)
    web_prompt = resolve_agent_prompt("web_query", build_web_prompt(), overrides)
    evidence_prompt = resolve_agent_prompt("evidence", build_evidence_prompt(language), overrides)
    repair_prompt = resolve_agent_prompt(
        "structural_editor",
        build_repair_prompt(format_instructions, output_format, language, free_form=args.free_format),
        overrides,
    )
    critic_prompt = resolve_agent_prompt("critic", build_critic_prompt(language, required_sections), overrides)
    revise_prompt = resolve_agent_prompt(
        "reviser",
        build_revise_prompt(format_instructions, output_format, language),
        overrides,
    )
    evaluate_prompt = resolve_agent_prompt("evaluator", build_evaluate_prompt(metrics), overrides)
    compare_prompt = resolve_agent_prompt("pairwise_compare", build_compare_prompt(), overrides)
    synthesize_prompt = resolve_agent_prompt(
        "synthesizer",
        build_synthesize_prompt(format_instructions, template_guidance_text, language),
        overrides,
    )
    template_adjuster_prompt = resolve_agent_prompt(
        "template_adjuster",
        build_template_adjuster_prompt(output_format),
        overrides,
    )
    image_prompt = resolve_agent_prompt("image_analyst", build_image_prompt(), overrides)
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
        "scout": {"model": scout_model, "system_prompt": scout_prompt},
        "clarifier": {
            "model": clarifier_model,
            "enabled": clarifier_enabled,
            "system_prompt": clarifier_prompt,
        },
        "alignment": {"model": alignment_model, "enabled": alignment_enabled, "system_prompt": align_prompt},
        "planner": {"model": planner_model, "system_prompt": plan_prompt},
        "plan_check": {"model": plan_check_model, "system_prompt": plan_check_prompt},
        "web_query": {"model": web_model, "enabled": web_enabled, "system_prompt": web_prompt},
        "evidence": {"model": evidence_model, "system_prompt": evidence_prompt},
        "writer": {"model": writer_model, "system_prompt": writer_prompt},
        "structural_editor": {"model": structural_model, "system_prompt": repair_prompt},
        "critic": {"model": critic_model, "enabled": critic_enabled, "system_prompt": critic_prompt},
        "reviser": {"model": reviser_model, "enabled": reviser_enabled, "system_prompt": revise_prompt},
        "evaluator": {"model": evaluator_model, "enabled": evaluator_enabled, "system_prompt": evaluate_prompt},
        "pairwise_compare": {
            "model": compare_model,
            "enabled": pairwise_enabled,
            "system_prompt": compare_prompt,
        },
        "synthesizer": {
            "model": synth_model,
            "enabled": synth_enabled,
            "system_prompt": synthesize_prompt,
        },
        "template_adjuster": {
            "model": template_adjuster_model,
            "enabled": template_adjust_enabled,
            "system_prompt": template_adjuster_prompt,
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
            "quality_model": quality_model,
            "model_vision": args.model_vision,
            "template": template_spec.name,
            "template_adjust": template_adjust_enabled,
            "free_format": args.free_format,
            "quality_iterations": args.quality_iterations,
            "quality_strategy": args.quality_strategy,
            "web_search": args.web_search,
            "alignment_check": args.alignment_check,
            "interactive": args.interactive,
        },
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


def write_template_preview(template_spec: TemplateSpec, output_path: Path) -> None:
    markdown = build_template_preview_markdown(template_spec)
    body_html = markdown_to_html(markdown)
    body_html = linkify_html(body_html)
    theme_css = load_template_css(template_spec)
    rendered = wrap_html(
        f"Template Preview - {template_spec.name}",
        body_html,
        template_name=template_spec.name,
        theme_css=theme_css,
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


def html_to_text(html_text: str) -> str:
    try:
        from bs4 import BeautifulSoup  # type: ignore
    except Exception:
        BeautifulSoup = None

    if BeautifulSoup is not None:
        soup = BeautifulSoup(html_text, "html.parser")
        for tag in soup(["script", "style", "noscript"]):
            tag.decompose()
        return soup.get_text("\n", strip=True)
    cleaned = re.sub(r"(?is)<(script|style|noscript).*?>.*?</\\1>", "", html_text)
    cleaned = re.sub(r"(?is)<br\\s*/?>", "\n", cleaned)
    cleaned = re.sub(r"(?is)</p>", "\n\n", cleaned)
    cleaned = re.sub(r"(?is)<[^>]+>", "", cleaned)
    return re.sub(r"\n{3,}", "\n\n", cleaned).strip()


def read_pdf_with_fitz(pdf_path: Path, max_pages: int, max_chars: int) -> str:
    try:
        import fitz  # type: ignore
    except Exception:
        return "PyMuPDF (pymupdf) is not installed. Cannot read PDF."
    doc = fitz.open(str(pdf_path))
    pages = min(max_pages, doc.page_count)
    chunks = []
    for page in range(pages):
        chunks.append(doc.load_page(page).get_text())
    text = "\n".join(chunks)
    return text[:max_chars]


def extract_pdf_images(
    pdf_path: Path,
    output_dir: Path,
    run_dir: Path,
    max_per_pdf: int,
    min_area: int,
) -> list[dict]:
    try:
        import fitz  # type: ignore
    except Exception:
        return []
    output_dir.mkdir(parents=True, exist_ok=True)
    records: list[dict] = []
    candidates: list[dict] = []
    pdf_rel = f"./{pdf_path.relative_to(run_dir).as_posix()}"
    try:
        doc = fitz.open(str(pdf_path))
    except Exception:
        return records
    seen: set[int] = set()
    for page_index in range(len(doc)):
        page = doc[page_index]
        images = page.get_images(full=True)
        for img_index, img in enumerate(images):
            xref = img[0]
            if xref in seen:
                continue
            seen.add(xref)
            try:
                base = doc.extract_image(xref)
            except Exception:
                continue
            width = int(base.get("width") or 0)
            height = int(base.get("height") or 0)
            if width and height and width * height < min_area:
                continue
            ext = (base.get("ext") or "png").lower()
            image_bytes = base.get("image", b"")
            if not image_bytes:
                continue
            pil = _pillow_image()
            if pil is not None:
                try:
                    image = pil.open(io.BytesIO(image_bytes))
                except Exception:
                    continue
                if not _image_is_probably_figure(image, min_area):
                    continue
            tag = f"{pdf_rel}#p{page_index + 1}-{img_index + 1}"
            candidates.append(
                {
                    "pdf_path": pdf_rel,
                    "page": page_index + 1,
                    "width": width,
                    "height": height,
                    "area": width * height,
                    "tag": tag,
                    "ext": ext,
                    "image": image_bytes,
                }
            )
    if candidates:
        candidates.sort(key=lambda item: item["area"], reverse=True)
        for candidate in candidates[:max_per_pdf]:
            name = f"{slugify_url(candidate['tag'])}.{candidate['ext']}"
            img_path = output_dir / name
            if not img_path.exists():
                try:
                    with img_path.open("wb") as handle:
                        handle.write(candidate["image"])
                except Exception:
                    continue
            img_rel = f"./{img_path.relative_to(run_dir).as_posix()}"
            records.append(
                {
                    "pdf_path": candidate["pdf_path"],
                    "image_path": img_rel,
                    "page": candidate["page"],
                    "width": candidate["width"],
                    "height": candidate["height"],
                    "method": "embedded",
                }
            )
    doc.close()
    return records


def _pillow_image() -> Optional[object]:
    try:
        from PIL import Image  # type: ignore
    except Exception:
        return None
    return Image


def encode_image_for_vision(image_path: Path, max_side: int = 1024) -> tuple[str, str]:
    Image = _pillow_image()
    if Image:
        try:
            with Image.open(image_path) as img:
                if max(img.size) > max_side:
                    scale = max_side / max(img.size)
                    new_size = (max(1, int(img.width * scale)), max(1, int(img.height * scale)))
                    img = img.resize(new_size)
                buffer = io.BytesIO()
                img.save(buffer, format="PNG")
                data = buffer.getvalue()
                return base64.b64encode(data).decode("utf-8"), "image/png"
        except Exception:
            pass
    data = image_path.read_bytes()
    mime = "image/png"
    if image_path.suffix.lower() in {".jpg", ".jpeg"}:
        mime = "image/jpeg"
    return base64.b64encode(data).decode("utf-8"), mime


def analyze_figure_with_vision(model, image_path: Path) -> Optional[dict]:
    payload_b64, mime = encode_image_for_vision(image_path)
    system_prompt = (
        "You are an image analyst. Describe the figure strictly based on what is visible. "
        "Return JSON only with keys: summary (1-2 sentences), type (chart/diagram/table/screenshot/photo/other), "
        "relevance (0-100), recommended (yes/no). If unclear, use summary='unclear'."
    )
    user_content = [
        {"type": "text", "text": "Analyze this figure for a technical report."},
        {"type": "image_url", "image_url": {"url": f"data:{mime};base64,{payload_b64}"}},
    ]
    try:
        result = model.invoke(
            [
                {"role": "system", "content": system_prompt},
                {"role": "user", "content": user_content},
            ]
        )
    except Exception as exc:
        return {"summary": "vision_error", "error": str(exc)}
    content = getattr(result, "content", None)
    text = content if isinstance(content, str) else str(content)
    parsed = extract_json_object(text)
    if isinstance(parsed, dict):
        return parsed
    return {"summary": text.strip()[:400]}


def _image_is_probably_figure(image, min_area: int) -> bool:
    width, height = image.size
    if width <= 0 or height <= 0:
        return False
    area = width * height
    if area < min_area:
        return False
    aspect = width / height
    if aspect > 6.0 or aspect < (1 / 6.0):
        return False
    if width < 80 or height < 80:
        return False
    try:
        from PIL import ImageStat  # type: ignore
    except Exception:
        return True
    try:
        thumb = image.resize((128, 128))
        gray = thumb.convert("L")
        hist = gray.histogram()
        total = max(sum(hist), 1)
        white = sum(hist[246:]) / total
        if white > 0.96:
            return False
        stats = ImageStat.Stat(gray)
        if stats.var and stats.var[0] < 30:
            return False
    except Exception:
        return True
    return True


def _crop_whitespace(image, min_area: int) -> Optional[object]:
    try:
        gray = image.convert("L")
        mask = gray.point(lambda x: 0 if x > 245 else 255, "1")
        bbox = mask.getbbox()
    except Exception:
        return image
    if not bbox:
        return None
    left, top, right, bottom = bbox
    margin = 6
    left = max(0, left - margin)
    top = max(0, top - margin)
    right = min(image.width, right + margin)
    bottom = min(image.height, bottom + margin)
    cropped = image.crop((left, top, right, bottom))
    if cropped.width * cropped.height < min_area:
        return None
    return cropped


def _opencv_backend():
    try:
        import cv2  # type: ignore
        import numpy as np  # type: ignore
    except Exception:
        return None, None
    return cv2, np


def _detect_figure_regions(image, min_area: int) -> list[tuple[int, int, int, int]]:
    cv2, np = _opencv_backend()
    if cv2 is None or np is None:
        return []
    if image is None:
        return []
    try:
        rgb = np.array(image.convert("RGB"))
    except Exception:
        return []
    gray = cv2.cvtColor(rgb, cv2.COLOR_RGB2GRAY)
    _, mask = cv2.threshold(gray, 245, 255, cv2.THRESH_BINARY_INV)
    kernel = cv2.getStructuringElement(cv2.MORPH_RECT, (5, 5))
    mask = cv2.morphologyEx(mask, cv2.MORPH_CLOSE, kernel, iterations=2)
    contours, _ = cv2.findContours(mask, cv2.RETR_EXTERNAL, cv2.CHAIN_APPROX_SIMPLE)
    if not contours:
        return []
    height, width = gray.shape[:2]
    page_area = max(width * height, 1)
    boxes: list[tuple[int, int, int, int]] = []
    min_w = max(int(width * 0.1), 80)
    min_h = max(int(height * 0.08), 80)
    for contour in contours:
        x, y, w, h = cv2.boundingRect(contour)
        area = w * h
        if area < min_area:
            continue
        if w < min_w or h < min_h:
            continue
        aspect = w / h if h else 0.0
        if aspect > 6.0 or aspect < (1 / 6.0):
            continue
        boxes.append((x, y, w, h))
    boxes.sort(key=lambda box: box[2] * box[3], reverse=True)
    if len(boxes) > 1:
        x, y, w, h = boxes[0]
        if (w * h) / page_area > 0.85:
            boxes = boxes[1:]
    return boxes


def extract_image_crops(image, min_area: int, max_regions: int) -> list[object]:
    if image is None:
        return []
    crops: list[object] = []
    regions = _detect_figure_regions(image, min_area)
    if regions:
        margin = 8
        for x, y, w, h in regions:
            left = max(0, x - margin)
            top = max(0, y - margin)
            right = min(image.width, x + w + margin)
            bottom = min(image.height, y + h + margin)
            cropped = image.crop((left, top, right, bottom))
            if cropped.width * cropped.height < min_area:
                continue
            crops.append(cropped)
            if max_regions and len(crops) >= max_regions:
                break
    if not crops:
        cropped = _crop_whitespace(image, min_area)
        if cropped is not None:
            crops.append(cropped)
    return crops


def _pdfium_available() -> bool:
    try:
        import pypdfium2  # type: ignore
    except Exception:
        return False
    return _pillow_image() is not None


def _poppler_available() -> bool:
    return shutil.which("pdftocairo") is not None


def _mupdf_available() -> bool:
    return shutil.which("mutool") is not None


def select_figure_renderer(choice: str) -> str:
    value = (choice or "auto").strip().lower()
    if value in {"none", "off"}:
        return "none"
    if value == "pdfium":
        return "pdfium" if _pdfium_available() else "none"
    if value == "poppler":
        return "poppler" if _poppler_available() else "none"
    if value == "mupdf":
        return "mupdf" if _mupdf_available() else "none"
    if _pdfium_available():
        return "pdfium"
    if _poppler_available():
        return "poppler"
    if _mupdf_available():
        return "mupdf"
    return "none"


def render_pdf_pages(
    pdf_path: Path,
    output_dir: Path,
    run_dir: Path,
    renderer: str,
    dpi: int,
    max_pages: int,
    min_area: int,
) -> list[dict]:
    choice = select_figure_renderer(renderer)
    if choice == "none":
        return []
    if choice == "pdfium":
        return render_pdf_pages_pdfium(pdf_path, output_dir, run_dir, dpi, max_pages, min_area)
    if choice == "poppler":
        return render_pdf_pages_poppler(pdf_path, output_dir, run_dir, dpi, max_pages, min_area)
    if choice == "mupdf":
        return render_pdf_pages_mupdf(pdf_path, output_dir, run_dir, dpi, max_pages, min_area)
    return []


def render_pdf_pages_pdfium(
    pdf_path: Path,
    output_dir: Path,
    run_dir: Path,
    dpi: int,
    max_pages: int,
    min_area: int,
) -> list[dict]:
    try:
        import pypdfium2 as pdfium  # type: ignore
    except Exception:
        return []
    pillow = _pillow_image()
    if pillow is None:
        return []
    output_dir.mkdir(parents=True, exist_ok=True)
    records: list[dict] = []
    pdf_rel = f"./{pdf_path.relative_to(run_dir).as_posix()}"
    doc = pdfium.PdfDocument(str(pdf_path))
    pages = len(doc)
    scale = max(dpi / 72.0, 0.1)
    for page_index in range(pages):
        if len(records) >= max_pages:
            break
        page = doc.get_page(page_index)
        try:
            bitmap = page.render(scale=scale)
            image = bitmap.to_pil()
        finally:
            try:
                page.close()
            except Exception:
                pass
        crops = extract_image_crops(image, min_area, max_pages - len(records)) if image else []
        if not crops:
            continue
        for crop_index, cropped in enumerate(crops, start=1):
            tag = f"{pdf_rel}#render-p{page_index + 1}"
            if len(crops) > 1:
                tag = f"{tag}-f{crop_index}"
            name = f"{slugify_url(tag)}.png"
            img_path = output_dir / name
            try:
                cropped.save(img_path, format="PNG")
            except Exception:
                continue
            img_rel = f"./{img_path.relative_to(run_dir).as_posix()}"
            records.append(
                {
                    "pdf_path": pdf_rel,
                    "image_path": img_rel,
                    "page": page_index + 1,
                    "width": int(cropped.width),
                    "height": int(cropped.height),
                    "method": "rendered",
                }
            )
            if len(records) >= max_pages:
                break
    return records


def _crop_image_path(image_path: Path, min_area: int) -> Optional[tuple[int, int]]:
    pillow = _pillow_image()
    if pillow is None:
        return None
    Image = pillow
    try:
        image = Image.open(image_path)
    except Exception:
        return None
    cropped = _crop_whitespace(image, min_area)
    if cropped is None:
        return None
    if cropped is not image:
        try:
            cropped.save(image_path, format="PNG")
        except Exception:
            return None
    return int(cropped.width), int(cropped.height)


def render_pdf_pages_poppler(
    pdf_path: Path,
    output_dir: Path,
    run_dir: Path,
    dpi: int,
    max_pages: int,
    min_area: int,
) -> list[dict]:
    if not _poppler_available():
        return []
    output_dir.mkdir(parents=True, exist_ok=True)
    records: list[dict] = []
    pdf_rel = f"./{pdf_path.relative_to(run_dir).as_posix()}"
    for page_index in range(max_pages):
        if len(records) >= max_pages:
            break
        tag = f"{pdf_rel}#render-p{page_index + 1}"
        name = f"{slugify_url(tag)}.png"
        img_path = output_dir / name
        prefix = img_path.with_suffix("")
        cmd = [
            "pdftocairo",
            "-f",
            str(page_index + 1),
            "-l",
            str(page_index + 1),
            "-png",
            "-singlefile",
            "-r",
            str(dpi),
            str(pdf_path),
            str(prefix),
        ]
        result = subprocess.run(cmd, capture_output=True, text=True)
        if result.returncode != 0 or not img_path.exists():
            if page_index == 0:
                break
            continue
        pillow = _pillow_image()
        if pillow is None:
            size = _crop_image_path(img_path, min_area)
            if size is None:
                continue
            width, height = size
            img_rel = f"./{img_path.relative_to(run_dir).as_posix()}"
            records.append(
                {
                    "pdf_path": pdf_rel,
                    "image_path": img_rel,
                    "page": page_index + 1,
                    "width": width,
                    "height": height,
                    "method": "rendered",
                }
            )
            continue
        try:
            image = pillow.open(img_path)
        except Exception:
            continue
        crops = extract_image_crops(image, min_area, max_pages - len(records))
        if not crops:
            continue
        if len(crops) > 1 and img_path.exists():
            try:
                img_path.unlink()
            except Exception:
                pass
        for crop_index, cropped in enumerate(crops, start=1):
            tag = f"{pdf_rel}#render-p{page_index + 1}"
            if len(crops) > 1:
                tag = f"{tag}-f{crop_index}"
            name = f"{slugify_url(tag)}.png"
            crop_path = output_dir / name
            try:
                cropped.save(crop_path, format="PNG")
            except Exception:
                continue
            img_rel = f"./{crop_path.relative_to(run_dir).as_posix()}"
            records.append(
                {
                    "pdf_path": pdf_rel,
                    "image_path": img_rel,
                    "page": page_index + 1,
                    "width": int(cropped.width),
                    "height": int(cropped.height),
                    "method": "rendered",
                }
            )
            if len(records) >= max_pages:
                break
    return records


def render_pdf_pages_mupdf(
    pdf_path: Path,
    output_dir: Path,
    run_dir: Path,
    dpi: int,
    max_pages: int,
    min_area: int,
) -> list[dict]:
    if not _mupdf_available():
        return []
    output_dir.mkdir(parents=True, exist_ok=True)
    records: list[dict] = []
    pdf_rel = f"./{pdf_path.relative_to(run_dir).as_posix()}"
    for page_index in range(max_pages):
        if len(records) >= max_pages:
            break
        tag = f"{pdf_rel}#render-p{page_index + 1}"
        name = f"{slugify_url(tag)}.png"
        img_path = output_dir / name
        cmd = [
            "mutool",
            "draw",
            "-r",
            str(dpi),
            "-o",
            str(img_path),
            str(pdf_path),
            str(page_index + 1),
        ]
        result = subprocess.run(cmd, capture_output=True, text=True)
        if result.returncode != 0 or not img_path.exists():
            if page_index == 0:
                break
            continue
        pillow = _pillow_image()
        if pillow is None:
            size = _crop_image_path(img_path, min_area)
            if size is None:
                continue
            width, height = size
            img_rel = f"./{img_path.relative_to(run_dir).as_posix()}"
            records.append(
                {
                    "pdf_path": pdf_rel,
                    "image_path": img_rel,
                    "page": page_index + 1,
                    "width": width,
                    "height": height,
                    "method": "rendered",
                }
            )
            continue
        try:
            image = pillow.open(img_path)
        except Exception:
            continue
        crops = extract_image_crops(image, min_area, max_pages - len(records))
        if not crops:
            continue
        if len(crops) > 1 and img_path.exists():
            try:
                img_path.unlink()
            except Exception:
                pass
        for crop_index, cropped in enumerate(crops, start=1):
            tag = f"{pdf_rel}#render-p{page_index + 1}"
            if len(crops) > 1:
                tag = f"{tag}-f{crop_index}"
            name = f"{slugify_url(tag)}.png"
            crop_path = output_dir / name
            try:
                cropped.save(crop_path, format="PNG")
            except Exception:
                continue
            img_rel = f"./{crop_path.relative_to(run_dir).as_posix()}"
            records.append(
                {
                    "pdf_path": pdf_rel,
                    "image_path": img_rel,
                    "page": page_index + 1,
                    "width": int(cropped.width),
                    "height": int(cropped.height),
                    "method": "rendered",
                }
            )
            if len(records) >= max_pages:
                break
    return records


def markdown_to_html(markdown_text: str) -> str:
    try:
        import markdown  # type: ignore
    except Exception:
        escaped = html_lib.escape(markdown_text)
        return f"<pre>{escaped}</pre>"
    return markdown.markdown(markdown_text, extensions=["extra", "tables", "fenced_code"])


_URL_RE = re.compile(r"(https?://[^\s<]+)")
_REL_PATH_RE = re.compile(r"(?<![\w/])(\./[A-Za-z0-9_./-]+)")
_ARCHIVE_PATH_RE = re.compile(r"(/archive/[A-Za-z0-9_./-]+)")
_BARE_PATH_RE = re.compile(
    r"(?<![\w./])((?:archive|instruction|report_notes|report|supporting)/[A-Za-z0-9_./-]+)"
)
_WINDOWS_ABS_RE = re.compile(r"^[A-Za-z]:/")
_CODE_LINK_RE = re.compile(
    r"^(https?://\S+|\.?/archive/\S+|\.?/instruction/\S+|\.?/report_notes/\S+|\.?/report/\S+|"
    r"\.?/supporting/\S+|archive/\S+|instruction/\S+|report_notes/\S+|report/\S+|supporting/\S+|[A-Za-z]:/\S+)$"
)
_CITED_PATH_RE = re.compile(
    r"(?<![\w./])((?:\./)?(?:archive|instruction|report_notes|report|supporting)/[A-Za-z0-9_./-]+)"
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


def render_viewer_html(title: str, body_html: str) -> str:
    safe_title = html_lib.escape(title)
    return (
        "<!doctype html>\n"
        "<html lang=\"en\">\n"
        "<head>\n"
        "  <meta charset=\"utf-8\" />\n"
        f"  <title>{safe_title}</title>\n"
        "  <script>\n"
        "    window.MathJax = {\n"
        "      tex: { inlineMath: [['$', '$'], ['\\\\(', '\\\\)']], displayMath: [['$$', '$$'], ['\\\\[', '\\\\]']] },\n"
        "      svg: { fontCache: 'global' }\n"
        "    };\n"
        "  </script>\n"
        "  <script src=\"https://cdn.jsdelivr.net/npm/mathjax@3/es5/tex-svg.js\"></script>\n"
        "  <style>\n"
        "    body { font-family: \"Iowan Old Style\", Georgia, serif; margin: 0; color: #1d1c1a; }\n"
        "    header { padding: 16px 20px; border-bottom: 1px solid #e7dfd2; background: #f7f4ee; }\n"
        "    header h1 { margin: 0; font-size: 1.1rem; }\n"
        "    main { padding: 20px; }\n"
        "    .meta-block { background: #fdf7ea; border: 1px solid #e7dfd2; padding: 12px 14px; margin-bottom: 16px; }\n"
        "    .meta-block p { margin: 0 0 6px 0; }\n"
        "    .meta-block p:last-child { margin-bottom: 0; }\n"
        "    pre { white-space: pre-wrap; font-family: \"SFMono-Regular\", Consolas, monospace; font-size: 0.95rem; }\n"
        "    code { font-family: \"SFMono-Regular\", Consolas, monospace; }\n"
        "    table { border-collapse: collapse; width: 100%; }\n"
        "    th, td { border: 1px solid #e7dfd2; padding: 8px 10px; text-align: left; }\n"
        "    th { background: #f6f1e8; }\n"
        "  </style>\n"
        "</head>\n"
        "<body>\n"
        f"  <header><h1>{safe_title}</h1></header>\n"
        f"  <main>{body_html}</main>\n"
        "  <script>\n"
        "    document.querySelectorAll('a').forEach((link) => {\n"
        "      link.setAttribute('target', '_blank');\n"
        "      link.setAttribute('rel', 'noopener');\n"
        "    });\n"
        "  </script>\n"
        "</body>\n"
        "</html>\n"
    )


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
                "authors": ", ".join(entry.get("authors", [])) if entry.get("authors") else None,
                "published": entry.get("published"),
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
                "authors": ", ".join(work.get("authors", [])) if work.get("authors") else None,
                "published": work.get("published"),
                "journal": work.get("journal"),
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


def tavily_search(api_key: str, query: str, max_results: int) -> dict:
    import requests

    payload = {
        "api_key": api_key,
        "query": query,
        "max_results": max_results,
        "search_depth": "advanced",
        "include_raw_content": False,
    }
    resp = requests.post("https://api.tavily.com/search", json=payload, timeout=60)
    resp.raise_for_status()
    return resp.json()


def tavily_extract(api_key: str, url: str) -> dict:
    import requests

    payload = {"api_key": api_key, "urls": [url], "include_images": False, "extract_depth": "advanced"}
    resp = requests.post("https://api.tavily.com/extract", json=payload, timeout=60)
    resp.raise_for_status()
    return resp.json()


def select_top_urls(search_entries: list[dict], max_fetch: int) -> list[dict]:
    scored: list[tuple[float, dict]] = []
    for entry in search_entries:
        results = entry.get("result", {}).get("results") or entry.get("results") or []
        for item in results:
            url = item.get("url")
            if not url:
                continue
            score = item.get("score") or 0.0
            scored.append((float(score), item))
    scored.sort(key=lambda pair: pair[0], reverse=True)
    selected = []
    seen: set[str] = set()
    for _, item in scored:
        url = item.get("url")
        if not url or url in seen:
            continue
        seen.add(url)
        selected.append(item)
        if len(selected) >= max_fetch:
            break
    return selected


def run_web_research(
    supporting_dir: Path,
    queries: list[str],
    max_results: int,
    max_fetch: int,
    max_chars: int,
    max_pdf_pages: int,
) -> tuple[str, list[dict]]:
    api_key = os.getenv("TAVILY_API_KEY")
    if not api_key:
        return "Web research skipped: missing TAVILY_API_KEY.", []
    search_path = supporting_dir / "web_search.jsonl"
    fetch_path = supporting_dir / "web_fetch.jsonl"
    extract_dir = supporting_dir / "web_extract"
    pdf_dir = supporting_dir / "web_pdf"
    text_dir = supporting_dir / "web_text"
    extract_dir.mkdir(parents=True, exist_ok=True)
    pdf_dir.mkdir(parents=True, exist_ok=True)
    text_dir.mkdir(parents=True, exist_ok=True)
    search_entries: list[dict] = []

    def append_jsonl(path: Path, payload: dict) -> None:
        with path.open("a", encoding="utf-8") as handle:
            handle.write(json.dumps(payload, ensure_ascii=False) + "\n")

    for query in queries:
        try:
            result = tavily_search(api_key, query, max_results)
            entry = {"query": query, "result": result, "timestamp": time.time()}
            append_jsonl(search_path, entry)
            search_entries.append(entry)
        except Exception as exc:
            append_jsonl(search_path, {"query": query, "error": str(exc), "timestamp": time.time()})

    selected = select_top_urls(search_entries, max_fetch)
    for idx, item in enumerate(selected, start=1):
        url = item.get("url")
        if not url:
            continue
        slug = slugify_url(url)
        record = {
            "url": url,
            "title": item.get("title"),
            "score": item.get("score"),
            "timestamp": time.time(),
        }
        try:
            import requests

            is_pdf = url.lower().endswith(".pdf")
            if not is_pdf:
                try:
                    head = requests.head(url, timeout=20, headers=request_headers(), allow_redirects=True)
                    ctype = head.headers.get("content-type", "").lower()
                    if "pdf" in ctype:
                        is_pdf = True
                except Exception:
                    pass
            if is_pdf:
                pdf_path = pdf_dir / f"{idx:03d}_{slug}.pdf"
                text_path = text_dir / f"{idx:03d}_{slug}.txt"
                with requests.get(url, stream=True, timeout=60, headers=request_headers()) as resp:
                    resp.raise_for_status()
                    with pdf_path.open("wb") as handle:
                        for chunk in resp.iter_content(chunk_size=8192):
                            if chunk:
                                handle.write(chunk)
                pdf_text = read_pdf_with_fitz(pdf_path, max_pdf_pages, max_chars)
                text_path.write_text(pdf_text, encoding="utf-8")
                record.update({"pdf_path": pdf_path.as_posix(), "text_path": text_path.as_posix()})
            else:
                extract_path = extract_dir / f"{idx:03d}_{slug}.txt"
                try:
                    extract_res = tavily_extract(api_key, url)
                    content = ""
                    results = extract_res.get("results") or extract_res.get("data") or []
                    if results and isinstance(results, list):
                        content = results[0].get("content") or results[0].get("raw_content") or ""
                    if not content:
                        content = json.dumps(extract_res, ensure_ascii=False)
                except Exception:
                    import requests

                    resp = requests.get(url, timeout=60, headers=request_headers())
                    resp.raise_for_status()
                    content = html_to_text(resp.text)
                content, truncated = truncate_for_view(content, max_chars)
                if truncated:
                    content = f"[truncated]\n{content}"
                extract_path.write_text(content, encoding="utf-8")
                record.update({"extract_path": extract_path.as_posix()})
        except Exception as exc:
            record.update({"error": str(exc)})
        append_jsonl(fetch_path, record)

    summary_lines = [
        f"Web research queries: {len(queries)}",
        f"Web search results stored: {search_path.relative_to(supporting_dir).as_posix()}",
        f"Web extracts stored: {extract_dir.relative_to(supporting_dir).as_posix()}",
    ]
    return "\n".join(summary_lines), search_entries


class SafeFilesystemBackend:
    def __init__(self, root_dir: Path) -> None:
        from deepagents.backends import FilesystemBackend  # type: ignore

        class _Backend(FilesystemBackend):
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
                        if _WINDOWS_ABS_RE.match(normalized):
                            mapped = self._map_windows_path(normalized)
                            if mapped is not None:
                                return super()._resolve_path(mapped)
                return super()._resolve_path(key)

        self._backend = _Backend(root_dir=root_dir, virtual_mode=True)

    def __getattr__(self, name: str):
        return getattr(self._backend, name)


def wrap_html(title: str, body_html: str, template_name: Optional[str] = None, theme_css: Optional[str] = None) -> str:
    safe_title = html_lib.escape(title)
    template_class = ""
    if template_name:
        template_class = f" template-{slugify_label(template_name)}"
    return (
        "<!doctype html>\n"
        "<html lang=\"en\">\n"
        "<head>\n"
        "  <meta charset=\"utf-8\" />\n"
        f"  <title>{safe_title}</title>\n"
        "  <script>\n"
        "    window.MathJax = {\n"
        "      tex: { inlineMath: [['$', '$'], ['\\\\(', '\\\\)']], displayMath: [['$$', '$$'], ['\\\\[', '\\\\]']] },\n"
        "      svg: { fontCache: 'global' }\n"
        "    };\n"
        "  </script>\n"
        "  <script src=\"https://cdn.jsdelivr.net/npm/mathjax@3/es5/tex-svg.js\"></script>\n"
        "  <style>\n"
        "    :root {\n"
        "      --ink: #1d1c1a;\n"
        "      --muted: #5a5956;\n"
        "      --accent: #b24a2f;\n"
        "      --paper: #ffffff;\n"
        "      --paper-alt: #f6f1e8;\n"
        "      --rule: #e7dfd2;\n"
        "      --shadow: rgba(0, 0, 0, 0.08);\n"
        "      --link: #1d4e89;\n"
        "      --link-hover: #0d2b4a;\n"
        "      --page-bg: radial-gradient(1200px 600px at 20% -10%, #f2efe8 0%, #f7f4ee 45%, #fdfcf9 100%);\n"
        "      --body-font: \"Iowan Old Style\", \"Charter\", \"Palatino Linotype\", \"Book Antiqua\", Georgia, serif;\n"
        "      --heading-font: \"Avenir Next\", \"Gill Sans\", \"Trebuchet MS\", \"Helvetica Neue\", sans-serif;\n"
        "      --ui-font: \"Avenir Next\", \"Gill Sans\", \"Trebuchet MS\", \"Helvetica Neue\", sans-serif;\n"
        "      --mono-font: \"SFMono-Regular\", \"Consolas\", \"Liberation Mono\", \"Courier New\", monospace;\n"
        "    }\n"
        "    * { box-sizing: border-box; }\n"
        "    body {\n"
        "      margin: 0;\n"
        "      color: var(--ink);\n"
        "      background: var(--page-bg);\n"
        "      font-family: var(--body-font);\n"
        "      line-height: 1.6;\n"
        "    }\n"
        "    .page {\n"
        "      max-width: 980px;\n"
        "      margin: 48px auto 80px;\n"
        "      padding: 0 24px;\n"
        "    }\n"
        "    .masthead {\n"
        "      border-bottom: 1px solid var(--rule);\n"
        "      padding-bottom: 16px;\n"
        "      margin-bottom: 32px;\n"
        "    }\n"
        "    .kicker {\n"
        "      font-family: var(--ui-font);\n"
        "      font-size: 0.82rem;\n"
        "      letter-spacing: 0.22em;\n"
        "      text-transform: uppercase;\n"
        "      color: var(--accent);\n"
        "    }\n"
        "    .report-title {\n"
        "      font-family: var(--heading-font);\n"
        "      font-size: 2.4rem;\n"
        "      margin: 8px 0 6px;\n"
        "    }\n"
        "    .report-deck {\n"
        "      color: var(--muted);\n"
        "      font-size: 1.05rem;\n"
        "    }\n"
        "    .article {\n"
        "      background: var(--paper);\n"
        "      border: 1px solid var(--rule);\n"
        "      border-radius: 16px;\n"
        "      padding: 36px 40px;\n"
        "      box-shadow: 0 18px 45px var(--shadow);\n"
        "    }\n"
        "    .article h1, .article h2, .article h3, .article h4 {\n"
        "      font-family: var(--heading-font);\n"
        "      color: var(--ink);\n"
        "    }\n"
        "    .article h1 { font-size: 2rem; margin-top: 0; }\n"
        "    .article h2 {\n"
        "      font-size: 1.5rem;\n"
        "      margin-top: 2.4rem;\n"
        "      padding-top: 0.6rem;\n"
        "      border-top: 1px solid var(--rule);\n"
        "    }\n"
        "    .article h3 { font-size: 1.2rem; margin-top: 1.6rem; }\n"
        "    .article p { font-size: 1.05rem; }\n"
        "    .article ul, .article ol { padding-left: 1.4rem; }\n"
        "    .article blockquote {\n"
        "      border-left: 3px solid var(--accent);\n"
        "      margin: 1.6rem 0;\n"
        "      padding: 0.5rem 1.2rem;\n"
        "      background: var(--paper-alt);\n"
        "      color: var(--muted);\n"
        "      font-style: italic;\n"
        "    }\n"
        "    .article a {\n"
        "      color: var(--link);\n"
        "      text-decoration: none;\n"
        "      border-bottom: 1px solid rgba(29, 78, 137, 0.35);\n"
        "    }\n"
        "    .article a:hover { color: var(--link-hover); border-bottom-color: var(--link-hover); }\n"
        "    .article code {\n"
        "      background: #f7f6f3;\n"
        "      padding: 2px 4px;\n"
        "      border-radius: 6px;\n"
        "      font-family: var(--mono-font);\n"
        "      font-size: 0.95em;\n"
        "    }\n"
        "    .article pre {\n"
        "      background: #f7f6f3;\n"
        "      border: 1px solid var(--rule);\n"
        "      border-radius: 12px;\n"
        "      padding: 14px;\n"
        "      overflow-x: auto;\n"
        "      white-space: pre-wrap;\n"
        "      font-family: var(--mono-font);\n"
        "    }\n"
        "    .article table { border-collapse: collapse; width: 100%; margin: 1.2rem 0; }\n"
        "    .article th, .article td { border: 1px solid var(--rule); padding: 8px 10px; }\n"
        "    .article th { background: var(--paper-alt); text-align: left; }\n"
        "    .article hr { border: none; border-top: 1px solid var(--rule); margin: 2rem 0; }\n"
        "    .misc-block {\n"
        "      font-size: 0.85rem;\n"
        "      color: var(--muted);\n"
        "      margin-top: 0.6rem;\n"
        "    }\n"
        "    .misc-block ul { margin: 0.6rem 0 0.8rem 1.2rem; }\n"
        "    .misc-block li { margin: 0.2rem 0; }\n"
        "    .report-figure {\n"
        "      margin: 1.4rem 0;\n"
        "      padding: 0.8rem 1rem;\n"
        "      border: 1px solid var(--rule);\n"
        "      border-radius: 12px;\n"
        "      background: var(--paper-alt);\n"
        "    }\n"
        "    .report-figure img { max-width: 100%; height: auto; display: block; margin: 0 auto; }\n"
        "    .report-figure figcaption { font-size: 0.9rem; color: var(--muted); margin-top: 0.4rem; }\n"
        "    .figure-callout { font-size: 0.95rem; color: var(--muted); margin: 0.8rem 0 1rem; font-style: italic; }\n"
        "    .viewer-overlay {\n"
        "      position: fixed;\n"
        "      inset: 0;\n"
        "      background: rgba(19, 18, 16, 0.35);\n"
        "      opacity: 0;\n"
        "      pointer-events: none;\n"
        "      transition: opacity 0.2s ease;\n"
        "    }\n"
        "    .viewer-overlay.open { opacity: 1; pointer-events: auto; }\n"
        "    .viewer-panel {\n"
        "      position: fixed;\n"
        "      top: 20px;\n"
        "      right: 20px;\n"
        "      width: min(560px, 92vw);\n"
        "      height: calc(100% - 40px);\n"
        "      background: #ffffff;\n"
        "      border: 1px solid var(--rule);\n"
        "      border-radius: 16px;\n"
        "      box-shadow: 0 24px 60px rgba(0, 0, 0, 0.2);\n"
        "      transform: translateX(120%);\n"
        "      transition: transform 0.25s ease;\n"
        "      display: flex;\n"
        "      flex-direction: column;\n"
        "      z-index: 30;\n"
        "    }\n"
        "    .viewer-panel.open { transform: translateX(0); }\n"
        "    .viewer-header {\n"
        "      display: flex;\n"
        "      align-items: center;\n"
        "      justify-content: space-between;\n"
        "      padding: 12px 16px;\n"
        "      border-bottom: 1px solid var(--rule);\n"
        "      font-family: var(--ui-font);\n"
        "      gap: 12px;\n"
        "    }\n"
        "    .viewer-title { font-size: 0.95rem; color: var(--ink); flex: 1; }\n"
        "    .viewer-actions { display: flex; gap: 8px; align-items: center; }\n"
        "    .viewer-actions a {\n"
        "      font-size: 0.85rem;\n"
        "      color: var(--link);\n"
        "      text-decoration: none;\n"
        "    }\n"
        "    .viewer-close {\n"
        "      border: none;\n"
        "      background: #f4efe6;\n"
        "      color: var(--ink);\n"
        "      border-radius: 999px;\n"
        "      width: 28px;\n"
        "      height: 28px;\n"
        "      cursor: pointer;\n"
        "    }\n"
        "    .viewer-frame { flex: 1; border: none; width: 100%; border-radius: 0 0 16px 16px; }\n"
        "    @media (max-width: 720px) {\n"
        "      .page { margin: 32px auto 56px; }\n"
        "      .article { padding: 24px; }\n"
        "      .report-title { font-size: 1.9rem; }\n"
        "    }\n"
        f"{theme_css or ''}\n"
        "  </style>\n"
        "</head>\n"
        f"<body class=\"{template_class.strip()}\">\n"
        "  <div class=\"page\">\n"
        "    <header class=\"masthead\">\n"
        "      <div class=\"kicker\">Federlicht</div>\n"
        f"      <div class=\"report-title\">{safe_title}</div>\n"
        "      <div class=\"report-deck\">Research review and tech survey</div>\n"
        "    </header>\n"
        "    <main class=\"article\">\n"
        f"{body_html}\n"
        "    </main>\n"
        "  </div>\n"
        "  <div id=\"viewer-overlay\" class=\"viewer-overlay\"></div>\n"
        "  <aside id=\"viewer-panel\" class=\"viewer-panel\" aria-hidden=\"true\">\n"
        "    <div class=\"viewer-header\">\n"
        "      <div class=\"viewer-title\" id=\"viewer-title\">Source preview</div>\n"
        "      <div class=\"viewer-actions\">\n"
        "        <a id=\"viewer-raw\" href=\"#\" target=\"_blank\" rel=\"noopener\">Open raw</a>\n"
        "        <button class=\"viewer-close\" id=\"viewer-close\" aria-label=\"Close\">x</button>\n"
        "      </div>\n"
        "    </div>\n"
        "    <iframe id=\"viewer-frame\" class=\"viewer-frame\" title=\"Source preview\"></iframe>\n"
        "  </aside>\n"
        "  <script>\n"
        "    (function() {\n"
        "      const panel = document.getElementById('viewer-panel');\n"
        "      const overlay = document.getElementById('viewer-overlay');\n"
        "      const frame = document.getElementById('viewer-frame');\n"
        "      const rawLink = document.getElementById('viewer-raw');\n"
        "      const title = document.getElementById('viewer-title');\n"
        "      const closeBtn = document.getElementById('viewer-close');\n"
        "      function closeViewer() {\n"
        "        panel.classList.remove('open');\n"
        "        overlay.classList.remove('open');\n"
        "        panel.setAttribute('aria-hidden', 'true');\n"
        "        frame.src = 'about:blank';\n"
        "      }\n"
        "      function openViewer(viewer, raw, label) {\n"
        "        frame.src = viewer;\n"
        "        rawLink.href = raw || viewer;\n"
        "        title.textContent = label || 'Source preview';\n"
        "        panel.classList.add('open');\n"
        "        overlay.classList.add('open');\n"
        "        panel.setAttribute('aria-hidden', 'false');\n"
        "      }\n"
        "      document.querySelectorAll('a').forEach((link) => {\n"
        "        const href = link.getAttribute('href') || '';\n"
        "        if (href.startsWith('http://') || href.startsWith('https://')) {\n"
        "          link.setAttribute('target', '_blank');\n"
        "          link.setAttribute('rel', 'noopener');\n"
        "        }\n"
        "        const viewer = link.getAttribute('data-viewer');\n"
        "        if (viewer) {\n"
        "          link.addEventListener('click', (event) => {\n"
        "            if (event.metaKey || event.ctrlKey) { return; }\n"
        "            event.preventDefault();\n"
        "            openViewer(viewer, link.getAttribute('data-raw'), link.textContent.trim());\n"
        "          });\n"
        "        }\n"
        "      });\n"
        "      overlay.addEventListener('click', closeViewer);\n"
        "      closeBtn.addEventListener('click', closeViewer);\n"
        "      document.addEventListener('keydown', (event) => {\n"
        "        if (event.key === 'Escape') { closeViewer(); }\n"
        "      });\n"
        "    })();\n"
        "  </script>\n"
        "</body>\n"
        "</html>\n"
    )


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
                "journal": (work.get("host_venue") or {}).get("display_name"),
                "published": work.get("publication_date") or work.get("publication_year"),
                "openalex_id_short": work.get("openalex_id_short"),
            }
            add_ref(url, title, "openalex", openalex, meta=meta)
            if limit_reached():
                return refs

    arxiv = archive_dir / "arxiv" / "papers.jsonl"
    if arxiv.exists():
        for entry in iter_jsonl(arxiv):
            url = entry.get("entry_id") or entry.get("pdf_url")
            title = entry.get("title")
            add_ref(url, title, "arxiv", arxiv)
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
    for rel_path, pos in ordered:
        pdf_path = resolve_related_pdf_path(rel_path, run_dir, meta_index)
        if not pdf_path:
            continue
        if pdf_path in pdf_targets:
            continue
        pdf_targets[pdf_path] = {"source_path": rel_path, "section": find_section_title(pos), "position": pos}

    if not pdf_targets:
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


def truncate_text(text: str, limit: int = 140) -> str:
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
            pdf_name = Path(entry.get("pdf_path") or "").name
            caption = f"Source PDF: {pdf_name}" if pdf_name else "Source PDF figure"
        caption = truncate_text(caption, 120)
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
        pdf_abs = (run_dir / entry["pdf_path"].lstrip("./")).resolve()
        img_href = os.path.relpath(img_abs, viewer_dir).replace("\\", "/")
        pdf_href = os.path.relpath(pdf_abs, viewer_dir).replace("\\", "/")
        caption = html_lib.escape(entry.get("caption") or "")
        vision_summary_raw = entry.get("vision_summary") or ""
        vision_summary = html_lib.escape(truncate_text(str(vision_summary_raw), 200)) if vision_summary_raw else ""
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
                    f"<p><strong>{candidate_id}</strong> — {html_lib.escape(entry['pdf_path'])} (p.{entry.get('page')})</p>",
                    f"<img src=\"{html_lib.escape(img_href)}\" alt=\"{candidate_id}\" />",
                    f"<p>{caption}</p>" if caption else "",
                    f"<p><em>Vision:</em> {vision_line}</p>" if vision_line else "",
                    f"<p>Source: <a href=\"{html_lib.escape(pdf_href)}\">{html_lib.escape(entry['pdf_path'])}</a></p>",
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
    for line in raw:
        cleaned = line.split("|", 1)[0].strip()
        if not cleaned or cleaned.startswith("#"):
            continue
        tokens.add(cleaned)
    if not tokens:
        return []
    selected: list[dict] = []
    for entry in entries:
        candidate_id = entry.get("candidate_id")
        img_path = entry.get("image_path")
        if candidate_id in tokens:
            selected.append(entry)
            continue
        if img_path in tokens or (isinstance(img_path, str) and img_path.lstrip("./") in tokens):
            selected.append(entry)
    return selected


def render_figure_block(
    entries: list[dict],
    output_format: str,
    report_dir: Path,
    run_dir: Path,
) -> str:
    blocks: list[str] = []
    for entry in entries:
        pdf_abs = (run_dir / entry["pdf_path"].lstrip("./")).resolve()
        img_abs = (run_dir / entry["image_path"].lstrip("./")).resolve()
        pdf_href = os.path.relpath(pdf_abs, report_dir).replace("\\", "/")
        img_href = os.path.relpath(img_abs, report_dir).replace("\\", "/")
        page = entry.get("page")
        caption = entry.get("caption")
        number = entry.get("figure_number")
        figure_label = f"{number}" if number else ""
        if output_format == "tex":
            if caption:
                caption_text = (
                    f"{latex_escape(caption)}. Source: \\\\texttt{{{latex_escape(entry['pdf_path'])}}}, page {page}."
                )
            else:
                caption_text = f"Source: \\\\texttt{{{latex_escape(entry['pdf_path'])}}}, page {page}."
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
            safe_label = html_lib.escape(entry["pdf_path"])
            safe_alt = html_lib.escape(f"Figure from {entry['pdf_path']} (page {page})")
            safe_caption = html_lib.escape(caption) if caption else ""
            fig_id = f' id="fig-{figure_label}"' if figure_label else ""
            figure_prefix = f"Figure {figure_label}" if figure_label else "Figure"
            if safe_caption:
                fig_caption = f"{figure_prefix}: {safe_caption} (Source: <a href=\"{safe_pdf}\">{safe_label}</a>, page {page})"
            else:
                fig_caption = f"{figure_prefix}: <a href=\"{safe_pdf}\">{safe_label}</a> (page {page})"
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

    def format_inline_citation(idx: int, target: str) -> str:
        if output_format == "tex":
            return latex_link(target, f"[{idx}]")
        return f"[\\[{idx}\\]]({target})"

    def replace_md_link(match: re.Match[str]) -> str:
        label = match.group(1)
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
    return updated, refs


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


def format_reference_item(ref: dict, output_format: str = "md") -> str:
    url = ref.get("url")
    title = display_title(ref.get("title"), url)
    cite_note = ""
    if ref.get("cited_by_count") is not None:
        if output_format == "tex":
            cite_note = f" \\textit{{citations: {ref['cited_by_count']}}}"
        else:
            cite_note = f" <small>citations: {ref['cited_by_count']}</small>"
    extra_bits = []
    if ref.get("journal"):
        extra_bits.append(ref["journal"])
    if ref.get("published"):
        extra_bits.append(str(ref["published"]))
    if ref.get("extra"):
        extra_bits.append(ref["extra"])
    extra_text = "; ".join(extra_bits)
    if output_format == "tex":
        safe_title = latex_escape(str(title))
        extra = f" ({latex_escape(extra_text)})" if extra_text else ""
        if url and isinstance(url, str):
            return f"{safe_title}{extra} --- {latex_link(url, 'link')}{cite_note}"
        return f"{safe_title}{extra}{cite_note}"
    extra = f" ({extra_text})" if extra_text else ""
    if url and isinstance(url, str):
        return f"{title}{extra} — [link]({url}){cite_note}"
    return f"{title}{extra}{cite_note}"


def render_reference_section(
    citations: list[dict],
    refs_meta: list[dict],
    openalex_meta: dict[str, dict],
    output_format: str = "md",
) -> str:
    if not citations:
        return ""
    by_archive = {ref.get("archive", "").lstrip("./"): ref for ref in refs_meta}
    by_url = {ref.get("url"): ref for ref in refs_meta if ref.get("url")}
    if output_format == "tex":
        lines = ["", "\\section*{References}", "\\renewcommand{\\labelenumi}{[\\arabic{enumi}]}", "\\begin{enumerate}"]
    else:
        lines = ["", "## References", ""]
    for entry in citations:
        idx = entry["index"]
        kind = entry["kind"]
        target = entry["target"]
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
                        lines.append(f"{idx}. {index_label} ({target}) — selected sources:")
                        for item in items[:6]:
                            lines.append(f"   - {format_reference_item(item, output_format)}")
                    continue
            meta = by_archive.get(norm)
            path_name = Path(norm).name
            short_id = Path(norm).stem if path_name.startswith("W") else None
            oa_meta = openalex_meta.get(short_id) if short_id else None
            url = meta.get("url") if meta else None
            title = display_title(
                (meta.get("title") if meta else None) or (oa_meta.get("title") if oa_meta else None),
                url,
            )
            if title == "Untitled source":
                title = path_name
            cite_note = ""
            if meta and meta.get("cited_by_count") is not None:
                cite_note = (
                    f" \\textit{{citations: {meta['cited_by_count']}}}"
                    if output_format == "tex"
                    else f" <small>citations: {meta['cited_by_count']}</small>"
                )
            elif oa_meta and oa_meta.get("cited_by_count") is not None:
                cite_note = (
                    f" \\textit{{citations: {oa_meta['cited_by_count']}}}"
                    if output_format == "tex"
                    else f" <small>citations: {oa_meta['cited_by_count']}</small>"
                )
            if url and isinstance(url, str) and url.startswith(("http://", "https://")):
                if output_format == "tex":
                    safe_title = latex_escape(str(title))
                    source_link = latex_link(url, "source")
                    file_link = latex_link(target, f"\\texttt{{{latex_escape(target)}}}")
                    lines.append(f"\\item {safe_title} ({source_link}) --- {file_link}{cite_note}")
                else:
                    lines.append(f"{idx}. {title} ([source]({url})) — [file]({target}){cite_note}")
            else:
                if output_format == "tex":
                    safe_title = latex_escape(str(title))
                    file_link = latex_link(target, f"\\texttt{{{latex_escape(target)}}}")
                    lines.append(f"\\item {safe_title} --- {file_link}{cite_note}")
                else:
                    lines.append(f"{idx}. {title} — [file]({target}){cite_note}")
        else:
            meta = by_url.get(target)
            title = display_title(meta.get("title") if meta else None, target)
            cite_note = ""
            if meta and meta.get("cited_by_count") is not None:
                cite_note = (
                    f" \\textit{{citations: {meta['cited_by_count']}}}"
                    if output_format == "tex"
                    else f" <small>citations: {meta['cited_by_count']}</small>"
                )
            if output_format == "tex":
                safe_title = latex_escape(str(title))
                lines.append(f"\\item {safe_title} --- {latex_link(target, 'link')}{cite_note}")
            else:
                lines.append(f"{idx}. {title} — [link]({target}){cite_note}")
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


def resolve_author_name(author_cli: Optional[str], report_prompt: Optional[str]) -> str:
    if author_cli:
        cleaned = author_cli.strip()
        if cleaned:
            return cleaned
    if report_prompt:
        for line in report_prompt.splitlines():
            match = _AUTHOR_LINE_RE.match(line)
            if match:
                name = match.group(1).strip()
                if name:
                    return name
    return DEFAULT_AUTHOR


def build_byline(author: str) -> str:
    stamp = dt.datetime.now().strftime("%Y-%m-%d %H:%M")
    return f'Federlicht assisted and prompted by "{author}" — {stamp}'


def print_progress(label: str, content: str, enabled: bool, max_chars: int) -> None:
    if not enabled:
        return
    snippet = content.strip()
    if max_chars > 0 and len(snippet) > max_chars:
        snippet = f"{snippet[:max_chars]}\n... [truncated]"
    print(f"\n[{label}]\n{snippet}\n")


_OPENAI_COMPAT_RE = re.compile(r"^qwen", re.IGNORECASE)
_OPENAI_MODEL_RE = re.compile(r"^(gpt-|o\\d)", re.IGNORECASE)


def is_openai_compat_model_name(model_name: str) -> bool:
    return bool(_OPENAI_COMPAT_RE.match(model_name.strip()))


def is_openai_model_name(model_name: str) -> bool:
    return bool(_OPENAI_MODEL_RE.match(model_name.strip()))


def build_openai_compat_model(model_name: str, streaming: bool = False):
    try:
        from langchain_openai import ChatOpenAI  # type: ignore
    except Exception:
        return None
    base_url = os.getenv("OPENAI_BASE_URL") or os.getenv("OPENAI_API_BASE")
    kwargs = {"model": model_name}
    if streaming:
        kwargs["streaming"] = True
    if base_url:
        try:
            return ChatOpenAI(**kwargs, base_url=base_url)
        except TypeError:
            try:
                return ChatOpenAI(**kwargs, openai_api_base=base_url)
            except TypeError:
                kwargs.pop("streaming", None)
                return ChatOpenAI(**kwargs, openai_api_base=base_url)
    try:
        return ChatOpenAI(**kwargs)
    except TypeError:
        kwargs.pop("streaming", None)
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


def create_agent_with_fallback(create_deep_agent, model_name: str, tools, system_prompt: str, backend):
    kwargs = {"tools": tools, "system_prompt": system_prompt, "backend": backend}
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
            compat_model = build_openai_compat_model(model_name, streaming=STREAMING_ENABLED)
            if compat_model is None:
                print(
                    "OpenAI-compatible model requested but langchain-openai is unavailable. "
                    "Install with: python -m pip install langchain-openai "
                    "and set OPENAI_BASE_URL/OPENAI_API_KEY if needed.",
                    file=sys.stderr,
                )
            else:
                model_value = compat_model
        elif STREAMING_ENABLED and is_openai_model_name(model_name):
            compat_model = build_openai_compat_model(model_name, streaming=True)
            if compat_model is not None:
                model_value = compat_model
        try:
            return create_deep_agent(model=model_value, **kwargs)
        except Exception as exc:  # pragma: no cover - fallback path
            msg = str(exc).lower()
            if model_name == DEFAULT_MODEL and any(token in msg for token in ("model", "unsupported", "unknown")):
                print(
                    f"Model '{DEFAULT_MODEL}' not supported by this deepagents setup. Falling back to default.",
                    file=sys.stderr,
                )
            else:
                raise
    return create_deep_agent(**kwargs)


def main() -> int:
    args = parse_args()
    agent_overrides: dict = {}
    if args.agent_config:
        try:
            config_overrides, raw_overrides = load_agent_config(args.agent_config)
        except (OSError, ValueError, json.JSONDecodeError) as exc:
            print(f"ERROR: failed to load agent config: {exc}", file=sys.stderr)
            return 2
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
    check_model = args.check_model.strip() if args.check_model else ""
    if not check_model:
        check_model = args.model
    global STREAMING_ENABLED
    STREAMING_ENABLED = bool(args.stream)
    output_format = choose_format(args.output)
    start_stamp = dt.datetime.now()
    start_timer = time.monotonic()
    if args.preview_template:
        value = args.preview_template.strip()
        if value.lower() == "all":
            out_dir = Path(args.preview_output) if args.preview_output else templates_dir()
            out_dir.mkdir(parents=True, exist_ok=True)
            for name in list_builtin_templates():
                spec = load_template_spec(name, None)
                output_path = out_dir / f"preview_{spec.name}.html"
                write_template_preview(spec, output_path)
                print(f"Wrote preview: {output_path}")
            return 0
        spec = load_template_spec(value, None)
        output_path = resolve_preview_output(spec, value, args.preview_output)
        write_template_preview(spec, output_path)
        print(f"Wrote preview: {output_path}")
        return 0
    if args.agent_info:
        language = normalize_lang(args.lang)
        report_prompt = load_report_prompt(args.prompt, args.prompt_file)
        if args.template and str(args.template).strip().lower() != "auto":
            style_choice = args.template
        else:
            style_choice = template_from_prompt(report_prompt) or DEFAULT_TEMPLATE_NAME
        template_spec = load_template_spec(style_choice, report_prompt)
        if not template_spec.sections:
            template_spec.sections = list(DEFAULT_SECTIONS)
        required_sections = (
            list(FREE_FORMAT_REQUIRED_SECTIONS) if args.free_format else list(template_spec.sections)
        )
        template_guidance_text = build_template_guidance_text(template_spec)
        payload = build_agent_info(
            args,
            output_format,
            language,
            report_prompt,
            template_spec,
            template_guidance_text,
            required_sections,
            args.free_format,
            agent_overrides,
        )
        write_agent_info(payload, args.agent_info)
        return 0
    if not args.run:
        print("ERROR: --run is required unless --preview-template is used.", file=sys.stderr)
        return 2
    try:
        from deepagents import create_deep_agent  # type: ignore
    except Exception:
        print("deepagents is required. Install with: python -m pip install deepagents", file=sys.stderr)
        return 1

    archive_dir, run_dir, query_id = resolve_archive(Path(args.run))
    archive_dir = archive_dir.resolve()
    run_dir = run_dir.resolve()
    index_file = find_index_file(archive_dir, query_id)
    instruction_file = find_instruction_file(run_dir)
    overview_path = write_run_overview(run_dir, instruction_file, index_file)
    baseline_report = find_baseline_report(run_dir)
    backend = SafeFilesystemBackend(root_dir=run_dir)
    notes_dir = resolve_notes_dir(run_dir, args.notes_dir)
    supporting_dir: Optional[Path] = None
    supporting_summary: Optional[str] = None
    alignment_max_chars = min(args.quality_max_chars, 8000)

    def resolve_run_path(rel_path: str) -> Path:
        candidate = Path(rel_path)
        if not candidate.is_absolute():
            candidate = run_dir / candidate
        resolved = candidate.resolve()
        if run_dir != resolved and run_dir not in resolved.parents:
            raise ValueError(f"Path is outside run folder: {rel_path}")
        if not resolved.exists():
            raise FileNotFoundError(f"Path does not exist: {rel_path}")
        return resolved

    def list_archive_files(pattern: Optional[str] = None, max_files: Optional[int] = None) -> str:
        """List archive files with sizes. Use to discover what to read."""
        files = []
        warning: Optional[str] = None
        if pattern:
            try:
                paths = archive_dir.rglob(pattern)
            except ValueError as exc:
                warning = f"Invalid pattern '{pattern}': {exc}. Falling back to '*'"
                paths = archive_dir.rglob("*")
        else:
            paths = archive_dir.rglob("*")
        for path in sorted(paths):
            if path.is_file():
                rel = path.relative_to(run_dir).as_posix()
                files.append({"path": rel, "bytes": path.stat().st_size})
        limit = args.max_files if max_files is None else max_files
        payload = {"total_files": len(files), "files": files[:limit]}
        if warning:
            payload["warning"] = warning
        return json.dumps(payload, indent=2, ensure_ascii=True)

    def list_supporting_files(pattern: Optional[str] = None, max_files: Optional[int] = None) -> str:
        """List supporting files with sizes (web research outputs)."""
        if not supporting_dir or not supporting_dir.exists():
            return json.dumps({"error": "Supporting folder not available."}, indent=2, ensure_ascii=True)
        files = []
        warning: Optional[str] = None
        if pattern:
            try:
                paths = supporting_dir.rglob(pattern)
            except ValueError as exc:
                warning = f"Invalid pattern '{pattern}': {exc}. Falling back to '*'"
                paths = supporting_dir.rglob("*")
        else:
            paths = supporting_dir.rglob("*")
        for path in sorted(paths):
            if path.is_file():
                rel = path.relative_to(run_dir).as_posix()
                files.append({"path": rel, "bytes": path.stat().st_size})
        limit = args.max_files if max_files is None else max_files
        payload = {"total_files": len(files), "files": files[:limit]}
        if warning:
            payload["warning"] = warning
        return json.dumps(payload, indent=2, ensure_ascii=True)

    def read_text_file(path: Path, start: int, max_chars: int) -> str:
        text = path.read_text(encoding="utf-8", errors="replace")
        start = max(0, start)
        return text[start : start + max_chars]

    def normalize_rel_paths(text: str) -> str:
        replacements = {
            "../instruction/": "./instruction/",
            "..\\instruction\\": "./instruction/",
            "../archive/": "./archive/",
            "..\\archive\\": "./archive/",
            "../report_notes/": "./report_notes/",
            "..\\report_notes\\": "./report_notes/",
            "../supporting/": "./supporting/",
            "..\\supporting\\": "./supporting/",
            "archive/../instruction/": "./instruction/",
            "archive\\..\\instruction\\": "./instruction/",
        }
        for old, new in replacements.items():
            text = text.replace(old, new)
        return text

    def resolve_pdf_text(pdf_path: Path) -> Optional[Path]:
        if pdf_path.parent.name == "pdf":
            text_dir = pdf_path.parent.parent / "text"
            candidate = text_dir / f"{pdf_path.stem}.txt"
            if candidate.exists():
                return candidate
        candidate = pdf_path.with_suffix(".txt")
        return candidate if candidate.exists() else None

    def read_document(rel_path: str, start: int = 0, max_chars: Optional[int] = None, max_pages: Optional[int] = None) -> str:
        """Read a text or PDF file from the run folder with optional paging."""
        try:
            path = resolve_run_path(rel_path)
        except (FileNotFoundError, ValueError) as exc:
            return f"[error] {exc}"
        limit = args.max_chars if max_chars is None else max_chars
        if path.suffix.lower() == ".pdf":
            page_limit = args.max_pdf_pages if max_pages is None else max_pages
            txt_path = resolve_pdf_text(path)
            if txt_path:
                text = normalize_rel_paths(read_text_file(txt_path, start, limit))
                return f"[from text] {txt_path.relative_to(run_dir).as_posix()}\n\n{text}"
            pdf_text = read_pdf_with_fitz(path, page_limit, limit)
            return f"[from pdf] {path.relative_to(run_dir).as_posix()}\n\n{pdf_text}"
        text = normalize_rel_paths(read_text_file(path, start, limit))
        return f"[from text] {path.relative_to(run_dir).as_posix()}\n\n{text}"

    tools = [list_archive_files, list_supporting_files, read_document]
    alignment_enabled = resolve_agent_enabled("alignment", bool(args.alignment_check), agent_overrides)
    web_search_enabled = resolve_agent_enabled("web_query", bool(args.web_search), agent_overrides)
    template_adjust_enabled = resolve_agent_enabled("template_adjuster", bool(args.template_adjust), agent_overrides)
    clarifier_enabled = resolve_agent_enabled("clarifier", True, agent_overrides)
    if args.free_format:
        template_adjust_enabled = False
    args.alignment_check = alignment_enabled
    args.web_search = web_search_enabled
    args.template_adjust = template_adjust_enabled
    vision_override = resolve_agent_model("image_analyst", args.model_vision or "", agent_overrides)
    if vision_override:
        args.model_vision = vision_override
    alignment_prompt = resolve_agent_prompt("alignment", build_alignment_prompt(normalize_lang(args.lang)), agent_overrides)
    alignment_model = resolve_agent_model("alignment", check_model, agent_overrides)

    def _coerce_stream_text(value: object) -> str:
        if isinstance(value, str):
            return value
        if isinstance(value, list):
            parts = []
            for item in value:
                if isinstance(item, str):
                    parts.append(item)
                elif isinstance(item, dict):
                    text = item.get("text") or item.get("content") or item.get("value")
                    if text:
                        parts.append(str(text))
            return "".join(parts)
        return ""

    def _unpack_stream_chunk(chunk: object) -> tuple[Optional[str], object]:
        if isinstance(chunk, tuple):
            if len(chunk) == 2:
                return chunk[0], chunk[1]
            if len(chunk) >= 3:
                return chunk[1], chunk[2]
        return None, None

    def run_agent(label: str, agent, payload: dict, show_progress: bool = True) -> str:
        if not args.stream:
            result = agent.invoke(payload)
            text = extract_agent_text(result)
            if show_progress:
                print_progress(label, text, args.progress, args.progress_chars)
            return text
        print(f"\n[{label}]\n", end="", flush=True)
        final_state = None
        streamed_parts: list[str] = []
        printed_any = False
        message_events = 0
        value_events = 0
        debug_samples = 0
        try:
            for chunk in agent.stream(payload, stream_mode=["messages", "values"], subgraphs=True):
                mode, data = _unpack_stream_chunk(chunk)
                if mode == "messages":
                    message_events += 1
                    if isinstance(data, tuple) and data:
                        message = data[0]
                    else:
                        message = data
                    msg_type = getattr(message, "type", None) or getattr(message, "role", None)
                    msg_type_label = str(msg_type).lower() if msg_type is not None else ""
                    if args.stream_debug and debug_samples < 3:
                        debug_samples += 1
                        print(
                            f"[stream-debug] {label}: mode=messages type={msg_type_label}",
                            file=sys.stderr,
                        )
                    if msg_type_label and msg_type_label not in ("ai", "assistant") and not msg_type_label.startswith("ai"):
                        continue
                    content = getattr(message, "content", None)
                    text = _coerce_stream_text(content)
                    if text:
                        streamed_parts.append(text)
                        printed_any = True
                        sys.stdout.write(text)
                        sys.stdout.flush()
                elif mode == "values":
                    value_events += 1
                    final_state = data
        except Exception as exc:
            print(f"\n[warn] streaming failed for {label}: {exc}", file=sys.stderr)
            result = agent.invoke(payload)
            text = extract_agent_text(result)
            if show_progress:
                print_progress(label, text, args.progress, args.progress_chars)
            return text
        if args.stream_debug:
            print(
                f"[stream-debug] {label}: messages={message_events} values={value_events} printed={printed_any}",
                file=sys.stderr,
            )
        if not printed_any and final_state is not None:
            fallback_text = extract_agent_text(final_state).strip()
            if fallback_text:
                sys.stdout.write(fallback_text)
                sys.stdout.flush()
        print("\n")
        if final_state is not None:
            return extract_agent_text(final_state)
        return "".join(streamed_parts).strip()

    def trim_to_sections(text: str) -> str:
        if not text:
            return ""
        pattern = r"^\\section\\*?\\{" if output_format == "tex" else r"^##\\s+"
        match = re.search(pattern, text, re.MULTILINE)
        return text[match.start() :].strip() if match else text.strip()

    def extract_section_headings(text: str) -> list[str]:
        if output_format == "tex":
            return [
                match.group(1).strip()
                for match in re.finditer(r"^\\section\\*?\\{([^}]+)\\}", text, re.MULTILINE)
            ]
        return [match.group(1).strip() for match in re.finditer(r"^##\\s+(.+)$", text, re.MULTILINE)]

    def coerce_required_headings(text: str, sections: list[str]) -> str:
        if output_format == "tex":
            return text
        if not text or not sections:
            return text
        lines = text.splitlines()
        lowered = [section.lower() for section in sections]
        for idx, line in enumerate(lines):
            if not line.startswith("### "):
                continue
            heading = line[4:].strip()
            if any(heading.lower().startswith(section) for section in lowered):
                lines[idx] = f"## {heading}"
        return "\n".join(lines)

    def report_needs_retry(text: str) -> tuple[bool, str]:
        if not text.strip():
            return True, "empty"
        if REPORT_PLACEHOLDER_RE.search(text):
            return True, "placeholder"
        headings = extract_section_headings(text)
        min_headings = max(len(required_sections), 3)
        if len(headings) < min_headings:
            return True, f"headings_{len(headings)}"
        missing = find_missing_sections(text, required_sections, output_format)
        if missing:
            return True, f"missing_{len(missing)}"
        return False, ""

    def build_writer_retry_guardrail(reason: str) -> str:
        required_list = "\n".join(f"- {section}" for section in required_sections)
        return "\n".join(
            [
                "CRITICAL: The previous output did not contain a complete report.",
                f"Reason: {reason}",
                "Return the full report body now. Do not include status updates, promises, or meta commentary.",
                "Use H2 headings (##) for top-level sections and H3 for subpoints.",
                "Include the required sections listed below using exact H2 headings and place them at the end:",
                required_list or "(none)",
            ]
        )

    def coerce_repair_headings(text: str, sections: list[str]) -> str:
        if output_format == "tex":
            return text
        if not text:
            return text
        lines = text.splitlines()
        lowered = [section.lower() for section in sections]
        for idx, line in enumerate(lines):
            if not line.startswith("### "):
                continue
            heading = line[4:].strip()
            if any(heading.lower().startswith(section) for section in lowered):
                lines[idx] = f"## {heading}"
        return "\n".join(lines)

    def append_missing_sections(report_text: str, supplement: str) -> str:
        cleaned = trim_to_sections(supplement)
        if not cleaned:
            return report_text
        if report_text.strip():
            return f"{report_text.rstrip()}\n\n{cleaned}\n"
        return f"{cleaned}\n"

    def run_structural_repair(report_text: str, missing_sections: list[str], label: str) -> str:
        if not missing_sections or args.repair_mode == "off":
            return report_text
        repair_mode = args.repair_mode
        repair_skeleton = build_report_skeleton(
            missing_sections if repair_mode == "append" else required_sections,
            output_format,
        )
        repair_prompt = resolve_agent_prompt(
            "structural_editor",
            build_repair_prompt(
                format_instructions,
                output_format,
                language,
                mode=repair_mode,
                free_form=args.free_format,
            ),
            agent_overrides,
        )
        repair_model = resolve_agent_model("structural_editor", args.model, agent_overrides)
        repair_agent = create_agent_with_fallback(create_deep_agent, repair_model, tools, repair_prompt, backend)
        repair_input = "\n".join(
            [
                "Required skeleton:",
                repair_skeleton,
                "",
                "Missing sections:",
                ", ".join(missing_sections),
                "",
                "Evidence notes:",
                truncate_text(evidence_notes, args.quality_max_chars),
                "",
                "Report focus prompt:",
                report_prompt or "(none)",
                "",
                "Current report:",
                truncate_text(report_text, args.quality_max_chars),
            ]
        )
        repair_text = run_agent(
            label,
            repair_agent,
            {"messages": [{"role": "user", "content": repair_input}]},
            show_progress=False,
        )
        repair_text = normalize_report_paths(repair_text, run_dir)
        repair_text = coerce_repair_headings(repair_text, missing_sections)
        repair_headings = extract_section_headings(repair_text)
        matching = [
            heading
            for heading in repair_headings
            if any(heading.lower().startswith(section.lower()) for section in missing_sections)
        ]
        if args.repair_debug:
            print(
                f"[repair-debug] {label}: mode={repair_mode} missing={len(missing_sections)} "
                f"report_len={len(report_text)} repair_len={len(repair_text)} "
                f"headings={repair_headings}",
                file=sys.stderr,
            )
        if repair_mode == "append":
            if not matching:
                if args.repair_debug:
                    print(
                        f"[repair-debug] {label}: no matching headings in repair output; skipping append",
                        file=sys.stderr,
                    )
                return report_text
            return append_missing_sections(report_text, repair_text)
        candidate = repair_text.strip()
        if not candidate:
            return report_text
        min_len = max(400, int(len(report_text) * 0.5))
        candidate_missing = find_missing_sections(candidate, required_sections, output_format)
        if not extract_section_headings(candidate):
            return report_text
        if len(candidate) < min_len or (candidate_missing and len(candidate_missing) >= len(missing_sections)):
            return append_missing_sections(report_text, candidate)
        return candidate

    def run_alignment_check(stage: str, content: str) -> Optional[str]:
        if not alignment_enabled:
            return None
        align_agent = create_agent_with_fallback(create_deep_agent, alignment_model, tools, alignment_prompt, backend)
        align_input = [
            f"Stage: {stage}",
            "",
            "Run context:",
            "\n".join(context_lines),
            "",
            "Report focus prompt:",
            report_prompt or "(none)",
            "",
            "Clarification questions:",
            clarification_questions or "(none)",
            "",
            "Clarification answers:",
            clarification_answers or "(none)",
            "",
            "Stage output:",
            truncate_text(content, alignment_max_chars),
            "",
            f"Write in {language}.",
        ]
        align_notes = run_agent(
            f"Alignment Check ({stage})",
            align_agent,
            {"messages": [{"role": "user", "content": "\n".join(align_input)}]},
            show_progress=True,
        )
        note_name = f"alignment_{slugify_label(stage)}.md"
        (notes_dir / note_name).write_text(align_notes, encoding="utf-8")
        return align_notes

    context_lines = [
        "Run folder: .",
        "Archive folder: ./archive",
        f"Query ID: {query_id}",
    ]
    if instruction_file:
        rel_instruction = instruction_file.relative_to(run_dir).as_posix()
        context_lines.append(f"Instruction file: ./{rel_instruction}")
    if baseline_report:
        rel_baseline = baseline_report.relative_to(run_dir).as_posix()
        context_lines.append(f"Baseline report: ./{rel_baseline}")
    if index_file:
        rel_index = index_file.relative_to(run_dir).as_posix()
        context_lines.append(f"Index file: ./{rel_index}")

    language = normalize_lang(args.lang)
    report_prompt = load_report_prompt(args.prompt, args.prompt_file)
    template_spec = load_template_spec(args.template, report_prompt)

    source_index = feder_tools.build_source_index(archive_dir, run_dir, supporting_dir)
    source_index_path = notes_dir / "source_index.jsonl"
    feder_tools.write_jsonl(source_index_path, source_index)
    source_triage = feder_tools.rank_sources(source_index, report_prompt or query_id, top_k=12)
    source_triage_text = feder_tools.format_source_triage(source_triage)
    source_triage_path = notes_dir / "source_triage.md"
    source_triage_path.write_text(source_triage_text, encoding="utf-8")
    try:
        rel_index = source_index_path.relative_to(run_dir).as_posix()
        context_lines.append(f"Source index: ./{rel_index}")
    except Exception:
        context_lines.append(f"Source index: {source_index_path.as_posix()}")
    try:
        rel_triage = source_triage_path.relative_to(run_dir).as_posix()
        context_lines.append(f"Source triage: ./{rel_triage}")
    except Exception:
        context_lines.append(f"Source triage: {source_triage_path.as_posix()}")
    scout_prompt = resolve_agent_prompt("scout", build_scout_prompt(language), agent_overrides)
    scout_model = resolve_agent_model("scout", args.model, agent_overrides)
    scout_agent = create_agent_with_fallback(create_deep_agent, scout_model, tools, scout_prompt, backend)
    scout_input = list(context_lines)
    if report_prompt:
        scout_input.extend(["", "Report focus prompt:", report_prompt])
    if source_triage_text:
        scout_input.extend(["", "Source triage (lightweight):", source_triage_text])
    scout_notes = run_agent(
        "Scout Notes",
        scout_agent,
        {"messages": [{"role": "user", "content": "\n".join(scout_input)}]},
        show_progress=True,
    )

    clarification_questions: Optional[str] = None
    clarification_answers = load_user_answers(args.answers, args.answers_file)
    if clarifier_enabled and (args.interactive or clarification_answers):
        clarifier_prompt = resolve_agent_prompt("clarifier", build_clarifier_prompt(language), agent_overrides)
        clarifier_model = resolve_agent_model("clarifier", args.model, agent_overrides)
        clarifier_agent = create_agent_with_fallback(create_deep_agent, clarifier_model, tools, clarifier_prompt, backend)
        clarifier_input = list(context_lines)
        clarifier_input.extend(["", "Scout notes:", scout_notes])
        if report_prompt:
            clarifier_input.extend(["", "Report focus prompt:", report_prompt])
        clarification_questions = run_agent(
            "Clarification Questions",
            clarifier_agent,
            {"messages": [{"role": "user", "content": "\n".join(clarifier_input)}]},
            show_progress=True,
        )
        if clarification_questions and "no_questions" not in clarification_questions.lower():
            if not clarification_answers and args.interactive:
                clarification_answers = read_user_answers()
                if clarification_answers:
                    print_progress("Clarification Answers", clarification_answers, args.progress, args.progress_chars)

    align_scout = run_alignment_check("scout", scout_notes)

    template_adjustment_path: Optional[Path] = None
    if template_adjust_enabled:
        template_adjuster_prompt = resolve_agent_prompt(
            "template_adjuster",
            build_template_adjuster_prompt(output_format),
            agent_overrides,
        )
        template_adjuster_model = resolve_agent_model("template_adjuster", args.model, agent_overrides)
        adjusted_spec, adjustment = adjust_template_spec(
            template_spec,
            report_prompt,
            scout_notes,
            align_scout,
            clarification_answers,
            language,
            output_format,
            args.model,
            create_deep_agent,
            backend,
            adjust_mode=args.template_adjust_mode,
            prompt_override=template_adjuster_prompt,
            model_override=template_adjuster_model,
        )
        if adjustment:
            template_adjustment_path = write_template_adjustment_note(
                notes_dir,
                template_spec,
                adjusted_spec,
                adjustment,
                output_format,
                language,
            )
        template_spec = adjusted_spec

    if not template_spec.sections:
        template_spec.sections = list(DEFAULT_SECTIONS)
    required_sections = (
        list(FREE_FORMAT_REQUIRED_SECTIONS) if args.free_format else list(template_spec.sections)
    )
    format_instructions = build_format_instructions(output_format, required_sections, free_form=args.free_format)
    report_skeleton = format_instructions.report_skeleton
    context_lines.append(f"Template: {template_spec.name}")
    if template_spec.source:
        context_lines.append(f"Template source: {template_spec.source}")
    template_guidance_text = build_template_guidance_text(template_spec)

    plan_prompt = resolve_agent_prompt("planner", build_plan_prompt(language), agent_overrides)
    plan_model = resolve_agent_model("planner", args.model, agent_overrides)
    plan_agent = create_agent_with_fallback(create_deep_agent, plan_model, tools, plan_prompt, backend)
    plan_input = list(context_lines)
    plan_input.extend(["", "Scout notes:", scout_notes])
    if source_triage_text:
        plan_input.extend(["", "Source triage (lightweight):", source_triage_text])
    if align_scout:
        plan_input.extend(["", "Alignment notes (scout):", align_scout])
    if template_guidance_text:
        plan_input.extend(["", "Template guidance:", template_guidance_text])
    if report_prompt:
        plan_input.extend(["", "Report focus prompt:", report_prompt])
    if clarification_answers:
        plan_input.extend(["", "User clarifications:", clarification_answers])
    plan_text = run_agent(
        "Plan",
        plan_agent,
        {"messages": [{"role": "user", "content": "\n".join(plan_input)}]},
        show_progress=True,
    )
    (notes_dir / "report_plan.md").write_text(plan_text, encoding="utf-8")
    align_plan = run_alignment_check("plan", plan_text)

    if args.supporting_dir:
        supporting_dir = resolve_supporting_dir(run_dir, args.supporting_dir)
    if args.web_search:
        supporting_dir = resolve_supporting_dir(run_dir, args.supporting_dir)
        web_prompt = resolve_agent_prompt("web_query", build_web_prompt(), agent_overrides)
        web_model = resolve_agent_model("web_query", args.model, agent_overrides)
        web_agent = create_agent_with_fallback(create_deep_agent, web_model, tools, web_prompt, backend)
        web_input = list(context_lines)
        web_input.extend(["", "Scout notes:", scout_notes, "", "Plan:", plan_text])
        if report_prompt:
            web_input.extend(["", "Report focus prompt:", report_prompt])
        web_text = run_agent(
            "Web Query Draft",
            web_agent,
            {"messages": [{"role": "user", "content": "\n".join(web_input)}]},
            show_progress=False,
        )
        web_queries = parse_query_lines(web_text, args.web_max_queries)
        print_progress("Web Queries", "\n".join(web_queries) if web_queries else "None", args.progress, args.progress_chars)
        if web_queries:
            supporting_summary, _ = run_web_research(
                supporting_dir,
                web_queries,
                args.web_max_results,
                args.web_max_fetch,
                args.max_chars,
                args.max_pdf_pages,
            )
        else:
            supporting_summary = "Web research skipped: no queries produced."
        manifest = {
            "created_at": dt.datetime.now().isoformat(),
            "queries": web_queries,
            "summary": supporting_summary,
            "report_prompt": report_prompt,
        }
        (supporting_dir / "manifest.json").write_text(
            json.dumps(manifest, ensure_ascii=False, indent=2), encoding="utf-8"
        )
        if supporting_summary:
            (supporting_dir / "summary.txt").write_text(supporting_summary, encoding="utf-8")
        print_progress("Web Research", supporting_summary or "Completed", args.progress, args.progress_chars)

    if supporting_dir:
        support_rel = supporting_dir.relative_to(run_dir).as_posix()
        context_lines.append(f"Supporting folder: {support_rel}")
        context_lines.append(f"Supporting search: {support_rel}/web_search.jsonl")
        context_lines.append(f"Supporting fetch: {support_rel}/web_fetch.jsonl")
        source_index = feder_tools.build_source_index(archive_dir, run_dir, supporting_dir)
        feder_tools.write_jsonl(source_index_path, source_index)
        source_triage = feder_tools.rank_sources(source_index, report_prompt or query_id, top_k=12)
        source_triage_text = feder_tools.format_source_triage(source_triage)
        source_triage_path.write_text(source_triage_text, encoding="utf-8")

    evidence_prompt = resolve_agent_prompt("evidence", build_evidence_prompt(language), agent_overrides)
    evidence_model = resolve_agent_model("evidence", args.model, agent_overrides)
    evidence_agent = create_agent_with_fallback(create_deep_agent, evidence_model, tools, evidence_prompt, backend)
    evidence_parts = list(context_lines)
    evidence_parts.extend(["", "Scout notes:", scout_notes])
    evidence_parts.extend(["", "Plan:", plan_text])
    if source_triage_text:
        evidence_parts.extend(["", "Source triage (lightweight):", source_triage_text])
    if align_plan:
        evidence_parts.extend(["", "Alignment notes (plan):", align_plan])
    if template_guidance_text:
        evidence_parts.extend(["", "Template guidance:", template_guidance_text])
    if report_prompt:
        evidence_parts.extend(["", "Report focus prompt:", report_prompt])
    if clarification_questions and "no_questions" not in clarification_questions.lower():
        evidence_parts.extend(["", "Clarification questions:", clarification_questions])
    if clarification_answers:
        evidence_parts.extend(["", "User clarifications:", clarification_answers])
    if supporting_summary:
        evidence_parts.extend(["", "Supporting web research summary:", supporting_summary])
    evidence_input = "\n".join(evidence_parts)
    evidence_notes = run_agent(
        "Evidence Notes",
        evidence_agent,
        {"messages": [{"role": "user", "content": evidence_input}]},
        show_progress=True,
    )
    (notes_dir / "evidence_notes.md").write_text(evidence_notes, encoding="utf-8")
    align_evidence = run_alignment_check("evidence", evidence_notes)

    plan_check_prompt = resolve_agent_prompt("plan_check", build_plan_check_prompt(language), agent_overrides)
    plan_check_model = resolve_agent_model("plan_check", check_model, agent_overrides)
    plan_check_agent = create_agent_with_fallback(create_deep_agent, plan_check_model, tools, plan_check_prompt, backend)
    plan_check_input = "\n".join(
        [
            "Plan:",
            plan_text,
            "",
            "Evidence notes:",
            evidence_notes,
            "",
            "Report focus prompt:",
            report_prompt or "(none)",
        ]
    )
    plan_text = run_agent(
        "Plan Update",
        plan_check_agent,
        {"messages": [{"role": "user", "content": plan_check_input}]},
        show_progress=True,
    )
    (notes_dir / "report_plan.md").write_text(plan_text, encoding="utf-8")

    claim_map = feder_tools.build_claim_map(evidence_notes, max_claims=80)
    claim_map_text = feder_tools.format_claim_map(claim_map)
    (notes_dir / "claim_map.md").write_text(claim_map_text, encoding="utf-8")
    plan_text = feder_tools.attach_evidence_to_plan(plan_text, claim_map, max_evidence=2)
    (notes_dir / "report_plan.md").write_text(plan_text, encoding="utf-8")
    gap_text = feder_tools.build_gap_report(plan_text, claim_map)
    (notes_dir / "gap_finder.md").write_text(gap_text, encoding="utf-8")

    writer_prompt = resolve_agent_prompt(
        "writer",
        build_writer_prompt(
            format_instructions,
            template_guidance_text,
            template_spec,
            required_sections,
            output_format,
            language,
        ),
        agent_overrides,
    )
    writer_model = resolve_agent_model("writer", args.model, agent_overrides)
    writer_agent = create_agent_with_fallback(create_deep_agent, writer_model, tools, writer_prompt, backend)
    writer_parts = list(context_lines)
    writer_parts.extend(["", "Evidence notes:", evidence_notes])
    writer_parts.extend(["", "Updated plan:", plan_text])
    if source_triage_text:
        writer_parts.extend(["", "Source triage (lightweight):", source_triage_text])
    if claim_map_text:
        writer_parts.extend(["", "Claim map (lightweight):", claim_map_text])
    if gap_text:
        writer_parts.extend(["", "Gap summary (lightweight):", gap_text])
    if align_evidence:
        writer_parts.extend(["", "Alignment notes (evidence):", align_evidence])
    if template_guidance_text:
        writer_parts.extend(["", "Template guidance:", template_guidance_text])
    if report_prompt:
        writer_parts.extend(["", "Report focus prompt:", report_prompt])
    if clarification_questions and "no_questions" not in clarification_questions.lower():
        writer_parts.extend(["", "Clarification questions:", clarification_questions])
    if clarification_answers:
        writer_parts.extend(["", "User clarifications:", clarification_answers])
    if supporting_summary:
        writer_parts.extend(["", "Supporting web research summary:", supporting_summary])
    writer_input = "\n".join(writer_parts)
    report = run_agent(
        "Writer Draft",
        writer_agent,
        {"messages": [{"role": "user", "content": writer_input}]},
        show_progress=False,
    )
    report = normalize_report_paths(report, run_dir)
    report = coerce_required_headings(report, required_sections)
    retry_needed, retry_reason = report_needs_retry(report)
    if retry_needed:
        retry_input = "\n".join([build_writer_retry_guardrail(retry_reason), "", writer_input])
        report = run_agent(
            "Writer Draft (retry)",
            writer_agent,
            {"messages": [{"role": "user", "content": retry_input}]},
            show_progress=False,
        )
        report = normalize_report_paths(report, run_dir)
        report = coerce_required_headings(report, required_sections)
    missing_sections = find_missing_sections(report, required_sections, output_format)
    report = run_structural_repair(report, missing_sections, "Structural Repair")
    align_draft = run_alignment_check("draft", report)
    candidates = [{"label": "draft", "text": report}]
    quality_model = args.quality_model or check_model or args.model
    if args.quality_iterations > 0:
        for idx in range(args.quality_iterations):
            critic_prompt = resolve_agent_prompt(
                "critic",
                build_critic_prompt(language, required_sections),
                agent_overrides,
            )
            critic_model = resolve_agent_model("critic", quality_model, agent_overrides)
            critic_agent = create_agent_with_fallback(create_deep_agent, critic_model, tools, critic_prompt, backend)
            critic_input = "\n".join(
                [
                    "Report:",
                    truncate_text(normalize_report_paths(report, run_dir), args.quality_max_chars),
                    "",
                    "Evidence notes:",
                    truncate_text(evidence_notes, args.quality_max_chars),
                    "",
                    "Report focus prompt:",
                    report_prompt or "(none)",
                    "",
                    "Alignment notes (draft):",
                    align_draft or "(none)",
                ]
            )
            critique = run_agent(
                f"Critique Pass {idx + 1}",
                critic_agent,
                {"messages": [{"role": "user", "content": critic_input}]},
                show_progress=True,
            )
            if "no_changes" in critique.lower():
                break

            revise_prompt = resolve_agent_prompt(
                "reviser",
                build_revise_prompt(format_instructions, output_format, language),
                agent_overrides,
            )
            revise_model = resolve_agent_model("reviser", quality_model, agent_overrides)
            revise_agent = create_agent_with_fallback(create_deep_agent, revise_model, tools, revise_prompt, backend)
            revise_input = "\n".join(
                [
                    "Original report:",
                    truncate_text(normalize_report_paths(report, run_dir), args.quality_max_chars),
                    "",
                    "Critique:",
                    critique,
                    "",
                    "Evidence notes:",
                    truncate_text(evidence_notes, args.quality_max_chars),
                    "",
                    "Report focus prompt:",
                    report_prompt or "(none)",
                    "",
                    "Alignment notes (draft):",
                    align_draft or "(none)",
                ]
            )
            report = run_agent(
                f"Revision Pass {idx + 1}",
                revise_agent,
                {"messages": [{"role": "user", "content": revise_input}]},
                show_progress=True,
            )
            candidates.append({"label": f"rev_{idx + 1}", "text": report})
    if args.quality_iterations > 0 and len(candidates) > 1:
        eval_path = notes_dir / "quality_evals.jsonl"
        pairwise_path = notes_dir / "quality_pairwise.jsonl"
        evaluations: list[dict] = []
        evaluator_model = resolve_agent_model("evaluator", quality_model, agent_overrides)
        for idx, candidate in enumerate(candidates):
            evaluation = evaluate_report(
                candidate["text"],
                evidence_notes,
                report_prompt,
                template_guidance_text,
                required_sections,
                output_format,
                language,
                evaluator_model,
                create_deep_agent,
                tools,
                backend,
                args.quality_max_chars,
            )
            evaluation["label"] = candidate["label"]
            evaluation["index"] = idx
            evaluations.append(evaluation)
            append_jsonl(eval_path, evaluation)
        if args.quality_strategy == "pairwise":
            wins = {idx: 0.0 for idx in range(len(candidates))}
            pairwise_notes: list[dict] = []
            compare_model = resolve_agent_model("pairwise_compare", quality_model, agent_overrides)
            for i in range(len(candidates)):
                for j in range(i + 1, len(candidates)):
                    result = compare_reports_pairwise(
                        candidates[i]["text"],
                        candidates[j]["text"],
                        evaluations[i],
                        evaluations[j],
                        evidence_notes,
                        report_prompt,
                        required_sections,
                        output_format,
                        language,
                        compare_model,
                        create_deep_agent,
                        tools,
                        backend,
                        args.quality_max_chars,
                    )
                    result["a"] = candidates[i]["label"]
                    result["b"] = candidates[j]["label"]
                    pairwise_notes.append(result)
                    append_jsonl(pairwise_path, result)
                    if result["winner"] == "A":
                        wins[i] += 1.0
                    elif result["winner"] == "B":
                        wins[j] += 1.0
                    else:
                        wins[i] += 0.5
                        wins[j] += 0.5
            ranked = sorted(
                range(len(candidates)),
                key=lambda idx: (wins.get(idx, 0.0), evaluations[idx].get("overall", 0.0)),
                reverse=True,
            )
            top_indices = ranked[:2]
            if len(top_indices) == 2:
                report = synthesize_reports(
                    candidates[top_indices[0]]["text"],
                    candidates[top_indices[1]]["text"],
                    evaluations[top_indices[0]],
                    evaluations[top_indices[1]],
                    pairwise_notes,
                    evidence_notes,
                    report_prompt,
                    template_guidance_text,
                    required_sections,
                    output_format,
                    language,
                    resolve_agent_model("synthesizer", quality_model, agent_overrides),
                    create_deep_agent,
                    tools,
                    backend,
                    args.quality_max_chars,
                )
                report = normalize_report_paths(report, run_dir)
            elif top_indices:
                report = candidates[top_indices[0]]["text"]
        else:
            best_idx = max(range(len(candidates)), key=lambda idx: evaluations[idx].get("overall", 0.0))
            report = candidates[best_idx]["text"]
    missing_sections = find_missing_sections(report, required_sections, output_format)
    report = run_structural_repair(report, missing_sections, "Structural Repair (final)")
    align_final = run_alignment_check("final", report)
    author_name = resolve_author_name(args.author, report_prompt)
    byline = build_byline(author_name)
    report = f"{format_byline(byline, output_format)}\n\n{report.strip()}"
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
            figure_entries = candidates
        else:
            figure_entries = select_figures(candidates, selection_path)
            if not figure_entries:
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
    if figure_entries:
        report_body = insert_figures_by_section(report_body, figure_entries, output_format, report_dir, run_dir)
    report = report_body
    if report_prompt:
        report = f"{report.rstrip()}{format_report_prompt_block(report_prompt, output_format)}"
    if clarification_questions and "no_questions" not in clarification_questions.lower():
        report = f"{report.rstrip()}{format_clarifications_block(clarification_questions, clarification_answers, output_format)}"
    refs = collect_references(archive_dir, run_dir, args.max_refs, supporting_dir)
    refs = filter_references(refs, report_prompt, evidence_notes, args.max_refs)
    openalex_meta = load_openalex_meta(archive_dir)
    report = f"{report.rstrip()}{render_reference_section(citation_refs, refs, openalex_meta, output_format)}"
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
    meta = {
        "generated_at": end_stamp.strftime("%Y-%m-%d %H:%M:%S"),
        "started_at": start_stamp.strftime("%Y-%m-%d %H:%M:%S"),
        "duration_seconds": round(elapsed, 2),
        "duration_hms": format_duration(elapsed),
        "model": args.model,
        "model_vision": args.model_vision,
        "quality_model": quality_model if args.quality_iterations > 0 else None,
        "quality_iterations": args.quality_iterations,
        "quality_strategy": args.quality_strategy if args.quality_iterations > 0 else "none",
        "template": template_spec.name,
        "output_format": output_format,
        "free_format": args.free_format,
        "pdf_status": "enabled" if output_format == "tex" and args.pdf else "disabled",
    }
    if overview_path:
        meta["run_overview_path"] = f"./{overview_path.relative_to(run_dir).as_posix()}"
    if report_overview_path:
        meta["report_overview_path"] = f"./{report_overview_path.relative_to(run_dir).as_posix()}"
    if index_file:
        meta["archive_index_path"] = f"./{index_file.relative_to(run_dir).as_posix()}"
    if instruction_file:
        meta["instruction_path"] = f"./{instruction_file.relative_to(run_dir).as_posix()}"
    if prompt_copy_path:
        meta["report_prompt_path"] = f"./{prompt_copy_path.relative_to(run_dir).as_posix()}"
    if template_adjustment_path:
        meta["template_adjustment_path"] = f"./{template_adjustment_path.relative_to(run_dir).as_posix()}"
    if preview_path:
        meta["figures_preview_path"] = f"./{preview_path.relative_to(run_dir).as_posix()}"
    report = f"{report.rstrip()}{format_metadata_block(meta, output_format)}"
    print_progress("Report Preview", report, args.progress, args.progress_chars)

    (notes_dir / "scout_notes.md").write_text(scout_notes, encoding="utf-8")
    template_lines = [
        f"Template: {template_spec.name}",
        f"Source: {template_spec.source or 'builtin/default'}",
        f"Latex: {template_spec.latex or 'default.tex'}",
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
    meta_path = notes_dir / "report_meta.json"
    meta_path.write_text(json.dumps(meta, ensure_ascii=False, indent=2), encoding="utf-8")

    theme_css = load_template_css(template_spec)
    rendered = report
    if output_format == "html":
        viewer_dir = run_dir / "report_views"
        viewer_map = build_viewer_map(report, run_dir, archive_dir, supporting_dir, report_dir, viewer_dir, args.max_chars)
        body_html = markdown_to_html(report)
        body_html = linkify_html(body_html)
        body_html = inject_viewer_links(body_html, viewer_map)
        rendered = wrap_html(
            f"Federlicht Report - {query_id}",
            body_html,
            template_name=template_spec.name,
            theme_css=theme_css,
        )
    elif output_format == "tex":
        latex_template = load_template_latex(template_spec)
        if language == "Korean":
            latex_template = ensure_korean_package(latex_template or DEFAULT_LATEX_TEMPLATE)
        report = close_unbalanced_lists(report)
        report = sanitize_latex_headings(report)
        rendered = render_latex_document(
            latex_template,
            f"Federlicht Report - {query_id}",
            author_name,
            dt.datetime.now().strftime("%Y-%m-%d"),
            report,
        )

    if args.output:
        if not final_path:
            raise RuntimeError("Output path resolution failed.")
        final_path.write_text(rendered, encoding="utf-8")
        print(f"Wrote report: {final_path}")
        if args.echo_markdown:
            print(report)
        if output_format == "tex" and args.pdf:
            ok, message = compile_latex_to_pdf(final_path)
            pdf_path = final_path.with_suffix(".pdf")
            if ok and pdf_path.exists():
                print(f"Wrote PDF: {pdf_path}")
                meta["pdf_status"] = "success"
            elif not ok:
                print(f"PDF compile failed: {truncate_text(message, 800)}", file=sys.stderr)
                meta["pdf_status"] = "failed"
            meta_path.write_text(json.dumps(meta, ensure_ascii=False, indent=2), encoding="utf-8")
    else:
        print(rendered)

    return 0


if __name__ == "__main__":
    raise SystemExit(main())
