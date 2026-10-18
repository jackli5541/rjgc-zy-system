"""Queue scheduling checks; run directly without a database."""
import threading
import unittest
from types import SimpleNamespace
from unittest.mock import MagicMock, patch
from uuid import uuid4

from app import worker
from app.modules.ai_grading.dispatch import GradingDispatcher


class DispatchTests(unittest.TestCase):
    def test_two_tasks_start_without_waiting_for_each_other_and_capacity_is_bounded(self):
        dispatcher = GradingDispatcher()
        release = threading.Event()
        started = [threading.Event(), threading.Event()]

        def task(index):
            started[index].set()
            release.wait(2)

        try:
            self.assertTrue(dispatcher.submit(task, 0))
            self.assertTrue(dispatcher.submit(task, 1))
            self.assertTrue(all(event.wait(1) for event in started))
            self.assertFalse(dispatcher.available())
            self.assertFalse(dispatcher.submit(task, 0))
            release.set()
            for future in dispatcher.futures:
                future.result(timeout=1)
            self.assertTrue(dispatcher.available())
        finally:
            release.set()
            dispatcher.close()

    def test_claiming_ai_job_dispatches_after_transaction_and_does_not_run_model_inline(self):
        job = SimpleNamespace(id=uuid4(), kind='AI_GRADING_DRAFT', payload={'draft_id': str(uuid4())}, attempts=0)
        db = MagicMock()
        db.scalar.return_value = job
        dispatcher = MagicMock()
        dispatcher.available.return_value = True
        with patch.object(worker.SessionLocal, 'begin') as begin, patch.object(worker, 'process_claimed_job') as process:
            begin.return_value.__enter__.return_value = db
            worker.run_once(run_maintenance=False, dispatcher=dispatcher)
            self.assertEqual(job.status, 'RUNNING')
            self.assertEqual(job.attempts, 1)
            begin.return_value.__exit__.assert_called_once()
            dispatcher.submit.assert_called_once_with(process, job.id, job.kind, job.payload, None, [])
            process.assert_not_called()
            db.execute.assert_not_called()

    def test_full_dispatcher_excludes_ai_jobs_from_claim(self):
        db = MagicMock()
        db.scalar.return_value = None
        dispatcher = MagicMock()
        dispatcher.available.return_value = False
        with patch.object(worker.SessionLocal, 'begin') as begin:
            begin.return_value.__enter__.return_value = db
            worker.run_once(run_maintenance=False, dispatcher=dispatcher)
        query = db.scalar.call_args.args[0]
        self.assertIn('NOT IN', str(query))
        dispatcher.submit.assert_not_called()


if __name__ == '__main__':
    unittest.main()
