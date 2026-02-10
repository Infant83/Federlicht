from __future__ import annotations

import argparse
from typing import TYPE_CHECKING, Any, Optional

if TYPE_CHECKING:
    from .report import PipelineState, ReportOutput
else:
    PipelineState = Any
    ReportOutput = Any


def run_pipeline(
    args: argparse.Namespace,
    create_deep_agent=None,
    agent_overrides: Optional[dict] = None,
    config_overrides: Optional[dict] = None,
    state: Optional[PipelineState] = None,
    state_only: bool = False,
) -> ReportOutput:
    from .pipeline_runner_impl import run_pipeline as _run_pipeline

    return _run_pipeline(
        args,
        create_deep_agent=create_deep_agent,
        agent_overrides=agent_overrides,
        config_overrides=config_overrides,
        state=state,
        state_only=state_only,
    )
