import datetime as dt
from pathlib import Path

from hidair_feather.utils import normalize_for_json, parse_date_from_filename, safe_filename


def test_parse_date_from_filename_valid() -> None:
    assert parse_date_from_filename("20260104") == dt.date(2026, 1, 4)


def test_parse_date_from_filename_invalid() -> None:
    assert parse_date_from_filename("2026-01-04") is None


def test_normalize_for_json_handles_date_and_path() -> None:
    payload = {"date": dt.date(2026, 1, 4), "path": Path("x/y")}
    normalized = normalize_for_json(payload)
    assert normalized["date"] == "2026-01-04"
    assert normalized["path"] == str(Path("x/y"))


def test_safe_filename_truncates() -> None:
    value = safe_filename("A B C", max_len=3)
    assert value == "A_B"
