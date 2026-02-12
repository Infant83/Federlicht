from __future__ import annotations

# ruff: noqa: F401,F403,F405

import math
import re
import time

from . import report as core
from .report import *  # noqa: F401,F403
from . import workflow_stages
from .workflow_trace import write_workflow_summary


WORKFLOW_SUMMARY_LINE_RE = re.compile(r"^\s*\d+\.\s+([a-z_]+):\s+([a-z_]+)(?:\s+\((.*)\))?\s*$")


def _parse_workflow_summary_line(line: str) -> tuple[str, str, str] | None:
    match = WORKFLOW_SUMMARY_LINE_RE.match(str(line or "").strip())
    if not match:
        return None
    stage_name = match.group(1).strip().lower()
    status = match.group(2).strip().lower()
    detail = (match.group(3) or "").strip()
    return stage_name, status, detail


def _flatten_execution_stage_order(execution_plan: list[str]) -> list[str]:
    ordered: list[str] = []
    seen: set[str] = set()
    for stage_name in execution_plan:
        for runtime_stage in workflow_stages.top_level_stage_bundle(stage_name):
            if runtime_stage in STAGE_ORDER and runtime_stage not in seen:
                seen.add(runtime_stage)
                ordered.append(runtime_stage)
    for runtime_stage in STAGE_ORDER:
        if runtime_stage not in seen:
            ordered.append(runtime_stage)
    return ordered


def _merge_workflow_stage_status(pass_summaries: list[list[str]]) -> dict[str, dict[str, str]]:
    merged: dict[str, dict[str, str]] = {}
    for summary in pass_summaries:
        for line in summary:
            parsed = _parse_workflow_summary_line(line)
            if not parsed:
                continue
            stage_name, status, detail = parsed
            current = merged.get(stage_name)
            if status == "disabled" and current and current.get("status") != "disabled":
                continue
            merged[stage_name] = {"status": status, "detail": detail}
    return merged


def _count_cached_stage_hits(summary: list[str], runtime_stages: tuple[str, ...]) -> int:
    if not summary:
        return 0
    selected = set(runtime_stages)
    hits = 0
    for line in summary:
        parsed = _parse_workflow_summary_line(line)
        if not parsed:
            continue
        stage_name, status, _detail = parsed
        if stage_name in selected and status == "cached":
            hits += 1
    return hits


def _estimate_pass_tokens(result: PipelineResult, previous_state: Optional[PipelineState]) -> int:
    ratio = 2.0 if str(getattr(result, "language", "")).lower().startswith("ko") else 4.0
    fields = (
        "scout_notes",
        "plan_text",
        "evidence_notes",
        "claim_map_text",
        "gap_text",
        "report",
    )
    delta_chars = 0
    for field in fields:
        current = str(getattr(result, field, "") or "")
        if not current:
            continue
        prev = str(getattr(previous_state, field, "") or "") if previous_state else ""
        delta_chars += max(0, len(current) - len(prev))
    if delta_chars <= 0:
        return 0
    return int(math.ceil(delta_chars / ratio))

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

    helpers = core
    pipeline_context = PipelineContext(args=args, output_format=output_format, check_model=check_model)
    state_only = state_only or bool(getattr(args, "_state_only", False))
    requested_top = workflow_stages.parse_top_level_stages(
        stages_raw=getattr(args, "stages", None),
        skip_stages_raw=getattr(args, "skip_stages", None),
    )
    canonical_top = workflow_stages.canonical_top_level_order(requested_top)
    execution_plan = workflow_stages.resolve_top_level_execution_plan(requested_top)
    if requested_top:
        requested_text = ",".join(requested_top)
        canonical_text = ",".join(canonical_top) if canonical_top else "(none)"
        execution_text = ",".join(execution_plan) if execution_plan else "(none)"
        print(
            "[workflow] "
            "resume_hint "
            f"requested_top={requested_text} "
            f"canonical_top={canonical_text} "
            f"execution_plan={execution_text}"
        )
    reordered_top = len(requested_top) > 1 and requested_top != canonical_top

    if reordered_top:
        pass_summaries: list[list[str]] = []
        current_state = state
        last_result: Optional[PipelineResult] = None
        last_report_result: Optional[PipelineResult] = None
        for pass_idx, stage_name in enumerate(execution_plan, start=1):
            runtime_bundle = workflow_stages.top_level_stage_bundle(stage_name)
            pass_args = argparse.Namespace(**vars(args))
            pass_args.stages = ",".join(runtime_bundle)
            pass_args.skip_stages = None
            pass_args._disable_stage_dependency_expansion = True
            pass_context = PipelineContext(args=pass_args, output_format=output_format, check_model=check_model)
            pass_orchestrator = ReportOrchestrator(pass_context, helpers, agent_overrides, create_deep_agent)
            pass_start = time.monotonic()
            pass_result = pass_orchestrator.run(state=current_state, allow_partial=True)
            elapsed_ms = max(0, int((time.monotonic() - pass_start) * 1000))
            pass_summaries.append(list(pass_result.workflow_summary or []))
            pass_cache_hits = _count_cached_stage_hits(pass_result.workflow_summary or [], runtime_bundle)
            pass_est_tokens = _estimate_pass_tokens(pass_result, current_state)
            bundle_text = "|".join(runtime_bundle)
            print(
                "[workflow] "
                f"stage={stage_name} status=ran "
                "detail="
                f"pass={pass_idx},elapsed_ms={elapsed_ms},est_tokens={pass_est_tokens},"
                f"cache_hits={pass_cache_hits},runtime={bundle_text}"
            )
            current_state = build_pipeline_state(pass_result)
            last_result = pass_result
            if str(pass_result.report or "").strip():
                last_report_result = pass_result
        if last_result is None:
            orchestrator = ReportOrchestrator(pipeline_context, helpers, agent_overrides, create_deep_agent)
            result = orchestrator.run(state=state, allow_partial=state_only)
        else:
            result = last_result
            if not state_only and not str(result.report or "").strip() and last_report_result:
                result.report = last_report_result.report
                result.align_draft = last_report_result.align_draft
                result.align_final = last_report_result.align_final
                result.quality_model = last_report_result.quality_model
            merged_status = _merge_workflow_stage_status(pass_summaries)
            merged_order = _flatten_execution_stage_order(execution_plan)
            merged_events: list[dict[str, str]] = []
            for pass_idx, summary in enumerate(pass_summaries, start=1):
                for line in summary:
                    parsed = _parse_workflow_summary_line(line)
                    if not parsed:
                        continue
                    stage_name, status, detail = parsed
                    merged_events.append(
                        {
                            "index": str(len(merged_events) + 1),
                            "timestamp": "",
                            "stage": stage_name,
                            "status": status,
                            "detail": f"pass={pass_idx}{(', ' + detail) if detail else ''}",
                        }
                    )
            for stage_name in merged_order:
                merged_status.setdefault(stage_name, {"status": "disabled", "detail": ""})
            workflow_summary, workflow_path = write_workflow_summary(
                stage_status=merged_status,
                stage_order=merged_order,
                notes_dir=result.notes_dir,
                run_dir=result.run_dir,
                template_adjustment_path=result.template_adjustment_path,
                stage_events=merged_events,
            )
            result.workflow_summary = workflow_summary
            result.workflow_path = workflow_path
    else:
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
        profile=core.ACTIVE_AGENT_PROFILE,
    )
    author_label = compose_author_label(author_name, author_organization)
    agent_label = (
        (core.ACTIVE_AGENT_PROFILE.name or "").strip()
        if core.ACTIVE_AGENT_PROFILE and getattr(core.ACTIVE_AGENT_PROFILE, "name", None)
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
    report = remove_placeholder_citations(report)
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
        "temperature_level": args.temperature_level,
        "model_vision": args.model_vision,
        "quality_model": quality_model if args.quality_iterations > 0 else None,
        "quality_iterations": args.quality_iterations,
        "quality_strategy": args.quality_strategy if args.quality_iterations > 0 else "none",
        "template": template_spec.name,
        "depth": result.depth,
        "template_rigidity": args.template_rigidity,
        "template_rigidity_effective": getattr(args, "template_rigidity_effective", {}),
        "template_adjust_mode": args.template_adjust_mode,
        "repair_mode": args.repair_mode,
        "agent_config": getattr(args, "agent_config", None),
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
    if core.ACTIVE_AGENT_PROFILE:
        meta["agent_profile"] = {
            "id": core.ACTIVE_AGENT_PROFILE.profile_id,
            "name": core.ACTIVE_AGENT_PROFILE.name,
            "tagline": core.ACTIVE_AGENT_PROFILE.tagline,
            "author_name": core.ACTIVE_AGENT_PROFILE.author_name,
            "organization": core.ACTIVE_AGENT_PROFILE.organization,
            "version": core.ACTIVE_AGENT_PROFILE.version,
            "apply_to": list(core.ACTIVE_AGENT_PROFILE.apply_to),
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
