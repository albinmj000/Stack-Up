import unittest

from services.analyzer import analyze_transactions


class AnalyzerTests(unittest.TestCase):
    def test_upi_received_counts_as_income_even_if_saved_as_transfer(self):
        result = analyze_transactions([
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
            {
                "amount": 1000,
                "type": "debit",
                "category": "Food",
                "transaction_type": "expense",
            },
        ])

        self.assertEqual(result["total_income"], 1500)
        self.assertEqual(result["total_expenses"], 1000)
        self.assertEqual(result["net_cash_flow"], 500)
        self.assertEqual(result["total_transfer_in"], 0)
        self.assertEqual(result["total_transfer_out"], 500)
