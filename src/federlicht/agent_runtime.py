from __future__ import annotations

from dataclasses import dataclass
from typing import Any, Optional, Sequence


@dataclass(frozen=True)
class ResolvedAgent:
    name: str
    model: str
    system_prompt: str
    enabled: bool
    max_input_tokens: Optional[int]
    max_input_tokens_source: str


class AgentRuntime:
    """Single resolution path for agent config (prompt/model/enabled/token budget)."""

    def __init__(
        self,
        *,
        args: Any,
        helpers: Any,
        overrides: Optional[dict] = None,
        create_deep_agent: Any = None,
        backend: Any = None,
    ) -> None:
        self._args = args
        self._helpers = helpers
        self._overrides = overrides or {}
        self._create_deep_agent = create_deep_agent
        self._backend = backend

    def enabled(self, name: str, default: bool, overrides: Optional[dict] = None) -> bool:
        active = self._overrides if overrides is None else overrides
        return self._helpers.resolve_agent_enabled(name, default, active)

    def prompt(self, name: str, default_prompt: str, overrides: Optional[dict] = None) -> str:
        active = self._overrides if overrides is None else overrides
        return self._helpers.resolve_agent_prompt(name, default_prompt, active)

    def model(self, name: str, default_model: str, overrides: Optional[dict] = None) -> str:
        active = self._overrides if overrides is None else overrides
        return self._helpers.resolve_agent_model(name, default_model, active)

    def max_input_tokens(
        self,
        name: str,
        overrides: Optional[dict] = None,
    ) -> tuple[Optional[int], str]:
        active = self._overrides if overrides is None else overrides
        return self._helpers.resolve_agent_max_input_tokens(name, self._args, active)

    def resolve(
        self,
        *,
        name: str,
        default_model: str,
        default_prompt: str,
        default_enabled: bool = True,
        overrides: Optional[dict] = None,
    ) -> ResolvedAgent:
        model = self.model(name, default_model, overrides)
        system_prompt = self.prompt(name, default_prompt, overrides)
        enabled = self.enabled(name, default_enabled, overrides)
        max_input_tokens, max_source = self.max_input_tokens(name, overrides)
        return ResolvedAgent(
            name=name,
            model=model,
            system_prompt=system_prompt,
            enabled=enabled,
            max_input_tokens=max_input_tokens,
            max_input_tokens_source=max_source,
        )

    def create(self, resolved: ResolvedAgent, tools: Sequence[Any]) -> Any:
        if self._create_deep_agent is None:
            raise RuntimeError("AgentRuntime.create requires create_deep_agent")
        if self._backend is None:
            raise RuntimeError("AgentRuntime.create requires backend")
        return self._helpers.create_agent_with_fallback(
            self._create_deep_agent,
            resolved.model,
            list(tools),
            resolved.system_prompt,
            self._backend,
            max_input_tokens=resolved.max_input_tokens,
            max_input_tokens_source=resolved.max_input_tokens_source,
        )

