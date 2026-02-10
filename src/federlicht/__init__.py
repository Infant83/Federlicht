"""Federlicht report generator package."""

from __future__ import annotations

from .versioning import VERSION as __version__

__all__ = ["Reporter", "create_reporter", "PipelineState", "__version__"]


def __getattr__(name: str):
    if name in {"Reporter", "create_reporter"}:
        from .api import Reporter, create_reporter

        return Reporter if name == "Reporter" else create_reporter
    if name == "PipelineState":
        from .orchestrator import PipelineState

        return PipelineState
    raise AttributeError(f"module 'federlicht' has no attribute {name!r}")


def __dir__() -> list[str]:
    return sorted(__all__)
