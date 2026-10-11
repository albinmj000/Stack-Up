import os
import json
import tempfile
import unittest
from pathlib import Path
from unittest.mock import MagicMock, patch

from database import database
from database.corrections import get_correction, save_correction
from services.auth_service import _send_email_otp


class DatabaseTests(unittest.TestCase):
    def setUp(self):
        self.temp_dir = tempfile.TemporaryDirectory()
        self.original_database_path = database.DATABASE_PATH
        database.DATABASE_PATH = str(Path(self.temp_dir.name) / "stack_up.db")
        self.database_env = patch.dict(os.environ, {"DATABASE_URL": ""})
        self.database_env.start()
        database.initialize_database()

    def tearDown(self):
        database.DATABASE_PATH = self.original_database_path
        self.database_env.stop()
        self.temp_dir.cleanup()

    def test_user_and_auth_schema_initialize(self):
        database.create_user("user-a")

        self.assertTrue(database.user_exists("user-a"))
        self.assertFalse(database.user_exists("missing-user"))
        with database.get_connection() as connection:
            columns = {
                row["name"]
                for row in connection.execute("PRAGMA table_info(auth_devices)").fetchall()
            }
        self.assertIn("active_user_id", columns)

    def test_otp_challenge_is_created_and_verified(self):
        challenge_id = database.create_otp_challenge(
            "person@example.com", "email", "123456", create_account=True,
            username="person", password_hash="hashed-password",
        )

        self.assertGreater(challenge_id, 0)
        challenge = database.verify_otp_challenge("person@example.com", "123456")
        self.assertEqual(challenge["username"], "person")
        self.assertEqual(challenge["password_hash"], "hashed-password")
        self.assertIsNone(database.verify_otp_challenge("person@example.com", "123456"))

    def test_statement_and_transactions_are_saved_once(self):
        transaction = {
            "transaction_number": 1,
            "date": "2026-01-02",
            "description": "Cafe",
            "amount": 125.0,
            "type": "debit",
            "balance": 875.0,
            "category": "Food",
            "transaction_type": "expense",
        }
        statement_id, created = database.save_statement_with_transactions(
            "user-a", "a" * 64, "statement.pdf", [transaction], b"pdf-data",
        )
        duplicate_id, duplicate_created = database.save_statement_with_transactions(
            "user-a", "a" * 64, "statement.pdf", [transaction], b"pdf-data",
        )

        self.assertTrue(created)
        self.assertFalse(duplicate_created)
        self.assertEqual(statement_id, duplicate_id)
        saved = database.get_statement_transactions("user-a", statement_id)
        self.assertEqual(len(saved), 1)
        self.assertEqual(saved[0]["description"], "Cafe")
        self.assertEqual(database.get_statement_pdf("user-a", statement_id)["pdf_data"], b"pdf-data")

    def test_merchant_corrections_are_account_scoped(self):
        save_correction("user-a", "cafe", "Food")
        save_correction("user-a", "cafe", "Entertainment")

        self.assertEqual(get_correction("user-a", "cafe"), "Entertainment")
        self.assertIsNone(get_correction("user-b", "cafe"))


class PostgreSQLAdapterTests(unittest.TestCase):
    class Cursor:
        rowcount = 1

    class FakeConnection:
        def __init__(self):
            self.query = None
            self.parameters = None

        def execute(self, query, parameters=()):
            self.query = query
            self.parameters = parameters
            return PostgreSQLAdapterTests.Cursor()

    def test_sqlite_insert_and_schema_syntax_is_translated(self):
        connection = self.FakeConnection()
        adapter = database.PostgreSQLConnection(connection)
        adapter.execute(
            "INSERT OR IGNORE INTO files (id INTEGER PRIMARY KEY AUTOINCREMENT, data BLOB) VALUES (?, ?)",
            ("file-a", b"data"),
        )

        self.assertIn("INSERT INTO", connection.query)
        self.assertIn("BIGSERIAL PRIMARY KEY", connection.query)
        self.assertIn("BYTEA", connection.query)
        self.assertIn("ON CONFLICT DO NOTHING", connection.query)
        self.assertIn("%s", connection.query)
        self.assertEqual(connection.parameters, ("file-a", b"data"))

    def test_pragma_table_info_uses_postgresql_catalog(self):
        connection = self.FakeConnection()
        database.PostgreSQLConnection(connection).execute("PRAGMA table_info(users)")

        self.assertIn("information_schema.columns", connection.query)
        self.assertEqual(connection.parameters, ("users",))


class EmailDeliveryTests(unittest.TestCase):
    def test_resend_email_uses_https_api(self):
        response = MagicMock()
        response.status = 200
        response.__enter__.return_value = response
        with patch.dict(os.environ, {
            "RESEND_API_KEY": "test-api-key",
            "RESEND_FROM_EMAIL": "Stack Up <verify@example.test>",
            "SMTP_HOST": "",
        }), patch("services.auth_service.urllib.request.urlopen", return_value=response) as send:
            _send_email_otp("person@example.test", "123456")

        request = send.call_args.args[0]
        payload = json.loads(request.data.decode())
        self.assertEqual(request.full_url, "https://api.resend.com/emails")
        self.assertEqual(request.get_header("Authorization"), "Bearer test-api-key")
        self.assertEqual(payload["to"], ["person@example.test"])
        self.assertIn("123456", payload["text"])


if __name__ == "__main__":
    unittest.main()
