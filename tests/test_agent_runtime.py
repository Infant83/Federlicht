from __future__ import annotations

from federlicht.agent_runtime import AgentRuntime, ResolvedAgent


class _DummyHelpers:
    def resolve_agent_enabled(self, name: str, default: bool, overrides: dict) -> bool:
        entry = overrides.get(name, {})
        enabled = entry.get("enabled")
        return enabled if isinstance(enabled, bool) else default

    def resolve_agent_prompt(self, name: str, default_prompt: str, overrides: dict) -> str:
        entry = overrides.get(name, {})
        prompt = entry.get("system_prompt")
        if isinstance(prompt, str) and prompt.strip():
            return prompt
        return default_prompt

    def resolve_agent_model(self, name: str, default_model: str, overrides: dict) -> str:
        entry = overrides.get(name, {})
        model = entry.get("model")
        if isinstance(model, str) and model.strip():
            return model
        return default_model

    def resolve_agent_max_input_tokens(self, name: str, args, overrides: dict) -> tuple[int | None, str]:
        entry = overrides.get(name, {})
        value = entry.get("max_input_tokens")
        if isinstance(value, int) and value > 0:
            return value, "agent"
        return getattr(args, "max_input_tokens", None), "cli"

    def create_agent_with_fallback(
        self,
        create_deep_agent,
        model,
        tools,
        system_prompt,
        backend,
        *,
        max_input_tokens,
        max_input_tokens_source,
    ):
        return {
            "builder": create_deep_agent,
            "model": model,
            "tools": tools,
            "system_prompt": system_prompt,
            "backend": backend,
            "max_input_tokens": max_input_tokens,
            "max_input_tokens_source": max_input_tokens_source,
        }


class _Args:
    max_input_tokens = 4096


def test_runtime_resolve_prefers_overrides() -> None:
    helpers = _DummyHelpers()
    runtime = AgentRuntime(
        args=_Args(),
        helpers=helpers,
        overrides={
            "writer": {
                "model": "gpt-5-mini",
                "system_prompt": "custom writer prompt",
                "enabled": False,
                "max_input_tokens": 8192,
            }
        },
    )

    resolved = runtime.resolve(
        name="writer",
        default_model="gpt-5",
        default_prompt="default writer prompt",
        default_enabled=True,
    )

    assert isinstance(resolved, ResolvedAgent)
    assert resolved.model == "gpt-5-mini"
    assert resolved.system_prompt == "custom writer prompt"
    assert resolved.enabled is False
    assert resolved.max_input_tokens == 8192
    assert resolved.max_input_tokens_source == "agent"


def test_runtime_create_requires_builder_and_backend() -> None:
    helpers = _DummyHelpers()
    runtime = AgentRuntime(args=_Args(), helpers=helpers, overrides={})
    resolved = runtime.resolve(
        name="scout",
        default_model="gpt-5",
        default_prompt="default scout prompt",
    )

    try:
        runtime.create(resolved, tools=[])
        assert False, "expected RuntimeError"
    except RuntimeError as exc:
        assert "create_deep_agent" in str(exc)


def test_runtime_create_uses_resolved_budget_and_prompt() -> None:
    helpers = _DummyHelpers()
    runtime = AgentRuntime(
        args=_Args(),
        helpers=helpers,
        overrides={"scout": {"max_input_tokens": 12000}},
        create_deep_agent=object(),
        backend=object(),
    )
    resolved = runtime.resolve(
        name="scout",
        default_model="gpt-5",
        default_prompt="scout prompt",
    )
    created = runtime.create(resolved, tools=["tool_a"])

    assert created["model"] == "gpt-5"
    assert created["system_prompt"] == "scout prompt"
    assert created["tools"] == ["tool_a"]
    assert created["max_input_tokens"] == 12000
    assert created["max_input_tokens_source"] == "agent"

