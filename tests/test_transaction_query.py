import unittest
from unittest.mock import patch

from services import transaction_query


class TransactionQueryTotalsTests(unittest.TestCase):
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
