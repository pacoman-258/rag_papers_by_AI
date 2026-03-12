from __future__ import annotations

import subprocess
import sys
import threading
from dataclasses import dataclass, field
from datetime import datetime
from pathlib import Path


@dataclass
class IngestJob:
    job_id: str
    status: str
    started_at: datetime
    finished_at: datetime | None = None
    return_code: int | None = None
    logs: list[str] = field(default_factory=list)


class IngestManager:
    def __init__(self, repo_root: Path) -> None:
        self.repo_root = repo_root
        self._lock = threading.Lock()
        self._current_job: IngestJob | None = None
        self._last_job: IngestJob | None = None

    def get_job(self, job_id: str) -> IngestJob | None:
        with self._lock:
            for job in (self._current_job, self._last_job):
                if job is not None and job.job_id == job_id:
                    return job
        return None

    def get_status(self) -> IngestJob | None:
        with self._lock:
            return self._current_job or self._last_job

    def start(self) -> IngestJob:
        with self._lock:
            if self._current_job is not None and self._current_job.status == "running":
                raise RuntimeError("An ingest job is already running.")

            job = IngestJob(
                job_id=datetime.utcnow().strftime("%Y%m%d%H%M%S%f"),
                status="running",
                started_at=datetime.utcnow(),
            )
            self._current_job = job

        thread = threading.Thread(target=self._run_job, args=(job,), daemon=True)
        thread.start()
        return job

    def _append_log(self, job: IngestJob, line: str) -> None:
        with self._lock:
            job.logs.append(line.rstrip("\n"))

    def _run_job(self, job: IngestJob) -> None:
        app_dir = self.repo_root / "local_paper_db" / "app"
        command = [sys.executable, "in.py"]
        process = subprocess.Popen(
            command,
            cwd=str(app_dir),
            stdout=subprocess.PIPE,
            stderr=subprocess.STDOUT,
            text=True,
            bufsize=1,
        )
        assert process.stdout is not None
        for line in process.stdout:
            self._append_log(job, line)
        process.wait()

        with self._lock:
            job.return_code = process.returncode
            job.finished_at = datetime.utcnow()
            job.status = "completed" if process.returncode == 0 else "failed"
            self._last_job = job
            self._current_job = None
