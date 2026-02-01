# Changelog

## 0.8.1
- Add shared input trimming across scout/plan/web/evidence/clarifier/writer payloads with priority caps to reduce context overflows.
- Add `--max-tool-chars` to cap cumulative `read_document` output across a run (CLI/API/Federnett).
- Add reducer-backed tool output summarization with chunk artifacts under `report_notes/tool_cache/` and NEEDS_VERIFICATION guidance for citation safety.
- Extend PDF reads with `start_page` support to allow targeted follow-up reads without increasing global limits.
- Add auto verification loop that re-reads NEEDS_VERIFICATION chunk artifacts and appends verification excerpts to evidence notes.
- Strengthen evidence/writer prompts to prefer verification excerpts and enforce safe citation handling.
- Merge orphaned citation-only lines into the preceding sentence to keep inline references readable.
- Enrich references with authors/year/venue metadata using text indices (OpenAlex/arXiv/local) and clearer source labels.
- Soften default template tone and add readability guidance while keeping professional structure.
- Add a Federnett custom template editor panel and refactor server helpers into smaller modules for maintainability.

## 0.8.0
- Add **Federnett**: a web studio wrapper around Feather and Federlicht with an HTTP server, SSE log streaming, background jobs, and kill control.
- Add a static Federnett UI under `site/federnett/` with Feather/Federlicht/Prompt tabs, theme switching, run discovery, and live logs.
- Move the Federnett implementation into a dedicated package at `src/federnett/app.py` and keep `federlicht.federnett` as a compatibility shim.
- Wire the `federnett` console script to `federnett.app:main` and document usage in `README.md`.

## 0.7.0
- Add `--generate-prompt` to scout a run and emit an editable report prompt (saved to `--output` or `instruction/`).
- Add a prompt generator system prompt with Template/Depth/Language headers and scoped guidance for evidence gaps.
- Record report summaries in `report_meta.json` and reuse them during `--site-refresh`.
- Make `--site-refresh` incremental: reuse manifest entries when report `mtime/size` are unchanged to avoid full HTML parsing.
- Add lazy rendering to the site index with “더 보기” pagination for Latest/Archive.
- Add search + template/lang/tag filters that also use lazy rendering for results.
- Enrich site manifest entries with `run`, `report_stem`, `source_mtime`, and `source_size`.
- Add PDF auto-extend reading (`--pdf-extend-pages`, `--pdf-extend-min-chars`) and emit truncation notes when not all pages are scanned.
- Allow `--max-pdf-pages 0` to attempt full PDF reads (documented in `--help`).
- Update API schema to include PDF extension controls.

## 0.6.0
- Split report generation into a reporting orchestrator with subagent stages to reduce `report.py` monolith and isolate pipeline logic.
- Move agent prompt builders into a dedicated reporting module for cleaner reuse and customization.
- Keep CLI output rendering intact while delegating report synthesis to the orchestrator pipeline.
- Route writer inputs through depth-aware context packing to reduce token usage for brief/normal runs while preserving deep evidence paths.
- Normalize HTML/TeX outputs by unwrapping fenced code blocks and stripping full document wrappers to keep body output format-correct.
- Make HTML previews log as plain text and sanitize streamed console output (strip HTML tags) while keeping streaming enabled.
- Add stream summary-only output for writer/repair stages to reduce noisy console output.
- Normalize archive list tool patterns (strip `archive/` prefix) and fall back to `*` when no matches are found.
- Apply `--model` to check/quality models by default unless explicitly overridden.
- Localize format instructions (section/citation/format rules) based on `--lang`.
- Condense writer evidence payload only when the input budget is exceeded, with a retry on context overflow.
- Add `api.create_reporter` to use Federlicht as a Python library, including a callable Reporter wrapper.
- Add stage registry controls (`--stages`, `--skip-stages`) and a Reporter tool wrapper for deepagent integration.
- Cache scout/plan/evidence/plan-check/alignment outputs under `report_notes/cache` and reuse them when inputs are unchanged.
- Expose the full Reporter input schema in `Reporter.as_tool` for deepagent-compatible structured inputs.
- Add pipeline state returns for partial runs and allow `Reporter.write` to finish reports from intermediate state snapshots.
- Add stage registry introspection via `--stage-info`, include stage details in `--agent-info`, and expose `Reporter.stage_info()`.
- Inject a report title derived from the prompt and include it in HTML/Markdown outputs and metadata.
- Record executed stage workflow to `report_notes/report_workflow.md`/`.json` and surface it in the Miscellaneous metadata block.
- Generate a static report hub (`site/index.html` + `site/manifest.json`) and update it after each run when outputs live under the site root (configurable via `--site-output`).
- Add `--site-refresh [path]` to rebuild the site index/manifest by scanning `<site>/runs` for all `report*.html` outputs.
- Add `--tags` to include manual report tags in Misc metadata and site manifests.

## 0.5.1
- Add configurable max input token guardrails for models without profile limits (env/CLI/agent-config) and expose values in `--agent-info`.
- Apply max input token overrides across agents, including quality/evaluation stages and template adjuster.
- Add writer output validation/retry to prevent placeholder/meta responses and enforce required H2 headings in free-format.
- Hide `max_input_tokens_source` from `--agent-info` and clarify `--max-input-tokens` help (underscore alias remains supported).
- Clarify `--lang` alias/pass-through behavior in `--help`.
- Route quality selection through a writer finalizer (pairwise merges via draft handoff) to prevent malformed synth outputs.

## 0.5.0
- Add agent streaming output with debug logging and optional Markdown echo (`--stream`, `--stream-debug`, `--echo-markdown`).
- Add separate check model selection for alignment/plan checks (`--check-model`, default gpt-4o).
- Add free-form report mode that lets the model choose structure while still requiring Risks & Gaps/Critics (`--free-format`).
- Harden structural repair and writer output (append/replace/off modes, debug logs, heading coercion, placeholder retry, no-status-output guardrails).
- Ensure Risks & Gaps/Critics are present across all templates with “Not applicable/해당없음” guidance.
- Default template adjuster to risk-only behavior and improve template adjustment logging.
- Fix filesystem path resolution for report viewers/supporting data under deepagents to avoid outside-root errors.
- Localize alignment-check prompt for Korean.

## 0.4.0
- Treat arXiv abstract URLs as arXiv IDs when `--download-pdf` is enabled (auto PDF download).
- Add optional arXiv source download with TeX/figure manifests (`--arxiv-src`).
- arXiv-derived templates now generate per-section `.tex` files and guidance Markdown files.
- Add `--update-run` to reuse existing run folders and merge new outputs in place.
- Added optional vision model support in Federlicht (`--model-vision`) for figure analysis.
- Documentation updates for installation, workflow, and publishing.
