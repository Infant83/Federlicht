from __future__ import annotations

import datetime as dt
import json
import re
import urllib.parse
from pathlib import Path
from typing import Iterable, Optional

WORD_RE = re.compile(r"[A-Za-z]{2,}|[\uac00-\ud7a3]{2,}")
YEAR_RE = re.compile(r"\b(19|20)\d{2}\b")
PLAN_STEP_RE = re.compile(r"^\s*-\s*\[[ xX]\]\s+")
REF_BLOCK_RE = re.compile(r"\[([^\]]+)\]")
MATH_SEGMENT_RE = re.compile(r"(\$\$.*?\$\$|\$.*?\$|\\\(.+?\\\)|\\\[.+?\\\])", re.DOTALL)
DELTA_E_RE = re.compile(r"\u0394E\s*_\s*\{?\s*ST\s*\}?", re.IGNORECASE)
DELTA_LATEX_RE = re.compile(r"\\Delta\s+E\s*_\s*\{?\s*ST\s*\}?", re.IGNORECASE)
ESTATE_RE = re.compile(r"\bE\(\s*([ST])\s*_?\s*(\d+|n)\s*\)", re.IGNORECASE)
STATE_RE = re.compile(r"\b([ST])\s*_\s*(\d+|n)\b")
INLINE_CODE_RE = re.compile(r"(`[^`]*`)")
FORMULA_HINT_RE = re.compile(r"(=|\\[A-Za-z]+|[_^])")
STATE_PAIR_RE = re.compile(r"\bS\s*1\s*/\s*T\s*1\b", re.IGNORECASE)

INDEX_ONLY_HINTS = (
    "tavily_search.jsonl",
    "openalex/works.jsonl",
    "arxiv/papers.jsonl",
    "youtube/videos.jsonl",
    "local/manifest.jsonl",
)


def iter_jsonl(path: Path) -> Iterable[dict]:
    try:
        with path.open("r", encoding="utf-8", errors="replace") as handle:
            for line in handle:
                line = line.strip()
                if not line:
                    continue
                try:
                    yield json.loads(line)
                except json.JSONDecodeError:
                    continue
    except FileNotFoundError:
        return


def safe_filename(text: str, max_len: int = 120) -> str:
    text = re.sub(r"[^\w\-.]+", "_", text, flags=re.UNICODE).strip("_")
    return text[:max_len] if len(text) > max_len else text


def tokenize(text: str) -> list[str]:
    if not text:
        return []
    return WORD_RE.findall(text.lower())


def extract_year(value: Optional[str]) -> Optional[int]:
    if not value:
        return None
    match = YEAR_RE.search(str(value))
    if not match:
        return None
    try:
        return int(match.group(0))
    except ValueError:
        return None


def normalize_url(url: Optional[str]) -> Optional[str]:
    if not url:
        return None
    raw = url.strip()
    if not raw:
        return None
    try:
        parsed = urllib.parse.urlsplit(raw)
        cleaned = parsed._replace(fragment="").geturl()
        return cleaned
    except Exception:
        return raw


def domain_from_url(url: Optional[str]) -> Optional[str]:
    if not url:
        return None
    try:
        return urllib.parse.urlsplit(url).netloc.lower() or None
    except Exception:
        return None


def _collect_tavily_extract_map(extract_dir: Path, run_dir: Path) -> dict[str, str]:
    mapping: dict[str, str] = {}
    if not extract_dir.exists():
        return mapping
    for path in extract_dir.glob("*.txt"):
        name = path.stem
        parts = name.split("_", 1)
        if len(parts) == 2:
            mapping[parts[1]] = f"./{path.relative_to(run_dir).as_posix()}"
    return mapping


def _collect_youtube_transcripts(transcript_dir: Path, run_dir: Path) -> dict[str, str]:
    mapping: dict[str, str] = {}
    if not transcript_dir.exists():
        return mapping
    for path in transcript_dir.glob("*.txt"):
        name = path.name
        match = re.search(r"youtu\.be-([A-Za-z0-9_-]{6,})-", name)
        if not match:
            continue
        mapping[match.group(1)] = f"./{path.relative_to(run_dir).as_posix()}"
    return mapping


def build_source_index(
    archive_dir: Path,
    run_dir: Path,
    supporting_dir: Optional[Path] = None,
    max_items: int = 5000,
) -> list[dict]:
    entries: list[dict] = []
    seen: set[str] = set()

    def add_entry(entry: dict) -> None:
        key = entry.get("url") or entry.get("local_path") or entry.get("text_path") or entry.get("pdf_path")
        if not key:
            return
        if key in seen:
            return
        seen.add(key)
        entries.append(entry)

    def rel(path: Path) -> str:
        try:
            return f"./{path.relative_to(run_dir).as_posix()}"
        except Exception:
            return path.as_posix()

    openalex = archive_dir / "openalex" / "works.jsonl"
    if openalex.exists():
        for entry in iter_jsonl(openalex):
            work = entry.get("work") or entry
            short_id = work.get("openalex_id_short")
            title = work.get("title")
            url = normalize_url(work.get("landing_page_url") or work.get("doi") or work.get("openalex_id"))
            year = extract_year(work.get("published"))
            cited_by = work.get("cited_by_count")
            text_path = None
            pdf_path = None
            if short_id:
                cand_text = archive_dir / "openalex" / "text" / f"{short_id}.txt"
                if cand_text.exists():
                    text_path = rel(cand_text)
                cand_pdf = archive_dir / "openalex" / "pdf" / f"{short_id}.pdf"
                if cand_pdf.exists():
                    pdf_path = rel(cand_pdf)
            add_entry(
                {
                    "id": f"openalex:{short_id or ''}".strip(":"),
                    "type": "openalex",
                    "title": title,
                    "url": url,
                    "year": year,
                    "cited_by_count": cited_by,
                    "text_path": text_path,
                    "pdf_path": pdf_path,
                    "source_path": rel(openalex),
                }
            )

    arxiv = archive_dir / "arxiv" / "papers.jsonl"
    if arxiv.exists():
        for entry in iter_jsonl(arxiv):
            paper = entry.get("paper") or entry
            arxiv_id = paper.get("arxiv_id")
            title = paper.get("title")
            url = normalize_url(paper.get("entry_id") or paper.get("pdf_url"))
            year = extract_year(paper.get("published"))
            text_path = None
            pdf_path = None
            if arxiv_id:
                cand_text = archive_dir / "arxiv" / "text" / f"{arxiv_id}.txt"
                if cand_text.exists():
                    text_path = rel(cand_text)
                cand_pdf = archive_dir / "arxiv" / "pdf" / f"{arxiv_id}.pdf"
                if cand_pdf.exists():
                    pdf_path = rel(cand_pdf)
            add_entry(
                {
                    "id": f"arxiv:{arxiv_id or ''}".strip(":"),
                    "type": "arxiv",
                    "title": title,
                    "url": url,
                    "year": year,
                    "text_path": text_path,
                    "pdf_path": pdf_path,
                    "source_path": rel(arxiv),
                }
            )

    tavily_search = archive_dir / "tavily_search.jsonl"
    tavily_extract_dir = archive_dir / "tavily_extract"
    tavily_map = _collect_tavily_extract_map(tavily_extract_dir, run_dir)
    if tavily_search.exists():
        for entry in iter_jsonl(tavily_search):
            results = entry.get("result", {}).get("results") or entry.get("results") or []
            for item in results:
                url = normalize_url(item.get("url"))
                if not url:
                    continue
                title = item.get("title")
                score = item.get("score")
                extract_path = None
                safe = safe_filename(url)
                if safe in tavily_map:
                    extract_path = tavily_map.get(safe)
                add_entry(
                    {
                        "id": f"web:{safe}",
                        "type": "tavily",
                        "title": title,
                        "url": url,
                        "score": score,
                        "extract_path": extract_path,
                        "source_path": rel(tavily_search),
                    }
                )

    youtube = archive_dir / "youtube" / "videos.jsonl"
    transcript_dir = archive_dir / "youtube" / "transcripts"
    transcript_map = _collect_youtube_transcripts(transcript_dir, run_dir)
    if youtube.exists():
        for entry in iter_jsonl(youtube):
            videos = []
            if isinstance(entry.get("videos"), list):
                videos = entry.get("videos") or []
            elif isinstance(entry.get("video"), dict):
                videos = [entry.get("video")]
            for item in videos:
                video_id = item.get("video_id")
                url = normalize_url(item.get("url"))
                title = item.get("title")
                year = extract_year(item.get("published_at"))
                transcript_path = transcript_map.get(video_id) if video_id else None
                add_entry(
                    {
                        "id": f"youtube:{video_id or ''}".strip(":"),
                        "type": "youtube",
                        "title": title,
                        "url": url,
                        "year": year,
                        "text_path": transcript_path,
                        "source_path": rel(youtube),
                    }
                )

    local_manifest = archive_dir / "local" / "manifest.jsonl"
    if local_manifest.exists():
        for entry in iter_jsonl(local_manifest):
            title = entry.get("title") or entry.get("path")
            text_path = entry.get("text_path")
            add_entry(
                {
                    "id": entry.get("doc_id"),
                    "type": "local",
                    "title": title,
                    "url": None,
                    "local_path": entry.get("path"),
                    "text_path": text_path,
                    "tags": entry.get("tags") or [],
                    "source_path": rel(local_manifest),
                }
            )

    if supporting_dir and supporting_dir.exists():
        web_search = supporting_dir / "web_search.jsonl"
        web_fetch = supporting_dir / "web_fetch.jsonl"
        if web_search.exists():
            for entry in iter_jsonl(web_search):
                results = entry.get("result", {}).get("results") or entry.get("results") or []
                for item in results:
                    url = normalize_url(item.get("url"))
                    if not url:
                        continue
                    title = item.get("title")
                    score = item.get("score")
                    add_entry(
                        {
                            "id": f"supporting:{safe_filename(url)}",
                            "type": "supporting",
                            "title": title,
                            "url": url,
                            "score": score,
                            "source_path": rel(web_search),
                        }
                    )
        if web_fetch.exists():
            for entry in iter_jsonl(web_fetch):
                url = normalize_url(entry.get("url"))
                title = entry.get("title")
                pdf_path = entry.get("pdf_path")
                text_path = entry.get("text_path") or entry.get("extract_path")
                add_entry(
                    {
                        "id": f"supporting_fetch:{safe_filename(url or title or '')}",
                        "type": "supporting",
                        "title": title,
                        "url": url,
                        "pdf_path": pdf_path,
                        "text_path": text_path,
                        "source_path": rel(web_fetch),
                    }
                )

    return entries[:max_items]


def write_jsonl(path: Path, items: Iterable[dict]) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    with path.open("w", encoding="utf-8") as handle:
        for item in items:
            handle.write(json.dumps(item, ensure_ascii=False) + "\n")


def rank_sources(
    sources: list[dict],
    focus_text: str,
    top_k: int = 12,
) -> list[dict]:
    focus_tokens = set(tokenize(focus_text))
    scored: list[tuple[float, dict]] = []
    current_year = dt.datetime.now().year

    type_weight = {
        "openalex": 1.0,
        "arxiv": 0.95,
        "local": 0.9,
        "supporting": 0.7,
        "tavily": 0.6,
        "youtube": 0.5,
    }

    for entry in sources:
        title = entry.get("title") or ""
        summary = entry.get("summary") or ""
        tokens = set(tokenize(f"{title} {summary}"))
        overlap = len(tokens & focus_tokens) / max(1, len(focus_tokens))
        year = entry.get("year")
        year_score = 0.0
        if isinstance(year, int) and year > 1900:
            delta = max(0, current_year - year)
            year_score = max(0.0, 1.0 - (delta / 10.0))
        cited = entry.get("cited_by_count") or 0
        cited_score = min(1.0, float(cited) / 100.0) if cited else 0.0
        text_bonus = 0.2 if entry.get("text_path") or entry.get("pdf_path") else 0.0
        t_weight = type_weight.get(entry.get("type"), 0.5)
        score = (t_weight * 0.5) + (overlap * 0.8) + (year_score * 0.3) + (cited_score * 0.2) + text_bonus
        entry = dict(entry)
        entry["score"] = round(score, 3)
        scored.append((score, entry))

    scored.sort(key=lambda item: item[0], reverse=True)
    return [item[1] for item in scored[:top_k]]


def format_source_triage(items: list[dict]) -> str:
    if not items:
        return "(no sources ranked)"
    lines = []
    for entry in items:
        title = entry.get("title") or "(untitled)"
        url = entry.get("url") or ""
        entry_type = entry.get("type") or "source"
        year = entry.get("year")
        score = entry.get("score")
        text_path = entry.get("text_path") or entry.get("pdf_path") or entry.get("extract_path")
        meta = []
        if isinstance(score, (int, float)):
            meta.append(f"score={score:.2f}")
        if year:
            meta.append(f"year={year}")
        if entry.get("cited_by_count"):
            meta.append(f"cited_by={entry.get('cited_by_count')}")
        if text_path:
            meta.append(f"text={text_path}")
        meta_str = "; ".join(meta) if meta else "no meta"
        line = f"- [{entry_type}] {title}"
        if url:
            line += f" — {url}"
        line += f" ({meta_str})"
        lines.append(line)
    return "\n".join(lines)


def extract_refs(text: str) -> list[str]:
    refs: list[str] = []
    for block in REF_BLOCK_RE.findall(text or ""):
        for part in re.split(r"[;|,]", block):
            token = part.strip().strip("()")
            if token:
                refs.append(token)
    refs.extend(re.findall(r"https?://[^\s\]]+", text or ""))
    refs.extend(re.findall(r"\./[^\s\]]+", text or ""))
    refs.extend(re.findall(r"/archive/[^\s\]]+", text or ""))
    cleaned = []
    for ref in refs:
        ref = ref.strip().rstrip(").,;")
        if not ref:
            continue
        cleaned.append(ref)
    return cleaned


def build_claim_map(evidence_text: str, max_claims: int = 80) -> list[dict]:
    if not evidence_text:
        return []
    claims: list[dict] = []
    seen: set[str] = set()
    for raw in evidence_text.splitlines():
        line = raw.strip()
        if not line:
            continue
        if not line.startswith(("-", "*", "•")):
            continue
        claim = re.sub(r"^[\-\*\u2022]\s*", "", line).strip()
        if not claim:
            continue
        claim_text = re.sub(r"\[[^\]]+\]", "", claim).strip()
        if not claim_text:
            continue
        if claim_text in seen:
            continue
        seen.add(claim_text)
        refs = extract_refs(line)
        evidence_strength = _classify_evidence_strength(refs)
        flags = _classify_flags(refs)
        claims.append(
            {
                "claim": claim_text,
                "evidence": refs,
                "evidence_strength": evidence_strength,
                "flags": flags,
            }
        )
        if len(claims) >= max_claims:
            break
    return claims


def _classify_evidence_strength(refs: list[str]) -> str:
    if not refs:
        return "none"
    strong = any(
        ref.endswith(".pdf")
        or "/text/" in ref
        or "doi.org" in ref
        or "arxiv.org" in ref
        for ref in refs
    )
    if strong:
        return "high"
    medium = any(
        "tavily_extract" in ref
        or "youtube/transcripts" in ref
        or "/local/text" in ref
        or "/web_text" in ref
        for ref in refs
    )
    return "medium" if medium else "low"


def _classify_flags(refs: list[str]) -> list[str]:
    flags: list[str] = []
    if not refs:
        return ["no_evidence"]
    if all(any(hint in ref for hint in INDEX_ONLY_HINTS) for ref in refs):
        flags.append("index_only")
    if all("/supporting/" in ref for ref in refs):
        flags.append("supporting_only")
    return flags


def format_claim_map(claims: list[dict]) -> str:
    if not claims:
        return "(no claims extracted)"
    lines = ["Claim | Evidence | Strength | Flags", "--- | --- | --- | ---"]
    for entry in claims:
        claim = entry.get("claim") or ""
        evidence = entry.get("evidence") or []
        strength = entry.get("evidence_strength") or "none"
        flags = ",".join(entry.get("flags") or [])
        ev_text = "; ".join(evidence[:3])
        if len(evidence) > 3:
            ev_text += f" (+{len(evidence)-3} more)"
        lines.append(f"{claim} | {ev_text or '(none)'} | {strength} | {flags or '-'}")
    return "\n".join(lines)


def attach_evidence_to_plan(plan_text: str, claims: list[dict], max_evidence: int = 2) -> str:
    if not plan_text:
        return plan_text
    claim_tokens = [
        (entry, set(tokenize(entry.get("claim") or ""))) for entry in claims if entry.get("claim")
    ]
    updated: list[str] = []
    for raw in plan_text.splitlines():
        line = raw.rstrip()
        if not PLAN_STEP_RE.match(line):
            updated.append(line)
            continue
        step_text = PLAN_STEP_RE.sub("", line)
        tokens = set(tokenize(step_text))
        scored: list[tuple[int, dict]] = []
        for entry, c_tokens in claim_tokens:
            overlap = len(tokens & c_tokens)
            if overlap:
                scored.append((overlap, entry))
        scored.sort(key=lambda item: item[0], reverse=True)
        evidence: list[str] = []
        for _, entry in scored[:5]:
            for ref in entry.get("evidence") or []:
                if ref not in evidence:
                    evidence.append(ref)
                if len(evidence) >= max_evidence:
                    break
            if len(evidence) >= max_evidence:
                break
        if evidence and "Evidence:" not in line:
            line = f"{line} | Evidence: {', '.join(evidence)}"
        updated.append(line)
    return "\n".join(updated)


def build_gap_report(plan_text: str, claims: list[dict]) -> str:
    missing_claims = [c for c in claims if not (c.get("evidence") or [])]
    index_only = [c for c in claims if "index_only" in (c.get("flags") or [])]
    steps_missing = []
    for raw in plan_text.splitlines():
        line = raw.strip()
        if PLAN_STEP_RE.match(line) and "Evidence:" not in line:
            steps_missing.append(PLAN_STEP_RE.sub("", line).strip())

    lines = ["Gaps Summary"]
    if steps_missing:
        lines.append("Plan steps missing evidence:")
        lines.extend([f"- {step}" for step in steps_missing[:10]])
        if len(steps_missing) > 10:
            lines.append(f"- ... and {len(steps_missing) - 10} more")
    if missing_claims:
        lines.append("Claims missing evidence:")
        for entry in missing_claims[:10]:
            lines.append(f"- {entry.get('claim')}")
        if len(missing_claims) > 10:
            lines.append(f"- ... and {len(missing_claims) - 10} more")
    if index_only:
        lines.append("Claims supported only by index files:")
        for entry in index_only[:10]:
            lines.append(f"- {entry.get('claim')}")
        if len(index_only) > 10:
            lines.append(f"- ... and {len(index_only) - 10} more")
    if len(lines) == 1:
        return "Gaps Summary\n- None detected."
    return "\n".join(lines)


def normalize_math_expressions(text: str) -> str:
    if not text:
        return text
    text = _normalize_bracket_math_blocks(text)
    lines = text.splitlines()
    out_lines: list[str] = []
    in_code_block = False
    for raw in lines:
        stripped = raw.strip()
        if stripped.startswith("```"):
            in_code_block = not in_code_block
            out_lines.append(raw)
            continue
        if in_code_block:
            out_lines.append(raw)
            continue
        out_lines.append(_normalize_math_inline(raw))
    return "\n".join(out_lines)


def _normalize_math_inline(line: str) -> str:
    if not line:
        return line
    parts = INLINE_CODE_RE.split(line)
    out_parts: list[str] = []
    for part in parts:
        if not part:
            continue
        if part.startswith("`") and part.endswith("`"):
            out_parts.append(part)
            continue
        out_parts.append(_normalize_math_segments(part))
    return "".join(out_parts)


def _normalize_math_segments(text: str) -> str:
    if not text:
        return text
    segments = MATH_SEGMENT_RE.split(text)
    out: list[str] = []
    for segment in segments:
        if not segment:
            continue
        if MATH_SEGMENT_RE.fullmatch(segment):
            out.append(segment)
            continue
        out.append(_apply_math_replacements(segment))
    return "".join(out)


def _apply_math_replacements(text: str) -> str:
    if not text:
        return text
    updated = STATE_PAIR_RE.sub(r"$S_1/T_1$", text)
    updated = DELTA_E_RE.sub(r"$\\Delta E_{ST}$", updated)
    updated = DELTA_LATEX_RE.sub(r"$\\Delta E_{ST}$", updated)
    updated = ESTATE_RE.sub(lambda m: f"$E({m.group(1).upper()}_{m.group(2)})$", updated)
    # Avoid nesting: split again on math markers after inserting new ones.
    parts = MATH_SEGMENT_RE.split(updated)
    out: list[str] = []
    for part in parts:
        if not part:
            continue
        if MATH_SEGMENT_RE.fullmatch(part):
            out.append(part)
            continue
        out.append(STATE_RE.sub(lambda m: f"${m.group(1).upper()}_{m.group(2)}$", part))
    return "".join(out)


def _normalize_bracket_math_blocks(text: str) -> str:
    lines = text.splitlines()
    out: list[str] = []
    idx = 0
    while idx < len(lines):
        line = lines[idx].strip()
        if line == "[" and idx + 2 < len(lines) and lines[idx + 2].strip() == "]":
            formula = lines[idx + 1].strip()
            if formula and FORMULA_HINT_RE.search(formula):
                out.extend(["$$", formula, "$$"])
                idx += 3
                continue
        out.append(lines[idx])
        idx += 1
    return "\n".join(out)
