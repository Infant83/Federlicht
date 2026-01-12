# deepagents_report_full.py

In-depth, multi-step report generator for a HiDair Feather run folder. It reads the archived sources (JSONL indices, PDFs, transcripts, local docs), synthesizes insights, and produces a narrative report with inline citations and a numbered References section.

## Install
```bash
# Deepagents + markdown renderer
python -m pip install -e ".[agents]"

# Optional: PDF text extraction
python -m pip install -e ".[all]"
```

You also need the LLM provider credentials required by `deepagents` (for example, the API key for the model you use).

## Quick start
```bash
python scripts/deepagents_report_full.py \
  --run ./runs/20260104_basic-oa \
  --output ./runs/20260104_basic-oa/report_full.html \
  --lang ko \
  --prompt-file ./examples/instructions/20260104_prompt_OLED.txt
```

Output format is inferred from the file extension:
- `.md` for Markdown
- `.html` for HTML (adds an interactive side-panel viewer)
- `.tex` for LaTeX (wraps the report body in a LaTeX template)

## Templates
Templates define the required H2 section order and optional style guidance.

Built-in templates live under `scripts/templates/`:
- `default`
- `executive_brief`
- `trend_scan`
- `technical_deep_dive`
- `mit_tech_review`
- `mit_tech_review_10_breakthroughs`
- `quanta_magazine`
- `nature_reviews`
- `review_of_modern_physics`
- `annual_review`
- `prl_perspective`
- `prl_manuscript`
- `arxiv_preprint`
- `nature_journal`
- `acs_review`

Select a template explicitly (both `--template` and `--templates` are accepted):
```bash
python scripts/deepagents_report_full.py --run ./runs/20260104_basic-oa --output ./runs/20260104_basic-oa/report_full.html --templates trend_scan
```

Or set it in the prompt file:
```
Template: executive_brief
```

If you pass a template path that does not exist, the basename is looked up in `scripts/templates/`.

Preview a template without running a report:
```bash
python scripts/deepagents_report_full.py --preview-template quanta_magazine
python scripts/deepagents_report_full.py --preview-template all --preview-output ./scripts/templates
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
Each built-in template ships with a matching CSS preset under `scripts/templates/styles/`.
Add a `css:` line in the template header to select the preset:
```
---
name: quanta_magazine
css: quanta_magazine.css
---
```
CSS paths are resolved relative to the template file; if missing, the loader falls back to the built-in `scripts/templates/styles/` folder. Preview output (`--preview-template`) includes the template CSS automatically.

## LaTeX output
When `--output` ends with `.tex`, the report body is written in LaTeX and wrapped with a template file.
Built-in LaTeX templates live alongside the Markdown templates in `scripts/templates/` (e.g., `default.tex`, `prl_revtex4-2.tex`).
Select them via the `latex:` field in each template header or by choosing a template that already maps to one.

By default, `.tex` output also triggers PDF compilation (via `latexmk` or `pdflatex`).
Disable it with `--no-pdf`.

Common LaTeX class dependencies:
- `revtex4-2` for PRL-style output (`prl_revtex4-2.tex`)
- `achemso` for ACS-style output (`acs_review.tex`)

Example:
```bash
python scripts/deepagents_report_full.py \
  --run ./runs/20260104_basic-oa \
  --output ./runs/20260104_basic-oa/report_full.tex \
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
- `report_views/`: HTML viewer pages for files (HTML output only).
- `supporting/<timestamp>/`: web research outputs (when `--web-search` is enabled).

The report output also appends a small `Miscellaneous` section with runtime metadata.

## Web research (optional)
Enable online enrichment using Tavily:
```bash
python scripts/deepagents_report_full.py \
  --run ./runs/20260104_basic-oa \
  --output ./runs/20260104_basic-oa/report_full.html \
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
python scripts/deepagents_report_full.py \
  --run ./runs/20260104_basic-oa \
  --output ./runs/20260104_basic-oa/report_full.html \
  --supporting-dir ./runs/20260104_basic-oa/supporting/20260111_090114
```

## Quality loops
Use critique/revision passes to refine the report:
```bash
python scripts/deepagents_report_full.py \
  --run ./runs/20260104_basic-oa \
  --output ./runs/20260104_basic-oa/report_full.html \
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
Hidair assisted and prompted by "Author Name" - YYYY-MM-DD HH:MM
```
Set it via `--author`, or include a line like `Author: Your Name` in the prompt file. If omitted, the default is:
`Hyun-Jung Kim / AI Governance Team`.

## Citations and References
- Inline citations use numeric brackets, for example `[1]`.
- A numbered `References` section is appended automatically.
- Citation counts appear when available (OpenAlex metadata).
- If a report cites an index JSONL file, the References section expands it into the underlying source URLs.

## HTML viewer behavior
When output is `.html`, links inside the report open in a side panel:
- `Open raw` opens the file or URL in a new tab.
- Markdown and JSON/JSONL are rendered for readability.
- Math expressions are rendered with MathJax.

## Key options (summary)
- `--model`: LLM model name (default `gpt-5.2` if supported).
- `--alignment-check` / `--no-alignment-check`: Validate alignment with the report prompt at each stage.
- `--overwrite-output`: Overwrite output file instead of creating `_1`, `_2`, ... copies.
- `--template`: Template name or path (default: `auto`).
- `--quality-strategy`: `pairwise` (default) or `best_of`.
- `--max-files`: Max files returned by listing tool.
- `--max-chars`: Max chars returned by file reader.
- `--max-pdf-pages`: Max PDF pages to extract per read.
- `--max-refs`: Max references appended to the report.
- `--notes-dir`: Override `report_notes/` location.
- `--progress` / `--no-progress`: Show or hide progress snippets.

## Troubleshooting
- `deepagents is required`: install with `python -m pip install -e ".[agents]"`.
- `Archive folder not found`: pass a valid run folder containing `archive/`.
- `Web research skipped: missing TAVILY_API_KEY`: set `TAVILY_API_KEY` or omit `--web-search`.
