"""Regression checks using simulated models, sessions and temporary local files."""
import asyncio
import json
import tempfile
import unittest
from contextlib import ExitStack
from pathlib import Path
from types import SimpleNamespace
from unittest.mock import AsyncMock, MagicMock, patch
from uuid import uuid4

from app import worker
from app.core.ai_client import AiClientError
from app.core.utils import now
from app.models import AiGradingDraft, Assignment, Submission, SubmissionVersion
from app.modules.ai_grading import service


def valid_result(long=False):
    return {'suggested_grade': 'B', 'grade_reason': '理由' * (80 if long else 1),
            'suggested_comment': '总评' * (90 if long else 1),
            'criteria_results': [{'criterion': '完整性', 'judgment': '需补充', 'evidence': '第1节'}],
            'review_points': ['补充边界']}


class OptionalCompactTests(unittest.TestCase):
    def run_model(self, compact=None, error=None, stalled=False, timeout=10):
        original = valid_result(long=True)

        class Client:
            calls = 0

            async def stream_chat(self, messages):
                self.calls += 1
                if self.calls == 1:
                    yield json.dumps(original)
                elif error:
                    raise error
                elif stalled:
                    await asyncio.sleep(10)
                else:
                    yield compact

        client = Client()
        with patch.object(service, 'get_ai_client', return_value=client):
            result = asyncio.run(service.generate_result([], timeout))
        return original, result, client.calls

    def test_invalid_optional_output_keeps_original_without_retry(self):
        for compact in ('broken JSON', '[]', 'null', '{}', '{"grade_reason":4}',
                        json.dumps({'grade_reason': '字' * 121, 'suggested_comment': '完整总评'})):
            with self.subTest(compact=compact):
                original, result, calls = self.run_model(compact=compact)
                self.assertEqual(result, service.parse_result(json.dumps(original)))
                self.assertEqual(calls, 2)

    def test_optional_model_failure_keeps_original(self):
        original, result, calls = self.run_model(error=AiClientError('模拟连接失败'))
        self.assertEqual(result['grade_reason'], original['grade_reason'])
        self.assertEqual(calls, 2)

    def test_optional_timeout_keeps_original(self):
        with patch.object(service, 'COMPACT_TIMEOUT_SECONDS', 0.01):
            original, result, calls = self.run_model(stalled=True)
        self.assertEqual(result['suggested_comment'], original['suggested_comment'])
        self.assertEqual(calls, 2)

    def test_limited_task_budget_skips_optional_call(self):
        original, result, calls = self.run_model(timeout=0.5)
        self.assertEqual(result['grade_reason'], original['grade_reason'])
        self.assertEqual(calls, 1)

    def test_optional_budget_is_at_most_five_seconds_and_leaves_save_time(self):
        real_timeout = asyncio.timeout
        for remaining in (10, 3):
            with self.subTest(remaining=remaining), patch.object(service.asyncio, 'timeout', wraps=real_timeout) as timer:
                self.run_model(compact='{}', timeout=remaining)
                budget = timer.call_args_list[1].args[0]
                self.assertLessEqual(budget, 5)
                self.assertLessEqual(budget, remaining - 1)

    def test_primary_model_failure_still_propagates(self):
        class Client:
            async def stream_chat(self, messages):
                raise AiClientError('模拟主请求失败')
                yield ''

        with patch.object(service, 'get_ai_client', return_value=Client()), self.assertRaises(AiClientError):
            asyncio.run(service.generate_result([], 10))

    def test_external_cancellation_is_not_swallowed(self):
        with self.assertRaises(asyncio.CancelledError):
            self.run_model(error=asyncio.CancelledError())

    def test_temporary_local_attachment_never_accesses_oss(self):
        with tempfile.TemporaryDirectory() as folder, ExitStack() as stack:
            root = Path(folder)
            (root / 'rubric.md').write_text('A: 完成要求', encoding='utf-8')
            stack.enter_context(patch.object(service.settings, 'storage_backend', 'local'))
            stack.enter_context(patch.object(service.settings, 'storage_local_only', True))
            stack.enter_context(patch.object(service.settings, 'local_storage_root', root))
            bucket = stack.enter_context(patch.object(service.storage, '_bucket_client', side_effect=AssertionError('OSS forbidden')))
            text = service.read_text_attachment(SimpleNamespace(original_name='标准.md', storage_path='rubric.md', size_bytes=20), '评分标准')
            self.assertEqual(text, 'A: 完成要求')
            bucket.assert_not_called()


class WorkerRetryTests(unittest.TestCase):
    def setup_task(self):
        draft = SimpleNamespace(id=uuid4(), status='PROCESSING', assignment_id=uuid4(),
                                submission_version_id=uuid4(), assignment_version=1,
                                rubric_snapshot={'_run': {'id': 'run-1', 'job_id': str(uuid4()), 'queued_at': now().isoformat()}},
                                analysis=None, suggested_grade=None, suggested_comment=None)
        assignment = SimpleNamespace(version=1)
        version = SimpleNamespace(submission_id=uuid4(), version_no=1)
        submission = SimpleNamespace(status='SUBMITTED', current_version_no=1)
        db = MagicMock()
        db.get.side_effect = lambda model, identifier: {
            AiGradingDraft: draft, Assignment: assignment, SubmissionVersion: version, Submission: submission,
        }[model]
        db.scalar.return_value = draft
        return draft, db

    def run_task(self, draft, db, generated=None, failure=None, run_id='run-1'):
        model = AsyncMock(return_value=generated or valid_result(), side_effect=failure)
        with patch.object(worker.SessionLocal, 'begin') as begin, \
                patch.object(worker, 'submission_context', return_value=({}, '合成正文')), \
                patch.object(worker, 'grading_messages', return_value=[{}, {'content': '合成正文'}]), \
                patch.object(worker, 'generate_result', model):
            begin.return_value.__enter__.return_value = db
            result = worker.process_ai_grading_draft(draft.id, run_id)
        return result, model

    def test_repeated_generation_saves_result_with_worker_identity(self):
        draft, db = self.setup_task()
        for run in ('run-1', 'run-2'):
            draft.status = 'PROCESSING'
            draft.rubric_snapshot['_run']['id'] = run
            result, model = self.run_task(draft, db, run_id=run)
            self.assertTrue(result)
            self.assertEqual(draft.status, 'READY')
            self.assertEqual(draft.suggested_grade, 'B')
            identity = draft.rubric_snapshot['_run']['worker']
            self.assertTrue(identity['host'])
            self.assertIsInstance(identity['pid'], int)
            self.assertTrue(identity['code_version'].startswith('sha256:'))
            self.assertIn('run=' + run, model.call_args.kwargs['log_context'])

    def test_primary_failure_records_stage_and_preserves_baseline(self):
        draft, db = self.setup_task()
        draft.rubric_snapshot['_previous'] = {'suggested_grade': 'A'}
        with self.assertLogs(worker.logger, level='ERROR') as logs:
            result, _ = self.run_task(draft, db, failure=AiClientError('模拟主请求失败'))
        self.assertFalse(result)
        self.assertEqual(draft.status, 'FAILED')
        self.assertEqual(draft.error_message, '模拟主请求失败')
        self.assertEqual(draft.rubric_snapshot['_run']['failed_stage'], 'GENERATING')
        self.assertEqual(draft.rubric_snapshot['_previous']['suggested_grade'], 'A')
        self.assertIn('stage=GENERATING', '\n'.join(logs.output))

    def test_stale_run_is_rejected_before_generation(self):
        draft, db = self.setup_task()
        draft.rubric_snapshot['_run']['id'] = 'new-run'
        result, model = self.run_task(draft, db)
        self.assertFalse(result)
        model.assert_not_called()
        self.assertEqual(draft.status, 'PROCESSING')

    def test_run_replaced_during_generation_cannot_overwrite_new_result(self):
        draft, db = self.setup_task()

        async def replace_run(*args, **kwargs):
            draft.rubric_snapshot['_run']['id'] = 'new-run'
            return valid_result()

        with patch.object(worker.SessionLocal, 'begin') as begin, \
                patch.object(worker, 'submission_context', return_value=({}, '合成正文')), \
                patch.object(worker, 'grading_messages', return_value=[{}, {'content': '合成正文'}]), \
                patch.object(worker, 'generate_result', side_effect=replace_run):
            begin.return_value.__enter__.return_value = db
            self.assertFalse(worker.process_ai_grading_draft(draft.id, 'run-1'))
        self.assertEqual(draft.status, 'PROCESSING')
        self.assertIsNone(draft.suggested_grade)


if __name__ == '__main__':
    unittest.main()
