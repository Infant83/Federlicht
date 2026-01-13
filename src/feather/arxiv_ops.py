import datetime as dt
import os
from pathlib import Path
from typing import Any, Dict, List, Optional

import requests

try:
    import arxiv  # type: ignore
except Exception:
    arxiv = None

try:
    import fitz  # type: ignore
except Exception:
    fitz = None

from . import __version__

ARXIV_AVAILABLE = arxiv is not None
PYMUPDF_AVAILABLE = fitz is not None
DEFAULT_USER_AGENT = f"Feather/{__version__} (+https://example.invalid)"


def request_headers() -> Dict[str, str]:
    ua = os.getenv("FEATHER_USER_AGENT", DEFAULT_USER_AGENT)
    return {"User-Agent": ua, "Accept": "application/pdf,*/*"}


def require_arxiv() -> None:
    if arxiv is None:
        raise RuntimeError("Missing dependency: arxiv (pip install arxiv)")


def require_pymupdf() -> None:
    if fitz is None:
        raise RuntimeError("Missing dependency: pymupdf (pip install pymupdf)")


def search_by_id(arxiv_id: str) -> Optional[Any]:
    require_arxiv()
    search = arxiv.Search(query=f"id:{arxiv_id}", max_results=1)
    return next(search.results(), None)


def result_to_metadata(result: Any) -> Dict[str, Any]:
    return {
        "arxiv_id": result.get_short_id(),
        "title": result.title,
        "authors": [a.name for a in result.authors],
        "published": result.published.isoformat() if result.published else None,
        "updated": result.updated.isoformat() if result.updated else None,
        "summary": result.summary,
        "primary_category": getattr(result, "primary_category", None),
        "categories": list(getattr(result, "categories", []) or []),
        "doi": getattr(result, "doi", None),
        "pdf_url": result.pdf_url,
        "entry_id": result.entry_id,
    }


def arxiv_search_recent(
    query: str,
    end_date: dt.date,
    days: int,
    max_results: int,
) -> List[Dict[str, Any]]:
    """
    Query arXiv using the arxiv python library.
    arXiv does not offer perfect strict date-range filtering via query; we:
    1) sort by SubmittedDate DESC
    2) over-fetch a bit
    3) filter by published timestamp locally
    """
    require_arxiv()

    start_dt = dt.datetime.combine(end_date - dt.timedelta(days=days), dt.time.min)
    end_dt = dt.datetime.combine(end_date, dt.time.max)

    search = arxiv.Search(
        query=query,
        max_results=max_results * 3,
        sort_by=arxiv.SortCriterion.SubmittedDate,
        sort_order=arxiv.SortOrder.Descending,
    )

    results: List[Dict[str, Any]] = []
    for r in search.results():
        if r.published:
            published = r.published
            if published.tzinfo is not None:
                published = published.astimezone(dt.timezone.utc).replace(tzinfo=None)
            if start_dt <= published <= end_dt:
                results.append(result_to_metadata(r))
        if len(results) >= max_results:
            break
    return results


def arxiv_download_pdf(pdf_url: str, out_pdf: Path, timeout: int = 120) -> None:
    out_pdf.parent.mkdir(parents=True, exist_ok=True)
    with requests.get(pdf_url, stream=True, timeout=timeout, headers=request_headers()) as r:
        r.raise_for_status()
        with out_pdf.open("wb") as f:
            for chunk in r.iter_content(chunk_size=1024 * 512):
                if chunk:
                    f.write(chunk)


def pdf_to_text(pdf_path: Path) -> str:
    require_pymupdf()
    doc = fitz.open(pdf_path.as_posix())
    parts: List[str] = []
    for i, page in enumerate(doc, start=1):
        parts.append(f"\n\n===== PAGE {i} =====\n")
        parts.append(page.get_text("text"))
    doc.close()
    return "".join(parts)
