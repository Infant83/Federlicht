#!/usr/bin/env python3
# -*- coding: utf-8 -*-

"""
Convenience runner for the local package without installation.
"""

from pathlib import Path
import sys

ROOT = Path(__file__).resolve().parent
SRC = ROOT / "src"
if SRC.exists():
    sys.path.insert(0, str(SRC))

from feather.cli import main  # noqa: E402


if __name__ == "__main__":
    raise SystemExit(main())
