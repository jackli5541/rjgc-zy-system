"""Bound model work without blocking the background queue's polling loop."""
import logging
from concurrent.futures import ThreadPoolExecutor

logger = logging.getLogger(__name__)


class GradingDispatcher:
    def __init__(self, workers=2):
        self.workers = workers
        self.executor = ThreadPoolExecutor(max_workers=workers, thread_name_prefix="ai-grading")
        self.futures = []

    def available(self):
        pending = []
        for future in self.futures:
            if future.done():
                try:
                    future.result()
                except Exception:
                    logger.exception("AI grading dispatch failed")
            else:
                pending.append(future)
        self.futures = pending
        return len(pending) < self.workers

    def submit(self, function, *args):
        if not self.available():
            return False
        self.futures.append(self.executor.submit(function, *args))
        return True

    def close(self):
        self.executor.shutdown(wait=True)
