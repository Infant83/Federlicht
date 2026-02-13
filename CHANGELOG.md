# Changelog

## 1.7.0
- Improve Federnett Ask panel execution UX and readability:
  - replace `Action mode` dropdown with a theme-consistent Plan/Act segmented switch
  - keep mode hint text synchronized with active mode
  - preserve preferences for action mode and artifact-write policy
- Add Ask-panel capability observability:
  - show `Agent 도구/스킬/MCP` capability chips in the panel
  - add per-capability runtime status indicators (`running/done/error/disabled`) with live activity text
  - add stream activity events for `source_index`, `web_research`, and `llm_generate`
- Strengthen help-agent response payloads:
  - include capability descriptors in both sync and streaming responses
  - forward activity telemetry without breaking existing source/done events
- Fix Live Logs line-join issue in streaming jobs:
  - preserve newline boundaries in server-side job log entries
  - keep log rendering readable for Feather/Federlicht stream output
- Add writer artwork-tool traceability:
  - log artwork tool calls to `report_notes/artwork_tool_calls.jsonl` and `report_notes/artwork_tool_calls.md`
  - emit concise `[artwork-tool]` runtime log lines
  - expose Artwork tool log link in report `Miscellaneous` metadata and appendix artifact list when available
- Help documentation update:
  - add Tools/Skills/MCP explanation and extension points in Help modal
- Test coverage additions:
  - metadata rendering for artwork tool log links
  - newline normalization in job log append behavior
  - streaming help-agent tests updated for activity/capabilities events

## 1.6.0
- Strengthen Federnett "Agent 와 작업하기" UX:
  - add left-side thread list with per-run/per-profile scoped conversation sessions
  - keep run-scoped history persistent per thread and restore safely on reopen
  - add answer-selection follow-up action (`선택 내용으로 후속 질문`)
  - add action preview modal before suggested execution (parameter confirmation gate)
  - improve streaming answer behavior and reduce stuck `질문 중...` states on stream completion
- Fix Agent Profiles `Apply to` parsing corruption:
  - remove faulty split behavior that broke tokens (for example `planner` -> `pla`, `er`)
  - replace free-text-only entry with explicit target chips + optional custom targets
  - keep save/load compatibility for existing profile data
- Improve Agent Profiles editor readability and typography baseline for Korean/English mixed content.
- Align Federnett UI panel structure updates (thread rail + answer/sources panes) for cleaner interaction flow.
- Add initial artwork/diagram integration groundwork:
  - introduce optional `artwork` extra in dependency profile
  - add artifact-oriented documentation for diagram/figure agent planning and DeepAgents 0.4 migration policy

## 1.5.1
- Simplify Federlicht/Federnett advanced controls by removing explicit temperature override wiring and keeping `temperature-level` as the single temperature control path.
- Consolidate pipeline control UX into Live Logs:
  - remove the separate Agent Pipeline panel
  - make workflow nodes directly toggleable/clickable for stage control
  - move quality loop control to the workflow `Quality xN` selector (dropdown)
  - default Live Logs view to Markdown (`MD 보기`)
- Improve responsive workflow rendering to reduce horizontal scrollbar pressure in narrow layouts.
- Add output filename collision guidance/suggestion for report generation so users can see and adopt safe suffixed names before run start.
- Strengthen workflow observability by expanding `report_workflow.md/.json` with richer stage timeline/telemetry and diagram-friendly history metadata.
- Harden Federnett Guide Agent model handling:
  - honor explicit model selection without silent fallback when strict selection is requested
  - keep env-driven model resolution (`$OPENAI_MODEL`) and OpenAI-compatible endpoint usage aligned across requests
- Improve report writing policy defaults for citation quality:
  - discourage placeholder citation markers (for example generic `[source]`)
  - prefer concrete URL/path-backed references and cleaner reader-facing prose
- Add/adjust Federnett branding asset placement for clearer header/logo composition.

## 1.5.0
- Federnett workflow pipeline upgraded from a static status strip to an interactive runtime map:
  - stage selection/toggle and drag-reorder reflected in the Live Logs workflow track
  - automatic dependency stage visibility (`auto`) and loop-back feedback cues for quality iterations
  - per-pass runtime telemetry surfaced from Federlicht (`elapsed_ms`, estimated tokens, cache hits, runtime bundle)
- Prompt/template generation and other ad-hoc background tasks are now shown as transient workflow “extra process” spots, improving live observability of non-core pipeline work.
- Live log UX improvements:
  - path-like tokens in raw logs are clickable and open directly in File Preview
  - result node path now follows the actual final output filename (for example `report_full_1.html` when suffixing occurs)
  - primary run buttons now show `Running...` and stay disabled while jobs are active
- Historical run workflow restoration and resume:
  - opening a history log now reconstructs pipeline progress from `report_workflow.json` (with `report_workflow.md` fallback) plus log signals
  - users can select a resume checkpoint stage directly on the workflow track and apply a resume stage preset to Federlicht (`--stages`)
  - one-click draft generation of a resume/update prompt file is wired back into `Prompt File` for iterative reruns
- Version management cleanup across components:
  - package version bumped to `1.5.0`
  - add shared version resolver (`federlicht.versioning`) that prefers local `pyproject.toml` version and falls back safely
  - Feather `__version__` and Federnett HTTP `server_version` now use the shared resolver instead of stale hardcoded strings
  - web research User-Agent now uses Feather version dynamically to prevent drift

## 1.4.1
- Expose Federlicht live log truncation controls in Federnett Advanced:
  - `Progress Chars` -> wires to `--progress-chars`
  - `Max Tool Chars` -> wires to `--max-tool-chars`
- Persist and restore these runtime controls via `report_notes/report_meta.json` so reopening a run restores `max_chars`, `max_tool_chars`, `max_pdf_pages`, and `progress_chars`.
- Add help text update in Federnett modal to document `--progress-chars` behavior and default.

## 1.4.0
- Add Federnett Guide Agent panel (`질문하기`) with repo-aware answers, source citations, and line-focused source preview links.
- Add Feather agentic search mode controls across CLI/UI (`--agentic-search`, `--model`, `--max-iter`) and stream trace visibility in logs.
- Add template control knobs in Federlicht pipeline (`template-rigidity`, `temperature-level` and explicit `temperature`) to balance structure vs. narrative flexibility.
- Improve template rendering/layout groundwork for sidebar TOC styles and stronger preview/report consistency in federlicht templates.
- Fix Federlicht runtime failure in report pipeline by resolving active profile wiring (`NameError: profile is not defined`).
- Fix Python 3.10 compatibility in prompt assembly and clean undefined type-hint references in API/orchestrator paths.
- Clean minor dead code/import noise in Feather/Federnett/Federlicht modules and re-verify build/test/lint health.

## 1.3.0
- Make report byline identity profile-aware: author now resolves in order `--author/--organization` -> agent profile (`author_name`/`organization`) -> prompt `Author:` line -> fallback.
- Add `--organization` to Federlicht and persist `organization` plus profile author metadata in `report_meta.json`.
- Extend agent profile schema with `author_name` and `organization` fields for reusable byline identity.
- Update Federnett Agent Profiles editor to manage `Author name` and optional `Organization`.
- Enforce random 6-digit IDs for new site agent profiles (including New/Clone flows) while keeping legacy site IDs editable.
- Document profile author metadata behavior and add auth-gated memory/DB connector TODOs in `README.md`.

## 1.2.0
- Add run log history indexing (`_log.txt`, `_feather_log.txt`, `_federlicht_log.txt`) and surface it in Recent Jobs.
- Allow historical logs to open in Live Logs with automatic run/form restoration.
- Simplify Recent Jobs into a compact summary card with a modal list view.
- Make Run Studio summary chips (reports/index files) open in File Preview.
- Stabilize Live Logs layout/scroll behavior for consistent visibility.
- Pass model/check-model/depth through prompt generation in Federnett to avoid internal model mismatches.

## 1.1.0
- Add FederHav CLI to draft update requests against an existing report and re-run Federlicht with a chosen agent profile.
- Add Federnett Agent Profiles panel (list/edit/save/delete) with site-scoped profile storage and memory hooks.
- Persist `agent_profile` into `report_meta.json` and restore it when reopening past runs.
- Improve citation rendering by stripping escaped `\\[n\\]` anchors and merging orphaned citation-only lines.
- Move Recent Jobs into a compact hero card near Run Folders and clean up the Live Logs panel framing/scroll behavior.

## 1.0.0
- Introduce **Canvas** in Federnett: open a report from File Preview, select excerpts, write update instructions, auto-generate an update prompt, and re-run Federlicht from the same workspace.
- Replace the standalone Update Report panel with the Canvas-based revision workflow.
- Restore run settings when reopening Past Runs (template/language/model/vision) using `report_notes/report_meta.json`.
- Add Run Studio trash action to move whole runs to a safe trash folder.
- Improve telemetry layout with resizable logs/preview split, collapsible logs, and clearer file preview handling for unsupported binaries (download-first).
- Add new Federnett themes (sage/amber) and darken template editor controls for better focus.

## 0.9.0
- Add shared input trimming across scout/plan/web/evidence/clarifier/writer payloads with priority caps to reduce context overflows.
- Add `--max-tool-chars` to cap cumulative `read_document` output across a run (CLI/API/Federnett).
- Add reducer-backed tool output summarization with chunk artifacts under `report_notes/tool_cache/` and NEEDS_VERIFICATION guidance for citation safety.
- Extend PDF reads with `start_page` support to allow targeted follow-up reads without increasing global limits.
- Add auto verification loop that re-reads NEEDS_VERIFICATION chunk artifacts and appends verification excerpts to evidence notes.
- Strengthen evidence/writer prompts to prefer verification excerpts and enforce safe citation handling.
- Merge orphaned citation-only lines into the preceding sentence to keep inline references readable.
- Enrich references with authors/year/venue metadata using text indices (OpenAlex/arXiv/local) and clearer source labels.
- Soften default template tone and add readability guidance while keeping professional structure.
- Resolve the duplicate truncate helper by splitting it into explicit middle/head variants for safer payload trimming.
- Move supporting web research execution into Feather utilities and keep Federlicht as a thin wrapper.
- Split HTML/Markdown rendering helpers into `federlicht.render.html` for cleaner modular boundaries.
- Add a Federnett custom template editor panel and refactor server helpers into smaller modules for maintainability.
- Add a Federlicht PPTX reader (structured slide text + embedded image extraction) with vision-ready figure candidates.
- Fix Feather local ingest to create `local/raw` and `local/text` folders before copying/extracting files.
- Add Federlicht logging to `_federlicht_log.txt` and mirror Feather logs to `_feather_log.txt`.
- Improve report HTML theme contrast for light templates and show PPTX/extract/log groups in Federnett Run Studio.
- Add Run Studio “Update Report” action to regenerate reports with a user-provided revision prompt.
- Record report update requests in `report_notes/update_history.jsonl` for traceability.
- Add Drag & Drop uploads in Federnett (stored under `site/uploads`) with auto `file:` line insertion.
- Update report prompts now include base report content for edit-only revisions and use date-based update_request filenames.

## 0.8.1
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
