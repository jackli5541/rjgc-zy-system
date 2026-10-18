"""Run directly with Python for checks that never connect to a database."""
import asyncio
import json
import unittest
from datetime import timedelta
from types import SimpleNamespace
from unittest.mock import patch

from app.core.errors import ApiError
from app.core.utils import now
from app.modules.ai_grading import service


class GradingUnitTests(unittest.TestCase):
    def test_local_only_mode_never_falls_back_to_oss(self):
        with patch.object(service.settings, "storage_local_only", True), patch.object(service.settings, "storage_backend", "oss"), patch.object(service.storage, "get_object_bytes") as read:
            with self.assertRaises(ApiError) as error:
                service.read_text_attachment(SimpleNamespace(), "评分标准")
            self.assertEqual(error.exception.code, "AI_GRADING_LOCAL_STORAGE_REQUIRED")
            read.assert_not_called()
            with self.assertRaises(RuntimeError):
                service.storage._bucket_client()

    def test_missing_local_file_is_actionable_without_oss(self):
        file = SimpleNamespace(original_name="评分.md", storage_path="missing", size_bytes=20)
        with patch.object(service.settings, "storage_local_only", True), patch.object(service.settings, "storage_backend", "local"), patch.object(service.storage, "local_path", return_value=SimpleNamespace(is_file=lambda: False)), patch.object(service.storage, "get_object_bytes") as read:
            with self.assertRaises(ApiError) as error:
                service.read_text_attachment(file, "评分标准")
            self.assertEqual(error.exception.code, "AI_GRADING_LOCAL_FILE_MISSING")
            read.assert_not_called()

    def test_result_requires_grade_reason_and_evidence(self):
        result = {"suggested_grade": "A", "grade_reason": "符合标准", "suggested_comment": "需求完整", "criteria_results": [{"criterion": "完整性", "judgment": "符合", "evidence": "第1节"}], "review_points": ["补充边界"]}
        self.assertEqual(service.parse_result(json.dumps(result))["grade_reason"], "符合标准")
        for key, value in [("suggested_grade", "F"), ("grade_reason", ""), ("criteria_results", []), ("suggested_comment", "")]:
            with self.subTest(key=key), self.assertRaises(ValueError):
                service.parse_result(json.dumps({**result, key: value}))

    def test_text_files_are_read_and_empty_or_unsupported_files_fail(self):
        file = SimpleNamespace(original_name="评分.md", storage_path="criteria", size_bytes=20)
        with patch.object(service.settings, "storage_local_only", False), patch.object(service.storage, "get_object_bytes", return_value="A：完整".encode()):
            self.assertEqual(service.read_text_attachment(file, "评分标准"), "A：完整")
        with patch.object(service.settings, "storage_local_only", False), patch.object(service.storage, "get_object_bytes", return_value=b" "), self.assertRaises(ApiError):
            service.read_text_attachment(file, "评分标准")
        file.original_name = "扫描.pdf"
        with self.assertRaises(ApiError):
            service.read_text_attachment(file, "评分标准")

    def test_formal_version_files_not_editable_workspace(self):
        criteria = SimpleNamespace(id="criteria", original_name="评分.md", storage_path="criteria", size_bytes=20)
        submitted = SimpleNamespace(original_name="提交.md", storage_path="snapshot", size_bytes=20)
        class Db:
            def scalars(self, query):
                self.query = str(query)
                return SimpleNamespace(all=lambda: [submitted])
        db = Db()
        with patch.object(service.settings, "storage_local_only", False), patch.object(service, "require_criteria", return_value=[criteria]), patch.object(service.storage, "get_object_bytes", side_effect=lambda key: {"criteria": b"A: complete", "snapshot": b"submitted content"}[key]):
            rubric, text = service.submission_context(db, SimpleNamespace(id="assignment", auto_review_criteria_text=""), SimpleNamespace(id="version"))
        self.assertIn("version_files", db.query)
        self.assertNotIn("submission_documents", db.query)
        self.assertIn("submitted content", text)
        self.assertEqual(rubric["criteria_files"][0]["content"], "A: complete")

    def test_failed_background_task_and_expired_wait_are_reported(self):
        draft = SimpleNamespace(id="draft", job_id=None, assignment_id="assignment", submission_version_id="version", status="PROCESSING", assignment_version=1, model_name=None, rubric_snapshot={}, analysis=None, suggested_grade=None, suggested_comment=None, error_message=None, created_at=now(), updated_at=now())
        db = SimpleNamespace(scalars=lambda query: SimpleNamespace(all=lambda: [SimpleNamespace(payload={"draft_id": "draft"}, status="FAILED")]))
        self.assertEqual(service.draft_state(db, draft)["status"], "FAILED")
        draft.created_at = now() - timedelta(seconds=181)
        db.scalars = lambda query: SimpleNamespace(all=lambda: [])
        self.assertIn("180", service.draft_state(db, draft)["error_message"])

    def test_model_has_total_timeout(self):
        class Client:
            async def stream_chat(self, messages):
                await asyncio.sleep(1)
                yield "ignored"
        with patch.object(service, "get_ai_client", return_value=Client()), self.assertRaises(TimeoutError):
            asyncio.run(service.generate_result([], 0.01))

    def test_grading_uses_its_own_output_budget(self):
        class Client:
            async def stream_chat(self, messages):
                self.request_budget = self.max_output_tokens
                yield 'result'
        client = Client()
        with patch.object(service, 'get_ai_client', return_value=client), patch.object(service, 'parse_result', return_value={}), patch.object(service.settings, 'ai_grading_max_output_tokens', 8192):
            asyncio.run(service.generate_result([], 1))
        self.assertEqual(client.request_budget, 8192)
        self.assertTrue(client.structured_output)
        self.assertEqual(client.temperature, 0)

    def test_concise_rewrite_preserves_grade_and_all_evidence(self):
        result = {'suggested_grade': 'B', 'grade_reason': '理由' * 80, 'suggested_comment': '总评' * 90, 'criteria_results': [{'evidence': '完整证据'}]}
        class Client:
            calls = 0
            async def stream_chat(self, messages):
                self.calls += 1
                yield json.dumps({'grade_reason': '符合多数要求，接口边界需补充。', 'suggested_comment': '完成主体设计，请补充接口边界。'}) if self.calls > 1 else 'original'
        client = Client()
        with patch.object(service, 'get_ai_client', return_value=client), patch.object(service, 'parse_result', return_value=result.copy()):
            compact = asyncio.run(service.generate_result([], 1))
        self.assertEqual(compact['suggested_grade'], 'B')
        self.assertEqual(compact['criteria_results'], result['criteria_results'])
        self.assertLessEqual(len(compact['grade_reason']), 120)
        self.assertLessEqual(len(compact['suggested_comment']), 150)

    def test_baseline_survives_failure_and_compares_only_known_materials(self):
        previous = {'status': 'READY', 'suggested_grade': 'A', 'analysis': {'grade_reason': '符合'}, 'suggested_comment': '完成', 'fingerprint': 'same'}
        draft = SimpleNamespace(status='FAILED', rubric_snapshot={'_previous': previous})
        self.assertEqual(service.successful_baseline(draft), previous)
        snapshot = {'_previous': previous, '_fingerprint': 'same'}
        self.assertTrue(service.result_comparison(snapshot, 'B')['grade_changed'])
        self.assertFalse(service.result_comparison(snapshot, 'A')['grade_changed'])
        snapshot['_fingerprint'] = 'new'
        self.assertTrue(service.result_comparison(snapshot, 'B')['materials_changed'])
        self.assertFalse(service.result_comparison(snapshot, 'B')['grade_changed'])
        self.assertFalse(service.result_comparison({}, 'A')['grade_changed'])
        previous['fingerprint'] = None
        self.assertIsNone(service.result_comparison(snapshot, 'B')['materials_changed'])

    def test_material_fingerprint_and_prompt_do_not_include_old_results(self):
        assignment = SimpleNamespace(title='作业', description='<p>说明</p>')
        messages = service.grading_messages(assignment, {'criteria_files': []}, '正文')
        fingerprint = service.material_fingerprint(messages)
        self.assertEqual(fingerprint, service.material_fingerprint(messages))
        other = service.grading_messages(assignment, {'criteria_files': []}, '改变正文')
        self.assertNotEqual(fingerprint, service.material_fingerprint(other))
        assignment.description = '改变说明'
        self.assertNotEqual(fingerprint, service.material_fingerprint(service.grading_messages(assignment, {}, '正文')))
        self.assertIn('先检查教师明确的降档条件', messages[0]['content'])
        self.assertIn('最多120字符', messages[0]['content'])
        self.assertNotIn('_previous', str(messages))

    def test_structured_deepseek_request_disables_thinking(self):
        import httpx
        from app.modules.ai_teacher.client import OpenAICompatibleClient
        requests = []
        def respond(request):
            requests.append(json.loads(request.content))
            return httpx.Response(200, text='data: {"choices":[{"delta":{"content":"{}"},"finish_reason":"stop"}]}\n\ndata: [DONE]\n\n')
        async def collect(client):
            return [chunk async for chunk in client.stream_chat([{'role': 'user', 'content': 'JSON'}])]
        with patch.object(service.settings, 'ai_teacher_enabled', True), patch.object(service.settings, 'ai_base_url', 'https://api.deepseek.com'), patch.object(service.settings, 'ai_chat_model', 'deepseek-flash'):
            client = OpenAICompatibleClient(transport=httpx.MockTransport(respond))
            asyncio.run(collect(client))
            self.assertNotIn('thinking', requests[-1])
            self.assertNotIn('response_format', requests[-1])
            client.structured_output = True
            asyncio.run(collect(client))
            self.assertEqual(requests[-1]['thinking'], {'type': 'disabled'})
            self.assertEqual(requests[-1]['response_format'], {'type': 'json_object'})


if __name__ == "__main__":
    unittest.main()
