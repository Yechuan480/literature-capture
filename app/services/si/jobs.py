"""In-memory SI job registry + worker threads."""

from __future__ import annotations

import threading
import uuid
from concurrent.futures import ThreadPoolExecutor
from typing import Any, Callable

from app.config import get_settings

_lock = threading.Lock()
_jobs: dict[str, dict[str, Any]] = {}
_by_pdf: dict[str, str] = {}  # filename -> job_id
_executor: ThreadPoolExecutor | None = None
_exec_lock = threading.Lock()


def _pool() -> ThreadPoolExecutor:
    global _executor
    with _exec_lock:
        if _executor is None:
            n = max(1, int(get_settings().si_max_concurrent_jobs or 2))
            _executor = ThreadPoolExecutor(max_workers=n, thread_name_prefix="si")
        return _executor


def get_job(job_id: str) -> dict[str, Any] | None:
    with _lock:
        j = _jobs.get(job_id)
        return dict(j) if j else None


def job_for_pdf(filename: str) -> dict[str, Any] | None:
    with _lock:
        jid = _by_pdf.get(filename)
        if not jid:
            return None
        j = _jobs.get(jid)
        return dict(j) if j else None


def update_job(job_id: str, **fields: Any) -> None:
    with _lock:
        j = _jobs.get(job_id)
        if not j:
            return
        j.update(fields)


def start_job(
    filename: str,
    worker: Callable[[str, dict[str, Any]], None],
    payload: dict[str, Any],
) -> dict[str, Any]:
    """
    Start a job for filename. If one is already queued/running, return it.
    worker(job_id, payload) runs in thread pool.
    """
    with _lock:
        existing_id = _by_pdf.get(filename)
        if existing_id:
            ex = _jobs.get(existing_id)
            if ex and ex.get("status") in ("queued", "running"):
                return dict(ex)
        job_id = uuid.uuid4().hex[:12]
        job = {
            "id": job_id,
            "filename": filename,
            "status": "queued",
            "progress": "queued",
            "error": None,
        }
        _jobs[job_id] = job
        _by_pdf[filename] = job_id

    def _run() -> None:
        update_job(job_id, status="running", progress="starting")
        try:
            worker(job_id, payload)
            with _lock:
                j = _jobs.get(job_id)
                if j and j.get("status") == "running":
                    j["status"] = "done"
                    j["progress"] = "done"
        except Exception as e:
            update_job(job_id, status="error", error=str(e), progress="error")

    _pool().submit(_run)
    with _lock:
        return dict(_jobs[job_id])
