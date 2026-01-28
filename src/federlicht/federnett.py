"""Compatibility shim for federnett.

Federnett now lives under the top-level `federnett` package.
This module remains to avoid breaking old imports.
"""

from federnett.app import build_parser, main

__all__ = ["build_parser", "main"]

if __name__ == "__main__":
    main()
