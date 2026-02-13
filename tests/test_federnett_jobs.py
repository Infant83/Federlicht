from pathlib import Path

from federnett.jobs import Job


def test_append_log_always_ends_with_newline() -> None:
    job = Job(job_id="abc123", kind="test", command=["echo"], cwd=Path("."))
    job.append_log("line-without-newline")
    assert job.logs
    assert str(job.logs[0]["text"]).endswith("\n")

