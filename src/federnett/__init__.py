"""Federnett web studio package."""

__all__ = ["build_parser", "main"]


def main(*args, **kwargs):
    # Import lazily so `python -m federnett.app` does not warn.
    from .app import main as _main

    return _main(*args, **kwargs)


def build_parser(*args, **kwargs):
    from .app import build_parser as _build_parser

    return _build_parser(*args, **kwargs)
