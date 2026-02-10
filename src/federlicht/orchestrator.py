
from __future__ import annotations

from dataclasses import dataclass
from pathlib import Path
from typing import Callable, Optional
import datetime as dt
import hashlib
import json
import re
import sys

from federlicht import tools as feder_tools

from . import prompts, workflow_stages
from .agent_runtime import AgentRuntime
from .agents import AgentRunner
from .verification_tools import parse_verification_requests
from .workflow_trace import write_workflow_summary


STAGE_INFO = {
    "scout": "Map the archive, list relevant sources, and propose a reading plan.",
    "clarifier": "Ask clarification questions when needed.",
    "template_adjust": "Adjust required sections using the template rules.",
    "plan": "Draft a concise report plan based on scout notes.",
    "web": "Generate web queries and optionally run web research.",
    "evidence": "Read sources and extract evidence with citations.",
    "plan_check": "Update the plan after evidence is collected.",
    "writer": "Draft the report body using evidence and template guidance.",
    "quality": "Critique, revise, evaluate, and finalize the report.",
}
STAGE_ORDER = [
    "scout",
    "clarifier",
    "template_adjust",
    "plan",
    "web",
    "evidence",
    "plan_check",
    "writer",
    "quality",
]


@dataclass
class PipelineContext:
    args: object
    output_format: str
    check_model: str


@dataclass
class PipelineResult:
    report: str
    scout_notes: str
    plan_text: str
    plan_context: str
    evidence_notes: str
    align_draft: Optional[str]
    align_final: Optional[str]
    align_scout: Optional[str]
    align_plan: Optional[str]
    align_evidence: Optional[str]
    template_spec: object
    template_guidance_text: str
    template_adjustment_path: Optional[Path]
    required_sections: list[str]
    report_prompt: Optional[str]
    clarification_questions: Optional[str]
    clarification_answers: Optional[str]
    output_format: str
    language: str
    run_dir: Path
    archive_dir: Path
    notes_dir: Path
    supporting_dir: Optional[Path]
    supporting_summary: Optional[str]
    source_triage_text: str
    claim_map_text: str
    gap_text: str
    context_lines: list[str]
    depth: str
    style_hint: str
    overview_path: Optional[Path]
    index_file: Optional[Path]
    instruction_file: Optional[Path]
    quality_model: str
    query_id: str
    workflow_summary: list[str]
    workflow_path: Optional[Path]


@dataclass
class PipelineState:
    run_dir: Path
    archive_dir: Path
    notes_dir: Path
    supporting_dir: Optional[Path]
    output_format: str
    language: str
    report_prompt: Optional[str]
    template_spec: object
    template_guidance_text: str
    required_sections: list[str]
    context_lines: list[str]
    source_triage_text: str
    scout_notes: str
    plan_text: str
    plan_context: str
    evidence_notes: str
    claim_map_text: str
    gap_text: str
    supporting_summary: Optional[str]
    clarification_questions: Optional[str]
    clarification_answers: Optional[str]
    align_scout: Optional[str]
    align_plan: Optional[str]
    align_evidence: Optional[str]
    depth: str
    style_hint: str
    query_id: str
    report: str = ""


class ReportOrchestrator:
    def __init__(
        self,
        context: PipelineContext,
        helpers: object,
        agent_overrides: dict,
        create_deep_agent,
    ) -> None:
        self._context = context
        self._helpers = helpers
        self._agent_overrides = agent_overrides
        self._create_deep_agent = create_deep_agent
        self._runner = AgentRunner(context.args, helpers.extract_agent_text, helpers.print_progress)

    def run(self, state: Optional[PipelineState] = None, allow_partial: bool = False) -> PipelineResult:
        args = self._context.args
        helpers = self._helpers
        output_format = self._context.output_format
        check_model = self._context.check_model

        archive_dir, run_dir, query_id = helpers.resolve_archive(Path(args.run))
        archive_dir = archive_dir.resolve()
        run_dir = run_dir.resolve()
        index_file = helpers.find_index_file(archive_dir, query_id)
        instruction_file = helpers.find_instruction_file(run_dir)
        overview_path = helpers.write_run_overview(run_dir, instruction_file, index_file)
        baseline_report = helpers.find_baseline_report(run_dir)
        notes_dir = helpers.resolve_notes_dir(run_dir, args.notes_dir)
        configured_tool_char_limit = int(getattr(args, "max_tool_chars", 0) or 0)
        tool_budget_source = "cli" if configured_tool_char_limit > 0 else "auto"
        if configured_tool_char_limit > 0:
            tool_char_limit = configured_tool_char_limit
        else:
            # Default conservatively to avoid silent context blowups in scout/evidence.
            lang_for_budget = helpers.normalize_lang(args.lang)
            char_ratio = 2 if helpers.is_korean_language(lang_for_budget) else 4
            token_cap = int(
                getattr(args, "max_input_tokens", 0)
                or getattr(helpers, "DEFAULT_MAX_INPUT_TOKENS", 0)
                or 128000
            )
            tool_char_limit = max(16000, min(48000, int(token_cap * char_ratio * 0.14)))
        fs_read_cap = max(1500, min(4000, max(2000, tool_char_limit // 8)))
        fs_total_cap = max(8000, min(tool_char_limit, int(tool_char_limit * 0.35)))
        # Keep run_dir as backend root so built-in file tools can resolve archive paths reliably.
        # Bound filesystem-tool reads/list payloads in the backend to prevent context blowups.
        backend = helpers.SafeFilesystemBackend(
            root_dir=run_dir,
            max_read_chars=fs_read_cap,
            max_total_chars=fs_total_cap,
        )
        agent_runtime = AgentRuntime(
            args=args,
            helpers=helpers,
            overrides=self._agent_overrides,
            create_deep_agent=self._create_deep_agent,
            backend=backend,
        )
        cache_dir = notes_dir / "cache"
        cache_dir.mkdir(parents=True, exist_ok=True)
        cache_schema_version = "v4"
        cache_enabled = bool(getattr(args, "cache", True))
        cache_scope_signature = ""
        supporting_dir: Optional[Path] = None
        supporting_summary: Optional[str] = None
        alignment_max_chars = min(args.quality_max_chars, 8000)
        pack_limit = min(args.quality_max_chars, 6000)
        report_prompt_limit = 4000 if pack_limit <= 0 else min(4000, pack_limit)
        triage_limit = 3000 if pack_limit <= 0 else min(3000, max(1500, pack_limit // 2))
        guidance_limit = triage_limit
        supporting_limit = triage_limit
        alignment_limit = 3000 if pack_limit <= 0 else min(3000, pack_limit)
        clarification_limit = alignment_limit
        triage_line_limit = 80
        guidance_line_limit = 80
        supporting_line_limit = 120
        context_limit = 2400 if pack_limit <= 0 else min(2400, max(1200, pack_limit // 2))
        context_line_limit = 60

        def pack_text(text: str) -> str:
            return helpers.truncate_text_middle(text, pack_limit)

        def cache_key(*parts: object) -> str:
            hasher = hashlib.sha256()
            for part in parts:
                if part is None:
                    text = ""
                elif isinstance(part, str):
                    text = part
                else:
                    text = json.dumps(part, ensure_ascii=True, sort_keys=True)
                hasher.update(text.encode("utf-8", errors="ignore"))
                hasher.update(b"\0")
            return hasher.hexdigest()

        def cache_path(stage: str, key: str) -> Path:
            safe_stage = re.sub(r"[^a-z0-9_-]+", "_", stage.lower())
            return cache_dir / f"{safe_stage}_{key}.json"

        def read_cache(stage: str, key: str) -> Optional[str]:
            path = cache_path(stage, key)
            if not path.exists():
                return None
            try:
                payload = json.loads(path.read_text(encoding="utf-8"))
            except Exception:
                return None
            content = payload.get("content")
            return content if isinstance(content, str) else None

        def write_cache(stage: str, key: str, content: str, meta: Optional[dict] = None) -> None:
            payload = {
                "content": content,
                "meta": meta or {},
                "created_at": dt.datetime.now().isoformat(),
            }
            cache_path(stage, key).write_text(json.dumps(payload, ensure_ascii=True, indent=2), encoding="utf-8")

        def get_cached_output(
            stage: str,
            model: str,
            prompt: str,
            payload: str,
            runner: Callable[[], str],
        ) -> tuple[str, bool]:
            if not cache_enabled:
                return runner(), False
            key = cache_key(
                cache_schema_version,
                stage,
                model,
                prompt,
                payload,
                cache_scope_signature,
                tool_char_limit,
                tool_budget_source,
                str(run_dir),
                str(notes_dir),
            )
            cached = read_cache(stage, key)
            if cached is not None:
                return cached, True
            result = runner()
            meta = {
                "stage": stage,
                "model": model,
                "prompt_hash": cache_key(prompt),
                "input_hash": cache_key(payload),
            }
            write_cache(stage, key, result, meta)
            return result, False

        def sanitize_console_text(text: str) -> str:
            sanitizer = getattr(self._runner, "_sanitize_console_text", None)
            if callable(sanitizer):
                return sanitizer(text)
            return text

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

        def normalize_archive_pattern(raw_pattern: str) -> str:
            cleaned = raw_pattern.strip().replace("\\", "/")
            for prefix in ("./archive/", "archive/"):
                if cleaned.startswith(prefix):
                    cleaned = cleaned[len(prefix) :]
            if cleaned in {"", "archive", ".", "/"}:
                return "*"
            return cleaned.replace("/", "\\")

        def list_archive_files(pattern: Optional[str] = None, max_files: Optional[int] = None) -> str:
            """List archive files (relative paths + size) as JSON."""
            files = []
            warning: Optional[str] = None
            normalized = normalize_archive_pattern(pattern) if pattern else "*"
            try:
                paths = archive_dir.rglob(normalized)
            except ValueError as exc:
                warning = f"Invalid pattern '{pattern}': {exc}. Falling back to '*'"
                paths = archive_dir.rglob("*")
            for path in sorted(paths):
                if path.is_file():
                    rel = path.relative_to(run_dir).as_posix()
                    files.append({"path": rel, "bytes": path.stat().st_size})
            if pattern and not files:
                warning = f"No matches for pattern '{pattern}'. Falling back to '*'"
                for path in sorted(archive_dir.rglob("*")):
                    if path.is_file():
                        rel = path.relative_to(run_dir).as_posix()
                        files.append({"path": rel, "bytes": path.stat().st_size})
            limit = args.max_files if max_files is None else max_files
            payload = {"total_files": len(files), "files": files[:limit]}
            if warning:
                payload["warning"] = warning
            return json.dumps(payload, indent=2, ensure_ascii=True)

        def list_supporting_files(pattern: Optional[str] = None, max_files: Optional[int] = None) -> str:
            """List supporting files (relative paths + size) as JSON."""
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
            start = max(0, start)
            if start == 0 and max_chars > 0:
                with path.open("r", encoding="utf-8", errors="replace") as handle:
                    return handle.read(max_chars)
            text = path.read_text(encoding="utf-8", errors="replace")
            if max_chars <= 0:
                return text[start:]
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

        tool_chars_used = 0
        reducer_chunk_chars = 3000
        reducer_chunk_overlap = 120
        reducer_max_chunk_summaries = 8
        tool_cache_dir = notes_dir / "tool_cache"
        tool_cache_dir.mkdir(parents=True, exist_ok=True)
        reducer_runner: Optional[Callable[[str, str, int], str]] = None

        def clean_reducer_text(text: str) -> str:
            if not text:
                return ""
            lines = [line for line in text.splitlines() if line.strip().lower() != "[reducer]"]
            cleaned = "\n".join(lines).strip()
            return cleaned or text.strip()

        def split_into_chunks(text: str, chunk_size: int, overlap: int) -> list[str]:
            if chunk_size <= 0 or not text:
                return [text]
            chunks: list[str] = []
            start = 0
            size = max(1, chunk_size)
            overlap = max(0, overlap)
            while start < len(text):
                end = min(len(text), start + size)
                chunk = text[start:end]
                if chunk.strip():
                    chunks.append(chunk)
                if end >= len(text):
                    break
                start = max(0, end - overlap)
            return chunks

        def reduce_text(
            raw_text: str,
            source_label: str,
            max_chars: int,
        ) -> str:
            if not raw_text:
                return raw_text
            if not reducer_runner:
                return helpers.truncate_text_middle(raw_text, max_chars)
            chunks = split_into_chunks(raw_text, reducer_chunk_chars, reducer_chunk_overlap)
            if len(chunks) > reducer_max_chunk_summaries:
                chunks = chunks[:reducer_max_chunk_summaries]
            summaries: list[str] = []
            total = len(chunks)
            per_chunk_target = max(300, max_chars // max(1, total))
            for idx, chunk in enumerate(chunks, start=1):
                chunk_file = f"chunk_{idx:03d}.txt"
                header = f"CHUNK {idx}/{total} [{chunk_file}] ({source_label})"
                prompt = "\n".join([header, chunk])
                summaries.append(clean_reducer_text(reducer_runner(prompt, source_label, per_chunk_target)))
            if len(summaries) == 1:
                summary = summaries[0]
            else:
                joined = "\n".join(summaries)
                summary = clean_reducer_text(
                    reducer_runner(
                    "\n".join(
                        [
                            f"CHUNK_SUMMARIES ({source_label})",
                            joined,
                            f"Target max chars: {max_chars}",
                        ]
                    ),
                    source_label,
                    max_chars,
                )
                )
            return helpers.truncate_text_middle(summary, max_chars)

        def apply_tool_budget(payload: str, raw_text: str, source_label: str) -> str:
            nonlocal tool_chars_used
            if tool_char_limit <= 0:
                return payload
            remaining = tool_char_limit - tool_chars_used
            if remaining <= 0:
                return (
                    "[error] Tool output budget exhausted. "
                    "Increase --max-tool-chars or reduce tool reads."
                )
            if len(payload) <= remaining:
                tool_chars_used += len(payload)
                return payload
            note = "\n\n[truncated: tool output budget reached]"
            if remaining > len(note) + 200:
                base_allow = remaining - len(note)
                header, _, body = payload.partition("\n\n")
                chunks = split_into_chunks(body, reducer_chunk_chars, reducer_chunk_overlap)
                cache_id = cache_key("tool_reduce", source_label, body)
                artifact_dir = tool_cache_dir / f"read_{cache_id}"
                artifact_dir.mkdir(parents=True, exist_ok=True)
                raw_path = artifact_dir / "raw.txt"
                raw_path.write_text(body, encoding="utf-8")
                for idx, chunk in enumerate(chunks, start=1):
                    (artifact_dir / f"chunk_{idx:03d}.txt").write_text(chunk, encoding="utf-8")
                artifact_rel = ""
                try:
                    artifact_rel = artifact_dir.relative_to(run_dir).as_posix()
                except Exception:
                    artifact_rel = artifact_dir.as_posix()
                artifact_note = f"\n\n[artifact] Original chunks: {artifact_rel}"
                safe_allow = max(200, base_allow - len(header) - 2 - len(artifact_note))
                reduced = reduce_text(body, source_label, safe_allow)
                summary_path = artifact_dir / "summary.txt"
                summary_path.write_text(reduced, encoding="utf-8")
                meta = {
                    "created_at": dt.datetime.now().isoformat(),
                    "source": source_label,
                    "raw_chars": len(body),
                    "chunk_chars": reducer_chunk_chars,
                    "chunk_overlap": reducer_chunk_overlap,
                    "chunk_count": len(chunks),
                    "artifact_dir": artifact_rel,
                }
                (artifact_dir / "meta.json").write_text(
                    json.dumps(meta, ensure_ascii=False, indent=2), encoding="utf-8"
                )
                text = f"{header}\n\n{reduced}{artifact_note}{note}"
            else:
                text = helpers.truncate_text_middle(payload, remaining)
            tool_chars_used += len(text)
            return text

        def read_verification_chunks(requests: list[tuple[str, str]], max_chars: int) -> str:
            if not requests:
                return ""
            seen = set()
            snippets: list[str] = []
            budget = max(500, max_chars)
            used = 0
            for artifact_dir, chunk_name in requests:
                key = (artifact_dir, chunk_name)
                if key in seen:
                    continue
                seen.add(key)
                try:
                    artifact_path = resolve_run_path(artifact_dir)
                    chunk_path = artifact_path / chunk_name
                    if not chunk_path.exists():
                        continue
                    content = read_text_file(chunk_path, 0, max(2000, budget))
                except Exception:
                    continue
                header = f"[verified] {artifact_dir}/{chunk_name}"
                entry = f"{header}\n{content}".strip()
                remaining = budget - used
                if remaining <= 0:
                    break
                if len(entry) > remaining:
                    entry = helpers.truncate_text_middle(entry, remaining)
                snippets.append(entry)
                used += len(entry)
            return "\n\n".join(snippets)

        def read_document(
            rel_path: str,
            start: int = 0,
            max_chars: Optional[int] = None,
            max_pages: Optional[int] = None,
            start_page: Optional[int] = None,
        ) -> str:
            """Read a file from the run folder (text/PDF) with optional slicing."""
            try:
                path = resolve_run_path(rel_path)
            except (FileNotFoundError, ValueError) as exc:
                return f"[error] {exc}"
            limit = args.max_chars if max_chars is None else max_chars
            try:
                if path.suffix.lower() == ".pdf":
                    page_limit = args.max_pdf_pages if max_pages is None else max_pages
                    page_start = 0 if start_page is None else max(0, start_page)
                    txt_path = resolve_pdf_text(path)
                    if txt_path:
                        text = normalize_rel_paths(read_text_file(txt_path, start, limit))
                        rel_label = txt_path.relative_to(run_dir).as_posix()
                        payload = f"[from text] {rel_label}\n\n{text}"
                        return apply_tool_budget(payload, text, rel_label)
                    pdf_text = helpers.read_pdf_with_fitz(
                        path,
                        page_limit,
                        limit,
                        start_page=page_start,
                        auto_extend_pages=int(getattr(args, "pdf_extend_pages", 0) or 0),
                        extend_min_chars=int(getattr(args, "pdf_extend_min_chars", 0) or 0),
                    )
                    rel_label = path.relative_to(run_dir).as_posix()
                    payload = f"[from pdf] {rel_label}\n\n{pdf_text}"
                    return apply_tool_budget(payload, pdf_text, rel_label)
                if path.suffix.lower() == ".pptx":
                    slide_limit = getattr(args, "max_pptx_slides", 0)
                    slide_start = 0 if start_page is None else max(0, start_page)
                    pptx_text = helpers.read_pptx_text(
                        path,
                        slide_limit,
                        limit,
                        start_slide=slide_start,
                        include_notes=True,
                    )
                    rel_label = path.relative_to(run_dir).as_posix()
                    payload = f"[from pptx] {rel_label}\n\n{pptx_text}"
                    return apply_tool_budget(payload, pptx_text, rel_label)
                if path.suffix.lower() in {".docx", ".doc"}:
                    docx_text = helpers.read_docx_text(path, limit, start=start)
                    rel_label = path.relative_to(run_dir).as_posix()
                    payload = f"[from docx] {rel_label}\n\n{docx_text}"
                    return apply_tool_budget(payload, docx_text, rel_label)
                if path.suffix.lower() in {".xlsx", ".xls"}:
                    sheet_limit = 0 if max_pages is None else max_pages
                    sheet_start = 0 if start_page is None else max(0, start_page)
                    xlsx_text = helpers.read_xlsx_text(
                        path,
                        limit,
                        max_sheets=sheet_limit,
                        start_sheet=sheet_start,
                    )
                    rel_label = path.relative_to(run_dir).as_posix()
                    payload = f"[from xlsx] {rel_label}\n\n{xlsx_text}"
                    return apply_tool_budget(payload, xlsx_text, rel_label)
                text = normalize_rel_paths(read_text_file(path, start, limit))
                rel_label = path.relative_to(run_dir).as_posix()
                payload = f"[from text] {rel_label}\n\n{text}"
                return apply_tool_budget(payload, text, rel_label)
            except Exception as exc:
                rel_label = path.relative_to(run_dir).as_posix()
                return (
                    f"[error] Failed to read '{rel_label}': {exc}. "
                    "Skip this file and continue with other sources."
                )

        tools = [list_archive_files, list_supporting_files, read_document]

        all_stages = set(STAGE_INFO)
        workflow_stage_order = workflow_stages.resolve_stage_order(
            all_stages=all_stages,
            default_stage_order=STAGE_ORDER,
            stages_raw=getattr(args, "stages", None),
        )
        stage_set = workflow_stages.resolve_stage_set(
            all_stages=all_stages,
            stages_raw=getattr(args, "stages", None),
            skip_stages_raw=getattr(args, "skip_stages", None),
        )
        auto_added_stages: dict[str, list[str]] = {}
        if not bool(getattr(args, "_disable_stage_dependency_expansion", False)):
            stage_set, auto_added_stages = workflow_stages.expand_stage_dependencies(
                stage_set=stage_set,
                all_stages=all_stages,
            )

        def stage_enabled(name: str) -> bool:
            return workflow_stages.stage_enabled(stage_set, name)

        stage_status = workflow_stages.initialize_stage_status(
            stage_order=workflow_stage_order,
            stage_set=stage_set,
        )

        def record_stage(name: str, status: str, detail: str = "") -> None:
            workflow_stages.record_stage(stage_status, name=name, status=status, detail=detail)
            detail_text = str(detail or "").strip()
            if detail_text:
                print(f"[workflow] stage={name} status={status} detail={detail_text}")
            else:
                print(f"[workflow] stage={name} status={status}")

        if auto_added_stages:
            order_index = {name: idx for idx, name in enumerate(workflow_stage_order)}
            for stage_name in sorted(
                auto_added_stages,
                key=lambda name: order_index.get(name, len(workflow_stage_order)),
            ):
                required_by = sorted(
                    set(auto_added_stages.get(stage_name, [])),
                    key=lambda name: order_index.get(name, len(workflow_stage_order)),
                )
                detail = (
                    f"auto_required_by={','.join(required_by)}"
                    if required_by
                    else "auto_required"
                )
                record_stage(stage_name, "pending", detail)

        alignment_enabled = agent_runtime.enabled("alignment", bool(args.alignment_check), self._agent_overrides)
        web_search_enabled = agent_runtime.enabled("web_query", bool(args.web_search), self._agent_overrides)
        template_adjust_enabled = agent_runtime.enabled(
            "template_adjuster",
            bool(args.template_adjust),
            self._agent_overrides,
        )
        clarifier_enabled = agent_runtime.enabled("clarifier", True, self._agent_overrides)
        if args.free_format:
            template_adjust_enabled = False
        if not stage_enabled("template_adjust"):
            template_adjust_enabled = False
        if not stage_enabled("clarifier"):
            clarifier_enabled = False
        if not template_adjust_enabled:
            record_stage("template_adjust", "skipped", "disabled")
        if not clarifier_enabled:
            record_stage("clarifier", "skipped", "disabled")
        args.web_search = web_search_enabled
        vision_override = agent_runtime.model("image_analyst", args.model_vision or "", self._agent_overrides)
        if vision_override:
            args.model_vision = vision_override
        alignment_prompt = agent_runtime.prompt(
            "alignment",
            prompts.build_alignment_prompt(helpers.normalize_lang(args.lang)),
            self._agent_overrides,
        )
        alignment_model = agent_runtime.model("alignment", check_model, self._agent_overrides)
        alignment_agent = None

        def agent_max_tokens(name: str) -> tuple[Optional[int], str]:
            return agent_runtime.max_input_tokens(name, self._agent_overrides)

        def normalize_depth(value: Optional[str]) -> Optional[str]:
            if not value:
                return None
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
            return None

        def infer_prompt_depth(prompt_text: Optional[str]) -> Optional[str]:
            text = (prompt_text or "").lower()
            if any(
                token in text
                for token in ("deepest", "exhaustive", "ultra", "ultra-deep", "매우심층", "최심층", "극심")
            ):
                return "exhaustive"
            if any(token in text for token in ("심층", "deep", "long-form", "comprehensive", "학술", "리뷰", "journal")):
                return "deep"
            if any(token in text for token in ("요약", "brief", "short", "간단", "summary")):
                return "brief"
            return None

        def infer_policy(prompt_text: Optional[str]) -> dict:
            text = (prompt_text or "").lower()
            prompt_depth = infer_prompt_depth(prompt_text)
            wants_web = any(token in text for token in ("최근", "latest", "trend", "news", "동향", "시장"))
            style = "default"
            if any(token in text for token in ("linkedin", "인플루언서", "홍보", "마케팅", "소개")):
                style = "influencer"
            elif any(token in text for token in ("journal", "논문", "academic", "학술", "리뷰")):
                style = "journal"
            return {"depth": prompt_depth, "wants_web": wants_web, "style": style}

        def infer_context_depth(template: object, style: str) -> str:
            if style == "journal" or template.name in prompts.FORMAL_TEMPLATES:
                return "deep"
            return "normal"

        def estimate_tokens(text: str) -> int:
            if not text:
                return 0
            # Conservative heuristic: keep extra headroom to avoid underestimation.
            ratio = 1.6 if helpers.is_korean_language(language) else 3.5
            base = int((len(text) / ratio) + 0.999)
            return int(base * 1.15) + 8

        def resolve_stage_budget(
            max_tokens: Optional[int],
            reserve: int = 3000,
            minimum: int = 2000,
            default_budget: int = 24000,
            hard_cap: int = 36000,
        ) -> Optional[int]:
            fallback = getattr(helpers, "DEFAULT_MAX_INPUT_TOKENS", None)
            budget = max_tokens or args.max_input_tokens or fallback
            if not budget:
                return max(minimum, min(default_budget, hard_cap))
            return max(minimum, min(int(budget) - reserve, hard_cap))

        def resolve_writer_budget(max_tokens: Optional[int]) -> Optional[int]:
            return resolve_stage_budget(
                max_tokens,
                reserve=9000,
                minimum=10000,
                default_budget=42000,
                hard_cap=42000,
            )

        def estimate_chars_for_tokens(token_budget: int) -> int:
            ratio = 2 if helpers.is_korean_language(language) else 4
            return max(0, token_budget * ratio)

        def trim_lines(text: str, max_lines: Optional[int]) -> str:
            if not text or not max_lines or max_lines <= 0:
                return text or ""
            lines = text.splitlines()
            if len(lines) <= max_lines:
                return text
            return "\n".join(lines[:max_lines])

        def make_section(
            key: str,
            header: Optional[str],
            content: Optional[str],
            priority: str = "medium",
            base_limit: Optional[int] = None,
            min_limit: int = 400,
            max_lines: Optional[int] = None,
        ) -> dict:
            return {
                "key": key,
                "header": header,
                "content": content or "",
                "priority": priority,
                "base_limit": base_limit,
                "min_limit": min_limit,
                "max_lines": max_lines,
            }

        def context_section(lines: list[str]) -> dict:
            return make_section(
                "context",
                None,
                "\n".join(lines),
                priority="high",
                base_limit=context_limit,
                min_limit=800,
                max_lines=context_line_limit,
            )

        def apply_section_limits(section: dict, ratio: float) -> None:
            content = section.get("content") or ""
            if not content:
                return
            max_lines = section.get("max_lines")
            if max_lines:
                content = trim_lines(content, max_lines)
            base_limit = section.get("base_limit")
            min_limit = section.get("min_limit", 400)
            limit: Optional[int] = None
            if base_limit:
                limit = max(min_limit, int(base_limit * ratio))
            elif ratio < 1.0:
                limit = max(min_limit, int(len(content) * ratio))
            if limit and len(content) > limit:
                content = helpers.truncate_text_middle(content, limit)
            section["content"] = content

        def build_payload(sections: list[dict]) -> str:
            lines: list[str] = []
            for section in sections:
                content = section.get("content") or ""
                if not content:
                    continue
                header = section.get("header")
                if header:
                    lines.extend(["", header, content])
                else:
                    lines.append(content)
            return "\n".join(lines)

        def build_stage_payload(
            sections: list[dict],
            budget: Optional[int],
            fallback_map: Optional[dict[str, str]] = None,
            force_fallback: bool = False,
        ) -> tuple[str, bool, bool]:
            for section in sections:
                apply_section_limits(section, 1.0)
            fallback_used = False
            if fallback_map and force_fallback:
                for section in sections:
                    key = section.get("key")
                    if key in fallback_map and fallback_map[key]:
                        section["content"] = fallback_map[key]
                        fallback_used = True
                for section in sections:
                    apply_section_limits(section, 1.0)
            payload = build_payload(sections)
            trimmed = fallback_used
            if not budget or estimate_tokens(payload) <= budget:
                return payload, trimmed, fallback_used
            if fallback_map and not fallback_used:
                for section in sections:
                    key = section.get("key")
                    if key in fallback_map and fallback_map[key]:
                        section["content"] = fallback_map[key]
                        fallback_used = True
                if fallback_used:
                    for section in sections:
                        apply_section_limits(section, 1.0)
                    payload = build_payload(sections)
                    trimmed = True
                    if estimate_tokens(payload) <= budget:
                        return payload, trimmed, fallback_used
            for priority in ("low", "medium", "high"):
                for ratio in (0.7, 0.5, 0.35):
                    for section in sections:
                        if section.get("priority") == priority:
                            apply_section_limits(section, ratio)
                    payload = build_payload(sections)
                    if estimate_tokens(payload) <= budget:
                        return payload, True, fallback_used
            max_chars = max(1000, estimate_chars_for_tokens(budget))
            payload = helpers.truncate_text_middle(payload, max_chars)
            return payload, True, fallback_used

        def is_context_overflow(exc: Exception) -> bool:
            message = str(exc).lower()
            return any(
                token in message
                for token in (
                    "context_length_exceeded",
                    "maximum context length",
                    "context window",
                    "prompt is too long",
                    "input is too long",
                    "too many tokens",
                )
            )

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
            if helpers.REPORT_PLACEHOLDER_RE.search(text):
                return True, "placeholder"
            headings = extract_section_headings(text)
            min_headings = max(len(required_sections), 3)
            if len(headings) < min_headings:
                return True, f"headings_{len(headings)}"
            missing = helpers.find_missing_sections(text, required_sections, output_format)
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
            repair_skeleton = helpers.build_report_skeleton(
                missing_sections if repair_mode == "append" else required_sections,
                output_format,
            )
            repair_prompt = agent_runtime.prompt(
                "structural_editor",
                prompts.build_repair_prompt(
                    format_instructions,
                    output_format,
                    language,
                    mode=repair_mode,
                    free_form=args.free_format,
                    template_rigidity=args.template_rigidity,
                ),
                self._agent_overrides,
            )
            repair_model = agent_runtime.model("structural_editor", args.model, self._agent_overrides)
            repair_max, repair_max_source = agent_max_tokens("structural_editor")
            repair_agent = helpers.create_agent_with_fallback(
                self._create_deep_agent,
                repair_model,
                tools,
                repair_prompt,
                backend,
                max_input_tokens=repair_max,
                max_input_tokens_source=repair_max_source,
            )
            repair_input = "\n".join(
                [
                    "Required skeleton:",
                    repair_skeleton,
                    "",
                    "Missing sections:",
                    ", ".join(missing_sections),
                    "",
                    "Evidence notes:",
                    helpers.truncate_text_middle(evidence_notes, args.quality_max_chars),
                    "",
                    "Report focus prompt:",
                    report_prompt or "(none)",
                    "",
                    "Current report:",
                    helpers.truncate_text_middle(report_text, args.quality_max_chars),
                ]
            )
            repair_text = self._runner.run(
                label,
                repair_agent,
                {"messages": [{"role": "user", "content": repair_input}]},
                show_progress=False,
            )
            repair_text = helpers.normalize_report_paths(repair_text, run_dir)
            repair_text = coerce_repair_headings(repair_text, missing_sections)
            repair_text = trim_to_sections(repair_text)
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
            candidate_missing = helpers.find_missing_sections(candidate, required_sections, output_format)
            if not extract_section_headings(candidate):
                return report_text
            if len(candidate) < min_len or (candidate_missing and len(candidate_missing) >= len(missing_sections)):
                return append_missing_sections(report_text, candidate)
            return candidate

        def run_writer_finalizer(
            primary_report: str,
            primary_label: str,
            secondary_report: Optional[str] = None,
            secondary_label: Optional[str] = None,
            primary_eval: Optional[dict] = None,
            secondary_eval: Optional[dict] = None,
            pairwise_notes: Optional[list[dict]] = None,
        ) -> str:
            finalizer_prompt = agent_runtime.prompt(
                "writer",
                prompts.build_writer_finalizer_prompt(
                    format_instructions,
                    template_guidance_text,
                    template_spec,
                    required_sections,
                    output_format,
                    language,
                    depth,
                    template_rigidity=args.template_rigidity,
                    figures_enabled=bool(args.extract_figures),
                    figures_mode=args.figures_mode,
                ),
                self._agent_overrides,
            )
            finalizer_model = agent_runtime.model("writer", args.model, self._agent_overrides)
            finalizer_max, finalizer_max_source = agent_max_tokens("writer")
            finalizer_agent = helpers.create_agent_with_fallback(
                self._create_deep_agent,
                finalizer_model,
                tools,
                finalizer_prompt,
                backend,
                max_input_tokens=finalizer_max,
                max_input_tokens_source=finalizer_max_source,
            )
            notes = "\n".join(
                f"- {note.get('reason', '')} (winner={note.get('winner')})"
                for note in (pairwise_notes or [])
                if note.get("reason")
            )
            finalizer_parts = list(context_lines)
            finalizer_parts.extend(
                [
                    "",
                    "Finalization instructions:",
                    "- Use the primary draft as the base.",
                    "- Use the secondary draft only to improve clarity, structure, or fill gaps.",
                    "- Do not add new claims or sources beyond the evidence notes.",
                    "- Preserve citations and required section headings.",
                    "",
                    f"Primary draft ({primary_label}):",
                    helpers.truncate_text_middle(primary_report, args.quality_max_chars),
                ]
            )
            if secondary_report:
                finalizer_parts.extend(
                    [
                        "",
                        f"Secondary draft ({secondary_label or 'secondary'}):",
                        helpers.truncate_text_middle(secondary_report, args.quality_max_chars),
                    ]
                )
            if primary_eval:
                finalizer_parts.extend(["", "Primary evaluation summary:", helpers.summarize_evaluation(primary_eval)])
            if secondary_eval:
                finalizer_parts.extend(["", "Secondary evaluation summary:", helpers.summarize_evaluation(secondary_eval)])
            if notes:
                finalizer_parts.extend(["", "Pairwise selection notes:", notes])
            if style_hint:
                finalizer_parts.extend(["", style_hint])
            finalizer_parts.extend(["", "Evidence notes:", helpers.truncate_text_middle(evidence_notes, args.quality_max_chars)])
            if template_guidance_text:
                finalizer_parts.extend(["", "Template guidance:", template_guidance_text])
            if report_prompt:
                finalizer_parts.extend(["", "Report focus prompt:", report_prompt])
            if clarification_answers:
                finalizer_parts.extend(["", "User clarifications:", clarification_answers])
            if supporting_summary:
                finalizer_parts.extend(["", "Supporting web research summary:", supporting_summary])
            finalizer_input = "\n".join(finalizer_parts)
            final_text = self._runner.run(
                "Writer Finalizer",
                finalizer_agent,
                {"messages": [{"role": "user", "content": finalizer_input}]},
                show_progress=False,
            )
            final_text = helpers.normalize_report_paths(final_text, run_dir)
            final_text = coerce_required_headings(final_text, required_sections)
            retry_needed, retry_reason = report_needs_retry(final_text)
            if retry_needed:
                retry_input = "\n".join([build_writer_retry_guardrail(retry_reason), "", finalizer_input])
                final_text = self._runner.run(
                    "Writer Finalizer (retry)",
                    finalizer_agent,
                    {"messages": [{"role": "user", "content": retry_input}]},
                    show_progress=False,
                )
                final_text = helpers.normalize_report_paths(final_text, run_dir)
                final_text = coerce_required_headings(final_text, required_sections)
            if report_needs_retry(final_text)[0]:
                return primary_report
            return final_text

        def run_alignment_check(stage: str, content: str) -> Optional[str]:
            nonlocal alignment_agent
            if not alignment_enabled:
                return None
            if alignment_agent is None:
                align_max, align_max_source = agent_max_tokens("alignment")
                alignment_agent = helpers.create_agent_with_fallback(
                    self._create_deep_agent,
                    alignment_model,
                    tools,
                    alignment_prompt,
                    backend,
                    max_input_tokens=align_max,
                    max_input_tokens_source=align_max_source,
                )
            align_input = [
                f"Stage: {stage}",
                "",
                "Run context:",
                "\n".join(context_lines),
                "",
                "Report focus prompt:",
                report_prompt or "(none)",
                "",
                "Stage content:",
                helpers.truncate_text_middle(content, alignment_max_chars),
            ]
            align_payload = "\n".join(align_input)
            align_notes, cached = get_cached_output(
                f"alignment_{stage}",
                alignment_model,
                alignment_prompt,
                align_payload,
                lambda: self._runner.run(
                    f"Alignment Check ({stage})",
                    alignment_agent,
                    {"messages": [{"role": "user", "content": align_payload}]},
                    show_progress=True,
                ),
            )
            if cached:
                helpers.print_progress(
                    f"Alignment Check ({stage}) [cache]",
                    sanitize_console_text(align_notes),
                    args.progress,
                    args.progress_chars,
                )
            note_name = f"alignment_{helpers.slugify_label(stage)}.md"
            (notes_dir / note_name).write_text(align_notes, encoding="utf-8")
            return align_notes

        context_from_state = bool(state and state.context_lines)
        context_lines = (
            list(state.context_lines)
            if state and state.context_lines
            else [
                "Run folder: .",
                "Archive folder: ./archive",
                f"Query ID: {query_id}",
            ]
        )
        if not context_from_state:
            if instruction_file:
                rel_instruction = instruction_file.relative_to(run_dir).as_posix()
                context_lines.append(f"Instruction file: ./{rel_instruction}")
            if baseline_report:
                rel_baseline = baseline_report.relative_to(run_dir).as_posix()
                context_lines.append(f"Baseline report: ./{rel_baseline}")
            if index_file:
                rel_index = index_file.relative_to(run_dir).as_posix()
                context_lines.append(f"Index file: ./{rel_index}")

        language = helpers.normalize_lang(args.lang)
        report_prompt = helpers.load_report_prompt(args.prompt, args.prompt_file)
        if state and state.report_prompt and not report_prompt:
            report_prompt = state.report_prompt
        template_spec = helpers.load_template_spec(args.template, report_prompt)
        policy = infer_policy(report_prompt)
        prompt_depth = normalize_depth(policy["depth"])
        style = policy["style"]
        wants_web = policy["wants_web"]
        depth = infer_context_depth(template_spec, style)
        if prompt_depth:
            depth = prompt_depth
        if state and state.depth:
            depth = normalize_depth(state.depth) or depth
        cli_depth = normalize_depth(getattr(args, "depth", None))
        if cli_depth:
            depth = cli_depth
        is_deep = depth in {"deep", "exhaustive"}
        if depth == "brief":
            alignment_enabled = False
            if template_adjust_enabled:
                template_adjust_enabled = False
                record_stage("template_adjust", "skipped", "depth=brief")
        args.alignment_check = alignment_enabled
        args.template_adjust = template_adjust_enabled
        use_web_search = bool(args.web_search and wants_web and stage_enabled("web"))
        use_evidence = depth != "brief" and stage_enabled("evidence")
        if args.quality_iterations <= 0:
            args.quality_iterations = 1 if is_deep else 0
        quality_iterations = args.quality_iterations
        if not stage_enabled("quality"):
            quality_iterations = 0
        style_hint = ""
        if style == "influencer" and template_spec.name not in prompts.FORMAL_TEMPLATES:
            style_hint = "Style hint: Write in a concise, engaging LinkedIn-style explanatory tone."
        if state and state.style_hint:
            style_hint = state.style_hint

        reducer_prompt = agent_runtime.prompt(
            "reducer",
            prompts.build_reducer_prompt(language),
            self._agent_overrides,
        )
        reducer_model = agent_runtime.model("reducer", check_model or args.model, self._agent_overrides)
        reducer_max, reducer_max_source = agent_max_tokens("reducer")
        reducer_agent = None

        def ensure_reducer_agent():
            nonlocal reducer_agent
            if reducer_agent is None:
                reducer_agent = helpers.create_agent_with_fallback(
                    self._create_deep_agent,
                    reducer_model,
                    [],
                    reducer_prompt,
                    backend,
                    max_input_tokens=reducer_max,
                    max_input_tokens_source=reducer_max_source,
                )
            return reducer_agent

        def run_reducer(prompt_text: str, source_label: str, max_chars: int) -> str:
            target = max(200, max_chars)
            payload = "\n".join([prompt_text, "", f"Target max chars: {target}"])
            return self._runner.run(
                "Reducer",
                ensure_reducer_agent(),
                {"messages": [{"role": "user", "content": payload}]},
                show_progress=False,
            )

        reducer_runner = run_reducer

        source_index: list[dict] = []
        source_triage: list[dict] = []
        source_triage_text = state.source_triage_text if state and state.source_triage_text else ""
        source_index_path = notes_dir / "source_index.jsonl"
        source_triage_path = notes_dir / "source_triage.md"
        needs_source_scan = bool(stage_enabled("scout") or stage_enabled("web") or stage_enabled("evidence"))
        if needs_source_scan or not source_triage_text:
            source_index = feder_tools.build_source_index(archive_dir, run_dir, supporting_dir)
            feder_tools.write_jsonl(source_index_path, source_index)
            source_triage = feder_tools.rank_sources(source_index, report_prompt or query_id, top_k=12)
            source_triage_text = feder_tools.format_source_triage(source_triage)
            source_triage_path.write_text(source_triage_text, encoding="utf-8")
        elif source_triage_text and not source_triage_path.exists():
            source_triage_path.write_text(source_triage_text, encoding="utf-8")
        try:
            cache_scope_signature = cache_key(
                source_index_path.read_text(encoding="utf-8", errors="ignore")
                if source_index_path.exists()
                else "",
                source_triage_text,
                bool(getattr(args, "web_search", False)),
                bool(getattr(args, "agentic_search", False)),
            )
        except Exception:
            cache_scope_signature = cache_key(
                source_triage_text,
                bool(getattr(args, "web_search", False)),
                bool(getattr(args, "agentic_search", False)),
            )

        def build_static_scout_notes(max_items: int = 12) -> str:
            lines = [
                "Static scout fallback summary (overflow-safe).",
                "Top candidate sources:",
            ]
            top_items = source_triage[: max(1, max_items)]
            for idx, item in enumerate(top_items, start=1):
                path = str(item.get("path") or item.get("rel_path") or "(unknown)")
                kind = str(item.get("kind") or item.get("source_type") or "source")
                reason = str(item.get("reason") or item.get("note") or "")
                if reason:
                    lines.append(f"- {idx}. [{kind}] {path} — {reason}")
                else:
                    lines.append(f"- {idx}. [{kind}] {path}")
            lines.append("")
            lines.append("Guidance: proceed to evidence using these sources; verify claims before writer stage.")
            return "\n".join(lines).strip()
        if not context_from_state:
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

        scout_prompt = agent_runtime.prompt(
            "scout",
            prompts.build_scout_prompt(language),
            self._agent_overrides,
        )
        scout_model = agent_runtime.model("scout", args.model, self._agent_overrides)
        scout_max, scout_max_source = agent_max_tokens("scout")
        scout_agent = helpers.create_agent_with_fallback(
            self._create_deep_agent,
            scout_model,
            tools,
            scout_prompt,
            backend,
            max_input_tokens=scout_max,
            max_input_tokens_source=scout_max_source,
        )
        scout_sections = [
            context_section(context_lines),
            make_section(
                "scout_guardrail",
                "Scout constraints:",
                (
                    "Scout is an inventory stage. Do not read full long documents. "
                    "Prefer list_archive_files and metadata/index files first. "
                    "Avoid large reads with read_file/read_document unless strictly required for source disambiguation."
                ),
                priority="high",
                base_limit=600,
                min_limit=200,
            ),
        ]
        if report_prompt:
            scout_sections.append(
                make_section(
                    "report_prompt",
                    "Report focus prompt:",
                    report_prompt,
                    priority="high",
                    base_limit=report_prompt_limit,
                    min_limit=800,
                )
            )
        if source_triage_text:
            scout_sections.append(
                make_section(
                    "source_triage",
                    "Source triage (lightweight):",
                    source_triage_text,
                    priority="low",
                    base_limit=triage_limit,
                    min_limit=400,
                    max_lines=triage_line_limit,
                )
            )
        scout_notes = ""
        if stage_enabled("scout"):
            scout_budget = resolve_stage_budget(
                scout_max,
                reserve=4000,
                minimum=2000,
                default_budget=16000,
                hard_cap=18000,
            )
            scout_payload, _, _ = build_stage_payload(scout_sections, scout_budget)
            cached = False
            try:
                scout_notes, cached = get_cached_output(
                    "scout",
                    scout_model,
                    scout_prompt,
                    scout_payload,
                    lambda: self._runner.run(
                        "Scout Notes",
                        scout_agent,
                        {"messages": [{"role": "user", "content": scout_payload}]},
                        show_progress=True,
                    ),
                )
            except Exception as exc:
                if not is_context_overflow(exc):
                    raise
                # Retry scout with lightweight tools only when the first pass overflows context.
                helpers.print_progress(
                    "Scout Notes",
                    "[warn] context overflow in scout; retrying with lightweight tools.",
                    args.progress,
                    args.progress_chars,
                )
                scout_fallback_agent = helpers.create_agent_with_fallback(
                    self._create_deep_agent,
                    scout_model,
                    [list_archive_files, list_supporting_files],
                    scout_prompt,
                    backend,
                    max_input_tokens=scout_max,
                    max_input_tokens_source=scout_max_source,
                )
                fallback_budget = max(2000, (scout_budget // 2) if scout_budget else 2000)
                fallback_sections = [context_section(context_lines)]
                fallback_sections.append(
                    make_section(
                        "scout_guardrail",
                        "Scout fallback constraints:",
                        (
                            "Fallback mode: list-only reconnaissance. "
                            "Do not open long files. Do not call read_file/read_document/glob/grep. "
                            "Use list_archive_files and list_supporting_files only."
                        ),
                        priority="high",
                        base_limit=500,
                        min_limit=200,
                    )
                )
                if report_prompt:
                    fallback_sections.append(
                        make_section(
                            "report_prompt",
                            "Report focus prompt:",
                            report_prompt,
                            priority="high",
                            base_limit=report_prompt_limit,
                            min_limit=800,
                        )
                    )
                if source_triage_text:
                    fallback_sections.append(
                        make_section(
                            "source_triage",
                            "Source triage (lightweight):",
                            source_triage_text,
                            priority="low",
                            base_limit=triage_limit,
                            min_limit=400,
                            max_lines=triage_line_limit,
                        )
                    )
                fallback_payload, _, _ = build_stage_payload(fallback_sections, fallback_budget)
                try:
                    scout_notes = self._runner.run(
                        "Scout Notes (fallback)",
                        scout_fallback_agent,
                        {"messages": [{"role": "user", "content": fallback_payload}]},
                        show_progress=True,
                    )
                    record_stage("scout", "ran", "overflow_fallback")
                except Exception as fallback_exc:
                    if not is_context_overflow(fallback_exc):
                        raise
                    scout_notes = build_static_scout_notes()
                    helpers.print_progress(
                        "Scout Notes (static fallback)",
                        sanitize_console_text(scout_notes),
                        args.progress,
                        args.progress_chars,
                    )
                    record_stage("scout", "ran", "overflow_static_fallback")
            else:
                if cached:
                    helpers.print_progress(
                        "Scout Notes [cache]",
                        sanitize_console_text(scout_notes),
                        args.progress,
                        args.progress_chars,
                    )
                record_stage("scout", "cached" if cached else "ran")
        if state and state.scout_notes and not scout_notes:
            scout_notes = state.scout_notes
        scout_context = scout_notes if len(scout_notes) <= pack_limit else pack_text(scout_notes)

        clarification_questions: Optional[str] = None
        clarification_answers = helpers.load_user_answers(args.answers, args.answers_file)
        if clarifier_enabled and (args.interactive or clarification_answers):
            clarifier_prompt = agent_runtime.prompt(
                "clarifier",
                prompts.build_clarifier_prompt(language),
                self._agent_overrides,
            )
            clarifier_model = agent_runtime.model("clarifier", args.model, self._agent_overrides)
            clarifier_max, clarifier_max_source = agent_max_tokens("clarifier")
            clarifier_agent = helpers.create_agent_with_fallback(
                self._create_deep_agent,
                clarifier_model,
                tools,
                clarifier_prompt,
                backend,
                max_input_tokens=clarifier_max,
                max_input_tokens_source=clarifier_max_source,
            )
            clarifier_sections = [
                context_section(context_lines),
                make_section(
                    "scout_notes",
                    "Scout notes:",
                    scout_context,
                    priority="high",
                    base_limit=pack_limit,
                    min_limit=800,
                ),
            ]
            if report_prompt:
                clarifier_sections.append(
                    make_section(
                        "report_prompt",
                        "Report focus prompt:",
                        report_prompt,
                        priority="high",
                        base_limit=report_prompt_limit,
                        min_limit=800,
                    )
                )
            clarifier_budget = resolve_stage_budget(
                clarifier_max,
                reserve=4000,
                minimum=2000,
                default_budget=12000,
                hard_cap=14000,
            )
            clarifier_payload, _, _ = build_stage_payload(clarifier_sections, clarifier_budget)
            try:
                clarification_questions = self._runner.run(
                    "Clarification Questions",
                    clarifier_agent,
                    {"messages": [{"role": "user", "content": clarifier_payload}]},
                    show_progress=True,
                )
                record_stage("clarifier", "ran")
            except Exception as exc:
                if not is_context_overflow(exc):
                    raise
                helpers.print_progress(
                    "Clarification Questions",
                    "[warn] context overflow in clarifier; retrying with reduced payload.",
                    args.progress,
                    args.progress_chars,
                )
                fallback_budget = max(2000, (clarifier_budget // 2) if clarifier_budget else 2000)
                fallback_payload, _, _ = build_stage_payload(clarifier_sections, fallback_budget)
                clarification_questions = self._runner.run(
                    "Clarification Questions (fallback)",
                    clarifier_agent,
                    {"messages": [{"role": "user", "content": fallback_payload}]},
                    show_progress=True,
                )
                record_stage("clarifier", "ran", "overflow_fallback")
            if clarification_questions and "no_questions" not in clarification_questions.lower():
                if not clarification_answers and args.interactive:
                    clarification_answers = helpers.read_user_answers()
                    if clarification_answers:
                        helpers.print_progress(
                            "Clarification Answers",
                            clarification_answers,
                            args.progress,
                            args.progress_chars,
                        )
        elif stage_enabled("clarifier"):
            record_stage("clarifier", "skipped", "no_questions")

        if state:
            if state.clarification_questions and not clarification_questions:
                clarification_questions = state.clarification_questions
            if state.clarification_answers and not clarification_answers:
                clarification_answers = state.clarification_answers

        align_scout = run_alignment_check("scout", scout_notes) if scout_notes else None
        if state and state.align_scout and not align_scout:
            align_scout = state.align_scout
        template_adjustment_path: Optional[Path] = None
        if template_adjust_enabled:
            adjust_max, adjust_max_source = agent_max_tokens("template_adjuster")
            original_template_spec = template_spec
            adjusted_spec, adjustment = helpers.adjust_template_spec(
                template_spec,
                report_prompt,
                scout_notes,
                align_scout,
                clarification_answers,
                language,
                output_format,
                args.model,
                self._create_deep_agent,
                backend,
                adjust_mode=args.template_adjust_mode,
                max_input_tokens=adjust_max,
                max_input_tokens_source=adjust_max_source,
            )
            template_spec = adjusted_spec
            if adjustment:
                template_adjustment_path = helpers.write_template_adjustment_note(
                    notes_dir,
                    original_template_spec,
                    adjusted_spec,
                    adjustment,
                    output_format,
                    language,
                )
            record_stage("template_adjust", "ran")

        if state and state.template_spec:
            template_spec = state.template_spec

        if not template_spec.sections:
            template_spec.sections = list(helpers.DEFAULT_SECTIONS)
        required_sections = (
            list(helpers.FREE_FORMAT_REQUIRED_SECTIONS) if args.free_format else list(template_spec.sections)
        )
        if state and state.required_sections:
            required_sections = list(state.required_sections)
        format_instructions = helpers.build_format_instructions(
            output_format,
            required_sections,
            free_form=args.free_format,
            language=language,
            template_rigidity=getattr(args, "template_rigidity", "balanced"),
        )
        context_lines.append(f"Template: {template_spec.name}")
        if template_spec.source:
            context_lines.append(f"Template source: {template_spec.source}")
        template_guidance_text = helpers.build_template_guidance_text(template_spec)
        if state and state.template_guidance_text:
            template_guidance_text = state.template_guidance_text

        plan_prompt = agent_runtime.prompt(
            "planner",
            prompts.build_plan_prompt(language),
            self._agent_overrides,
        )
        plan_model = agent_runtime.model("planner", args.model, self._agent_overrides)
        plan_max, plan_max_source = agent_max_tokens("planner")
        plan_agent = helpers.create_agent_with_fallback(
            self._create_deep_agent,
            plan_model,
            tools,
            plan_prompt,
            backend,
            max_input_tokens=plan_max,
            max_input_tokens_source=plan_max_source,
        )
        plan_sections = [
            context_section(context_lines),
            make_section(
                "scout_notes",
                "Scout notes:",
                scout_context,
                priority="high",
                base_limit=pack_limit,
                min_limit=800,
            ),
        ]
        if source_triage_text:
            plan_sections.append(
                make_section(
                    "source_triage",
                    "Source triage (lightweight):",
                    source_triage_text,
                    priority="low",
                    base_limit=triage_limit,
                    min_limit=400,
                    max_lines=triage_line_limit,
                )
            )
        if align_scout:
            plan_sections.append(
                make_section(
                    "align_scout",
                    "Alignment notes (scout):",
                    align_scout,
                    priority="medium",
                    base_limit=alignment_limit,
                    min_limit=600,
                )
            )
        if template_guidance_text:
            plan_sections.append(
                make_section(
                    "template_guidance",
                    "Template guidance:",
                    template_guidance_text,
                    priority="low",
                    base_limit=guidance_limit,
                    min_limit=400,
                    max_lines=guidance_line_limit,
                )
            )
        if report_prompt:
            plan_sections.append(
                make_section(
                    "report_prompt",
                    "Report focus prompt:",
                    report_prompt,
                    priority="high",
                    base_limit=report_prompt_limit,
                    min_limit=800,
                )
            )
        if clarification_answers:
            plan_sections.append(
                make_section(
                    "clarification_answers",
                    "User clarifications:",
                    clarification_answers,
                    priority="high",
                    base_limit=clarification_limit,
                    min_limit=800,
                )
            )
        plan_text = ""
        plan_context = ""
        align_plan = None
        if stage_enabled("plan"):
            plan_budget = resolve_stage_budget(
                plan_max,
                reserve=4000,
                minimum=2000,
                default_budget=16000,
                hard_cap=20000,
            )
            plan_payload, _, _ = build_stage_payload(plan_sections, plan_budget)
            cached = False
            try:
                plan_text, cached = get_cached_output(
                    "plan",
                    plan_model,
                    plan_prompt,
                    plan_payload,
                    lambda: self._runner.run(
                        "Plan",
                        plan_agent,
                        {"messages": [{"role": "user", "content": plan_payload}]},
                        show_progress=True,
                    ),
                )
                if cached:
                    helpers.print_progress(
                        "Plan [cache]",
                        sanitize_console_text(plan_text),
                        args.progress,
                        args.progress_chars,
                    )
                record_stage("plan", "cached" if cached else "ran")
            except Exception as exc:
                if not is_context_overflow(exc):
                    raise
                helpers.print_progress(
                    "Plan",
                    "[warn] context overflow in plan; retrying with reduced payload.",
                    args.progress,
                    args.progress_chars,
                )
                fallback_budget = max(2000, (plan_budget // 2) if plan_budget else 2000)
                fallback_payload, _, _ = build_stage_payload(plan_sections, fallback_budget)
                plan_text = self._runner.run(
                    "Plan (fallback)",
                    plan_agent,
                    {"messages": [{"role": "user", "content": fallback_payload}]},
                    show_progress=True,
                )
                record_stage("plan", "ran", "overflow_fallback")
            plan_context = plan_text if len(plan_text) <= pack_limit else pack_text(plan_text)
            (notes_dir / "report_plan.md").write_text(plan_text, encoding="utf-8")
            align_plan = run_alignment_check("plan", plan_text)
        if state and state.plan_text and not plan_text:
            plan_text = state.plan_text
        if state and state.plan_context and not plan_context:
            plan_context = state.plan_context
        if state and state.align_plan and not align_plan:
            align_plan = state.align_plan
        if plan_text and not plan_context:
            plan_context = plan_text if len(plan_text) <= pack_limit else pack_text(plan_text)

        if args.supporting_dir:
            supporting_dir = helpers.resolve_supporting_dir(run_dir, args.supporting_dir)
        if state and state.supporting_dir:
            supporting_dir = state.supporting_dir
        if use_web_search:
            supporting_dir = helpers.resolve_supporting_dir(run_dir, args.supporting_dir)
            web_prompt = agent_runtime.prompt(
                "web_query",
                prompts.build_web_prompt(),
                self._agent_overrides,
            )
            web_model = agent_runtime.model("web_query", args.model, self._agent_overrides)
            web_max, web_max_source = agent_max_tokens("web_query")
            web_agent = helpers.create_agent_with_fallback(
                self._create_deep_agent,
                web_model,
                tools,
                web_prompt,
                backend,
                max_input_tokens=web_max,
                max_input_tokens_source=web_max_source,
            )
            web_sections = [
                context_section(context_lines),
                make_section(
                    "scout_notes",
                    "Scout notes:",
                    scout_context,
                    priority="high",
                    base_limit=pack_limit,
                    min_limit=800,
                ),
                make_section(
                    "plan",
                    "Plan:",
                    plan_context,
                    priority="high",
                    base_limit=pack_limit,
                    min_limit=800,
                ),
            ]
            if report_prompt:
                web_sections.append(
                    make_section(
                        "report_prompt",
                        "Report focus prompt:",
                        report_prompt,
                        priority="high",
                        base_limit=report_prompt_limit,
                        min_limit=800,
                    )
                )
            web_budget = resolve_stage_budget(
                web_max,
                reserve=4000,
                minimum=2000,
                default_budget=14000,
                hard_cap=18000,
            )
            web_payload, _, _ = build_stage_payload(web_sections, web_budget)
            try:
                web_text = self._runner.run(
                    "Web Query Draft",
                    web_agent,
                    {"messages": [{"role": "user", "content": web_payload}]},
                    show_progress=False,
                )
            except Exception as exc:
                if not is_context_overflow(exc):
                    raise
                helpers.print_progress(
                    "Web Query Draft",
                    "[warn] context overflow in web-query stage; retrying with reduced payload.",
                    args.progress,
                    args.progress_chars,
                )
                fallback_budget = max(2000, (web_budget // 2) if web_budget else 2000)
                fallback_payload, _, _ = build_stage_payload(web_sections, fallback_budget)
                web_text = self._runner.run(
                    "Web Query Draft (fallback)",
                    web_agent,
                    {"messages": [{"role": "user", "content": fallback_payload}]},
                    show_progress=False,
                )
            web_queries = helpers.parse_query_lines(web_text, args.web_max_queries)
            helpers.print_progress(
                "Web Queries",
                "\n".join(web_queries) if web_queries else "None",
                args.progress,
                args.progress_chars,
            )
            if web_queries:
                supporting_summary, _ = helpers.run_web_research(
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
            helpers.print_progress(
                "Web Research",
                supporting_summary or "Completed",
                args.progress,
                args.progress_chars,
            )
            record_stage("web", "ran")
        if state and state.supporting_summary and not supporting_summary:
            supporting_summary = state.supporting_summary
        if stage_enabled("web") and not use_web_search and not stage_status.get("web", {}).get("status") == "ran":
            record_stage("web", "skipped", "policy")

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
        if state and state.source_triage_text:
            source_triage_text = state.source_triage_text

        evidence_notes = scout_context
        align_evidence = None
        claim_map_text = ""
        gap_text = ""
        condensed = ""
        evidence_for_writer = evidence_notes
        if use_evidence:
            evidence_prompt = agent_runtime.prompt(
                "evidence",
                prompts.build_evidence_prompt(language),
                self._agent_overrides,
            )
            evidence_model = agent_runtime.model("evidence", args.model, self._agent_overrides)
            evidence_max, evidence_max_source = agent_max_tokens("evidence")
            evidence_agent = helpers.create_agent_with_fallback(
                self._create_deep_agent,
                evidence_model,
                tools,
                evidence_prompt,
                backend,
                max_input_tokens=evidence_max,
                max_input_tokens_source=evidence_max_source,
            )
            evidence_sections = [
                context_section(context_lines),
                make_section(
                    "scout_notes",
                    "Scout notes:",
                    scout_context,
                    priority="high",
                    base_limit=pack_limit,
                    min_limit=800,
                ),
                make_section(
                    "plan",
                    "Plan:",
                    plan_context,
                    priority="high",
                    base_limit=pack_limit,
                    min_limit=800,
                ),
            ]
            if source_triage_text:
                evidence_sections.append(
                    make_section(
                        "source_triage",
                        "Source triage (lightweight):",
                        source_triage_text,
                        priority="low",
                        base_limit=triage_limit,
                        min_limit=400,
                        max_lines=triage_line_limit,
                    )
                )
            if align_plan:
                evidence_sections.append(
                    make_section(
                        "align_plan",
                        "Alignment notes (plan):",
                        align_plan,
                        priority="medium",
                        base_limit=alignment_limit,
                        min_limit=600,
                    )
                )
            if template_guidance_text:
                evidence_sections.append(
                    make_section(
                        "template_guidance",
                        "Template guidance:",
                        template_guidance_text,
                        priority="low",
                        base_limit=guidance_limit,
                        min_limit=400,
                        max_lines=guidance_line_limit,
                    )
                )
            if report_prompt:
                evidence_sections.append(
                    make_section(
                        "report_prompt",
                        "Report focus prompt:",
                        report_prompt,
                        priority="high",
                        base_limit=report_prompt_limit,
                        min_limit=800,
                    )
                )
            if clarification_questions and "no_questions" not in clarification_questions.lower():
                evidence_sections.append(
                    make_section(
                        "clarification_questions",
                        "Clarification questions:",
                        clarification_questions,
                        priority="medium",
                        base_limit=clarification_limit,
                        min_limit=600,
                    )
                )
            if clarification_answers:
                evidence_sections.append(
                    make_section(
                        "clarification_answers",
                        "User clarifications:",
                        clarification_answers,
                        priority="high",
                        base_limit=clarification_limit,
                        min_limit=800,
                    )
                )
            if supporting_summary:
                evidence_sections.append(
                    make_section(
                        "supporting_summary",
                        "Supporting web research summary:",
                        supporting_summary,
                        priority="low",
                        base_limit=supporting_limit,
                        min_limit=400,
                        max_lines=supporting_line_limit,
                    )
                )
            evidence_budget = resolve_stage_budget(
                evidence_max,
                reserve=4500,
                minimum=2500,
                default_budget=22000,
                hard_cap=26000,
            )
            evidence_input, _, _ = build_stage_payload(evidence_sections, evidence_budget)
            cached = False
            try:
                evidence_notes, cached = get_cached_output(
                    "evidence",
                    evidence_model,
                    evidence_prompt,
                    evidence_input,
                    lambda: self._runner.run(
                        "Evidence Notes",
                        evidence_agent,
                        {"messages": [{"role": "user", "content": evidence_input}]},
                        show_progress=True,
                    ),
                )
                record_stage("evidence", "cached" if cached else "ran")
                if cached:
                    helpers.print_progress(
                        "Evidence Notes [cache]",
                        sanitize_console_text(evidence_notes),
                        args.progress,
                        args.progress_chars,
                    )
            except Exception as exc:
                if not is_context_overflow(exc):
                    raise
                helpers.print_progress(
                    "Evidence Notes",
                    "[warn] context overflow in evidence; retrying with reduced payload.",
                    args.progress,
                    args.progress_chars,
                )
                fallback_budget = max(2000, (evidence_budget // 2) if evidence_budget else 2000)
                fallback_payload, _, _ = build_stage_payload(evidence_sections, fallback_budget)
                try:
                    evidence_notes = self._runner.run(
                        "Evidence Notes (fallback)",
                        evidence_agent,
                        {"messages": [{"role": "user", "content": fallback_payload}]},
                        show_progress=True,
                    )
                    record_stage("evidence", "ran", "overflow_fallback")
                except Exception as fallback_exc:
                    if not is_context_overflow(fallback_exc):
                        raise
                    evidence_notes = (
                        "Evidence fallback summary (overflow-safe).\n\n"
                        f"{build_static_scout_notes(max_items=8)}\n\n"
                        "Limitations: evidence extraction was reduced due model context limits. "
                        "Re-run with a higher-capacity model or lower stage scope."
                    )
                    helpers.print_progress(
                        "Evidence Notes (static fallback)",
                        sanitize_console_text(evidence_notes),
                        args.progress,
                        args.progress_chars,
                    )
                    record_stage("evidence", "ran", "overflow_static_fallback")
            (notes_dir / "evidence_notes.md").write_text(evidence_notes, encoding="utf-8")
            align_evidence = run_alignment_check("evidence", evidence_notes)
            verification_requests = parse_verification_requests(evidence_notes)
            if verification_requests:
                verify_limit = min(args.quality_max_chars, 6000)
                verified = read_verification_chunks(verification_requests, verify_limit)
                if verified:
                    evidence_notes = "\n".join(
                        [
                            evidence_notes.rstrip(),
                            "",
                            "Verification excerpts:",
                            verified,
                        ]
                    )
                    (notes_dir / "evidence_notes.md").write_text(evidence_notes, encoding="utf-8")

            if stage_enabled("plan_check"):
                plan_check_prompt = agent_runtime.prompt(
                    "plan_check",
                    prompts.build_plan_check_prompt(language),
                    self._agent_overrides,
                )
                plan_check_model = agent_runtime.model("plan_check", check_model, self._agent_overrides)
                plan_check_max, plan_check_max_source = agent_max_tokens("plan_check")
                plan_check_agent = helpers.create_agent_with_fallback(
                    self._create_deep_agent,
                    plan_check_model,
                    tools,
                    plan_check_prompt,
                    backend,
                    max_input_tokens=plan_check_max,
                    max_input_tokens_source=plan_check_max_source,
                )
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
                plan_text, cached = get_cached_output(
                    "plan_check",
                    plan_check_model,
                    plan_check_prompt,
                    plan_check_input,
                    lambda: self._runner.run(
                        "Plan Update",
                        plan_check_agent,
                        {"messages": [{"role": "user", "content": plan_check_input}]},
                        show_progress=True,
                    ),
                )
                record_stage("plan_check", "cached" if cached else "ran")
                if cached:
                    helpers.print_progress(
                        "Plan Update [cache]",
                        sanitize_console_text(plan_text),
                        args.progress,
                        args.progress_chars,
                    )
                (notes_dir / "report_plan.md").write_text(plan_text, encoding="utf-8")
                plan_context = plan_text if len(plan_text) <= pack_limit else pack_text(plan_text)
        elif stage_enabled("plan_check"):
            record_stage("plan_check", "skipped", "missing_evidence")

        if evidence_notes and depth != "brief":
            claim_map = feder_tools.build_claim_map(evidence_notes, max_claims=80)
            claim_map_text = feder_tools.format_claim_map(claim_map)
            (notes_dir / "claim_map.md").write_text(claim_map_text, encoding="utf-8")
            plan_text = feder_tools.attach_evidence_to_plan(plan_text, claim_map, max_evidence=2)
            (notes_dir / "report_plan.md").write_text(plan_text, encoding="utf-8")
            gap_text = feder_tools.build_gap_report(plan_text, claim_map)
            (notes_dir / "gap_finder.md").write_text(gap_text, encoding="utf-8")
            if not is_deep:
                condensed = "\n".join(section for section in [claim_map_text, gap_text] if section)
                evidence_for_writer = condensed or helpers.truncate_text_middle(evidence_notes, pack_limit)
            else:
                evidence_for_writer = evidence_notes
        else:
            evidence_for_writer = evidence_notes
            if stage_enabled("evidence"):
                record_stage("evidence", "skipped", "depth=brief")
        if state:
            if state.evidence_notes and not evidence_notes:
                evidence_notes = state.evidence_notes
            if state.align_evidence and not align_evidence:
                align_evidence = state.align_evidence
            if state.claim_map_text and not claim_map_text:
                claim_map_text = state.claim_map_text
            if state.gap_text and not gap_text:
                gap_text = state.gap_text
            if not condensed and (state.claim_map_text or state.gap_text):
                condensed = "\n".join(section for section in [claim_map_text, gap_text] if section)
            if state.supporting_summary and not supporting_summary:
                supporting_summary = state.supporting_summary
        if evidence_notes:
            if not is_deep and condensed:
                evidence_for_writer = condensed
            elif not evidence_for_writer:
                evidence_for_writer = evidence_notes
        reuse_state_report_for_quality = bool(
            stage_set
            and "writer" not in stage_set
            and stage_enabled("quality")
            and state
            and str(getattr(state, "report", "")).strip()
        )
        if stage_set and "writer" not in stage_set and not reuse_state_report_for_quality:
            if not allow_partial:
                raise ValueError("Writer stage is required for report generation. Include 'writer' in --stages.")
            quality_model = args.quality_model or check_model or args.model
            record_stage("writer", "skipped", "state_only")
            record_stage("quality", "skipped", "state_only")
            workflow_summary, workflow_path = write_workflow_summary(
                stage_status=stage_status,
                stage_order=workflow_stage_order,
                notes_dir=notes_dir,
                run_dir=run_dir,
                template_adjustment_path=template_adjustment_path,
            )
            return PipelineResult(
                report="",
                scout_notes=scout_notes,
                plan_text=plan_text,
                plan_context=plan_context,
                evidence_notes=evidence_notes,
                align_draft=None,
                align_final=None,
                align_scout=align_scout,
                align_plan=align_plan,
                align_evidence=align_evidence,
                template_spec=template_spec,
                template_guidance_text=template_guidance_text,
                template_adjustment_path=template_adjustment_path,
                required_sections=required_sections,
                report_prompt=report_prompt,
                clarification_questions=clarification_questions,
                clarification_answers=clarification_answers,
                output_format=output_format,
                language=language,
                run_dir=run_dir,
                archive_dir=archive_dir,
                notes_dir=notes_dir,
                supporting_dir=supporting_dir,
                supporting_summary=supporting_summary,
                source_triage_text=source_triage_text,
                claim_map_text=claim_map_text,
                gap_text=gap_text,
                context_lines=list(context_lines),
                depth=depth,
                style_hint=style_hint,
                overview_path=overview_path,
                index_file=index_file,
                instruction_file=instruction_file,
                quality_model=quality_model,
                query_id=query_id,
                workflow_summary=workflow_summary,
                workflow_path=workflow_path,
            )
        plan_for_writer = plan_text if is_deep else plan_context
        writer_prompt = agent_runtime.prompt(
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
                figures_enabled=bool(args.extract_figures),
                figures_mode=args.figures_mode,
            ),
            self._agent_overrides,
        )
        writer_model = agent_runtime.model("writer", args.model, self._agent_overrides)
        writer_max, writer_max_source = agent_max_tokens("writer")
        writer_agent = helpers.create_agent_with_fallback(
            self._create_deep_agent,
            writer_model,
            tools,
            writer_prompt,
            backend,
            max_input_tokens=writer_max,
            max_input_tokens_source=writer_max_source,
        )
        plan_limit = pack_limit if pack_limit > 0 else 6000

        def build_writer_sections(evidence_payload: str) -> list[dict]:
            sections = [
                context_section(context_lines),
                make_section(
                    "evidence",
                    "Evidence notes:",
                    evidence_payload,
                    priority="high",
                    base_limit=None,
                    min_limit=1000,
                ),
                make_section(
                    "plan",
                    "Updated plan:",
                    plan_for_writer,
                    priority="high",
                    base_limit=plan_limit,
                    min_limit=800,
                ),
            ]
            if source_triage_text:
                sections.append(
                    make_section(
                        "source_triage",
                        "Source triage (lightweight):",
                        source_triage_text,
                        priority="low",
                        base_limit=triage_limit,
                        min_limit=400,
                        max_lines=triage_line_limit,
                    )
                )
            if is_deep:
                if claim_map_text:
                    sections.append(
                        make_section(
                            "claim_map",
                            "Claim map (lightweight):",
                            claim_map_text,
                            priority="medium",
                            base_limit=guidance_limit,
                            min_limit=400,
                        )
                    )
                if gap_text:
                    sections.append(
                        make_section(
                            "gap_summary",
                            "Gap summary (lightweight):",
                            gap_text,
                            priority="medium",
                            base_limit=guidance_limit,
                            min_limit=400,
                        )
                    )
            if align_evidence:
                sections.append(
                    make_section(
                        "align_evidence",
                        "Alignment notes (evidence):",
                        align_evidence,
                        priority="medium",
                        base_limit=alignment_limit,
                        min_limit=600,
                    )
                )
            if template_guidance_text:
                sections.append(
                    make_section(
                        "template_guidance",
                        "Template guidance:",
                        template_guidance_text,
                        priority="low",
                        base_limit=guidance_limit,
                        min_limit=400,
                        max_lines=guidance_line_limit,
                    )
                )
            if style_hint:
                sections.append(
                    make_section(
                        "style_hint",
                        None,
                        style_hint,
                        priority="high",
                        base_limit=400,
                        min_limit=200,
                    )
                )
            if report_prompt:
                sections.append(
                    make_section(
                        "report_prompt",
                        "Report focus prompt:",
                        report_prompt,
                        priority="high",
                        base_limit=report_prompt_limit,
                        min_limit=800,
                    )
                )
            if clarification_questions and "no_questions" not in clarification_questions.lower():
                sections.append(
                    make_section(
                        "clarification_questions",
                        "Clarification questions:",
                        clarification_questions,
                        priority="medium",
                        base_limit=clarification_limit,
                        min_limit=600,
                    )
                )
            if clarification_answers:
                sections.append(
                    make_section(
                        "clarification_answers",
                        "User clarifications:",
                        clarification_answers,
                        priority="high",
                        base_limit=clarification_limit,
                        min_limit=800,
                    )
                )
            if supporting_summary:
                sections.append(
                    make_section(
                        "supporting_summary",
                        "Supporting web research summary:",
                        supporting_summary,
                        priority="low",
                        base_limit=supporting_limit,
                        min_limit=400,
                        max_lines=supporting_line_limit,
                    )
                )
            return sections

        condensed_evidence = condensed or helpers.truncate_text_middle(evidence_notes, pack_limit)
        writer_budget = resolve_writer_budget(writer_max)
        if reuse_state_report_for_quality:
            report = helpers.normalize_report_paths(state.report, run_dir)
            report = coerce_required_headings(report, required_sections)
            missing_sections = helpers.find_missing_sections(report, required_sections, output_format)
            report = run_structural_repair(report, missing_sections, "Structural Repair")
            record_stage("writer", "skipped", "state_report")
            align_draft = run_alignment_check("draft", report)
        else:
            condensed_ready = bool(condensed_evidence and evidence_for_writer == condensed_evidence)
            writer_sections = build_writer_sections(evidence_for_writer)
            writer_input, _, fallback_used = build_stage_payload(
                writer_sections,
                writer_budget,
                fallback_map={"evidence": condensed_evidence} if condensed_evidence else None,
            )
            condensed_applied = fallback_used or condensed_ready
            try:
                report = self._runner.run(
                    "Writer Draft",
                    writer_agent,
                    {"messages": [{"role": "user", "content": writer_input}]},
                    show_progress=False,
                )
            except Exception as exc:
                if not condensed_applied and is_context_overflow(exc):
                    writer_sections = build_writer_sections(condensed_evidence or evidence_for_writer)
                    writer_input, _, _ = build_stage_payload(
                        writer_sections,
                        writer_budget,
                        fallback_map={"evidence": condensed_evidence} if condensed_evidence else None,
                        force_fallback=True,
                    )
                    report = self._runner.run(
                        "Writer Draft",
                        writer_agent,
                        {"messages": [{"role": "user", "content": writer_input}]},
                        show_progress=False,
                    )
                else:
                    raise
            record_stage("writer", "ran")
            report = helpers.normalize_report_paths(report, run_dir)
            report = coerce_required_headings(report, required_sections)
            retry_needed, retry_reason = report_needs_retry(report)
            if retry_needed:
                retry_input = "\n".join([build_writer_retry_guardrail(retry_reason), "", writer_input])
                report = self._runner.run(
                    "Writer Draft (retry)",
                    writer_agent,
                    {"messages": [{"role": "user", "content": retry_input}]},
                    show_progress=False,
                )
                report = helpers.normalize_report_paths(report, run_dir)
                report = coerce_required_headings(report, required_sections)
            missing_sections = helpers.find_missing_sections(report, required_sections, output_format)
            report = run_structural_repair(report, missing_sections, "Structural Repair")
            align_draft = run_alignment_check("draft", report)
        candidates = [{"label": "draft", "text": report}]
        selected_label = "draft"
        selected_report = report
        selected_eval: Optional[dict] = None
        secondary_label: Optional[str] = None
        secondary_report: Optional[str] = None
        secondary_eval: Optional[dict] = None
        pairwise_notes: list[dict] = []
        quality_model = args.quality_model or check_model or args.model
        if quality_iterations > 0:
            for idx in range(quality_iterations):
                critic_prompt = agent_runtime.prompt(
                    "critic",
                    prompts.build_critic_prompt(language, required_sections),
                    self._agent_overrides,
                )
                critic_model = agent_runtime.model("critic", quality_model, self._agent_overrides)
                critic_max, critic_max_source = agent_max_tokens("critic")
                critic_agent = helpers.create_agent_with_fallback(
                    self._create_deep_agent,
                    critic_model,
                    tools,
                    critic_prompt,
                    backend,
                    max_input_tokens=critic_max,
                    max_input_tokens_source=critic_max_source,
                )
                critic_input = "\n".join(
                    [
                        "Report:",
                        helpers.truncate_text_middle(helpers.normalize_report_paths(report, run_dir), args.quality_max_chars),
                        "",
                        "Evidence notes:",
                        helpers.truncate_text_middle(evidence_notes, args.quality_max_chars),
                        "",
                        "Report focus prompt:",
                        report_prompt or "(none)",
                        "",
                        "Alignment notes (draft):",
                        align_draft or "(none)",
                    ]
                )
                critique = self._runner.run(
                    f"Critique Pass {idx + 1}",
                    critic_agent,
                    {"messages": [{"role": "user", "content": critic_input}]},
                    show_progress=True,
                )
                if "no_changes" in critique.lower():
                    break

                revise_prompt = agent_runtime.prompt(
                    "reviser",
                    prompts.build_revise_prompt(format_instructions, output_format, language),
                    self._agent_overrides,
                )
                revise_model = agent_runtime.model("reviser", quality_model, self._agent_overrides)
                revise_max, revise_max_source = agent_max_tokens("reviser")
                revise_agent = helpers.create_agent_with_fallback(
                    self._create_deep_agent,
                    revise_model,
                    tools,
                    revise_prompt,
                    backend,
                    max_input_tokens=revise_max,
                    max_input_tokens_source=revise_max_source,
                )
                revise_input = "\n".join(
                    [
                        "Original report:",
                        helpers.truncate_text_middle(helpers.normalize_report_paths(report, run_dir), args.quality_max_chars),
                        "",
                        "Critique:",
                        critique,
                        "",
                        "Evidence notes:",
                        helpers.truncate_text_middle(evidence_notes, args.quality_max_chars),
                        "",
                        "Report focus prompt:",
                        report_prompt or "(none)",
                        "",
                        "Alignment notes (draft):",
                        align_draft or "(none)",
                    ]
                )
                report = self._runner.run(
                    f"Revision Pass {idx + 1}",
                    revise_agent,
                    {"messages": [{"role": "user", "content": revise_input}]},
                    show_progress=True,
                )
                candidates.append({"label": f"rev_{idx + 1}", "text": report})
            record_stage("quality", "ran", f"iterations={quality_iterations}")
        elif stage_enabled("quality"):
            record_stage("quality", "skipped", "iterations=0")
        if quality_iterations > 0 and len(candidates) > 1:
            eval_path = notes_dir / "quality_evals.jsonl"
            pairwise_path = notes_dir / "quality_pairwise.jsonl"
            evaluations: list[dict] = []
            evaluator_model = agent_runtime.model("evaluator", quality_model, self._agent_overrides)
            for idx, candidate in enumerate(candidates):
                eval_max, eval_max_source = agent_max_tokens("evaluator")
                evaluation = helpers.evaluate_report(
                    candidate["text"],
                    evidence_notes,
                    report_prompt,
                    template_guidance_text,
                    required_sections,
                    output_format,
                    language,
                    evaluator_model,
                    self._create_deep_agent,
                    tools,
                    backend,
                    args.quality_max_chars,
                    max_input_tokens=eval_max,
                    max_input_tokens_source=eval_max_source,
                )
                evaluation["label"] = candidate["label"]
                evaluation["index"] = idx
                evaluations.append(evaluation)
                helpers.append_jsonl(eval_path, evaluation)
            if args.quality_strategy == "pairwise":
                wins = {idx: 0.0 for idx in range(len(candidates))}
                compare_model = agent_runtime.model("pairwise_compare", quality_model, self._agent_overrides)
                for i in range(len(candidates)):
                    for j in range(i + 1, len(candidates)):
                        compare_max, compare_max_source = agent_max_tokens("pairwise_compare")
                        result = helpers.compare_reports_pairwise(
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
                            self._create_deep_agent,
                            tools,
                            backend,
                            args.quality_max_chars,
                            max_input_tokens=compare_max,
                            max_input_tokens_source=compare_max_source,
                        )
                        result["a"] = candidates[i]["label"]
                        result["b"] = candidates[j]["label"]
                        pairwise_notes.append(result)
                        helpers.append_jsonl(pairwise_path, result)
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
                if top_indices:
                    primary_idx = top_indices[0]
                    selected_report = candidates[primary_idx]["text"]
                    selected_label = candidates[primary_idx]["label"]
                    selected_eval = evaluations[primary_idx]
                    if len(top_indices) > 1:
                        secondary_idx = top_indices[1]
                        secondary_report = candidates[secondary_idx]["text"]
                        secondary_label = candidates[secondary_idx]["label"]
                        secondary_eval = evaluations[secondary_idx]
            else:
                best_idx = max(range(len(candidates)), key=lambda idx: evaluations[idx].get("overall", 0.0))
                selected_report = candidates[best_idx]["text"]
                selected_label = candidates[best_idx]["label"]
                selected_eval = evaluations[best_idx]
        if quality_iterations > 0:
            use_finalizer = bool(secondary_report) or selected_label != "draft"
            if use_finalizer:
                report = run_writer_finalizer(
                    selected_report,
                    selected_label,
                    secondary_report=secondary_report,
                    secondary_label=secondary_label,
                    primary_eval=selected_eval,
                    secondary_eval=secondary_eval,
                    pairwise_notes=pairwise_notes,
                )
            else:
                report = selected_report
        missing_sections = helpers.find_missing_sections(report, required_sections, output_format)
        report = run_structural_repair(report, missing_sections, "Structural Repair (final)")
        align_final = run_alignment_check("final", report)

        workflow_summary, workflow_path = write_workflow_summary(
            stage_status=stage_status,
            stage_order=workflow_stage_order,
            notes_dir=notes_dir,
            run_dir=run_dir,
            template_adjustment_path=template_adjustment_path,
        )

        return PipelineResult(
            report=report,
            scout_notes=scout_notes,
            plan_text=plan_text,
            plan_context=plan_context,
            evidence_notes=evidence_notes,
            align_draft=align_draft,
            align_final=align_final,
            align_scout=align_scout,
            align_plan=align_plan,
            align_evidence=align_evidence,
            template_spec=template_spec,
            template_guidance_text=template_guidance_text,
            template_adjustment_path=template_adjustment_path,
            required_sections=required_sections,
            report_prompt=report_prompt,
            clarification_questions=clarification_questions,
            clarification_answers=clarification_answers,
            output_format=output_format,
            language=language,
            run_dir=run_dir,
            archive_dir=archive_dir,
            notes_dir=notes_dir,
            supporting_dir=supporting_dir,
            supporting_summary=supporting_summary,
            source_triage_text=source_triage_text,
            claim_map_text=claim_map_text,
            gap_text=gap_text,
            context_lines=list(context_lines),
            depth=depth,
            style_hint=style_hint,
            overview_path=overview_path,
            index_file=index_file,
            instruction_file=instruction_file,
            quality_model=quality_model,
            query_id=query_id,
            workflow_summary=workflow_summary,
            workflow_path=workflow_path,
        )

