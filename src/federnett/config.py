from __future__ import annotations

from dataclasses import dataclass
from pathlib import Path


@dataclass
class FedernettConfig:
    root: Path
    static_dir: Path
    run_roots: list[Path]
    site_root: Path
