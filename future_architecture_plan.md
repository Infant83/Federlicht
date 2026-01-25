# Future Architecture Plan (Stable Evidence Pipeline)

## Goal
- Preserve long-document context without truncation loss.
- Keep evidence traceable to source chunks.
- Separate "reading/navigation" from "writing" to reduce hallucinations and improve depth.

## Current Pipeline (Summary)
- Scout/Plan/Evidence/Writer pass a single combined prompt.
- read_document is a one-shot read with max_chars/max_pdf_pages.
- Long documents get truncated; writer only sees summaries.
- Quality loop may synthesize candidates and can output meta text.

## Proposed Pipeline (Stable Architecture)
### 1) Ingestion + Indexing (Non-LLM)
- Scan archive/ for all sources (pdf/text/html extracts).
- Build a document index and chunk index up front.
- Prefer extracted text; fall back to full PDF text extraction if missing.

### 2) Chunking
- Split documents into chunks by heading/page/offset.
- Store chunk metadata and a short summary.
- Maintain stable IDs for traceability.

### 3) Navigation / Retrieval (LLM)
- Decide which documents/chunks to read next.
- Tools:
  - list_docs()
  - list_chunks(doc_id)
  - search_doc(doc_id, query)
  - read_chunk(chunk_id)

### 4) Evidence Curation (LLM)
- Read selected chunks and write claims with citations.
- Output claims.jsonl (claim -> chunk refs).

### 5) Writing (LLM)
- Writer consumes claims + gap report + plan only.
- No direct reading in writer; request-more-reading routed to Navigation.

### 6) Validation
- Structural checks for headings and required sections.
- Retry or fallback if synthesis outputs meta text.

## Data Artifacts (Proposed)
- doc_index.jsonl
  - doc_id, title, type, source_url, local_path, text_path, pdf_path,
    year, authors, keywords, page_count, char_count
- chunk_index.jsonl
  - doc_id, chunk_id, page_range, char_range, heading, summary, path
- claims.jsonl
  - claim_id, claim_text, strength, chunk_refs, source_url
- reading_plan.jsonl
  - step_id, rationale, doc_id, chunk_ids
- gap_report.md
  - missing sections / missing evidence summary

## Agent Roles (Proposed)
- Scout: builds initial reading map using doc_index/chunk_index.
- Navigator: chooses chunks to read based on plan and gaps.
- Evidence: extracts claims from selected chunks.
- Writer: composes report from claims and plan only.
- Validator: checks structure + language compliance.

## Tool/API Additions (Proposed)
- list_docs()
- list_chunks(doc_id)
- search_doc(doc_id, query, top_k)
- read_chunk(chunk_id)
- read_pdf_pages(doc_id, page_range) (for scanned PDFs)
- ocr_page_image(page_image) (optional)

## Token + Memory Strategy
- Keep full text on disk; send only summaries + chunk IDs to LLM.
- Use short summaries in plan/evidence; open raw chunks only on demand.
- Avoid passing full reports into quality loop without size limits.

## Implementation Phases
1) Build indexer + chunk store (doc_index + chunk_index).
2) Add Navigation agent and chunk tools.
3) Update Evidence to use chunk retrieval + claims.jsonl.
4) Update Writer to consume claims/gap report only.
5) Add OCR/vision fallback for scanned PDFs.

## Risks + Mitigations
- More IO and preprocessing time -> cache chunk indexes per run.
- More moving parts -> add run_overview metadata + logs.
- OCR noise -> only use when text extraction fails.
