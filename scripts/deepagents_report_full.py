#!/usr/bin/env python3
# -*- coding: utf-8 -*-

"""
In-depth, multi-step report generator for a HiDair Feather run.

Usage:
  python scripts/deepagents_report_full.py --run ./runs/20260109_sectioned --output ./runs/20260109_sectioned/report_full.md
  python scripts/deepagents_report_full.py --run ./runs/20260109_sectioned --notes-dir ./runs/20260109_sectioned/report_notes
  python scripts/deepagents_report_full.py --run ./runs/20260104_basic-oa --output ./runs/20260104_basic-oa/report_full.html --web-search
  python scripts/deepagents_report_full.py --run ./runs/20260104_basic-oa --output ./runs/20260104_basic-oa/report_full.tex --template prl_manuscript
"""

from __future__ import annotations

import argparse
import datetime as dt
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
from typing import Optional


DEFAULT_MODEL = "gpt-5.2"
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
DEFAULT_LATEX_TEMPLATE = r"""\documentclass[11pt]{article}
\usepackage[margin=1in]{geometry}
\usepackage{hyperref}
\usepackage{amsmath,amssymb}
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


def templates_dir() -> Path:
    return Path(__file__).resolve().parent / "templates"


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
        "  python scripts/deepagents_report_full.py --run ./runs/20260104_basic-oa --output ./runs/20260104_basic-oa/report_full.html\n"
        "  python scripts/deepagents_report_full.py --run ./runs/20260104_basic-oa --output ./runs/20260104_basic-oa/report_full.html --template executive_brief\n"
        "  python scripts/deepagents_report_full.py --run ./runs/20260104_basic-oa --output ./runs/20260104_basic-oa/report_full.tex --template prl_manuscript\n"
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
        "--preview-template",
        help="Generate template preview HTML and exit (name, path, or 'all').",
    )
    ap.add_argument(
        "--preview-output",
        help="Preview output path or directory (default: scripts/templates/).",
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
    ap.add_argument("--quality-max-chars", type=int, default=12000, help="Max chars passed to critique/revision.")
    ap.add_argument("--model", default=DEFAULT_MODEL, help=f"Model name (default: {DEFAULT_MODEL} if supported).")
    ap.add_argument(
        "--progress",
        action=argparse.BooleanOptionalAction,
        default=True,
        help="Print intermediate progress snippets (default: enabled).",
    )
    ap.add_argument(
        "--alignment-check",
        action=argparse.BooleanOptionalAction,
        default=True,
        help="Check alignment with the report prompt at each stage (default: enabled).",
    )
    ap.add_argument("--progress-chars", type=int, default=800, help="Max chars for progress snippets.")
    ap.add_argument("--max-files", type=int, default=200, help="Max files to list in tool output.")
    ap.add_argument("--max-chars", type=int, default=16000, help="Max chars returned by read tool.")
    ap.add_argument("--max-pdf-pages", type=int, default=6, help="Max PDF pages to extract when needed.")
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


def build_report_skeleton(sections: list[str], output_format: str) -> str:
    if output_format == "tex":
        return "\n".join(f"\\section{{{section}}}" for section in sections)
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
    if meta.get("quality_model"):
        lines.append(f"Quality model: {meta.get('quality_model')}")
    lines.append(f"Quality strategy: {meta.get('quality_strategy', '-')}")
    lines.append(f"Quality iterations: {meta.get('quality_iterations', '-')}")
    lines.append(f"Template: {meta.get('template', '-')}")
    lines.append(f"Output format: {meta.get('output_format', '-')}")
    if meta.get("pdf_status"):
        lines.append(f"PDF compile: {meta.get('pdf_status')}")
    if output_format == "tex":
        block = ["", "\\section*{Miscellaneous}", "\\small", "\\begin{itemize}"]
        block.extend([f"\\item {latex_escape(line)}" for line in lines])
        block.extend(["\\end{itemize}", "\\normalsize"])
        return "\n".join(block)
    if output_format == "html":
        items = "\n".join(f"<li>{html_lib.escape(line)}</li>" for line in lines)
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
    evaluator_prompt = (
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
    judge_prompt = (
        "You are a senior journal editor. Compare Report A vs Report B and choose the stronger report. "
        "Consider alignment, evidence grounding, hallucination risk, format compliance, clarity, "
        "and narrative strength. Return JSON only:\n"
        "{\"winner\": \"A|B|Tie\", \"reason\": \"...\", \"focus_improvements\": [\"...\"]}\n"
        "Do not include any extra text outside JSON."
    )
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
    section_instruction = (
        "Use the following exact H2 headings in this order (do not rename; do not add extra H2 headings):\n"
        if output_format != "tex"
        else "Use the following exact \\section headings in this order (do not rename; do not add extra \\section headings):\n"
    )
    format_instruction = ""
    if output_format == "tex":
        format_instruction = (
            "Write LaTeX body only (no documentclass/preamble). "
            "Use \\section{...} headings for each required section and \\subsection for subpoints. "
            "Do not use Markdown formatting. "
            "Avoid square brackets except for raw source citations. "
        )
    synthesis_prompt = (
        "You are a chief editor. Merge the strongest parts of Report A and Report B, fix weaknesses, "
        "and produce a final report with higher overall quality. "
        "Preserve citations; do not invent sources. "
        "Do not add a full References list; the script appends it automatically. "
        f"{section_instruction}{build_report_skeleton(required_sections, output_format)}\n"
        f"{'Template guidance:\\n' + template_guidance_text + '\\n' if template_guidance_text else ''}"
        f"{format_instruction}"
        f"Write in {language}."
    )
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
        counter += 1


def compile_latex_to_pdf(tex_path: Path) -> tuple[bool, str]:
    workdir = tex_path.parent
    if shutil.which("latexmk"):
        cmd = ["latexmk", "-pdf", "-interaction=nonstopmode", "-halt-on-error", tex_path.name]
        result = subprocess.run(cmd, cwd=workdir, capture_output=True, text=True)
        if result.returncode == 0:
            return True, ""
        return False, (result.stderr or result.stdout or "latexmk failed.")
    if shutil.which("pdflatex"):
        cmd = ["pdflatex", "-interaction=nonstopmode", "-halt-on-error", tex_path.name]
        for _ in range(2):
            result = subprocess.run(cmd, cwd=workdir, capture_output=True, text=True)
            if result.returncode != 0:
                return False, (result.stderr or result.stdout or "pdflatex failed.")
        return True, ""
    return False, "No LaTeX compiler found (latexmk or pdflatex)."


def request_headers() -> dict[str, str]:
    return {"User-Agent": "HiDairFeather/1.0 (+https://example.local)"}


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
                for marker in ("/archive", "/instruction", "/report", "/report_notes"):
                    idx = normalized.lower().find(marker)
                    if idx != -1:
                        rel = normalized[idx + 1 :]
                        return f"/{rel}"
                return None

            def _resolve_path(self, key: str) -> Path:  # type: ignore[override]
                if self.virtual_mode and isinstance(key, str):
                    raw = key.strip()
                    normalized = raw.replace("\\", "/")
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
        "      <div class=\"kicker\">HiDair Feather</div>\n"
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
    return f'Hidair assisted and prompted by "{author}" — {stamp}'


def print_progress(label: str, content: str, enabled: bool, max_chars: int) -> None:
    if not enabled:
        return
    snippet = content.strip()
    if max_chars > 0 and len(snippet) > max_chars:
        snippet = f"{snippet[:max_chars]}\n... [truncated]"
    print(f"\n[{label}]\n{snippet}\n")


def create_agent_with_fallback(create_deep_agent, model_name: str, tools, system_prompt: str, backend):
    kwargs = {"tools": tools, "system_prompt": system_prompt, "backend": backend}
    if model_name:
        try:
            return create_deep_agent(model=model_name, **kwargs)
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
                text = read_text_file(txt_path, start, limit)
                return f"[from text] {txt_path.relative_to(run_dir).as_posix()}\n\n{text}"
            pdf_text = read_pdf_with_fitz(path, page_limit, limit)
            return f"[from pdf] {path.relative_to(run_dir).as_posix()}\n\n{pdf_text}"
        text = read_text_file(path, start, limit)
        return f"[from text] {path.relative_to(run_dir).as_posix()}\n\n{text}"

    tools = [list_archive_files, list_supporting_files, read_document]

    def run_alignment_check(stage: str, content: str) -> Optional[str]:
        if not args.alignment_check:
            return None
        align_prompt = (
            "You are an alignment auditor. Check whether the stage output aligns with the report focus prompt "
            "and any user clarifications. If no prompt or clarifications exist, judge alignment to the run context "
            "(query ID, instruction scope, and available sources). Return in this exact format:\n"
            "Alignment score: <0-100>\n"
            "Aligned:\n- ...\n"
            "Gaps/Risks:\n- ...\n"
            "Next-step guidance:\n- ...\n"
            "Be concise and actionable."
        )
        align_agent = create_agent_with_fallback(create_deep_agent, args.model, tools, align_prompt, backend)
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
        align_result = align_agent.invoke({"messages": [{"role": "user", "content": "\n".join(align_input)}]})
        align_notes = extract_agent_text(align_result)
        print_progress(f"Alignment Check ({stage})", align_notes, args.progress, args.progress_chars)
        note_name = f"alignment_{slugify_label(stage)}.md"
        (notes_dir / note_name).write_text(align_notes, encoding="utf-8")
        return align_notes

    context_lines = [
        f"Run folder: {run_dir.as_posix()}",
        f"Archive folder: {archive_dir.as_posix()}",
        f"Query ID: {query_id}",
    ]
    if instruction_file:
        context_lines.append(f"Instruction file: {instruction_file.relative_to(run_dir).as_posix()}")
    if baseline_report:
        context_lines.append(f"Baseline report: {baseline_report.relative_to(run_dir).as_posix()}")
    if index_file:
        context_lines.append(f"Index file: {index_file.relative_to(run_dir).as_posix()}")

    language = normalize_lang(args.lang)
    report_prompt = load_report_prompt(args.prompt, args.prompt_file)
    template_spec = load_template_spec(args.template, report_prompt)
    required_sections = list(template_spec.sections)
    report_skeleton = build_report_skeleton(required_sections, output_format)
    context_lines.append(f"Template: {template_spec.name}")
    if template_spec.source:
        context_lines.append(f"Template source: {template_spec.source}")
    template_guidance_lines: list[str] = []
    if template_spec.description:
        template_guidance_lines.append(f"Template description: {template_spec.description}")
    if template_spec.tone:
        template_guidance_lines.append(f"Template tone: {template_spec.tone}")
    if template_spec.audience:
        template_guidance_lines.append(f"Template audience: {template_spec.audience}")
    if template_spec.section_guidance:
        section_lines = [f"- {key}: {value}" for key, value in template_spec.section_guidance.items()]
        template_guidance_lines.append("Section guidance:\n" + "\n".join(section_lines))
    if template_spec.writer_guidance:
        template_guidance_lines.append("Template writing guidance:\n" + "\n".join(template_spec.writer_guidance))
    template_guidance_text = "\n\n".join(template_guidance_lines) if template_guidance_lines else ""
    scout_prompt = (
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
    scout_agent = create_agent_with_fallback(create_deep_agent, args.model, tools, scout_prompt, backend)
    scout_input = list(context_lines)
    if report_prompt:
        scout_input.extend(["", "Report focus prompt:", report_prompt])
    scout_result = scout_agent.invoke({"messages": [{"role": "user", "content": "\n".join(scout_input)}]})
    scout_notes = extract_agent_text(scout_result)
    print_progress("Scout Notes", scout_notes, args.progress, args.progress_chars)

    clarification_questions: Optional[str] = None
    clarification_answers = load_user_answers(args.answers, args.answers_file)
    if args.interactive or clarification_answers:
        clarifier_prompt = (
            "You are a report planning assistant. Based on the run context, scout notes, and report focus prompt, "
            "decide if you need clarifications from the user. If none are needed, respond with 'NO_QUESTIONS'. "
            f"Otherwise, list up to 5 concise questions in {language}."
        )
        clarifier_agent = create_agent_with_fallback(create_deep_agent, args.model, tools, clarifier_prompt, backend)
        clarifier_input = list(context_lines)
        clarifier_input.extend(["", "Scout notes:", scout_notes])
        if report_prompt:
            clarifier_input.extend(["", "Report focus prompt:", report_prompt])
        clarifier_result = clarifier_agent.invoke({"messages": [{"role": "user", "content": "\n".join(clarifier_input)}]})
        clarification_questions = extract_agent_text(clarifier_result)
        print_progress("Clarification Questions", clarification_questions, args.progress, args.progress_chars)
        if clarification_questions and "no_questions" not in clarification_questions.lower():
            if not clarification_answers and args.interactive:
                clarification_answers = read_user_answers()
                if clarification_answers:
                    print_progress("Clarification Answers", clarification_answers, args.progress, args.progress_chars)

    align_scout = run_alignment_check("scout", scout_notes)

    plan_prompt = (
        "You are a report planner. Create a concise, ordered plan (5-9 steps) to produce the final report. "
        "Each step should be one line with a status checkbox. "
        "Use this format:\n"
        "- [ ] Step title — short description\n"
        "Focus on reading the most relevant sources, extracting evidence, and synthesizing insights. "
        "Align the plan with the report focus prompt and clarifications. "
        f"Write in {language}."
    )
    plan_agent = create_agent_with_fallback(create_deep_agent, args.model, tools, plan_prompt, backend)
    plan_input = list(context_lines)
    plan_input.extend(["", "Scout notes:", scout_notes])
    if align_scout:
        plan_input.extend(["", "Alignment notes (scout):", align_scout])
    if template_guidance_text:
        plan_input.extend(["", "Template guidance:", template_guidance_text])
    if report_prompt:
        plan_input.extend(["", "Report focus prompt:", report_prompt])
    if clarification_answers:
        plan_input.extend(["", "User clarifications:", clarification_answers])
    plan_result = plan_agent.invoke({"messages": [{"role": "user", "content": "\n".join(plan_input)}]})
    plan_text = extract_agent_text(plan_result)
    print_progress("Plan", plan_text, args.progress, args.progress_chars)
    (notes_dir / "report_plan.md").write_text(plan_text, encoding="utf-8")
    align_plan = run_alignment_check("plan", plan_text)

    if args.supporting_dir:
        supporting_dir = resolve_supporting_dir(run_dir, args.supporting_dir)
    if args.web_search:
        supporting_dir = resolve_supporting_dir(run_dir, args.supporting_dir)
        web_prompt = (
            "You are planning targeted web searches to enrich a research report. "
            "Provide up to 6 concise search queries in English, one per line. "
            "Focus on recent, credible sources and technical specifics. "
            "Avoid broad keywords; include concrete phrases, paper titles, or domains when helpful."
        )
        web_agent = create_agent_with_fallback(create_deep_agent, args.model, tools, web_prompt, backend)
        web_input = list(context_lines)
        web_input.extend(["", "Scout notes:", scout_notes, "", "Plan:", plan_text])
        if report_prompt:
            web_input.extend(["", "Report focus prompt:", report_prompt])
        web_result = web_agent.invoke({"messages": [{"role": "user", "content": "\n".join(web_input)}]})
        web_queries = parse_query_lines(extract_agent_text(web_result), args.web_max_queries)
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

    evidence_prompt = (
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
    evidence_agent = create_agent_with_fallback(create_deep_agent, args.model, tools, evidence_prompt, backend)
    evidence_parts = list(context_lines)
    evidence_parts.extend(["", "Scout notes:", scout_notes])
    evidence_parts.extend(["", "Plan:", plan_text])
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
    evidence_result = evidence_agent.invoke({"messages": [{"role": "user", "content": evidence_input}]})
    evidence_notes = extract_agent_text(evidence_result)
    print_progress("Evidence Notes", evidence_notes, args.progress, args.progress_chars)
    (notes_dir / "evidence_notes.md").write_text(evidence_notes, encoding="utf-8")
    align_evidence = run_alignment_check("evidence", evidence_notes)

    plan_check_prompt = (
        "You are a plan checker. Update the plan by marking completed steps with [x] and "
        "adding any missing steps needed to finish the report. Keep it concise. "
        f"Write in {language}."
    )
    plan_check_agent = create_agent_with_fallback(create_deep_agent, args.model, tools, plan_check_prompt, backend)
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
    plan_check_result = plan_check_agent.invoke({"messages": [{"role": "user", "content": plan_check_input}]})
    plan_text = extract_agent_text(plan_check_result)
    print_progress("Plan Update", plan_text, args.progress, args.progress_chars)
    (notes_dir / "report_plan.md").write_text(plan_text, encoding="utf-8")

    critics_guidance = ""
    if any(section.lower().startswith("critics") for section in required_sections):
        critics_guidance = (
            "For the Critics section, write in a concise editorial tone with a short headline, brief paragraphs, "
            "and a few bullet points highlighting orthogonal or contrarian viewpoints, risks, or overlooked constraints. "
            "If relevant, touch on AI ethics, regulation (e.g., EU AI Act), safety/security, and explainability. "
        )
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
    format_instruction = ""
    if output_format == "tex":
        format_instruction = (
            "Write LaTeX body only (no documentclass/preamble). "
            "Use \\section{...} headings for each required section and \\subsection for subpoints. "
            "Do not use Markdown formatting. "
            "Avoid square brackets except for raw source citations. "
        )
    tone_instruction = (
        "Use a formal/academic research-journal tone suitable for PRL/Nature/Annual Review-style manuscripts. "
        if template_spec.name in FORMAL_TEMPLATES
        else "Use an explanatory review style (설명형 리뷰) with a professional yet natural narrative tone. "
    )
    writer_prompt = (
        "You are a senior research writer. Using the instruction, baseline report, and evidence notes, "
        "produce a detailed report with citations. "
        f"{tone_instruction}"
        f"{section_heading_instruction}{report_skeleton}\n"
        f"{'Template guidance:\\n' + template_guidance_text + '\\n' if template_guidance_text else ''}"
        f"{format_instruction}"
        "Synthesize across sources (not a list of summaries), use clear transitions, and surface actionable insights. "
        "Do not dump JSONL contents; focus on analyzing the referenced documents and articles. "
        "Never cite JSONL index files (e.g., tavily_search.jsonl, openalex/works.jsonl). Cite actual source URLs "
        "and extracted text/PDF/transcript files instead. "
        "Do not include a full References list; the script appends a Source Index automatically. "
        "Do not add Report Prompt or Clarifications sections; the script appends them automatically. "
        "When citing file paths, use relative paths like ./archive/... or ./instruction/... (avoid absolute paths). "
        f"{citation_instruction}"
        "When formulas are important, render them in LaTeX using $...$ or $$...$$ so they can be rendered in HTML. "
        f"{critics_guidance}"
        "If supporting web research exists under ./supporting/..., integrate it as updated evidence and label it as "
        "web-derived support (not primary experimental evidence). "
        f"Write the report in {language}. Keep proper nouns and source titles in their original language. "
        "Avoid speculation and clearly separate facts from interpretation."
    )
    writer_agent = create_agent_with_fallback(create_deep_agent, args.model, tools, writer_prompt, backend)
    writer_parts = list(context_lines)
    writer_parts.extend(["", "Evidence notes:", evidence_notes])
    writer_parts.extend(["", "Updated plan:", plan_text])
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
    writer_result = writer_agent.invoke({"messages": [{"role": "user", "content": writer_input}]})
    report = extract_agent_text(writer_result)
    report = normalize_report_paths(report, run_dir)
    missing_sections = find_missing_sections(report, required_sections, output_format)
    if missing_sections:
        repair_prompt = (
            "You are a structural editor. The report is missing required sections. "
            "Add the missing sections while preserving all existing content and citations. "
            "Use the exact section headings in the required skeleton and keep their order. "
            "Do not add extra section headings. "
            f"{'Prefer markdown links for file paths. ' if output_format != 'tex' else 'Keep LaTeX section commands and avoid Markdown formatting. '}"
            f"Write in {language}."
        )
        repair_agent = create_agent_with_fallback(create_deep_agent, args.model, tools, repair_prompt, backend)
        repair_input = "\n".join(
            [
                "Required skeleton:",
                report_skeleton,
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
                truncate_text(report, args.quality_max_chars),
            ]
        )
        repair_result = repair_agent.invoke({"messages": [{"role": "user", "content": repair_input}]})
        report = extract_agent_text(repair_result)
        report = normalize_report_paths(report, run_dir)
    align_draft = run_alignment_check("draft", report)
    required_sections_label = ", ".join(required_sections)
    candidates = [{"label": "draft", "text": report}]
    quality_model = args.quality_model or args.model
    if args.quality_iterations > 0:
        for idx in range(args.quality_iterations):
            critic_prompt = (
                "You are a rigorous journal editor. Critique the report for clarity, narrative flow, "
                "depth of insight, evidence usage, and alignment with the report focus. "
                "Flag any reliance on JSONL index data instead of source content, including citations that point "
                "to JSONL index files rather than the underlying sources. "
                f"Confirm all required sections are present ({required_sections_label}) and note any missing. "
                "If the report already meets high-quality standards, respond with 'NO_CHANGES'. "
                f"Write in {language}."
            )
            critic_agent = create_agent_with_fallback(create_deep_agent, quality_model, tools, critic_prompt, backend)
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
            critic_result = critic_agent.invoke({"messages": [{"role": "user", "content": critic_input}]})
            critique = extract_agent_text(critic_result)
            print_progress(f"Critique Pass {idx + 1}", critique, args.progress, args.progress_chars)
            if "no_changes" in critique.lower():
                break

            revise_prompt = (
                "You are a senior editor. Revise the report to address the critique. "
                "Preserve the required sections and citations. "
                "Improve narrative flow, synthesis, and technical rigor. "
                "Do not add a full References list; the script appends a Source Index automatically. "
                f"{'Keep LaTeX formatting and section commands; do not convert to Markdown. ' if output_format == 'tex' else ''}"
                f"Write in {language}."
            )
            revise_agent = create_agent_with_fallback(create_deep_agent, quality_model, tools, revise_prompt, backend)
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
            revise_result = revise_agent.invoke({"messages": [{"role": "user", "content": revise_input}]})
            report = extract_agent_text(revise_result)
            print_progress(f"Revision Pass {idx + 1}", report, args.progress, args.progress_chars)
            candidates.append({"label": f"rev_{idx + 1}", "text": report})
    if args.quality_iterations > 0 and len(candidates) > 1:
        eval_path = notes_dir / "quality_evals.jsonl"
        pairwise_path = notes_dir / "quality_pairwise.jsonl"
        evaluations: list[dict] = []
        for idx, candidate in enumerate(candidates):
            evaluation = evaluate_report(
                candidate["text"],
                evidence_notes,
                report_prompt,
                template_guidance_text,
                required_sections,
                output_format,
                language,
                quality_model,
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
                        quality_model,
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
                    quality_model,
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
    if missing_sections:
        repair_prompt = (
            "You are a structural editor. The report is missing required sections. "
            "Add the missing sections while preserving all existing content and citations. "
            "Use the exact section headings in the required skeleton and keep their order. "
            "Do not add extra section headings. "
            f"{'Prefer markdown links for file paths. ' if output_format != 'tex' else 'Keep LaTeX section commands and avoid Markdown formatting. '}"
            f"Write in {language}."
        )
        repair_agent = create_agent_with_fallback(create_deep_agent, args.model, tools, repair_prompt, backend)
        repair_input = "\n".join(
            [
                "Required skeleton:",
                report_skeleton,
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
                truncate_text(report, args.quality_max_chars),
            ]
        )
        repair_result = repair_agent.invoke({"messages": [{"role": "user", "content": repair_input}]})
        report = extract_agent_text(repair_result)
        report = normalize_report_paths(report, run_dir)
    align_final = run_alignment_check("final", report)
    author_name = resolve_author_name(args.author, report_prompt)
    byline = build_byline(author_name)
    report = f"{format_byline(byline, output_format)}\n\n{report.strip()}"
    report_body, citation_refs = rewrite_citations(report.rstrip(), output_format)
    report = report_body
    if report_prompt:
        report = f"{report.rstrip()}{format_report_prompt_block(report_prompt, output_format)}"
    if clarification_questions and "no_questions" not in clarification_questions.lower():
        report = f"{report.rstrip()}{format_clarifications_block(clarification_questions, clarification_answers, output_format)}"
    refs = collect_references(archive_dir, run_dir, args.max_refs, supporting_dir)
    refs = filter_references(refs, report_prompt, evidence_notes, args.max_refs)
    openalex_meta = load_openalex_meta(archive_dir)
    report = f"{report.rstrip()}{render_reference_section(citation_refs, refs, openalex_meta, output_format)}"
    end_stamp = dt.datetime.now()
    elapsed = time.monotonic() - start_timer
    meta = {
        "generated_at": end_stamp.strftime("%Y-%m-%d %H:%M:%S"),
        "started_at": start_stamp.strftime("%Y-%m-%d %H:%M:%S"),
        "duration_seconds": round(elapsed, 2),
        "duration_hms": format_duration(elapsed),
        "model": args.model,
        "quality_model": quality_model if args.quality_iterations > 0 else None,
        "quality_iterations": args.quality_iterations,
        "quality_strategy": args.quality_strategy if args.quality_iterations > 0 else "none",
        "template": template_spec.name,
        "output_format": output_format,
        "pdf_status": "enabled" if output_format == "tex" and args.pdf else "disabled",
    }
    report = f"{report.rstrip()}{format_metadata_block(meta, output_format)}"
    print_progress("Report Preview", report, args.progress, args.progress_chars)

    (notes_dir / "scout_notes.md").write_text(scout_notes, encoding="utf-8")
    template_lines = [
        f"Template: {template_spec.name}",
        f"Source: {template_spec.source or 'builtin/default'}",
        f"Latex: {template_spec.latex or 'default.tex'}",
        "Sections:",
        *[f"- {section}" for section in required_sections],
    ]
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
        report_dir = run_dir if not args.output else Path(args.output).resolve().parent
        viewer_dir = run_dir / "report_views"
        viewer_map = build_viewer_map(report, run_dir, archive_dir, supporting_dir, report_dir, viewer_dir, args.max_chars)
        body_html = markdown_to_html(report)
        body_html = linkify_html(body_html)
        body_html = inject_viewer_links(body_html, viewer_map)
        rendered = wrap_html(
            f"HiDair Feather Report - {query_id}",
            body_html,
            template_name=template_spec.name,
            theme_css=theme_css,
        )
    elif output_format == "tex":
        latex_template = load_template_latex(template_spec)
        rendered = render_latex_document(
            latex_template,
            f"HiDair Feather Report - {query_id}",
            author_name,
            dt.datetime.now().strftime("%Y-%m-%d"),
            report,
        )

    if args.output:
        out_path = Path(args.output)
        out_path.parent.mkdir(parents=True, exist_ok=True)
        companion_suffixes = [".pdf"] if output_format == "tex" else None
        final_path = resolve_output_path(out_path, args.overwrite_output, companion_suffixes)
        final_path.write_text(rendered, encoding="utf-8")
        print(f"Wrote report: {final_path}")
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
