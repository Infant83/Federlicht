Example inputs you can run quickly.

```bash
python -m pip install -e .
python -m feather --input ./examples/instructions --output ./runs --set-id example

# Or without installing:
python run.py --input ./examples/instructions --output ./runs --set-id example

# Run all curated examples:
python examples/test_run.py --output ./runs
```

## Running test_run.py
```bash
python examples/test_run.py --output ./runs
python examples/test_run.py --only basic --only iccv25 --output ./runs
python examples/test_run.py --skip-download-pdf --output ./runs
python examples/test_run.py --no-openalex --output ./runs
python examples/test_run.py --no-youtube --output ./runs
python examples/test_run.py --dry-run
```

## Example cases

### 1) Simple keyword queries (no PDFs)
Uses `examples/instructions/20260104.txt`.

```bash
python -m feather --input ./examples/instructions/20260104.txt --output ./runs --set-id basic
```

### 1b) Open-access papers via OpenAlex (PDF download)
Uses the same file and adds OA search across journals (including open access in Nature when available).

```bash
python -m feather --input ./examples/instructions/20260104.txt --output ./runs --set-id basic-oa --download-pdf
```

Outputs of interest for LLM inputs:
- `runs/<queryID>/archive/openalex/works.jsonl` (open-access metadata)
- `runs/<queryID>/archive/openalex/pdf/*.pdf` (PDFs, when available)
- `runs/<queryID>/archive/openalex/text/*.txt` (PDF text, when `pymupdf` is available)
- `runs/<queryID>/archive/<queryID>-index.md` (relative paths to all outputs)

### 1c) ICCV 2025 + GitHub code (OpenAlex + Tavily)
Uses `examples/instructions/20251015.txt`. Consider expanding the date range to capture the conference window.

```bash
python -m feather --input ./examples/instructions/20251015.txt --output ./runs --set-id iccv25 --download-pdf --days 180
```

Notes:
- `github` as a hint will bias code-related queries toward `site:github.com`.
- OpenAlex only returns open-access works; some ICCV papers may not have OA PDFs.

### 2) arXiv metadata + PDF/text extraction
Uses `examples/instructions/20260105.txt`. Requires optional deps.

```bash
python -m pip install -e ".[all]"
python -m feather --input ./examples/instructions/20260105.txt --output ./runs --set-id arxiv --download-pdf
```

Outputs of interest for LLM inputs:
- `runs/<queryID>/archive/arxiv/papers.jsonl` (metadata)
- `runs/<queryID>/archive/arxiv/text/*.txt` (PDF text, when `--download-pdf`)
- `runs/<queryID>/archive/<queryID>-index.md` (relative paths to all outputs)

### 3) Mixed queries + URLs + arXiv IDs
Uses `examples/instructions/20260106.txt`.

```bash
python -m feather --input ./examples/instructions/20260106.txt --output ./runs --set-id mixed --max-results 5
```

Outputs of interest for LLM inputs:
- `runs/<queryID>/archive/tavily_search.jsonl` (includes per-result `summary` and `query_summary`)
- `runs/<queryID>/archive/tavily_extract/*.txt`
- `runs/<queryID>/archive/<queryID>-index.md` (relative paths to all outputs)

### 4) AI trends + CES 2026 + conferences (multi-source)
Uses `examples/instructions/20260107.txt`. This is a heavier run; consider lowering result caps.

```bash
python -m feather --input ./examples/instructions/20260107.txt --output ./runs --set-id ai-trends --days 30 --max-results 5 --oa-max-results 2 --download-pdf --lang en
```

### 5) Quantum computing + AI + industry + YouTube (with journals)
Uses `examples/instructions/20260108.txt`. This includes queries that work well for YouTube, plus arXiv IDs and major journal searches.

```bash
python -m feather --input ./examples/instructions/20260108.txt --output ./runs --set-id qc-youtube --youtube --yt-transcript --yt-order date --max-results 5 --yt-max-results 5
```

Notes:
- Requires `YOUTUBE_API_KEY` in your environment.
- `--yt-transcript` needs `youtube-transcript-api`. Omit it if you only want metadata.

### 6) Sectioned instructions with per-section hints
Uses `examples/instructions/20260109.txt`. Each section has its own hints (e.g., `linkedin`, `news`, `youtube`, `github`).

```bash
python -m feather --input ./examples/instructions/20260109.txt --output ./runs --set-id sectioned --max-results 5 --youtube
```

Notes:
- Hints only apply within the section they appear in.
- Repeat hint lines across sections if you want them to apply broadly.

### 6b) Deepagents report for the basic-oa run
Generate an LLM report from the archived outputs.

```bash
python -m pip install -e ".[agents]"
python -m feather --input ./examples/instructions/20260104.txt --output ./runs --set-id basic-oa --download-pdf
python scripts/deepagents_report.py --run ./runs/20260104_basic-oa --output ./runs/20260104_basic-oa/report.md --lang ko --prompt-file ./examples/instructions/20260104_prompt_OLED.txt
python scripts/deepagents_report.py --run ./runs/20260104_basic-oa --output ./runs/20260104_basic-oa/report.html --lang ko --prompt-file ./examples/instructions/20260104_prompt_OLED.txt
```

### 6c) Deepagents in-depth report (multi-step)
Runs a scout + evidence + writer pipeline and optionally saves notes.

```bash
python -m pip install -e ".[agents]"
python -m feather --input ./examples/instructions/20260104.txt --output ./runs --set-id basic-oa --download-pdf
python scripts/deepagents_report_full.py --run ./runs/20260104_basic-oa --output ./runs/20260104_basic-oa/report_full.md --notes-dir ./runs/20260104_basic-oa/report_notes --lang ko --prompt-file ./examples/instructions/20260104_prompt_OLED.txt --quality-iterations 5
python scripts/deepagents_report_full.py --run ./runs/20260104_basic-oa --output ./runs/20260104_basic-oa/report_full.html --lang ko --prompt-file ./examples/instructions/20260104_prompt_OLED.txt --quality-iterations 5
python scripts/deepagents_report_full.py --run ./runs/20260104_basic-oa --output ./runs/20260104_basic-oa/report_full.html --lang ko --prompt-file ./examples/instructions/20260104_prompt_OLED.txt --quality-iterations 2 --web-search

Notes:
- `--web-search` will create `./runs/20260104_basic-oa/supporting/<timestamp>` and store `web_search.jsonl`, `web_fetch.jsonl`, and extracted texts.
- Requires `TAVILY_API_KEY` in the environment.
- Reports now include a `Critics` section and numbered citations with a `References` list.
- You can set the report byline with `--author "Name / Team"` or add `Author: Name / Team` inside the prompt file.

### 7) Quantum computing for materials + OLED emitters (industry + academia)
Uses `examples/instructions/20260110.txt` and a report prompt at `examples/instructions/20260110_prompt_QC_OLED.txt`.

```bash
python -m feather --input ./examples/instructions/20260110.txt --output ./runs --set-id qc-oled --download-pdf --days 365 --max-results 5 --oa-max-results 5 --lang en
python scripts/deepagents_report_full.py --run ./runs/20260110_qc-oled --output ./runs/20260110_qc-oled/report_full.html --lang ko --prompt-file ./examples/instructions/20260110_prompt_QC_OLED.txt --quality-iterations 2 --web-search
```

Notes:
- Requires `TAVILY_API_KEY` for web search support.
```
