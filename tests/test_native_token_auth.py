import os
import tempfile
import unittest
from pathlib import Path
from unittest.mock import patch

from fastapi.testclient import TestClient

from backend import main
from database import database


class NativeTokenAuthTests(unittest.TestCase):
    def setUp(self):
        self.temp_dir = tempfile.TemporaryDirectory()
        self.original_database_path = database.DATABASE_PATH
        database.DATABASE_PATH = str(Path(self.temp_dir.name) / "native.db")
        self.database_env = patch.dict(os.environ, {"DATABASE_URL": ""})
        self.database_env.start()
        database.initialize_database()
        database.create_user("native-user")
        self.token = "native-session-token"
        database.create_auth_session("native-user", self.token)
        self.client = TestClient(main.app)
        self.addCleanup(self.client.close)
        self.addCleanup(self.temp_dir.cleanup)
        self.addCleanup(self.database_env.stop)
        self.addCleanup(self._restore_database_path)

    def _restore_database_path(self):
        database.DATABASE_PATH = self.original_database_path

    def test_session_header_authenticates_without_cookie(self):
        response = self.client.get(
            "/auth/me", headers={"X-Stack-Up-Session-Token": self.token}
        )
        self.assertEqual(response.status_code, 200)

    def test_invalid_header_token_is_rejected(self):
        response = self.client.get(
            "/auth/me", headers={"X-Stack-Up-Session-Token": "wrong"}
        )
        self.assertEqual(response.status_code, 401)

    def test_no_credentials_is_rejected(self):
        self.assertEqual(self.client.get("/auth/me").status_code, 401)

    def test_tokens_are_only_exposed_to_native_clients(self):
        class FakeRequest:
            def __init__(self, headers):
                self.headers = headers

        class FakeResponse:
            def __init__(self):
                self.headers = {}
                self.cookies = []

            def set_cookie(self, **kwargs):
                self.cookies.append(kwargs["key"])

        native = FakeResponse()
        main.set_auth_cookies(native, "s", "d", FakeRequest({"x-stack-up-client": "native"}))
        self.assertEqual(native.headers["X-Stack-Up-Session-Token"], "s")

        web = FakeResponse()
        main.set_auth_cookies(web, "s", "d", FakeRequest({}))
        self.assertEqual(web.headers, {})
        self.assertEqual(web.cookies, ["stack_up_session", "stack_up_device"])


if __name__ == "__main__":
    unittest.main()
