import unittest
from unittest.mock import patch

from services import transaction_query


class TransactionQueryTotalsTests(unittest.TestCase):
    def test_user_selected_upi_credit_is_income_in_user_totals(self):
        with patch.object(
            transaction_query,
            "get_user_transactions",
            return_value=[
                {
                    "amount": 1500,
                    "type": "credit",
                    "category": "UPI Received",
                    "transaction_type": "transfer",
                    "income_included": 1,
                },
            ],
        ):
            result = transaction_query.get_transaction_totals("user-a")

        self.assertEqual(result["total_income"], 1500)
        self.assertEqual(result["total_upi_received"], 1500)

    def test_user_selected_upi_credit_is_income_in_statement_totals(self):
        with patch.object(
            transaction_query,
            "get_statement_transactions",
            return_value=[
                {
                    "amount": 1500,
                    "type": "credit",
                    "category": "UPI Received",
                    "transaction_type": "transfer",
                    "income_included": 1,
                },
            ],
        ):
            result = transaction_query.get_statement_totals("user-a", 1)

        self.assertEqual(result["total_income"], 1500)
        self.assertEqual(result["total_upi_received"], 1500)

    def setUp(self):
        self.transactions = [
            {
                "amount": 1500,
                "type": "credit",
                "category": "UPI Received",
                "transaction_type": "income",
            },
            {
                "amount": 500,
                "type": "debit",
                "category": "UPI Sent",
                "transaction_type": "expense",
            },
            {
                "amount": 200,
                "type": "debit",
                "category": "Transfer",
                "description": "Own account transfer",
                "transaction_type": "income",
            },
        ]

    @patch.object(transaction_query, "get_user_transactions")
    def test_user_totals_separate_upi_from_income_and_expenses(self, get_transactions):
        get_transactions.return_value = self.transactions

        result = transaction_query.get_transaction_totals("user-a")

        self.assertEqual(result["total_income"], 0)
        self.assertEqual(result["total_expenses"], 200)
        self.assertEqual(result["total_transfer_in"], 0)
        self.assertEqual(result["total_transfer_out"], 200)
        self.assertEqual(result["total_upi_received"], 1500)
        self.assertEqual(result["total_upi_sent"], 500)

    @patch.object(transaction_query, "get_statement_transactions")
    def test_statement_totals_separate_upi_from_income_and_expenses(self, get_transactions):
        get_transactions.return_value = self.transactions

        result = transaction_query.get_statement_totals("user-a", 1)

        self.assertEqual(result["total_income"], 0)
        self.assertEqual(result["total_expenses"], 200)
        self.assertEqual(result["total_transfer_in"], 0)
        self.assertEqual(result["total_transfer_out"], 200)
        self.assertEqual(result["total_upi_received"], 1500)
        self.assertEqual(result["total_upi_sent"], 500)

    @patch.object(transaction_query, "get_user_transactions")
    def test_shared_expense_uses_owner_share_in_totals_and_category_queries(
        self, get_transactions
    ):
        get_transactions.return_value = [
            {
                "amount": 15000,
                "type": "debit",
                "category": "Bills & Utilities",
                "transaction_type": "expense",
                "shared_bill_owner_share": 7500,
            },
        ]

        totals = transaction_query.get_transaction_totals("user-a")
        category_totals = transaction_query.get_category_totals("user-a")
        category_total = transaction_query.get_category_total(
            "user-a", "Bills & Utilities"
        )

        self.assertEqual(totals["total_expenses"], 7500)
        self.assertEqual(category_totals["Bills & Utilities"], 7500)
        self.assertEqual(category_total, 7500)

    @patch.object(transaction_query, "get_statement_transactions")
    def test_statement_category_totals_use_shared_owner_share(self, get_transactions):
        get_transactions.return_value = [
            {
                "amount": 15000,
                "type": "debit",
                "category": "Bills & Utilities",
                "transaction_type": "expense",
                "shared_bill_owner_share": 7500,
            },
        ]

        category_totals = transaction_query.get_statement_category_totals(
            "user-a", 1
        )
        category_total = transaction_query.get_statement_category_total(
            "user-a", 1, "Bills & Utilities"
        )

        self.assertEqual(category_totals["Bills & Utilities"], 7500)
        self.assertEqual(category_total, 7500)
