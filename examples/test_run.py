#!/usr/bin/env python3
# -*- coding: utf-8 -*-

"""
Run example instruction files in ./examples/instructions.

Usage:
  python examples/test_run.py --output ./runs
  python examples/test_run.py --only basic --only iccv25 --output ./runs
  python examples/test_run.py --skip-download-pdf --output ./runs
  python examples/test_run.py --no-openalex --output ./runs
  python examples/test_run.py --no-youtube --output ./runs
  python examples/test_run.py --dry-run
"""

from __future__ import annotations

import argparse
import subprocess
import sys
from pathlib import Path


EXAMPLES = [
    {
        "name": "basic",
        "file": "20260104.txt",
        "args": ["--set-id", "basic"],
    },
    {
        "name": "basic-oa",
        "file": "20260104.txt",
        "args": ["--set-id", "basic-oa", "--download-pdf", "--oa-max-results", "5"],
    },
    {
        "name": "arxiv",
        "file": "20260105.txt",
        "args": ["--set-id", "arxiv", "--download-pdf"],
    },
    {
        "name": "mixed",
        "file": "20260106.txt",
        "args": ["--set-id", "mixed", "--max-results", "5"],
    },
    {
        "name": "iccv25",
        "file": "20251015.txt",
        "args": ["--set-id", "iccv25", "--download-pdf", "--days", "180", "--oa-max-results", "5"],
    },
    {
        "name": "ai-trends",
        "file": "20260107.txt",
        "args": ["--set-id", "ai-trends", "--days", "30", "--max-results", "5", "--oa-max-results", "2", "--download-pdf", "--lang", "en"],
    },
    {
        "name": "qc-youtube",
        "file": "20260108.txt",
        "args": [
            "--set-id",
            "qc-youtube",
            "--max-results",
            "5",
            "--yt-max-results",
            "5",
            "--youtube",
            "--yt-transcript",
            "--yt-order",
            "date",
        ],
    },
    {
        "name": "sectioned",
        "file": "20260109.txt",
        "args": ["--set-id", "sectioned", "--max-results", "5", "--youtube"],
    },
    {
        "name": "qc-oled",
        "file": "20260110.txt",
        "args": ["--set-id", "qc-oled", "--download-pdf", "--days", "365", "--max-results", "5", "--oa-max-results", "5", "--lang", "en"],
    },
]


def parse_args() -> argparse.Namespace:
    ap = argparse.ArgumentParser(description="Run example instruction files.")
    ap.add_argument("--output", default="runs", help="Output root folder (default: runs)")
    ap.add_argument("--python", default=sys.executable, help="Python executable (default: current)")
    ap.add_argument("--only", action="append", help="Run only the named example(s)")
    ap.add_argument("--skip-download-pdf", action="store_true", help="Skip --download-pdf steps")
    ap.add_argument("--no-openalex", action="store_true", help="Disable OpenAlex even if examples set it")
    ap.add_argument("--no-youtube", action="store_true", help="Disable YouTube even if examples set it")
    ap.add_argument("--dry-run", action="store_true", help="Print commands without running")
    return ap.parse_args()


def filter_args(args: list[str], skip_download_pdf: bool, no_youtube: bool) -> list[str]:
    if not skip_download_pdf and not no_youtube:
        return list(args)
    out: list[str] = []
    skip_next = False
    for token in args:
        if skip_next:
            skip_next = False
            continue
        if skip_download_pdf:
            if token == "--download-pdf":
                continue
            if token == "--oa-max-results":
                skip_next = True
                continue
        if no_youtube:
            if token in {"--youtube", "--yt-transcript"}:
                continue
            if token in {"--yt-max-results", "--yt-order"}:
                skip_next = True
                continue
        out.append(token)
    return out


def run() -> int:
    args = parse_args()
    base = Path(__file__).resolve().parent
    instr_dir = base / "instructions"
    out_root = Path(args.output)

    selected = {name for name in (args.only or [])}
    examples = EXAMPLES if not selected else [ex for ex in EXAMPLES if ex["name"] in selected]
    if not examples:
        print("No matching examples found.")
        return 1

    for ex in examples:
        instr = instr_dir / ex["file"]
        cmd = [
            args.python,
            "-m",
            "feather",
            "--input",
            str(instr),
            "--output",
            str(out_root),
        ]
        cmd.extend(filter_args(ex["args"], args.skip_download_pdf, args.no_youtube))
        if args.no_openalex:
            cmd.append("--no-openalex")
        if args.no_youtube:
            cmd.append("--no-youtube")
        print("$ " + " ".join(cmd))
        if not args.dry_run:
            subprocess.run(cmd, check=True)

    return 0


if __name__ == "__main__":
    raise SystemExit(run())
