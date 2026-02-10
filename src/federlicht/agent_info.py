from __future__ import annotations

import argparse
from typing import TYPE_CHECKING, Any, Optional

if TYPE_CHECKING:
    from .report import TemplateSpec
else:
    TemplateSpec = Any


def build_agent_info(
    args: argparse.Namespace,
    output_format: str,
    language: str,
    report_prompt: Optional[str],
    template_spec: TemplateSpec,
    template_guidance_text: str,
    required_sections: list[str],
    free_format: bool = False,
    agent_overrides: Optional[dict] = None,
) -> dict:
    from .agent_info_impl import build_agent_info as _build_agent_info

    return _build_agent_info(
        args,
        output_format,
        language,
        report_prompt,
        template_spec,
        template_guidance_text,
        required_sections,
        free_format=free_format,
        agent_overrides=agent_overrides,
    )
