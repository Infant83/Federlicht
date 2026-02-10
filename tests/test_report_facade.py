from __future__ import annotations

from federlicht import report
from federlicht import cli as report_cli


def test_report_module_exposes_symbols() -> None:
    assert isinstance(report.DEFAULT_MODEL, str) and report.DEFAULT_MODEL
    assert callable(report.parse_args)
    assert report._normalize_template_name(" Name With Space ") == "Name With Space"


def test_report_main_delegates_to_cli(monkeypatch) -> None:
    monkeypatch.setattr(report_cli, "main", lambda: 7)
    assert report.main() == 7
