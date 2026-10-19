"""Identify the code and process handling a grading task without credentials."""
import hashlib
import os
import socket
from functools import lru_cache
from pathlib import Path


@lru_cache(maxsize=1)
def code_version():
    app_root = Path(__file__).resolve().parents[2]
    digest = hashlib.sha256()
    for name in ("worker.py", "settings.py", "database.py", "core/ai_client.py",
                 "modules/ai_grading/service.py", "modules/ai_grading/client.py",
                 "modules/ai_grading/diagnostics.py"):
        digest.update(name.encode())
        digest.update((app_root / name).read_bytes().replace(b"\r\n", b"\n"))
    return "sha256:" + digest.hexdigest()[:16]


def worker_identity():
    return {"host": socket.gethostname(), "pid": os.getpid(), "code_version": code_version()}


def task_log_context(draft_id, run_id, job_id, identity):
    return (f"draft={draft_id} run={run_id} job={job_id} "
            f"host={identity['host']} pid={identity['pid']} code_version={identity['code_version']}")
