from __future__ import annotations

import argparse
import datetime as dt
import subprocess
import sys
from pathlib import Path


def _resolve_run_dir(run: str) -> Path:
    path = Path(run).expanduser()
    if not path.is_absolute():
        path = Path.cwd() / path
    return path.resolve()


def _next_update_path(run_dir: Path) -> Path:
    notes_dir = run_dir / "report_notes"
    notes_dir.mkdir(parents=True, exist_ok=True)
    stamp = dt.datetime.now().strftime("%Y%m%d")
    base = notes_dir / f"update_request_{stamp}.txt"
    if not base.exists():
        return base
    idx = 1
    while True:
        candidate = notes_dir / f"update_request_{stamp}_{idx}.txt"
        if not candidate.exists():
            return candidate
        idx += 1


def _build_update_prompt(base_report: str, update: str, second: str | None) -> str:
    lines = [f"Base report: {base_report}", "", "Update request:"]
    if update:
        lines.append(update.strip())
    if second:
        lines.append("")
        lines.append("Second prompt:")
        lines.append(second.strip())
    return "\n".join(lines).strip() + "\n"


def _default_output(run_dir: Path) -> Path:
    return run_dir / "report_full.html"


def main() -> int:
    parser = argparse.ArgumentParser(
        description="FederHav (Federlicht platform): profile-guided report revision and update runner."
    )
    parser.add_argument("--run", required=True, help="Run directory (site/runs/...)")
    parser.add_argument("--base-report", required=True, help="Base report path (relative or absolute)")
    parser.add_argument("--update", required=True, help="Update request / revision instructions")
    parser.add_argument("--second", help="Optional second prompt to append")
    parser.add_argument("--output", help="Output report path (default: report_full.html in run)")
    parser.add_argument("--model", help="Model name (e.g., gpt-4o-mini)")
    parser.add_argument("--depth", help="Report depth (brief|standard|deep|extreme)")
    parser.add_argument("--lang", default="ko", help="Report language (default: ko)")
    parser.add_argument("--template", help="Template name/path override")
    parser.add_argument("--agent-profile", default="federhav", help="Agent profile to apply")
    args = parser.parse_args()

    run_dir = _resolve_run_dir(args.run)
    if not run_dir.exists():
        raise SystemExit(f"Run directory not found: {run_dir}")

    base_path = Path(args.base_report).expanduser()
    if not base_path.is_absolute():
        base_path = (run_dir / base_path).resolve()
    if not base_path.exists():
        raise SystemExit(f"Base report not found: {base_path}")

    update_path = _next_update_path(run_dir)
    rel_base = f"./{base_path.relative_to(run_dir).as_posix()}"
    update_text = _build_update_prompt(rel_base, args.update, args.second)
    update_path.write_text(update_text, encoding="utf-8")

    output_path = Path(args.output).expanduser() if args.output else _default_output(run_dir)
    if not output_path.is_absolute():
        output_path = (run_dir / output_path).resolve()

    cmd = [
        sys.executable,
        "-m",
        "federlicht.report",
        "--run",
        str(run_dir),
        "--output",
        str(output_path),
        "--prompt-file",
        str(update_path),
        "--lang",
        args.lang,
    ]
    if args.depth:
        cmd.extend(["--depth", args.depth])
    if args.model:
        cmd.extend(["--model", args.model])
    if args.template:
        cmd.extend(["--template", args.template])
    if args.agent_profile:
        cmd.extend(["--agent-profile", args.agent_profile])

    print(f"[federhav] update prompt: {update_path}")
    print(f"[federhav] output target: {output_path}")
    print(f"[federhav] running: {' '.join(cmd)}")
    return subprocess.call(cmd)


if __name__ == "__main__":
    raise SystemExit(main())
