import argparse
import os
import shutil
from pathlib import Path
from typing import Iterable, Optional

from .collector import prepare_jobs, run_job, run_job_agentic
from .review import (
    collect_run_summary,
    find_run_dirs,
    format_run_list,
    render_jsonl_review,
    render_jsonl_review_full,
    render_review,
    render_review_full,
    render_review_json,
)
from .tavily import TavilyClient


def normalize_lang(value: Optional[str]) -> Optional[str]:
    if not value:
        return None
    val = value.strip().lower()
    if val in {"any", "auto", "none"}:
        return None
    if val in {"en", "eng", "english"}:
        return "en"
    if val in {"ko", "kor", "korean"}:
        return "ko"
    raise SystemExit(f"Invalid --lang value: {value}. Use en/eng or ko/kor.")


def build_parser() -> argparse.ArgumentParser:
    epilog = (
        "Examples:\n"
        "  feather --input ./instructions --output ./archive --max-results 5\n"
        "  feather --query \"quantum computing; recent 30 days; arXiv:2401.01234\" --output ./runs --lang en\n"
        "  feather --input ./instructions --output ./archive --openalex --download-pdf\n"
        "  feather --list ./runs\n"
        "  feather --review ./runs/20260104\n"
        "  feather --input ./instructions --output ./archive --youtube --yt-transcript\n"
        "  python -m feather --input ./instructions --output ./archive --download-pdf\n"
        "  python run.py --input ./examples/instructions --output ./runs\n"
        "\n"
        "Library mode:\n"
        "  python -c \"from feather.cli import main; main(['--input','./instructions','--output','./archive'])\"\n"
        "  python -c \"from feather.collector import prepare_jobs, run_job; from feather.tavily import TavilyClient; "
        "import os; jobs=prepare_jobs(input_path=Path('./instructions'), query=None, output_root=Path('./archive'), "
        "lang_pref=None, openalex_enabled=False, openalex_max_results=None, youtube_enabled=False, "
        "youtube_max_results=None, youtube_transcript=False, youtube_order='relevance', days=30, max_results=8, "
        "download_pdf=False, arxiv_source=False); "
        "t=TavilyClient(os.getenv('TAVILY_API_KEY')); [run_job(j, t) for j in jobs]\"\n"
    )
    class CleanHelpFormatter(argparse.RawDescriptionHelpFormatter):
        def __init__(self, prog: str) -> None:
            width = shutil.get_terminal_size((120, 20)).columns
            super().__init__(prog, width=width, max_help_position=32)

    ap = argparse.ArgumentParser(
        description="Feather collector (Federlicht platform): non-LLM evidence intake for web/arXiv/local sources via TXT instructions.",
        formatter_class=CleanHelpFormatter,
        epilog=epilog,
    )
    group = ap.add_mutually_exclusive_group(required=True)
    group.add_argument("--input", help="Input folder with .txt files or a single .txt file")
    group.add_argument(
        "--query",
        help="Inline instructions separated by ';' or newlines (quoted). Blank lines or '---' split sections.",
    )
    group.add_argument(
        "--list",
        nargs="?",
        const=".",
        metavar="PATH",
        help="List run folders under PATH (default: current directory).",
    )
    group.add_argument("--review", metavar="PATH", help="Show outputs for a single run folder or its archive path.")
    ap.add_argument("--output", help="Output archive root folder")
    ap.add_argument(
        "--filter",
        dest="filter_text",
        help="Filter list entries by queryID substring (case-insensitive). Use with --list.",
    )
    ap.add_argument(
        "--format",
        choices=["text", "json"],
        help="Output format for --review (text or json).",
    )
    ap.add_argument(
        "--review-full",
        "--review_full",
        action="store_true",
        help="Show full outputs when reviewing a run or JSONL file.",
    )
    ap.add_argument("--days", type=int, default=30, help="Lookback window (days)")
    ap.add_argument("--max-results", type=int, default=8, help="Max results per Tavily/arXiv search step")
    ap.add_argument(
        "--agentic-search",
        action="store_true",
        help="Enable LLM-driven iterative search planning on top of the standard Feather pipeline.",
    )
    ap.add_argument(
        "--model",
        help="Model for --agentic-search planner turns (OpenAI-compatible; defaults to OPENAI_MODEL).",
    )
    ap.add_argument(
        "--max-iter",
        type=int,
        default=3,
        help="Maximum agentic planning iterations when --agentic-search is enabled (default: 3).",
    )
    ap.add_argument("--download-pdf", action="store_true", help="Download arXiv PDFs and extract PDF text")
    ap.add_argument(
        "--arxiv-src",
        action="store_true",
        help="Download arXiv source tarballs (e-print) and extract TeX/figure manifests",
    )
    ap.add_argument(
        "--update-run",
        action="store_true",
        help="Reuse an existing run folder (skip numbered suffix) and update outputs in place.",
    )
    ap.add_argument("--lang", help="Preferred language for search results (en/eng or ko/kor). Soft preference only.")
    ap.add_argument("--no-stdout-log", action="store_true", help="Write logs only to _log.txt (no console output).")
    ap.add_argument("--no-citations", action="store_true", help="Disable citation enrichment for papers.")
    oa_group = ap.add_mutually_exclusive_group()
    oa_group.add_argument(
        "--openalex",
        "--oa",
        action="store_true",
        help="Enable OpenAlex open-access search and optional PDF download (default when --download-pdf).",
    )
    oa_group.add_argument(
        "--no-openalex",
        action="store_true",
        help="Disable OpenAlex search (overrides the default when --download-pdf is set).",
    )
    ap.add_argument("--oa-max-results", type=int, help="Max OpenAlex results per query (default: --max-results)")
    yt_group = ap.add_mutually_exclusive_group()
    yt_group.add_argument("--youtube", action="store_true", help="Enable YouTube search.")
    yt_group.add_argument("--no-youtube", action="store_true", help="Disable YouTube search.")
    ap.add_argument("--yt-max-results", type=int, help="Max YouTube results per query (default: --max-results)")
    ap.add_argument(
        "--yt-order",
        choices=["relevance", "date", "viewCount", "rating"],
        default="relevance",
        help="YouTube search ordering.",
    )
    ap.add_argument(
        "--yt-transcript",
        action="store_true",
        help="Fetch YouTube transcripts (requires youtube-transcript-api).",
    )
    return ap


def main(argv: Optional[Iterable[str]] = None) -> int:
    args = build_parser().parse_args(argv)

    if args.filter_text and args.list is None:
        raise SystemExit("--filter requires --list.")
    if args.format and not args.review:
        raise SystemExit("--format is only valid with --review.")
    if args.review_full and not args.review:
        raise SystemExit("--review-full is only valid with --review.")
    if args.no_youtube and args.yt_transcript:
        raise SystemExit("--yt-transcript cannot be combined with --no-youtube.")
    if args.max_iter is not None and args.max_iter < 1:
        raise SystemExit("--max-iter must be >= 1.")

    if args.list is not None:
        run_dirs = find_run_dirs(Path(args.list))
        summaries = [collect_run_summary(run_dir) for run_dir in run_dirs]
        if args.filter_text:
            needle = args.filter_text.strip().lower()
            if needle:
                summaries = [summary for summary in summaries if needle in summary.query_id.lower()]
        print(format_run_list(summaries))
        return 0
    if args.review:
        review_path = Path(args.review)
        if review_path.is_file():
            if review_path.suffix.lower() != ".jsonl":
                raise SystemExit("--review supports .jsonl files only when pointing to a file path.")
            if args.format:
                raise SystemExit("--format is not supported when reviewing a JSONL file.")
            if args.review_full:
                print(render_jsonl_review_full(review_path))
            else:
                print(render_jsonl_review(review_path))
            return 0
        run_dirs = find_run_dirs(review_path)
        if not run_dirs:
            raise SystemExit("No runs found to review.")
        if len(run_dirs) > 1:
            choices = "\n".join(f"- {run_dir.name}" for run_dir in run_dirs)
            raise SystemExit(f"Multiple runs found. Pick one:\n{choices}")
        if args.review_full and args.format == "json":
            raise SystemExit("--review-full is not supported with --format json.")
        if args.review_full:
            print(render_review_full(run_dirs[0]))
        elif (args.format or "text") == "json":
            print(render_review_json(run_dirs[0]))
        else:
            print(render_review(run_dirs[0]))
        return 0

    if not args.output:
        raise SystemExit("Missing --output. Required with --input/--query.")

    api_key = os.getenv("TAVILY_API_KEY")
    if not api_key:
        raise SystemExit("Missing environment variable: TAVILY_API_KEY")

    tavily = TavilyClient(api_key=api_key)
    lang_pref = normalize_lang(args.lang)
    openalex_enabled = bool(args.openalex or args.download_pdf)
    if args.no_openalex:
        openalex_enabled = False
    youtube_enabled = bool(args.youtube or args.yt_transcript)
    if args.no_youtube:
        youtube_enabled = False
    jobs = prepare_jobs(
        input_path=Path(args.input) if args.input else None,
        query=args.query,
        output_root=Path(args.output),
        lang_pref=lang_pref,
        openalex_enabled=openalex_enabled,
        openalex_max_results=args.oa_max_results,
        youtube_enabled=youtube_enabled,
        youtube_max_results=args.yt_max_results,
        youtube_transcript=args.yt_transcript,
        youtube_order=args.yt_order,
        days=args.days,
        max_results=args.max_results,
        download_pdf=args.download_pdf,
        arxiv_source=args.arxiv_src,
        update_run=args.update_run,
        citations_enabled=not args.no_citations,
        agentic_search=args.agentic_search,
        agentic_model=args.model,
        agentic_max_iter=args.max_iter,
    )
    for job in jobs:
        if args.agentic_search:
            run_job_agentic(
                job,
                tavily,
                model_name=args.model,
                max_iter=args.max_iter,
                stdout=not args.no_stdout_log,
            )
        else:
            run_job(job, tavily, stdout=not args.no_stdout_log)
    return 0
