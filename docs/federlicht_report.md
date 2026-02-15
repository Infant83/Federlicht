# Federlicht Report CLI

In-depth, multi-step report generator in the Federlicht platform. It reads archived sources from Feather runs (JSONL indices, PDFs, transcripts, local docs), synthesizes insights, and produces narrative reports with inline citations and a numbered References section.

## Install
```bash
# PyPI install (distribution name):
python -m pip install federlicht[report-lite]

# Deepagents + markdown renderer
python -m pip install -e ".[agents]"

# Optional: AGPL/commercial pymupdf path (review license policy first)
python -m pip install federlicht[report]

# Optional: full feature bundle including PDF figure tooling
python -m pip install -e ".[all]"

# Federlicht-focused bundle (report + PDF tooling)
python -m pip install -e ".[report]"

# Optional: artwork helpers for local chart/diagram generation
python -m pip install -e ".[artwork]"
```

License note:
- Core package is MIT.
- `pymupdf` is dual-licensed (AGPL/commercial), and is included in `report` / `all`.
- If you need permissive-only dependency posture, prefer `report-lite`.

You also need the LLM provider credentials required by `deepagents` (for example, the API key for the model you use).
For OpenAI-compatible local models (e.g., `qwen3-*`), set `OPENAI_BASE_URL` (or `OPENAI_API_BASE`) and `OPENAI_API_KEY`.

Diagram tooling notes:
- Mermaid rendering in HTML/report viewers works via client-side JavaScript (no local binary required).
- Mermaid artifact export (`artwork_mermaid_render`) requires Mermaid CLI:
  - `npm i -g @mermaid-js/mermaid-cli` (check: `mmdc --version`)
- D2 export is optional and requires the `d2` CLI:
  - install (Windows): `winget install -e --id Terrastruct.D2`
  - if PATH is not reflected yet, set `D2_BIN` to full path (e.g., `C:\Program Files\D2\d2.exe`).
- Python diagrams export (`artwork_diagrams_render`) requires:
  - python packages: `diagrams`, `graphviz`
  - Graphviz CLI (`dot`) binary
  - if PATH is not reflected yet, set `GRAPHVIZ_DOT` to full path (e.g., `C:\Program Files\Graphviz\bin\dot.exe`).
- If D2/diagrams renderers are unavailable, artwork tools fall back to Mermaid snippets.

## Quick start
```bash
federlicht \
  --run ./examples/runs/20260104_oled \
  --output ./examples/runs/20260104_oled/report_full.html \
  --lang ko \
  --prompt-file ./examples/instructions/20260104_prompt_oled.txt
```

Module entrypoint is equivalent:
```bash
python -m federlicht.report --run ./examples/runs/20260104_oled --output ./examples/runs/20260104_oled/report_full.html --lang ko --prompt-file ./examples/instructions/20260104_prompt_oled.txt
```

Output format is inferred from the file extension:
- `.md` for Markdown
- `.html` for HTML (adds an interactive side-panel viewer)
- `.tex` for LaTeX (wraps the report body in a LaTeX template)

## Templates
Templates define the required H2 section order and optional style guidance.

Built-in templates are managed under `src/federlicht/templates/` (repo) and packaged as `federlicht/templates/` at install time:
- `default`
- `executive_brief`
- `trend_scan`
- `technical_deep_dive`
- `mit_tech_review`
- `mit_tech_review_10_breakthroughs`
- `linkedin_review`
- `quanta_magazine`
- `nature_reviews`
- `review_of_modern_physics`
- `annual_review`
- `prl_perspective`
- `prl_manuscript`
- `arxiv_preprint`
- `nature_journal`
- `acs_review`

Override lookup with `FEDERLICHT_TEMPLATES_DIR` (falls back to `FEATHER_TEMPLATES_DIR`).

Select a template explicitly (both `--template` and `--templates` are accepted):
```bash
federlicht --run ./examples/runs/20260104_oled --output ./examples/runs/20260104_oled/report_full.html --templates trend_scan
```

Or set it in the prompt file:
```
Template: executive_brief
```

If you pass a template path that does not exist, the basename is looked up in the built-in templates folder.

Preview a template without running a report:
```bash
federlicht --preview-template quanta_magazine
federlicht --preview-template all --preview-output ./src/federlicht/templates
```

## Template File Format
Templates are Markdown with a simple header block:
```
---
name: executive_brief
description: Executive summary format.
tone: Concise, decision-focused.
audience: Technical leaders.
latex: default.tex
section: Executive Summary
section: Key Findings
section: Risks & Gaps
guide Executive Summary: 4-6 sentences, no bullets.
writer_guidance: Emphasize decisions and near-term actions.
---
```
Anything after the header block is treated as additional guidance.

## Template CSS presets
Each built-in template ships with a matching CSS preset under `src/federlicht/templates/styles/` (repo) and `federlicht/templates/styles/` (installed package).
Add a `css:` line in the template header to select the preset:
```
---
name: quanta_magazine
css: quanta_magazine.css
---
```
CSS paths are resolved relative to the template file; if missing, the loader falls back to the built-in templates styles folder. Preview output (`--preview-template`) includes the template CSS automatically.

## LaTeX output
When `--output` ends with `.tex`, the report body is written in LaTeX and wrapped with a template file.
Built-in LaTeX templates live alongside the Markdown templates in `src/federlicht/templates/` (repo) and `federlicht/templates/` (installed package) (e.g., `default.tex`, `prl_revtex4-2.tex`).
Select them via the `latex:` field in each template header or by choosing a template that already maps to one.

By default, `.tex` output also triggers PDF compilation (via `latexmk` or `pdflatex`).
Disable it with `--no-pdf`.

Common LaTeX class dependencies:
- `revtex4-2` for PRL-style output (`prl_revtex4-2.tex`)
- `achemso` for ACS-style output (`acs_review.tex`)

Example:
```bash
federlicht \
  --run ./examples/runs/20260104_oled \
  --output ./examples/runs/20260104_oled/report_full.tex \
  --template prl_manuscript
```

## Inputs
- `--run` (required): Path to a run folder or its `archive/` folder.
- `--prompt` / `--prompt-file`: Report focus prompt. The prompt is appended to the report for reproducibility.
- `--interactive`: Let the agent ask clarification questions.
- `--answers` / `--answers-file`: Pre-supply answers to clarifications.
- `--lang`: Language preference (default `ko`).

## Output artifacts
The script writes additional artifacts under the run folder:
- `report_notes/`: scout notes, evidence notes, prompt, clarification Q/A.
- `report_notes/quality_evals.jsonl`: per-iteration evaluation scores (when quality loops run).
- `report_notes/quality_pairwise.jsonl`: pairwise comparison notes (pairwise strategy).
- `report_notes/report_meta.json`: runtime metadata (duration, model, format, etc.).
- `report_notes/figures_candidates.jsonl`: figure candidates extracted from referenced PDFs.
- `report_notes/figures_selected.txt`: user selection file (one candidate ID per line).
- `report_notes/figures.jsonl`: selected figures inserted into the report.
- `report_assets/figures/`: extracted PDF figures (PNG/JPG).
- `report_views/`: HTML viewer pages for files (HTML output only).
- `supporting/<timestamp>/`: web research outputs (when `--web-search` is enabled).

The report output also appends a small `Miscellaneous` section with runtime metadata.

## PDF figure extraction (optional)
If enabled, embedded images are extracted from referenced PDFs and inserted near the section that cites the source.
This preserves provenance (source PDF + page) without interpreting the chart content.

Default workflow is two-stage:
1) Run once to generate candidates and a preview (`report_views/figures_preview.html`).
2) Add selected candidate IDs to `report_notes/figures_selected.txt` and rerun.

Default is `--figures-mode auto` (insert all candidates). Use `select` to require manual selection.

Optional: add a custom caption in the selection file:
```
fig-001 | Overview of the model architecture
fig-002 | Dataset distribution summary
```

Preview-only (no report regeneration):
```bash
federlicht \
  --run ./examples/runs/20260104_oled \
  --output ./examples/runs/20260104_oled/report_full.html \
  --figures-preview
```

```bash
federlicht \
  --run ./examples/runs/20260104_oled \
  --output ./examples/runs/20260104_oled/report_full.html \
  --figures \
  --figures-max-per-pdf 4 \
  --figures-min-area 12000 \
  --figures-renderer auto \
  --figures-dpi 150
```

Options:
- `--figures` / `--no-figures`: enable or disable figure extraction (default: enabled).
- `--figures-max-per-pdf`: cap the number of images per PDF.
- `--figures-min-area`: discard small icons/logos (area in pixels squared).
- `--figures-renderer`: render vector pages when embedded images are absent (`auto`, `pdfium`, `poppler`, `mupdf`, `none`).
- `--figures-dpi`: render quality for vector pages.
- `--figures-mode`: `auto` (default) or `select`.
- `--figures-select`: path to a selection file (defaults to `report_notes/figures_selected.txt`).
- `--figures-preview`: generate `figures_preview.html` from an existing report and exit.
- `--model-vision`: optional vision model for figure analysis (uses `OPENAI_BASE_URL_VISION` / `OPENAI_API_KEY_VISION` if set).

Requires `pymupdf` (already included in `.[all]`). For vector-only PDFs, install:
- `pypdfium2` + `pillow` (default, pure Python).
- Optional fallbacks: Poppler (`pdftocairo`) or MuPDF (`mutool`).
If `opencv-python` is installed, Federlicht detects figure regions and crops rendered pages automatically.
If `pdfplumber` is installed, simple figure captions are attached when found.

## Web research (optional)
Enable online enrichment using Tavily:
```bash
federlicht \
  --run ./examples/runs/20260104_oled \
  --output ./examples/runs/20260104_oled/report_full.html \
  --web-search \
  --web-max-queries 4 \
  --web-max-results 5 \
  --web-max-fetch 6
```
Requirements:
- `TAVILY_API_KEY` in the environment.
- `requests` (already included).
- `beautifulsoup4` improves HTML-to-text extraction (optional).

Reuse a previous supporting folder:
```bash
federlicht \
  --run ./examples/runs/20260104_oled \
  --output ./examples/runs/20260104_oled/report_full.html \
  --supporting-dir ./examples/runs/20260104_oled/supporting/20260111_090114
```

## Quality loops
Use critique/revision passes to refine the report:
```bash
federlicht \
  --run ./examples/runs/20260104_oled \
  --output ./examples/runs/20260104_oled/report_full.html \
  --quality-iterations 2 \
  --quality-max-chars 12000
```
Optional: `--quality-model` to use a different model for critiques.
Quality selection strategy:
- `--quality-strategy pairwise` (default): compare candidate reports pairwise, then synthesize the top two.
- `--quality-strategy best_of`: pick the highest-scoring candidate without synthesis.

## Author line
The report header includes:
```
Federlicht assisted and prompted by "Author Name" - YYYY-MM-DD HH:MM
```
Set it via `--author` (and optionally `--organization`), or include a line like `Author: Your Name` in the prompt file.
If omitted, profile metadata is used when available, otherwise fallback is `Federlicht Writer`.

## Citations and References
- Inline citations use numeric brackets, for example `[1]`.
- A numbered `References` section is appended automatically.
- Citation counts appear when available (OpenAlex metadata).
- If a report cites an index JSONL file, the References section expands it into the underlying source URLs.

## Transparency and source notice
- Reports append an `AI Transparency and Source Notice` block at the end (`Miscellaneous` section).
- The notice declares AI-assisted generation, high-stakes verification guidance, and third-party source rights caveats.
- Report Hub (`site/index.html`) shows the same policy note in the footer for shared publishing contexts.

## HTML viewer behavior
When output is `.html`, links inside the report open in a side panel:
- `Open raw` opens the file or URL in a new tab.
- Markdown and JSON/JSONL are rendered for readability.
- Math expressions are rendered with MathJax.
- Mermaid code fences are rendered as diagrams.

## Artwork agent (writer subagent)
- The writer stage can delegate diagram generation to an internal `artwork_agent` subagent.
- Primary output is Mermaid snippets (flowchart/timeline) for inline insertion.
- `mermaid_render` is available when Mermaid CLI (`mmdc`) is installed, and can export SVG/PNG/PDF under `report_assets/artwork/`.
- Optional D2 path: when `d2` CLI is installed, the agent can render SVG artifacts under `report_assets/artwork/`.
- This path is best used for workflow maps, timelines, architecture blocks, and compact explanatory figures.

## Key options (summary)
- `--model`: LLM model name (default `gpt-5.2` if supported).
- `--model` note: if `OPENAI_BASE_URL` is set and the model name is not OpenAI (`gpt-*`/`o*`), Federlicht uses `langchain_openai.ChatOpenAI` for OpenAI-compatible endpoints.
- `--model-vision`: Optional vision model name for figure analysis; set `OPENAI_BASE_URL_VISION` and `OPENAI_API_KEY_VISION` for on-prem endpoints.
- `--alignment-check` / `--no-alignment-check`: Validate alignment with the report prompt at each stage.
- `--overwrite-output`: Overwrite output file instead of creating `_1`, `_2`, ... copies.
- `--template`: Template name or path (default: `auto`).
- `--quality-strategy`: `pairwise` (default) or `best_of`.
- `--max-files`: Max files returned by listing tool.
- `--max-chars`: Max chars returned by file reader.
- `--max-pdf-pages`: Max PDF pages to extract per read.
- `--figures` / `--no-figures`: Enable or disable embedded PDF figures.
- `--figures-max-per-pdf`: Max figures extracted per PDF.
- `--figures-min-area`: Minimum image area to keep (px^2).
- `--figures-renderer`: Renderer for vector pages when embedded images are missing.
- `--figures-dpi`: DPI for page rendering.
- `--max-refs`: Max references appended to the report.
- `--notes-dir`: Override `report_notes/` location.
- `--progress` / `--no-progress`: Show or hide progress snippets.

## Troubleshooting
- `deepagents is required`: install with `python -m pip install -e ".[agents]"`.
- `Archive folder not found`: pass a valid run folder containing `archive/`.
- `Web research skipped: missing TAVILY_API_KEY`: set `TAVILY_API_KEY` or omit `--web-search`.
- `OpenAI-compatible model requested but langchain-openai missing`: install with `python -m pip install langchain-openai` and set `OPENAI_BASE_URL`/`OPENAI_API_KEY`.
