import datetime as dt
import os
import re
from pathlib import Path
from typing import Any, Dict, List, Optional

import requests

from . import __version__

OPENALEX_BASE = "https://api.openalex.org"
DEFAULT_USER_AGENT = f"Feather/{__version__} (+https://example.invalid)"


def request_headers() -> Dict[str, str]:
    ua = os.getenv("FEATHER_USER_AGENT", DEFAULT_USER_AGENT)
    return {"User-Agent": ua, "Accept": "application/pdf,*/*"}


def openalex_id_short(openalex_id: Optional[str]) -> Optional[str]:
    if not openalex_id:
        return None
    return openalex_id.rstrip("/").split("/")[-1]

def collect_pdf_urls(work: Dict[str, Any]) -> List[str]:
    urls: List[str] = []
    seen = set()

    def add(url: Optional[str]) -> None:
        if not url:
            return
        if url in seen:
            return
        seen.add(url)
        urls.append(url)

    best_oa = work.get("best_oa_location") or {}
    add(best_oa.get("pdf_url"))
    landing = best_oa.get("landing_page_url") or best_oa.get("url")
    if landing and landing.lower().endswith(".pdf"):
        add(landing)

    for loc in work.get("locations", []) or []:
        add(loc.get("pdf_url"))
        loc_landing = loc.get("landing_page_url") or loc.get("url")
        if loc_landing and loc_landing.lower().endswith(".pdf"):
            add(loc_landing)

    return urls


def abstract_from_inverted_index(inverted: Optional[Dict[str, List[int]]]) -> Optional[str]:
    if not inverted:
        return None
    max_pos = -1
    for positions in inverted.values():
        if positions:
            max_pos = max(max_pos, max(positions))
    if max_pos < 0:
        return None
    words = [""] * (max_pos + 1)
    for word, positions in inverted.items():
        if not positions:
            continue
        for pos in positions:
            if 0 <= pos <= max_pos:
                words[pos] = word
    text = " ".join(token for token in words if token)
    return text.strip() or None


def work_to_metadata(work: Dict[str, Any]) -> Dict[str, Any]:
    open_access = work.get("open_access") or {}
    best_oa = work.get("best_oa_location") or {}
    primary = work.get("primary_location") or {}
    source = primary.get("source") or work.get("host_venue") or {}

    authors = []
    for auth in work.get("authorships", []) or []:
        author = auth.get("author") or {}
        name = author.get("display_name")
        if name:
            authors.append(name)

    openalex_id = work.get("id")
    pdf_urls = collect_pdf_urls(work)
    return {
        "openalex_id": openalex_id,
        "openalex_id_short": openalex_id_short(openalex_id),
        "title": work.get("title"),
        "authors": authors,
        "published": work.get("publication_date"),
        "abstract": abstract_from_inverted_index(work.get("abstract_inverted_index")),
        "doi": work.get("doi"),
        "journal": source.get("display_name"),
        "cited_by_count": work.get("cited_by_count"),
        "pdf_url": best_oa.get("pdf_url"),
        "pdf_urls": pdf_urls,
        "landing_page_url": best_oa.get("landing_page_url") or best_oa.get("url") or open_access.get("oa_url"),
        "is_oa": open_access.get("is_oa"),
        "oa_status": open_access.get("oa_status"),
    }


def openalex_search_recent(
    query: str,
    end_date: dt.date,
    days: int,
    max_results: int,
    api_key: Optional[str] = None,
    mailto: Optional[str] = None,
) -> List[Dict[str, Any]]:
    start_date = (end_date - dt.timedelta(days=days)).isoformat()
    end_date_str = end_date.isoformat()
    per_page = min(max_results, 200)
    params = {
        "search": query,
        "filter": f"from_publication_date:{start_date},to_publication_date:{end_date_str},is_oa:true",
        "per-page": per_page,
    }
    if api_key:
        params["api_key"] = api_key
    if mailto:
        params["mailto"] = mailto

    r = requests.get(f"{OPENALEX_BASE}/works", params=params, timeout=60, headers=request_headers())
    r.raise_for_status()
    data = r.json()

    results: List[Dict[str, Any]] = []
    for work in data.get("results", []) or []:
        results.append(work_to_metadata(work))
        if len(results) >= max_results:
            break
    return results


def openalex_download_pdf(
    pdf_url: str,
    out_pdf: Path,
    timeout: int = 120,
    referer: Optional[str] = None,
) -> None:
    out_pdf.parent.mkdir(parents=True, exist_ok=True)
    headers = request_headers()
    if referer:
        headers["Referer"] = referer
    with requests.get(pdf_url, stream=True, timeout=timeout, headers=headers) as r:
        r.raise_for_status()
        with out_pdf.open("wb") as f:
            for chunk in r.iter_content(chunk_size=1024 * 512):
                if chunk:
                    f.write(chunk)


def normalize_doi(value: Optional[str]) -> Optional[str]:
    if not value:
        return None
    doi = value.strip()
    doi = doi.replace("https://doi.org/", "").replace("http://doi.org/", "")
    doi = doi.replace("doi:", "").strip()
    return doi or None


def normalize_arxiv_id(value: Optional[str]) -> Optional[str]:
    if not value:
        return None
    arxiv_id = value.strip()
    arxiv_id = arxiv_id.replace("arxiv:", "").replace("arXiv:", "").strip()
    arxiv_id = re.sub(r"v\d+$", "", arxiv_id)
    return arxiv_id or None


def build_params(api_key: Optional[str], mailto: Optional[str]) -> dict:
    params = {}
    if api_key:
        params["api_key"] = api_key
    if mailto:
        params["mailto"] = mailto
    return params


def openalex_fetch_by_doi(doi: str, api_key: Optional[str], mailto: Optional[str]) -> Optional[Dict[str, Any]]:
    params = build_params(api_key, mailto)
    url = f"{OPENALEX_BASE}/works/https://doi.org/{doi}"
    r = requests.get(url, params=params, timeout=60, headers=request_headers())
    if r.status_code == 404:
        return None
    r.raise_for_status()
    return r.json()


def openalex_fetch_by_arxiv(arxiv_id: str, api_key: Optional[str], mailto: Optional[str]) -> Optional[Dict[str, Any]]:
    params = build_params(api_key, mailto)
    params["filter"] = f"arxiv:{arxiv_id}"
    r = requests.get(f"{OPENALEX_BASE}/works", params=params, timeout=60, headers=request_headers())
    if r.status_code == 404:
        return None
    r.raise_for_status()
    data = r.json()
    results = data.get("results") or []
    if not results:
        return None
    return results[0]


def openalex_get_citations(
    doi: Optional[str],
    arxiv_id: Optional[str],
    api_key: Optional[str] = None,
    mailto: Optional[str] = None,
) -> Optional[int]:
    doi_norm = normalize_doi(doi)
    arxiv_norm = normalize_arxiv_id(arxiv_id)
    work = None
    if doi_norm:
        work = openalex_fetch_by_doi(doi_norm, api_key, mailto)
    if work is None and arxiv_norm:
        work = openalex_fetch_by_arxiv(arxiv_norm, api_key, mailto)
    if not work:
        return None
    return work.get("cited_by_count")
