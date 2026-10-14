import os
import tempfile
import unittest
from pathlib import Path
from unittest.mock import patch

from fastapi.testclient import TestClient

from backend import main
from database import database
from database.corrections import get_correction, save_correction
from services import message_handler


class UserDataIsolationApiTests(unittest.TestCase):
    def setUp(self):
        self.temp_dir = tempfile.TemporaryDirectory()
        self.original_database_path = database.DATABASE_PATH
        database.DATABASE_PATH = str(Path(self.temp_dir.name) / "isolation.db")
        self.database_env = patch.dict(os.environ, {"DATABASE_URL": ""})
        self.database_env.start()
        database.initialize_database()

        database.create_user("user-a")
        database.create_user("user-b")
        with database.get_connection() as connection:
            connection.execute(
                "UPDATE users SET username = ? WHERE user_id = ?",
                ("account-a", "user-a"),
            )
            connection.execute(
                "UPDATE users SET username = ? WHERE user_id = ?",
                ("account-b", "user-b"),
            )
        self.token_a = "session-token-user-a"
        self.token_b = "session-token-user-b"
        database.create_auth_session("user-a", self.token_a)
        database.create_auth_session("user-b", self.token_b)
        self.client = TestClient(main.app)
        self.addCleanup(self.client.close)

        self.bank_a = database.create_user_bank_account("user-a", "A checking")
        self.bank_b = database.create_user_bank_account("user-b", "B checking")
        self.statement_a, _ = database.save_statement_with_transactions(
            "user-a",
            "a" * 64,
            "a-statement.pdf",
            [
                {
                    "date": "2026-09-01",
                    "description": "A private grocery",
                    "amount": 100,
                    "type": "debit",
                    "category": "Food",
                    "transaction_type": "expense",
                },
            ],
            b"%PDF-user-a",
        )
        self.statement_b, _ = database.save_statement_with_transactions(
            "user-b",
            "b" * 64,
            "b-statement.pdf",
            [
                {
                    "date": "2026-09-02",
                    "description": "UPI/P2M/123/B private merchant/UPI/BANK",
                    "amount": 250,
                    "type": "debit",
                    "category": "Shopping",
                    "transaction_type": "expense",
                },
                {
                    "date": "2026-09-03",
                    "description": "UPI/P2A/456/B private sender/UPI/BANK",
                    "amount": 400,
                    "type": "credit",
                    "category": "UPI Received",
                    "transaction_type": "transfer",
                },
            ],
            b"%PDF-user-b",
        )
        database.assign_statement_bank_account(
            "user-a", self.statement_a, self.bank_a["id"]
        )
        database.assign_statement_bank_account(
            "user-b", self.statement_b, self.bank_b["id"]
        )
        self.transaction_b_debit, self.transaction_b_credit = [
            row["id"] for row in database.get_statement_transactions(
                "user-b", self.statement_b
            )
        ]
        save_correction("user-b", "B private merchant", "Shopping")

    def tearDown(self):
        database.DATABASE_PATH = self.original_database_path
        self.database_env.stop()
        self.temp_dir.cleanup()

    def request_as_a(self, method, path, **kwargs):
        cookies = kwargs.pop("cookies", {})
        token = cookies.get("stack_up_session", self.token_a)
        self.client.cookies.set("stack_up_session", token)
        return self.client.request(method, path, **kwargs)

    def test_authentication_and_account_lists_are_user_scoped(self):
        device_token = database.remember_account_on_device(None, "user-a")
        self.client.cookies.set("stack_up_device", device_token)
        profile = self.request_as_a("GET", "/auth/me")
        accounts = self.request_as_a("GET", "/auth/accounts")

        self.assertEqual(profile.status_code, 200)
        self.assertEqual(profile.json()["username"], "account-a")
        self.assertEqual(accounts.status_code, 200)
        self.assertEqual(
            {row["user_id"] for row in accounts.json()["accounts"]},
            {"user-a"},
        )
        bank_accounts = self.request_as_a("GET", "/bank-accounts")
        self.assertEqual(bank_accounts.status_code, 200)
        self.assertEqual(
            {row["name"] for row in bank_accounts.json()["bank_accounts"]},
            {"A checking"},
        )
        switch_to_b = self.request_as_a(
            "POST",
            "/auth/switch-account",
            json={"user_id": "user-b"},
        )
        self.assertEqual(switch_to_b.status_code, 404)
        self.assertEqual(
            self.request_as_a("GET", "/auth/me").json()["username"],
            "account-a",
        )
        self.client.cookies.delete("stack_up_device")
        self.assertEqual(
            self.request_as_a(
                "GET", "/auth/me", cookies={"stack_up_session": "invalid"}
            ).status_code,
            401,
        )

    def test_add_account_does_not_authenticate_or_expose_another_user(self):
        response = self.request_as_a("POST", "/auth/add-account")

        self.assertEqual(response.status_code, 200)
        self.assertEqual(self.request_as_a("GET", "/auth/me").status_code, 401)
        self.client.cookies.set("stack_up_session", self.token_b)
        profile_b = self.client.get("/auth/me")
        self.assertEqual(profile_b.status_code, 200)
        self.assertEqual(profile_b.json()["username"], "account-b")

    def test_statement_reads_and_deletes_reject_another_users_ids(self):
        history = self.request_as_a("GET", "/statements")
        self.assertEqual(history.status_code, 200)
        self.assertEqual(
            {row["statement_id"] for row in history.json()["statements"]},
            {self.statement_a},
        )
        combined = self.request_as_a("GET", "/statements/combined")
        self.assertEqual(combined.status_code, 200)
        self.assertEqual(len(combined.json()["transactions"]), 1)
        self.assertEqual(
            combined.json()["transactions"][0]["description"],
            "A private grocery",
        )

        self.assertEqual(
            self.request_as_a(
                "GET", f"/statements/{self.statement_b}"
            ).status_code,
            404,
        )
        self.assertEqual(
            self.request_as_a(
                "GET", f"/statements/{self.statement_b}/pdf"
            ).status_code,
            404,
        )
        self.assertEqual(
            self.request_as_a(
                "GET",
                "/statements/selection",
                params={"statement_ids": self.statement_b},
            ).status_code,
            404,
        )
        self.assertEqual(
            self.request_as_a(
                "DELETE", f"/statements/{self.statement_b}"
            ).status_code,
            404,
        )
        self.assertIsNotNone(database.get_statement("user-b", self.statement_b))

    def test_category_and_income_updates_cannot_mutate_another_users_transaction(self):
        category_response = self.request_as_a(
            "PATCH",
            f"/transactions/{self.transaction_b_debit}/category",
            json={"category": "Food"},
        )
        inclusion_response = self.request_as_a(
            "PATCH",
            f"/transactions/{self.transaction_b_credit}/income-inclusion",
            json={"included": True},
        )

        self.assertEqual(category_response.status_code, 200)
        self.assertEqual(category_response.json()["status"], "error")
        self.assertEqual(inclusion_response.status_code, 404)
        b_transactions = database.get_statement_transactions(
            "user-b", self.statement_b
        )
        b_by_id = {row["id"]: row for row in b_transactions}
        self.assertEqual(b_by_id[self.transaction_b_debit]["category"], "Shopping")
        self.assertFalse(b_by_id[self.transaction_b_credit]["income_included"])
        self.assertIsNone(get_correction("user-a", "B private merchant"))
        self.assertEqual(
            get_correction("user-b", "B private merchant"),
            "Shopping",
        )

    def test_bank_account_assignment_enforces_statement_and_account_ownership(self):
        foreign_statement = self.request_as_a(
            "PATCH",
            f"/statements/{self.statement_b}/bank-account",
            json={"bank_account_id": self.bank_a["id"]},
        )
        foreign_account = self.request_as_a(
            "PATCH",
            f"/statements/{self.statement_a}/bank-account",
            json={"bank_account_id": self.bank_b["id"]},
        )

        self.assertEqual(foreign_statement.status_code, 404)
        self.assertEqual(foreign_account.status_code, 404)
        self.assertTrue(database.assign_statement_bank_account(
            "user-a", self.statement_a, self.bank_a["id"]
        ))
        self.assertTrue(database.assign_statement_bank_account(
            "user-b", self.statement_b, self.bank_b["id"]
        ))

    def test_upload_rejects_another_users_bank_account(self):
        response = self.request_as_a(
            "POST",
            "/upload-statement",
            data={"bank_account_id": str(self.bank_b["id"])},
            files={
                "file": (
                    "new-statement.pdf",
                    b"%PDF-not-stored",
                    "application/pdf",
                )
            },
        )

        self.assertEqual(response.status_code, 404)
        self.assertEqual(
            len(database.get_user_transactions("user-b")),
            2,
        )

    @patch.object(
        message_handler,
        "understand_financial_question",
        return_value={
            "intent": "general",
            "category": None,
            "answer": "Reviewed the authorized statement data.",
        },
    )
    def test_assistant_context_contains_only_authenticated_users_data(
        self, understand
    ):
        response = self.request_as_a(
            "POST",
            "/message",
            params={"message": "Can I afford a purchase based on my statement?"},
            json={},
        )

        self.assertEqual(response.status_code, 200)
        context_transactions = understand.call_args.args[1]
        self.assertEqual(len(context_transactions), 1)
        self.assertEqual(
            context_transactions[0]["description"],
            "A private grocery",
        )
        self.assertNotIn(
            "B private merchant",
            repr(context_transactions),
        )

    def test_message_route_rejects_another_users_statement_selection(self):
        with patch.object(
            main,
            "handle_user_message",
            side_effect=AssertionError("must reject before handling the request"),
        ):
            response = self.request_as_a(
                "POST",
                "/message",
                params={
                    "message": "Summarize my statement",
                    "statement_ids": self.statement_b,
                },
                json={},
            )

        self.assertEqual(response.status_code, 404)
