import pytest

from federlicht import cli_args, report


def test_report_parse_args_matches_cli_args() -> None:
    argv = [
        "--run",
        "sample_run",
        "--output",
        "report_full.md",
        "--no-stream",
        "--max-tool-chars",
        "24000",
        "--temperature-level",
        "balanced",
    ]
    via_report = report.parse_args(argv)
    direct = cli_args.parse_args(argv)
    assert vars(via_report) == vars(direct)


def test_temperature_override_flag_removed() -> None:
    with pytest.raises(SystemExit):
        cli_args.parse_args(["--run", "sample_run", "--temperature", "0.5"])
