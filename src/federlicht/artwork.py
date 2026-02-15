from __future__ import annotations

import os
import re
import shutil
import subprocess
import tempfile
from pathlib import Path


_FLOW_DIRECTIONS = {"LR", "RL", "TB", "BT"}
_DEFAULT_D2_OUTPUT = "report_assets/artwork/d2_diagram.svg"
_DEFAULT_DIAGRAMS_OUTPUT = "report_assets/artwork/diagrams_architecture.svg"
_MERMAID_FORMATS = {"svg", "png", "pdf"}
_DOT_CANDIDATES = (
    Path("C:/Program Files/Graphviz/bin/dot.exe"),
    Path("C:/Program Files (x86)/Graphviz/bin/dot.exe"),
)
_D2_CANDIDATES = (
    Path("C:/Program Files/D2/d2.exe"),
    Path("C:/Program Files (x86)/D2/d2.exe"),
)


def _slugify(value: str) -> str:
    token = re.sub(r"[^A-Za-z0-9]+", "_", str(value or "").strip())
    token = token.strip("_").lower()
    return token or "node"


def _split_lines(spec: str) -> list[str]:
    parts = re.split(r"[\n;]+", str(spec or ""))
    return [part.strip() for part in parts if part and part.strip()]


def _escape_mermaid(text: str) -> str:
    return str(text or "").replace('"', '\\"')


def list_artwork_capabilities() -> str:
    d2_ok = bool(_resolve_d2_command())
    mmdc_ok = bool(_resolve_mmdc_command())
    diagrams_ok = _has_diagrams_package()
    dot_ok = _resolve_dot_command() is not None
    lines = [
        "Artwork toolkit capabilities:",
        "- mermaid_flowchart: process/logic flow diagram from node/edge specs.",
        "- mermaid_timeline: chronology/timeline diagram from date|event specs.",
        f"- mermaid_render: {'available' if mmdc_ok else 'missing Mermaid CLI(mmdc)'} (renders SVG/PNG/PDF artifact).",
        f"- d2_render: {'available' if d2_ok else 'missing d2 CLI'} (architecture diagram SVG rendering).",
        f"- diagrams_render: {'available' if diagrams_ok and dot_ok else 'missing diagrams package or graphviz(dot)'} "
        "(Python diagrams fallback for architecture SVG).",
        "",
        "Selection guide:",
        "- Prefer Mermaid for simple process/timeline visuals in Markdown/HTML.",
        "- Prefer D2 for dense architecture/topology.",
        "- Use diagrams_render when provider/icon-style architecture is preferred in Python workflow.",
        "",
        "Output rule: return only diagram snippets/artifact links with concise captions.",
    ]
    if not mmdc_ok:
        lines.append("Install Mermaid CLI: npm i -g @mermaid-js/mermaid-cli")
    if not d2_ok:
        lines.append("Install d2: https://d2lang.com/tour/install (or set D2_BIN to d2.exe path)")
    if not diagrams_ok:
        lines.append("Install diagrams package: python -m pip install diagrams graphviz")
    if not dot_ok:
        lines.append("Install Graphviz CLI and expose dot (or set GRAPHVIZ_DOT to dot.exe path)")
    return "\n".join(lines)


def build_mermaid_flowchart(
    nodes_spec: str,
    edges_spec: str,
    *,
    direction: str = "LR",
    title: str = "",
) -> str:
    node_map: dict[str, str] = {}
    node_order: list[str] = []
    lines = _split_lines(nodes_spec)
    for idx, raw in enumerate(lines, start=1):
        label = raw
        node_id = ""
        for marker in ("|", ":", "="):
            if marker in raw:
                left, right = raw.split(marker, 1)
                if left.strip() and right.strip():
                    node_id = _slugify(left)
                    label = right.strip()
                    break
        if not node_id:
            node_id = _slugify(raw)
            if node_id in node_map:
                node_id = f"{node_id}_{idx}"
        if node_id not in node_map:
            node_map[node_id] = label.strip() or node_id
            node_order.append(node_id)

    edge_lines = _split_lines(edges_spec)
    parsed_edges: list[tuple[str, str, str]] = []
    edge_re = re.compile(r"^\s*([^>\-\s][^>]*)\s*->\s*([^|:]+?)(?:\s*[|:]\s*(.+))?$")
    for raw in edge_lines:
        match = edge_re.match(raw)
        if not match:
            continue
        src = _slugify(match.group(1))
        dst = _slugify(match.group(2))
        rel_label = str(match.group(3) or "").strip()
        if src not in node_map:
            node_map[src] = src.replace("_", " ").title()
            node_order.append(src)
        if dst not in node_map:
            node_map[dst] = dst.replace("_", " ").title()
            node_order.append(dst)
        parsed_edges.append((src, dst, rel_label))

    flow_dir = str(direction or "LR").upper().strip()
    if flow_dir not in _FLOW_DIRECTIONS:
        flow_dir = "LR"
    diagram: list[str] = [f"flowchart {flow_dir}"]
    for node_id in node_order:
        diagram.append(f'    {node_id}["{_escape_mermaid(node_map[node_id])}"]')
    for src, dst, rel_label in parsed_edges:
        if rel_label:
            diagram.append(f"    {src} -->|{_escape_mermaid(rel_label)}| {dst}")
        else:
            diagram.append(f"    {src} --> {dst}")
    if len(diagram) == 1:
        diagram.append('    a["Placeholder"]')
    snippet = [
        "```mermaid",
        *diagram,
        "```",
    ]
    if title.strip():
        snippet.append(f"*Figure: {title.strip()}*")
    return "\n".join(snippet)


def build_mermaid_timeline(events_spec: str, *, title: str = "") -> str:
    rows = _split_lines(events_spec)
    timeline_lines = ["timeline"]
    if title.strip():
        timeline_lines.append(f"    title {_escape_mermaid(title.strip())}")
    if not rows:
        timeline_lines.append("    1 : Placeholder event")
    for idx, row in enumerate(rows, start=1):
        date_token = f"Step {idx}"
        event_text = row
        for marker in ("|", ":", "="):
            if marker in row:
                left, right = row.split(marker, 1)
                if left.strip() and right.strip():
                    date_token = left.strip()
                    event_text = right.strip()
                    break
        timeline_lines.append(f"    {_escape_mermaid(date_token)} : {_escape_mermaid(event_text)}")
    return "\n".join(["```mermaid", *timeline_lines, "```"])


def _resolve_under_run(run_dir: Path, rel_path: str) -> Path:
    candidate = (run_dir / str(rel_path or "").replace("\\", "/")).resolve()
    run_root = run_dir.resolve()
    try:
        candidate.relative_to(run_root)
    except Exception as exc:
        raise ValueError("output_rel_path must stay under the run directory") from exc
    return candidate


def _resolve_mmdc_command() -> list[str]:
    mmdc = shutil.which("mmdc")
    if mmdc:
        return [mmdc]
    local_bin_dir = Path.cwd() / "node_modules" / ".bin"
    for filename in ("mmdc.cmd", "mmdc"):
        local_mmdc = local_bin_dir / filename
        if local_mmdc.exists():
            return [str(local_mmdc)]
    npx = shutil.which("npx")
    if npx:
        try:
            probe = subprocess.run(
                [npx, "--no-install", "mmdc", "--version"],
                capture_output=True,
                text=True,
                timeout=4,
                check=False,
            )
            if probe.returncode == 0:
                return [npx, "--no-install", "mmdc"]
        except Exception:
            pass
    return []


def _resolve_d2_command() -> list[str]:
    env_bin = Path(str(os.getenv("D2_BIN", "")).strip())
    if str(env_bin) and env_bin.exists() and env_bin.is_file():
        return [str(env_bin)]
    d2 = shutil.which("d2")
    if d2:
        return [d2]
    for candidate in _D2_CANDIDATES:
        if candidate.exists() and candidate.is_file():
            return [str(candidate)]
    return []


def _resolve_dot_command() -> str | None:
    env_bin = str(os.getenv("GRAPHVIZ_DOT", "")).strip()
    if env_bin and Path(env_bin).exists() and Path(env_bin).is_file():
        return env_bin
    dot = shutil.which("dot")
    if dot:
        return dot
    for candidate in _DOT_CANDIDATES:
        if candidate.exists() and candidate.is_file():
            return str(candidate)
    return None


def _has_diagrams_package() -> bool:
    try:
        import diagrams  # noqa: F401
    except Exception:
        return False
    return True


def _ensure_graphviz_runtime(dot_bin: str) -> None:
    dot_path = Path(dot_bin)
    os.environ["GRAPHVIZ_DOT"] = str(dot_path)
    bin_dir = str(dot_path.parent)
    current = os.environ.get("PATH", "")
    parts = current.split(os.pathsep) if current else []
    if bin_dir not in parts:
        os.environ["PATH"] = bin_dir + os.pathsep + current


def _normalize_mermaid_format(value: str) -> str:
    token = str(value or "").strip().lower().lstrip(".")
    return token if token in _MERMAID_FORMATS else "svg"


def _safe_int(value: object, default: int = 0) -> int:
    try:
        return int(str(value).strip())
    except Exception:
        return default


def _safe_float(value: object, default: float = 1.0) -> float:
    try:
        return float(str(value).strip())
    except Exception:
        return default


def render_d2_svg(
    run_dir: Path,
    d2_source: str,
    *,
    output_rel_path: str = _DEFAULT_D2_OUTPUT,
    theme: str = "200",
    layout: str = "dagre",
) -> dict[str, str]:
    d2_command = _resolve_d2_command()
    if not d2_command:
        return {
            "ok": "false",
            "error": "d2_cli_missing",
            "message": "D2 CLI is not installed. Install https://d2lang.com/tour/install or set D2_BIN.",
        }
    if not str(d2_source or "").strip():
        return {"ok": "false", "error": "empty_source", "message": "d2_source is empty"}

    out_path = _resolve_under_run(run_dir, output_rel_path or _DEFAULT_D2_OUTPUT)
    if out_path.suffix.lower() != ".svg":
        out_path = out_path.with_suffix(".svg")
    out_path.parent.mkdir(parents=True, exist_ok=True)

    temp_file: Path | None = None
    try:
        with tempfile.NamedTemporaryFile("w", encoding="utf-8", suffix=".d2", delete=False) as handle:
            handle.write(d2_source)
            handle.flush()
            temp_file = Path(handle.name)
        cmd = [
            *d2_command,
            "--theme",
            str(theme or "200"),
            "--layout",
            str(layout or "dagre"),
            str(temp_file),
            str(out_path),
        ]
        proc = subprocess.run(cmd, capture_output=True, text=True, check=False)
        if proc.returncode != 0:
            detail = (proc.stderr or proc.stdout or "d2 render failed").strip()
            return {
                "ok": "false",
                "error": "d2_render_failed",
                "message": detail[:400],
            }
    finally:
        if temp_file and temp_file.exists():
            try:
                temp_file.unlink()
            except Exception:
                pass

    rel_out = f"./{out_path.relative_to(run_dir).as_posix()}"
    return {
        "ok": "true",
        "path": rel_out,
        "markdown": f"![Diagram]({rel_out})",
    }


def render_diagrams_architecture(
    run_dir: Path,
    nodes_spec: str,
    edges_spec: str,
    *,
    output_rel_path: str = _DEFAULT_DIAGRAMS_OUTPUT,
    direction: str = "LR",
    title: str = "",
) -> dict[str, str]:
    if not _has_diagrams_package():
        return {
            "ok": "false",
            "error": "diagrams_missing",
            "message": "Python package 'diagrams' is missing. Install: python -m pip install diagrams graphviz",
        }
    dot_bin = _resolve_dot_command()
    if not dot_bin:
        return {
            "ok": "false",
            "error": "graphviz_dot_missing",
            "message": "Graphviz dot executable is missing. Install Graphviz or set GRAPHVIZ_DOT.",
        }
    _ensure_graphviz_runtime(dot_bin)

    try:
        from diagrams import Diagram, Edge
        from diagrams.generic.blank import Blank
    except Exception as exc:
        return {
            "ok": "false",
            "error": "diagrams_import_failed",
            "message": str(exc)[:400],
        }

    out_path = _resolve_under_run(run_dir, output_rel_path or _DEFAULT_DIAGRAMS_OUTPUT)
    if out_path.suffix.lower() != ".svg":
        out_path = out_path.with_suffix(".svg")
    out_path.parent.mkdir(parents=True, exist_ok=True)
    filename_base = out_path.with_suffix("")

    node_map: dict[str, str] = {}
    node_order: list[str] = []
    for idx, raw in enumerate(_split_lines(nodes_spec), start=1):
        label = raw
        node_id = ""
        for marker in ("|", ":", "="):
            if marker in raw:
                left, right = raw.split(marker, 1)
                if left.strip() and right.strip():
                    node_id = _slugify(left)
                    label = right.strip()
                    break
        if not node_id:
            node_id = _slugify(raw)
            if node_id in node_map:
                node_id = f"{node_id}_{idx}"
        if node_id not in node_map:
            node_map[node_id] = label.strip() or node_id
            node_order.append(node_id)

    edge_re = re.compile(r"^\s*([^>\-\s][^>]*)\s*->\s*([^|:]+?)(?:\s*[|:]\s*(.+))?$")
    parsed_edges: list[tuple[str, str, str]] = []
    for raw in _split_lines(edges_spec):
        match = edge_re.match(raw)
        if not match:
            continue
        src = _slugify(match.group(1))
        dst = _slugify(match.group(2))
        rel_label = str(match.group(3) or "").strip()
        if src not in node_map:
            node_map[src] = src.replace("_", " ").title()
            node_order.append(src)
        if dst not in node_map:
            node_map[dst] = dst.replace("_", " ").title()
            node_order.append(dst)
        parsed_edges.append((src, dst, rel_label))

    if not node_order:
        node_order = ["placeholder_a", "placeholder_b"]
        node_map["placeholder_a"] = "Start"
        node_map["placeholder_b"] = "End"
        parsed_edges = [("placeholder_a", "placeholder_b", "flow")]

    graph_dir = str(direction or "LR").upper().strip()
    if graph_dir not in _FLOW_DIRECTIONS:
        graph_dir = "LR"

    try:
        with Diagram(
            title.strip() or filename_base.name,
            filename=str(filename_base),
            outformat="svg",
            direction=graph_dir,
            show=False,
        ):
            nodes = {node_id: Blank(node_map[node_id]) for node_id in node_order}
            if parsed_edges:
                for src, dst, rel_label in parsed_edges:
                    edge = Edge(label=rel_label) if rel_label else Edge()
                    nodes[src] >> edge >> nodes[dst]
    except Exception as exc:
        return {
            "ok": "false",
            "error": "diagrams_render_failed",
            "message": str(exc)[:400],
        }

    rel_out = f"./{out_path.relative_to(run_dir).as_posix()}"
    return {
        "ok": "true",
        "path": rel_out,
        "format": "svg",
        "markdown": f"![Architecture Diagram]({rel_out})",
    }


def render_mermaid_diagram(
    run_dir: Path,
    diagram_source: str,
    *,
    output_rel_path: str = "report_assets/artwork/mermaid_diagram.svg",
    output_format: str = "svg",
    theme: str = "default",
    background_color: str = "transparent",
    width: int = 0,
    height: int = 0,
    scale: float = 1.0,
) -> dict[str, str]:
    command_prefix = _resolve_mmdc_command()
    if not command_prefix:
        return {
            "ok": "false",
            "error": "mmdc_missing",
            "message": "Mermaid CLI(mmdc)가 없습니다. npm i -g @mermaid-js/mermaid-cli 또는 npm i -D @mermaid-js/mermaid-cli",
        }
    source_text = str(diagram_source or "").strip()
    if not source_text:
        return {"ok": "false", "error": "empty_source", "message": "diagram_source is empty"}
    fmt = _normalize_mermaid_format(output_format)
    out_path = _resolve_under_run(run_dir, output_rel_path or "report_assets/artwork/mermaid_diagram.svg")
    if out_path.suffix.lower() != f".{fmt}":
        out_path = out_path.with_suffix(f".{fmt}")
    out_path.parent.mkdir(parents=True, exist_ok=True)
    width_px = max(0, _safe_int(width, 0))
    height_px = max(0, _safe_int(height, 0))
    scale_value = _safe_float(scale, 1.0)
    if scale_value <= 0:
        scale_value = 1.0
    temp_file: Path | None = None
    try:
        with tempfile.NamedTemporaryFile("w", encoding="utf-8", suffix=".mmd", delete=False) as handle:
            handle.write(source_text)
            handle.flush()
            temp_file = Path(handle.name)
        cmd = [
            *command_prefix,
            "-i",
            str(temp_file),
            "-o",
            str(out_path),
            "-t",
            str(theme or "default"),
            "-b",
            str(background_color or "transparent"),
            "-s",
            str(scale_value),
            "-q",
        ]
        if width_px > 0:
            cmd.extend(["-w", str(width_px)])
        if height_px > 0:
            cmd.extend(["-H", str(height_px)])
        proc = subprocess.run(cmd, capture_output=True, text=True, check=False)
        if proc.returncode != 0:
            detail = (proc.stderr or proc.stdout or "mmdc render failed").strip()
            return {
                "ok": "false",
                "error": "mmdc_render_failed",
                "message": detail[:400],
            }
    finally:
        if temp_file and temp_file.exists():
            try:
                temp_file.unlink()
            except Exception:
                pass
    rel_out = f"./{out_path.relative_to(run_dir).as_posix()}"
    markdown = f"![Diagram]({rel_out})" if fmt in {"svg", "png"} else f"[Diagram PDF]({rel_out})"
    return {
        "ok": "true",
        "path": rel_out,
        "format": fmt,
        "markdown": markdown,
    }
