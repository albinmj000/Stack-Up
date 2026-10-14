import asyncio
import unittest
from unittest.mock import patch

from backend import main


class TransactionCategoryApiTests(unittest.TestCase):
    def setUp(self):
        self.credit_transaction = {
            "id": 101,
            "description": "UPI/P2P/123/Alex Kumar/UPI/BANK",
            "type": "credit",
            "statement_id": 7,
        }
        self.debit_transaction = {
            "id": 102,
            "description": "UPI/P2P/456/Alex Kumar/UPI/BANK",
            "type": "debit",
            "statement_id": 7,
        }
        self.auth_patch = patch.object(
            main,
            "authenticated_account",
            return_value={"user_id": "user-a"},
        )
        self.auth_patch.start()
        self.addCleanup(self.auth_patch.stop)

    def invoke(self, transaction_id, payload):
        return asyncio.run(
            main.change_transaction_category(transaction_id, None, payload)
        )

    @patch.object(main, "get_statement_transactions", return_value=[])
    @patch.object(main, "save_correction")
    @patch.object(main, "update_transaction_categories", return_value=2)
    @patch.object(main, "get_user_transactions")
    def test_upi_received_edit_keeps_matching_debits_as_upi_sent(
        self,
        get_transactions,
        update_categories,
        _save_correction,
        _statement_transactions,
    ):
        get_transactions.return_value = [
            self.credit_transaction,
            self.debit_transaction,
        ]

        result = self.invoke(101, {"category": "UPI Received"})

        update_categories.assert_called_once_with(
            "user-a",
            [
                (101, "UPI Received", "income"),
                (102, "UPI Sent", "transfer"),
            ],
        )
        self.assertEqual(result["category"], "UPI Received")
        self.assertEqual(result["transaction_type"], "income")
        self.assertEqual(result["updated_count"], 2)
