# HiDair Feather Collector

Feather-light knowledge intake for HiDair. This CLI ingests date-named text instructions (YYYYMMDD.txt), runs Tavily search/extract, fetches arXiv papers, and builds an offline-friendly archive of everything it collected. Input can be a single `.txt` file or a folder of `.txt` files.

## Features
- Parse natural-language instructions from date-named `.txt` files.
- Tavily search and content extraction (requires `TAVILY_API_KEY`).
- Optional arXiv metadata fetch; optional PDF download and text extraction.
- Optional YouTube search and transcript capture.
- Writes a reproducible archive per instruction file with logs and an `index.md` summary.
- List and review existing run folders.

## Requirements
- Python 3.9+ recommended.
- Required package: `requests` (declared in `pyproject.toml`).
- Optional packages (extra features, declared as extras):
  - `arxiv` for arXiv metadata/search.
  - `pymupdf` (imported as `fitz`) for PDF-to-text extraction.
  - `youtube-transcript-api` for YouTube transcript capture.
  - `python-docx` / `python-pptx` / `beautifulsoup4` for local file ingestion (docx/pptx/html).
- Optional packages: `deepagents` for report scripts and `markdown` for HTML output (LLM API key required).
- Environment: `TAVILY_API_KEY` must be set for search/extract steps.
- Environment: `YOUTUBE_API_KEY` must be set for YouTube search.
- Optional env: `YOUTUBE_PROXY` or `YOUTUBE_PROXY_HTTP` / `YOUTUBE_PROXY_HTTPS` for transcript access when YouTube blocks direct requests.
- Optional env: `OPENALEX_API_KEY` (used if set) and `OPENALEX_MAILTO` (polite contact string).
- Optional env: `HIDAIR_USER_AGENT` to set a polite `User-Agent` for PDF downloads and OpenAlex requests.
- `requirements.txt` is a convenience bundle for local runs/tests and includes optional deps + pytest.

## Installation
```bash
# Recommended: install the package (editable during development)
python -m pip install -e .
# For a regular install, use: python -m pip install .

# With optional features (arXiv + PDF text):
python -m pip install -e ".[all]"

# Local file ingestion only:
python -m pip install -e ".[local]"

# Only YouTube transcripts:
python -m pip install -e ".[youtube]"

# Deepagents report script:
python -m pip install -e ".[agents]"

# Dependency-only install for run.py / local scripts:
python -m pip install -r requirements.txt
```

## Usage
```bash
hidair-feather --input ./instructions --output ./archive --set-id oled --download-pdf --max-results 8

# Inline query mode (separate items with ';' or newlines):
hidair-feather --query "what is quantum computer; recent 30 days; arXiv:2401.01234; https://aaa.blog" --output ./runs --set-id qc --lang en

# Open-access papers via OpenAlex (optional):
hidair-feather --input ./instructions --output ./archive --openalex --download-pdf

# YouTube search with transcripts:
hidair-feather --input ./instructions --output ./archive --youtube --yt-transcript

# List or review existing runs:
hidair-feather --list ./runs
hidair-feather --review ./runs/20260104_basic
hidair-feather --review ./runs/20260104_basic --review-full
hidair-feather --list ./runs --filter ai
hidair-feather --review ./runs/20260104_basic --format json
hidair-feather --review ./runs/20260104_basic/archive/tavily_search.jsonl

# Or:
python -m hidair_feather --input ./instructions --output ./archive --set-id oled --download-pdf --max-results 8

# Or without installing (local runner):
python run.py --input ./instructions --output ./archive --set-id oled --download-pdf --max-results 8

# Deepagents report generation (requires deepagents + LLM key):
python scripts/deepagents_report.py --run ./runs/20260107_ai-trends --output ./runs/20260107_ai-trends/report.md --lang ko --prompt "Focus on trends, insights, and implications."
# HTML output (markdown conversion requires the optional "markdown" package, included in the agents extra):
python scripts/deepagents_report.py --run ./runs/20260107_ai-trends --output ./runs/20260107_ai-trends/report.html
# Full, multi-step report (deepagents_report_full.py):
python scripts/deepagents_report_full.py --run ./runs/20260104_basic-oa --output ./runs/20260104_basic-oa/report_full.html --lang ko --prompt-file ./examples/instructions/20260104_prompt_OLED.txt
# See scripts/README_deepagents_report_full.md for detailed options.

# Windows wrappers (no install):
# .\hidair-feather.ps1 --input .\instructions --output .\archive --set-id oled --max-results 8
# .\hidair-feather.cmd --input .\instructions --output .\archive --set-id oled --max-results 8
```

Arguments:
- `--input` (required): Folder containing one or more `YYYYMMDD.txt` instruction files, or a single `.txt` file.
- `--query` (required if `--input` is not set): Inline instructions separated by `;` or newlines.
- `--list`: List run folders under a path (default: current directory).
- `--filter`: Filter list entries by queryID substring (case-insensitive). Use with `--list`.
- `--review`: Show outputs for a single run folder or its `archive` path.
- `--review <file.jsonl>`: Show a compact summary of a JSONL file (e.g., `tavily_search.jsonl`).
- `--review-full`: Show full outputs when reviewing a run or JSONL file.
- `--format`: Output format for `--review` (`text` or `json`).
- `--output` (required): Archive root; each run creates `output/<queryID>/`.
- `--days` (default 30): Lookback window for the "recent" arXiv search heuristic.
- `--max-results` (default 8): Max Tavily/arXiv results per query.
- `--download-pdf`: If set, arXiv PDFs are downloaded and converted to text.
- `--no-citations`: Disable citation enrichment for papers (OpenAlex is used by default when available).
- `--lang`: Preferred language for search results (`en`/`eng` or `ko`/`kor`). This is a soft preference only.
- `--no-stdout-log`: Disable console logging (write to `_log.txt` only).
- `--openalex` / `--oa`: Also search OpenAlex for open-access papers (optional; default on when `--download-pdf` is set).
- `--no-openalex`: Disable OpenAlex search (overrides the default when `--download-pdf` is set).
- `--oa-max-results`: Max OpenAlex results per query (defaults to `--max-results`).
- `--youtube`: Enable YouTube search.
- `--no-youtube`: Disable YouTube search.
- `--yt-max-results`: Max YouTube results per query (defaults to `--max-results`).
- `--yt-order`: YouTube search ordering (`relevance`, `date`, `viewCount`, `rating`).
- `--yt-transcript`: Fetch YouTube transcripts (requires `youtube-transcript-api`).
- `--set-id`: Optional keyword appended to the queryID. If omitted, jobs are numbered.

QueryID rules:
- Default: `YYYYMMDD_001`, `YYYYMMDD_002`, ...
- With `--set-id oled`: `YYYYMMDD_oled` (or `YYYYMMDD_oled_001` if multiple input files).

## Instruction File Format
- File name must be `YYYYMMDD.txt`.
- Lines are grouped into sections; blank lines or separator-only lines (`-_=*#`) split sections.
- Site hints apply only to queries in the same section; repeat hints across sections if needed.
- Multiple hint lines in a section are combined.
- Lines detected as URLs are treated as direct extract targets.
- Local file directives are supported:
  - `file: <path>` for a single file
  - `dir: <path>` for a directory (recursive)
  - `glob: <pattern>` for explicit file patterns
  - Optional metadata: `| title="..." | tags=a,b | lang=en`
- Supported local file types: `pdf`, `docx`, `pptx`, `txt`, `md`, `html`, `htm`.
- YouTube URLs (watch/shorts/embed) are handled by the YouTube collector when `--youtube` is enabled.
- YouTube search only runs if a `youtube` hint is present or the query includes `site:youtube.com`/`youtu.be`.
- LinkedIn post URLs are extracted via LinkedIn's public embed page (no comments; includes post text and image URLs).
- Lines containing an arXiv ID (e.g., `arXiv:2401.01234`) are fetched directly.
- Simple site hints: lines equal to `linkedin`, `arxiv`, `news`, or `github` may be used to bias search.
  - `linkedin`: short queries may add `site:linkedin.com`.
  - `github`: code-related queries (e.g., containing "code" or "repo") may add `site:github.com`.
- Everything else is treated as a search query.
- Inline `--query` supports the same section splitters (use blank lines or `---`) and `;` separators.

Example (`instructions/20250101.txt`):
```
LLM evaluation frameworks
linkedin
news

-----
youtube
agentic AI demos for manufacturing

arXiv:2401.01234
https://example.com/blog/post
file: ./local/report.pdf | title="Local report"
dir: ./local/briefings
glob: ./local/**/*.md
```

## Outputs (per instruction file)
Created under `--output/<queryID>/`:
- `instruction/`: Copy of the input instruction file.
- `archive/`: All run outputs:
  - `_job.json`: Parsed job inputs (queries, URLs, arXiv IDs, options) for reproducibility.
  - `_log.txt`: Timestamped log of all actions and errors.
  - `tavily_search.jsonl`: One JSON object per query with Tavily search results; each result includes a short `summary` plus a `query_summary`.
  - `tavily_extract/`: Per-URL extraction JSON (pretty-printed).
  - `local/manifest.jsonl`: One JSON object per local document (path, title, tags, text path).
  - `local/raw/`: Copied local source files.
  - `local/text/`: Extracted text from local files.
  - `web/pdf/`: PDFs downloaded directly from URL instructions (when the URL ends in `.pdf` and `--download-pdf` is set).
  - `web/text/`: Extracted text from `web/pdf` (when `pymupdf` is available).
  - `openalex/works.jsonl`: OpenAlex open-access metadata including `cited_by_count` (when `--openalex` is set).
  - `openalex/pdf/`: OpenAlex PDFs (when `--download-pdf`).
  - `openalex/text/`: Extracted text from OpenAlex PDFs (when `pymupdf` is available).
  - `youtube/videos.jsonl`: YouTube video metadata (when `--youtube` is set).
  - `youtube/transcripts/`: YouTube transcripts named `youtu.be-<id>-<title>.txt` (title truncated to 80 chars) with header metadata (title, URL, tags, summary).
  - `arxiv/papers.jsonl`: arXiv metadata (includes `cited_by_count` when available); includes heuristic recent search entries when applicable.
  - `arxiv/pdf/`: Downloaded arXiv PDFs (when `--download-pdf`).
  - `arxiv/text/`: Extracted text from PDFs (when `--download-pdf` and `pymupdf` available).
  - `<queryID>-index.md`: Human-friendly summary with relative file paths for downstream ingestion.

## Project Layout
- `src/hidair_feather/`: Core package code.
- `tests/`: Unit tests (pytest).
- `examples/`: Sample instruction files.
- `scripts/`: Helper scripts (e.g., deepagents report generator).
- `.backup/`: Archived files moved out of the main tree.
- `run.py`: Local CLI runner without installation.
- `hidair-feather.ps1` / `hidair-feather.cmd`: Convenience wrappers for Windows.

## Testing
```bash
python -m pip install -r requirements.txt
pytest
```

## Lint
```bash
python -m pip install -r requirements.txt
ruff check .
```

## List Output Columns
- `Date`: From `archive/_job.json` if present.
- `Q/U/A`: Query, URL, and arXiv ID counts.
- `Tavily`: `S` if `tavily_search.jsonl` exists; `+E#` for extracted text count.
- `arXiv`: `pdf/txt` counts if `arxiv/papers.jsonl` exists.
- `OpenAlex`: `pdf/txt` counts if `openalex/works.jsonl` exists.
- `YouTube`: `videos/transcripts` counts if `youtube/videos.jsonl` exists.
- `Local`: `raw/text` counts for ingested local files.
- `WebPDF`: `pdf/txt` counts from direct PDF downloads.
- `Index`: `Y` if a `*-index.md` exists.

## JSONL Review Output
- `tavily_search.jsonl` prints one line per query with query text, result counts, result type counts (pdf/arXiv/web), a top result summary, and the query summary.
- Other JSONL files show a short preview with detected keys and limited lines.
- Use `--review-full` to print full JSONL entries or full text outputs.

## Notes and Tips
- Set `TAVILY_API_KEY` in your environment before running.
- Set `YOUTUBE_API_KEY` in your environment before running YouTube search.
- If transcripts fail with `IpBlocked`, set `YOUTUBE_PROXY` (or `YOUTUBE_PROXY_HTTP`/`YOUTUBE_PROXY_HTTPS`) or omit `--yt-transcript`.
- Tavily and arXiv calls include short sleeps to be polite; heavy batches may take time.
- If `arxiv` or `pymupdf` are missing, those features are skipped with runtime errors logged per item.
- The program stops early if no `.txt` files are found in `--input`.
