from __future__ import annotations

import re

_ARTIFACT_RE = re.compile(r"\[artifact\]\s+Original chunks:\s+(\S+)")
_CHUNK_RE = re.compile(r"\[chunk_(\d{3})\]")


def parse_verification_requests(text: str) -> list[tuple[str, str]]:
    """Parse NEEDS_VERIFICATION lines into (artifact_dir, chunk_file) pairs."""
    if not text:
        return []
    latest_artifact = ""
    requests: list[tuple[str, str]] = []
    for line in text.splitlines():
        artifact_match = _ARTIFACT_RE.search(line)
        if artifact_match:
            latest_artifact = artifact_match.group(1).strip()
        if "NEEDS_VERIFICATION" not in line or not latest_artifact:
            continue
        for chunk in _CHUNK_RE.findall(line):
            requests.append((latest_artifact, f"chunk_{chunk}.txt"))
    return requests

