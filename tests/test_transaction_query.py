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
                "transaction_type": "transfer",
            },
            {
                "amount": 500,
                "type": "debit",
                "category": "UPI Sent",
                "transaction_type": "transfer",
            },
        ]

    @patch.object(transaction_query, "get_user_transactions")
    def test_user_totals_include_legacy_upi_received_as_income(self, get_transactions):
        get_transactions.return_value = self.transactions

        result = transaction_query.get_transaction_totals("user-a")

        self.assertEqual(result["total_income"], 1500)
        self.assertEqual(result["total_transfer_in"], 0)
        self.assertEqual(result["total_transfer_out"], 500)

    @patch.object(transaction_query, "get_statement_transactions")
    def test_statement_totals_include_upi_received_as_income(self, get_transactions):
        get_transactions.return_value = self.transactions

        result = transaction_query.get_statement_totals("user-a", 1)

        self.assertEqual(result["total_income"], 1500)
        self.assertEqual(result["total_transfer_in"], 0)
        self.assertEqual(result["total_transfer_out"], 500)
