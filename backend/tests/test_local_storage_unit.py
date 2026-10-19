"""Database-free checks: run with python -m unittest discover -s tests -p test_local_storage_unit.py."""
import tempfile
import unittest
from pathlib import Path
from unittest.mock import patch
from urllib.parse import parse_qs, urlencode, urlsplit

from fastapi import FastAPI
from fastapi.testclient import TestClient

from app import storage
from app.core.errors import ApiError
from app.modules.system.router import router
from app.settings import settings


class LocalStorageTests(unittest.TestCase):
    def setUp(self):
        temporary = tempfile.TemporaryDirectory()
        self.addCleanup(temporary.cleanup)
        for key, value in {
            "storage_backend": "local",
            "local_storage_root": Path(temporary.name),
            "local_storage_secret": "unit-test-secret",
        }.items():
            patcher = patch.object(settings, key, value)
            patcher.start()
            self.addCleanup(patcher.stop)
        app = FastAPI()
        app.include_router(router)

        @app.exception_handler(ApiError)
        async def api_error(request, error):
            from fastapi.responses import JSONResponse
            return JSONResponse({"code": error.code}, status_code=error.status)

        self.client = TestClient(app)

    def test_bytes_stream_and_delete(self):
        storage.put_bytes("nested/file.txt", b"content")
        self.assertTrue(storage.object_exists("nested/file.txt"))
        self.assertEqual(storage.get_object_bytes("nested/file.txt"), b"content")
        self.assertEqual(b"".join(storage.get_object_stream("nested/file.txt")), b"content")
        storage.delete_object("nested/file.txt")
        storage.delete_object("nested/file.txt")
        self.assertFalse(storage.object_exists("nested/file.txt"))

    def test_upload_and_signed_download(self):
        source = settings.local_storage_root / "source.txt"
        source.write_bytes(b"upload")
        storage.put_object("uploads/copy.txt", source)
        url = storage.sign_get_url("uploads/copy.txt", 60, {"response-content-disposition": "attachment"})
        response = self.client.get(url)
        self.assertEqual(response.status_code, 200)
        self.assertEqual(response.content, b"upload")
        self.assertEqual(response.headers["content-disposition"], "attachment")

    def test_expired_and_tampered_links_are_rejected(self):
        storage.put_bytes("file.txt", b"private")
        self.assertEqual(self.client.get(storage.sign_get_url("file.txt", -1)).status_code, 403)
        url = storage.sign_get_url("file.txt", 60)
        query = parse_qs(urlsplit(url).query)
        query["key"] = ["other.txt"]
        self.assertEqual(self.client.get("/api/v1/local-files?" + urlencode({k: v[0] for k, v in query.items()})).status_code, 403)

    def test_path_traversal_is_rejected(self):
        for key in ("../outside.txt", "nested/../../outside.txt"):
            with self.assertRaises(ValueError):
                storage.put_bytes(key, b"escape")


if __name__ == "__main__":
    unittest.main()
