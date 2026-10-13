import os
import json
import io
import tempfile
import unittest
from pathlib import Path
from unittest.mock import MagicMock, patch
from urllib.error import HTTPError

from database import database
from database.corrections import get_correction, save_correction
from services import auth_service
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
        self.assertEqual(saved[0]["income_included"], 0)
        self.assertEqual(database.get_statement_pdf("user-a", statement_id)["pdf_data"], b"pdf-data")

    def test_shared_bill_persists_owner_share_and_scopes_repayments(self):
        transaction = {
            "transaction_number": 1,
            "date": "2026-01-02",
            "description": "Monthly rent",
            "amount": 15000.0,
            "type": "debit",
            "balance": 0,
            "category": "Bills & Utilities",
            "transaction_type": "expense",
        }
        statement_id, _ = database.save_statement_with_transactions(
            "user-a", "a" * 64, "rent.pdf", [transaction], b"pdf",
        )
        transaction_id = database.get_statement_transactions(
            "user-a", statement_id
        )[0]["id"]
        bill_id = database.create_user_shared_bill(
            "user-a",
            transaction_id,
            "Monthly rent",
            7500,
            [
                {"name": "Alex", "share_amount": 5000},
                {"name": "Sam", "share_amount": 2500},
            ],
        )
        with self.assertRaisesRegex(ValueError, "already has a shared bill"):
            database.create_user_shared_bill(
                "user-a",
                transaction_id,
                "Duplicate rent",
                7500,
                [{"name": "Alex", "share_amount": 7500}],
            )
        bill = database.list_user_shared_bills("user-a")[0]

        self.assertEqual(bill["id"], bill_id)
        self.assertEqual(bill["gross_amount"], 15000)
        self.assertEqual(bill["owner_share"], 7500)
        self.assertEqual(bill["amount_owed"], 7500)
        self.assertTrue(database.set_shared_bill_participant_paid(
            "user-a", bill_id, bill["participants"][0]["id"], True
        ))
        self.assertEqual(
            database.get_statement_transactions("user-a", statement_id)[0][
                "shared_bill_repaid_amount"
            ],
            5000,
        )
        self.assertFalse(database.set_shared_bill_participant_paid(
            "user-b", bill_id, bill["participants"][1]["id"], True
        ))
        updated_bill = database.list_user_shared_bills("user-a")[0]
        self.assertEqual(updated_bill["repaid_amount"], 5000)
        self.assertEqual(updated_bill["amount_owed"], 2500)
        self.assertTrue(database.set_shared_bill_participant_paid(
            "user-a", bill_id, bill["participants"][0]["id"], False
        ))
        self.assertEqual(
            database.get_statement_transactions("user-a", statement_id)[0][
                "shared_bill_repaid_amount"
            ],
            0,
        )

        saved_transaction = database.get_statement_transactions(
            "user-a", statement_id
        )[0]
        self.assertEqual(saved_transaction["shared_bill_id"], bill_id)
        self.assertEqual(saved_transaction["shared_bill_owner_share"], 7500)
        self.assertTrue(database.delete_user_shared_bill("user-a", bill_id))
        self.assertIsNone(
            database.get_statement_transactions("user-a", statement_id)[0][
                "shared_bill_owner_share"
            ]
        )

    def test_statement_replacement_clears_its_shared_bill_tracking(self):
        transaction = {
            "transaction_number": 1,
            "date": "2026-01-02",
            "description": "Shared dinner",
            "amount": 100,
            "type": "debit",
            "balance": 0,
            "category": "Food",
            "transaction_type": "expense",
        }
        statement_id, _ = database.save_statement_with_transactions(
            "user-a", "a" * 64, "dinner.pdf", [transaction], b"pdf",
        )
        transaction_id = database.get_statement_transactions(
            "user-a", statement_id
        )[0]["id"]
        database.create_user_shared_bill(
            "user-a",
            transaction_id,
            "Dinner",
            50,
            [{"name": "Alex", "share_amount": 50}],
        )

        database.replace_statement_transactions(
            "user-a",
            statement_id,
            [{**transaction, "description": "Updated dinner"}],
        )

        self.assertEqual(database.list_user_shared_bills("user-a"), [])
        replaced = database.get_statement_transactions("user-a", statement_id)
        self.assertEqual(len(replaced), 1)
        self.assertIsNone(replaced[0]["shared_bill_owner_share"])

    def test_income_inclusion_is_saved_and_scoped_to_the_user(self):
        transaction = {
            "transaction_number": 1,
            "date": "2026-01-02",
            "description": "UPI/P2P/Person",
            "amount": 8000.0,
            "type": "credit",
            "category": "UPI Received",
            "transaction_type": "transfer",
        }
        owner_statement, _ = database.save_statement_with_transactions(
            "user-a", "a" * 64, "owner.pdf", [transaction], b"owner-pdf",
        )
        other_statement, _ = database.save_statement_with_transactions(
            "user-b", "b" * 64, "other.pdf", [transaction], b"other-pdf",
        )
        owner_transaction_id = database.get_statement_transactions(
            "user-a", owner_statement
        )[0]["id"]
        other_transaction_id = database.get_statement_transactions(
            "user-b", other_statement
        )[0]["id"]

        self.assertTrue(database.update_transaction_income_inclusion(
            "user-a", owner_transaction_id, True
        ))
        self.assertFalse(database.update_transaction_income_inclusion(
            "user-a", other_transaction_id, True
        ))
        self.assertEqual(
            database.get_statement_transactions("user-a", owner_statement)[0][
                "income_included"
            ],
            1,
        )
        self.assertEqual(
            database.get_statement_transactions("user-b", other_statement)[0][
                "income_included"
            ],
            0,
        )

    def test_bank_accounts_and_statement_assignments_are_user_scoped(self):
        account_id = database.create_user_bank_account("user-a", "Everyday account")["id"]
        other_account_id = database.create_user_bank_account("user-b", "Everyday account")["id"]
        with self.assertRaisesRegex(ValueError, "name already exists"):
            database.create_user_bank_account("user-a", "everyday ACCOUNT")
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
        statement_id, _ = database.save_statement_with_transactions(
            "user-a", "a" * 64, "january.pdf", [transaction], b"pdf",
        )

        self.assertTrue(database.assign_statement_bank_account(
            "user-a", statement_id, account_id
        ))
        with self.assertRaisesRegex(ValueError, "Bank account not found"):
            database.assign_statement_bank_account(
                "user-a", statement_id, other_account_id
            )
        saved_statement = database.list_user_statements("user-a")[0]
        self.assertEqual(saved_statement["bank_account_id"], account_id)
        self.assertEqual(saved_statement["bank_account_name"], "Everyday account")
        self.assertEqual(
            database.get_statement_transactions("user-a", statement_id)[0]["bank_account_id"],
            account_id,
        )
        self.assertEqual(database.get_user_transactions("user-a")[0]["bank_account_id"], account_id)
        self.assertEqual(database.list_user_bank_accounts("user-a")[0]["name"], "Everyday account")
        self.assertEqual(database.list_user_bank_accounts("user-b")[0]["id"], other_account_id)

    def test_bulk_category_update_is_scoped_to_the_user(self):
        transaction = {
            "transaction_number": 1,
            "date": "2026-01-02",
            "description": "UPI/P2P/123/Seeta/UPI/BANK",
            "amount": 125.0,
            "type": "debit",
            "balance": 875.0,
            "category": "UPI Sent",
            "transaction_type": "transfer",
        }
        owner_statement, _ = database.save_statement_with_transactions(
            "user-a", "a" * 64, "owner.pdf", [transaction], b"owner-pdf",
        )
        other_statement, _ = database.save_statement_with_transactions(
            "user-b", "b" * 64, "other.pdf", [transaction], b"other-pdf",
        )
        owner_transaction_id = database.get_statement_transactions(
            "user-a", owner_statement
        )[0]["id"]
        other_transaction_id = database.get_statement_transactions(
            "user-b", other_statement
        )[0]["id"]

        updated_count = database.update_transaction_categories(
            "user-a",
            [
                (owner_transaction_id, "Food", "expense"),
                (other_transaction_id, "Food", "expense"),
            ],
        )

        self.assertEqual(updated_count, 1)
        self.assertEqual(
            database.get_statement_transactions("user-a", owner_statement)[0]["category"],
            "Food",
        )
        self.assertEqual(
            database.get_statement_transactions("user-b", other_statement)[0]["category"],
            "UPI Sent",
        )

    def test_delete_statement_removes_only_owned_statement_and_transactions(self):
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
        statement_id, _ = database.save_statement_with_transactions(
            "user-a", "a" * 64, "statement.pdf", [transaction], b"pdf-data",
        )
        transaction_id = database.get_statement_transactions(
            "user-a", statement_id
        )[0]["id"]
        database.create_user_shared_bill(
            "user-a",
            transaction_id,
            "Cafe with a friend",
            60,
            [{"name": "Alex", "share_amount": 65}],
        )

        self.assertFalse(database.delete_user_statement("user-b", statement_id))
        self.assertIsNotNone(database.get_statement("user-a", statement_id))
        self.assertTrue(database.delete_user_statement("user-a", statement_id))
        self.assertIsNone(database.get_statement("user-a", statement_id))
        self.assertEqual(database.get_statement_transactions("user-a", statement_id), [])
        self.assertEqual(database.list_user_shared_bills("user-a"), [])

    def test_merchant_corrections_are_account_scoped(self):
        save_correction("user-a", "cafe", "Food")
        save_correction("user-a", "cafe", "Entertainment")

        self.assertEqual(get_correction("user-a", "cafe"), "Entertainment")
        self.assertIsNone(get_correction("user-b", "cafe"))

    def test_password_update_preserves_only_current_session(self):
        database.create_user("user-a")
        database.create_auth_session("user-a", "current-session")
        database.create_auth_session("user-a", "other-session")
        current_device = database.remember_account_on_device(None, "user-a")
        other_device = database.remember_account_on_device(None, "user-a")

        self.assertTrue(database.update_account_password(
            "user-a", "new-password-hash", "current-session", current_device
        ))
        self.assertIsNotNone(database.get_session_user("current-session"))
        self.assertIsNone(database.get_session_user("other-session"))
        self.assertIsNotNone(database.get_auth_device_user(current_device))
        self.assertIsNone(database.get_auth_device_user(other_device))

    def test_remembered_account_removal_is_device_scoped_and_cannot_remove_active(self):
        account_a = database.create_account("a@example.com", "email", "account-a")
        account_b = database.create_account("b@example.com", "email", "account-b")
        device_token = database.remember_account_on_device(None, account_a["user_id"])
        database.remember_account_on_device(device_token, account_b["user_id"])
        database.switch_auth_device_account(device_token, account_a["user_id"])

        self.assertFalse(database.remove_auth_device_account(device_token, account_a["user_id"]))
        self.assertTrue(database.remove_auth_device_account(device_token, account_b["user_id"]))
        self.assertEqual(
            [item["user_id"] for item in database.list_auth_device_accounts(device_token)],
            [account_a["user_id"]],
        )

    def test_profile_updates_keep_username_and_contact_unique(self):
        account_a = database.create_account("a@example.com", "email", "account-a")
        account_b = database.create_account("b@example.com", "email", "account-b")

        with self.assertRaisesRegex(ValueError, "username is already in use"):
            database.update_account_username(account_a["user_id"], "account-b")
        with self.assertRaisesRegex(ValueError, "email or phone number is already used"):
            database.update_account_contact(
                account_a["user_id"], "email", account_b["email"]
            )

    def test_delete_account_removes_only_owned_financial_and_auth_data(self):
        account_a = database.create_account("a@example.com", "email", "account-a")
        account_b = database.create_account("b@example.com", "email", "account-b")
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
        statement_a, _ = database.save_statement_with_transactions(
            account_a["user_id"], "a" * 64, "a.pdf", [transaction], b"a-pdf",
        )
        statement_b, _ = database.save_statement_with_transactions(
            account_b["user_id"], "b" * 64, "b.pdf", [transaction], b"b-pdf",
        )
        save_correction(account_a["user_id"], "cafe", "Food")
        save_correction(account_b["user_id"], "cafe", "Food")
        database.create_user_bank_account(account_a["user_id"], "Daily account")
        database.create_user_bank_account(account_b["user_id"], "Daily account")
        database.create_auth_session(account_a["user_id"], "account-a-session")
        database.create_auth_session(account_b["user_id"], "account-b-session")
        device_a = database.remember_account_on_device(None, account_a["user_id"])
        database.create_otp_challenge(
            "a@example.com", "email", "123456",
            purpose="account_deletion", user_id=account_a["user_id"],
        )

        self.assertTrue(database.delete_user_account(account_a["user_id"]))
        self.assertIsNone(database.get_account_by_id(account_a["user_id"]))
        self.assertEqual(database.get_user_transactions(account_a["user_id"]), [])
        self.assertEqual(database.list_user_statements(account_a["user_id"]), [])
        self.assertIsNone(get_correction(account_a["user_id"], "cafe"))
        self.assertIsNone(database.get_session_user("account-a-session"))
        self.assertIsNone(database.get_auth_device(device_a))
        self.assertEqual(database.list_user_bank_accounts(account_a["user_id"]), [])
        self.assertTrue(database.get_user_transactions(account_b["user_id"]))
        self.assertEqual(database.list_user_bank_accounts(account_b["user_id"])[0]["name"], "Daily account")
        self.assertEqual(database.get_statement(account_b["user_id"], statement_b)["filename"], "b.pdf")
        self.assertEqual(get_correction(account_b["user_id"], "cafe"), "Food")
        self.assertIsNotNone(database.get_session_user("account-b-session"))
        self.assertIsNone(database.get_statement(account_a["user_id"], statement_a))

    def test_contact_change_otp_is_bound_to_authenticated_account_and_purpose(self):
        account = database.create_account("owner@example.com", "email", "owner")
        codes = []

        with patch.object(auth_service, "_send_email_otp", side_effect=lambda _, code: codes.append(code)):
            contact, channel = auth_service.request_contact_change_otp(
                account["user_id"], "new-owner@example.com"
            )

        challenge = database.verify_otp_challenge(contact, codes[0])
        self.assertEqual(channel, "email")
        self.assertEqual(challenge["purpose"], "contact_change")
        self.assertEqual(challenge["user_id"], account["user_id"])

    def test_sensitive_action_otp_is_bound_to_its_owner_and_purpose(self):
        account = database.create_account("owner@example.com", "email", "owner")
        codes = []

        with patch.object(auth_service, "_send_email_otp", side_effect=lambda _, code: codes.append(code)):
            channel = auth_service.request_account_verification_otp(
                account["user_id"], "account_deletion"
            )

        challenge = database.verify_otp_challenge("owner@example.com", codes[0])
        self.assertEqual(channel, "email")
        self.assertEqual(challenge["purpose"], "account_deletion")
        self.assertEqual(challenge["user_id"], account["user_id"])


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
            "RESEND_FROM_EMAIL": "",
            "RESEND_TEST_RECIPIENT": "person@example.test",
        }), patch("services.auth_service.urllib.request.urlopen", return_value=response) as send:
            _send_email_otp("person@example.test", "123456")

        request = send.call_args.args[0]
        payload = json.loads(request.data.decode())
        self.assertEqual(request.full_url, "https://api.resend.com/emails")
        self.assertEqual(request.get_header("Authorization"), "Bearer test-api-key")
        self.assertEqual(request.get_header("Accept"), "application/json")
        self.assertEqual(request.get_header("User-agent"), "Stack-Up/1.0")
        self.assertEqual(payload["from"], "onboarding@resend.dev")
        self.assertEqual(payload["to"], ["person@example.test"])
        self.assertIn("123456", payload["text"])

    def test_resend_test_sender_rejects_unlisted_recipient(self):
        with patch.dict(os.environ, {
            "RESEND_API_KEY": "test-api-key",
            "RESEND_FROM_EMAIL": "onboarding@resend.dev",
            "RESEND_TEST_RECIPIENT": "person@example.test",
        }), patch("services.auth_service.urllib.request.urlopen") as send:
            with self.assertRaisesRegex(RuntimeError, "restricted"):
                _send_email_otp("someone-else@example.test", "123456")

        send.assert_not_called()

    def test_missing_resend_key_does_not_fall_back_to_smtp(self):
        with patch.dict(os.environ, {
            "RESEND_API_KEY": "",
            "SMTP_HOST": "smtp.example.test",
            "SMTP_USERNAME": "test-user",
            "SMTP_PASSWORD": "test-password",
            "RESEND_FROM_EMAIL": "",
        }), patch("services.auth_service.urllib.request.urlopen") as send:
            with self.assertRaisesRegex(RuntimeError, "RESEND_API_KEY"):
                _send_email_otp("person@example.test", "123456")

        send.assert_not_called()

    def test_resend_http_error_is_sanitized(self):
        api_key = "test-api-key-do-not-log"
        otp = "654321"
        provider_message = (
            f"The sender cannot deliver to person@example.test; key {api_key}; code {otp}."
        )
        provider_error = HTTPError(
            "https://api.resend.com/emails", 403, "Forbidden", {},
            io.BytesIO(json.dumps({
                "statusCode": 403,
                "name": "validation_error",
                "message": provider_message,
            }).encode()),
        )
        with patch.dict(os.environ, {
            "RESEND_API_KEY": api_key,
            "RESEND_FROM_EMAIL": "onboarding@resend.dev",
            "RESEND_TEST_RECIPIENT": "person@example.test",
        }), patch("services.auth_service.urllib.request.urlopen", side_effect=provider_error):
            with self.assertLogs("services.auth_service", level="WARNING") as captured:
                with self.assertRaisesRegex(RuntimeError, "HTTP 403") as raised:
                    _send_email_otp("person@example.test", otp)

        output = " ".join(captured.output) + str(raised.exception)
        self.assertIn("HTTP 403", output)
        self.assertIn("name=validation_error", output)
        self.assertIn("The sender cannot deliver to", output)
        self.assertNotIn(api_key, output)
        self.assertNotIn(otp, output)
        self.assertNotIn("person@example.test", output)

    def test_resend_non_json_error_does_not_log_raw_body(self):
        api_key = "test-resend-api-key"
        otp = "123456"
        raw_body = (
            f"Request denied for person@example.test; key {api_key}; code {otp}. "
            + "x" * 500
        ).encode()
        provider_error = HTTPError(
            "https://api.resend.com/emails", 403, "Forbidden",
            {"Content-Type": "text/plain; charset=utf-8"},
            io.BytesIO(raw_body),
        )
        with patch.dict(os.environ, {
            "RESEND_API_KEY": api_key,
            "RESEND_FROM_EMAIL": "onboarding@resend.dev",
            "RESEND_TEST_RECIPIENT": "person@example.test",
        }), patch("services.auth_service.urllib.request.urlopen", side_effect=provider_error):
            with self.assertLogs("services.auth_service", level="WARNING") as captured:
                with self.assertRaisesRegex(RuntimeError, "HTTP 403"):
                    _send_email_otp("person@example.test", "123456")

        output = " ".join(captured.output)
        self.assertIn("HTTP 403", output)
        self.assertIn("content_type=text/plain; charset=utf-8", output)
        self.assertIn("response_excerpt=Request denied for [email redacted]", output)
        excerpt = output.split("response_excerpt=", 1)[1][:-2]
        self.assertLessEqual(len(excerpt), 300)
        self.assertNotIn(api_key, output)
        self.assertNotIn(otp, output)
        self.assertNotIn("person@example.test", output)
        self.assertNotIn("Authorization", output)
        self.assertNotIn("x" * 350, output)


if __name__ == "__main__":
    unittest.main()
