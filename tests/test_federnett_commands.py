from __future__ import annotations

from pathlib import Path

from federnett.commands import _build_federlicht_cmd, _build_generate_prompt_cmd
from federnett.config import FedernettConfig


def _cfg(tmp_path: Path) -> FedernettConfig:
    root = tmp_path.resolve()
    static_dir = root / "site" / "federnett"
    static_dir.mkdir(parents=True, exist_ok=True)
    site_root = root / "site"
    site_root.mkdir(parents=True, exist_ok=True)
    run_root = root / "site" / "runs"
    run_root.mkdir(parents=True, exist_ok=True)
    return FedernettConfig(
        root=root,
        static_dir=static_dir,
        run_roots=[run_root],
        site_root=site_root,
    )


def test_build_federlicht_cmd_includes_agent_config(tmp_path: Path) -> None:
    cfg = _cfg(tmp_path)
    payload = {
        "run": "site/runs/demo",
        "output": "site/runs/demo/report_full.md",
        "agent_config": "site/runs/demo/instruction/agent_config.json",
    }

    cmd = _build_federlicht_cmd(cfg, payload)

    assert "--agent-config" in cmd
    idx = cmd.index("--agent-config")
    assert cmd[idx + 1] == str((tmp_path / "site" / "runs" / "demo" / "instruction" / "agent_config.json").resolve())


def test_build_generate_prompt_cmd_includes_agent_config(tmp_path: Path) -> None:
    cfg = _cfg(tmp_path)
    payload = {
        "run": "site/runs/demo",
        "agent_config": "site/runs/demo/instruction/agent_config.json",
    }

    cmd = _build_generate_prompt_cmd(cfg, payload)

    assert "--agent-config" in cmd
    idx = cmd.index("--agent-config")
    assert cmd[idx + 1] == str((tmp_path / "site" / "runs" / "demo" / "instruction" / "agent_config.json").resolve())


def test_build_federlicht_cmd_free_format_disables_template_args(tmp_path: Path) -> None:
    cfg = _cfg(tmp_path)
    payload = {
        "run": "site/runs/demo",
        "output": "site/runs/demo/report_full.md",
        "template": "default",
        "template_rigidity": "balanced",
        "free_format": True,
    }

    cmd = _build_federlicht_cmd(cfg, payload)

    assert "--free-format" in cmd
    assert "--template" not in cmd
    assert "--template-rigidity" not in cmd


def test_build_generate_prompt_cmd_free_format_disables_template_args(tmp_path: Path) -> None:
    cfg = _cfg(tmp_path)
    payload = {
        "run": "site/runs/demo",
        "template": "default",
        "template_rigidity": "balanced",
        "free_format": True,
    }

    cmd = _build_generate_prompt_cmd(cfg, payload)

    assert "--free-format" in cmd
    assert "--template" not in cmd
    assert "--template-rigidity" not in cmd


def test_build_federlicht_cmd_ignores_temperature_override(tmp_path: Path) -> None:
    cfg = _cfg(tmp_path)
    payload = {
        "run": "site/runs/demo",
        "output": "site/runs/demo/report_full.md",
        "temperature_level": "high",
        "temperature": 0.9,
    }

    cmd = _build_federlicht_cmd(cfg, payload)

    assert "--temperature-level" in cmd
    assert "--temperature" not in cmd


def test_build_generate_prompt_cmd_ignores_temperature_override(tmp_path: Path) -> None:
    cfg = _cfg(tmp_path)
    payload = {
        "run": "site/runs/demo",
        "temperature_level": "high",
        "temperature": 0.9,
    }

    cmd = _build_generate_prompt_cmd(cfg, payload)

    assert "--temperature-level" in cmd
    assert "--temperature" not in cmd
