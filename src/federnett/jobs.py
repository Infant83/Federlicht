from __future__ import annotations

import os
import subprocess
import threading
import uuid
from dataclasses import dataclass, field
from pathlib import Path
from typing import Any, Optional

from .utils import now_ts


@dataclass
class Job:
    job_id: str
    kind: str
    command: list[str]
    cwd: Path
    created_at: float = field(default_factory=now_ts)
    status: str = "running"
    returncode: Optional[int] = None
    logs: list[dict[str, Any]] = field(default_factory=list)
    _lock: threading.Lock = field(default_factory=threading.Lock)
    _cond: threading.Condition = field(init=False)
    _proc: Optional[subprocess.Popen[str]] = None

    def __post_init__(self) -> None:
        self._cond = threading.Condition(self._lock)

    def attach(self, proc: subprocess.Popen[str]) -> None:
        self._proc = proc

    def append_log(self, text: str, stream: str = "stdout") -> None:
        if not text:
            return
        with self._cond:
            entry = {
                "index": len(self.logs),
                "ts": now_ts(),
                "stream": stream,
                "text": text.rstrip("\n"),
            }
            self.logs.append(entry)
            self._cond.notify_all()

    def mark_done(self, returncode: int) -> None:
        with self._cond:
            self.returncode = returncode
            self.status = "done" if returncode == 0 else "error"
            self._cond.notify_all()

    def kill(self) -> bool:
        proc = self._proc
        if not proc or proc.poll() is not None:
            return False
        proc.kill()
        with self._cond:
            self.status = "killed"
            self._cond.notify_all()
        return True

    def wait_for_logs(self, last_index: int, timeout: float = 1.0) -> tuple[list[dict[str, Any]], bool]:
        with self._cond:
            if last_index >= len(self.logs) and self.status == "running":
                self._cond.wait(timeout=timeout)
            new_logs = self.logs[last_index:]
            done = self.status != "running"
            return new_logs, done


class JobRegistry:
    def __init__(self) -> None:
        self._jobs: dict[str, Job] = {}
        self._lock = threading.Lock()

    def get(self, job_id: str) -> Optional[Job]:
        with self._lock:
            return self._jobs.get(job_id)

    def start(self, kind: str, command: list[str], cwd: Path) -> Job:
        job_id = uuid.uuid4().hex[:12]
        job = Job(job_id=job_id, kind=kind, command=command, cwd=cwd)
        with self._lock:
            self._jobs[job_id] = job
        self._launch(job)
        return job

    def _launch(self, job: Job) -> None:
        env = os.environ.copy()
        try:
            src_path = str((job.cwd / "src").resolve())
            current = env.get("PYTHONPATH", "")
            if current:
                if src_path not in current.split(os.pathsep):
                    env["PYTHONPATH"] = os.pathsep.join([src_path, current])
            else:
                env["PYTHONPATH"] = src_path
        except Exception:
            env = os.environ.copy()
        proc = subprocess.Popen(
            job.command,
            cwd=str(job.cwd),
            env=env,
            stdout=subprocess.PIPE,
            stderr=subprocess.STDOUT,
            text=True,
            encoding="utf-8",
            errors="replace",
            bufsize=1,
        )
        job.attach(proc)
        job.append_log(f"$ {' '.join(job.command)}", stream="meta")

        def reader() -> None:
            assert proc.stdout is not None
            try:
                for line in proc.stdout:
                    job.append_log(line)
            finally:
                rc = proc.wait()
                job.mark_done(rc)

        threading.Thread(target=reader, name=f"federnett-job-{job.job_id}", daemon=True).start()
