import unittest

from services.analyzer import analyze_transactions


class AnalyzerTests(unittest.TestCase):
    def test_upi_activity_is_separate_from_income_expenses_and_transfers(self):
        result = analyze_transactions([
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
                "amount": 100,
                "type": "debit",
                "category": "Transfer",
                "description": "UPI/P2P/Another account",
                "transaction_type": "transfer",
            },
            {
                "amount": 1000,
                "type": "debit",
                "category": "Food",
                "transaction_type": "expense",
            },
            {
                "amount": 300,
                "type": "debit",
                "category": "Transfer",
                "description": "Own account transfer",
                "transaction_type": "income",
            },
        ])

        self.assertEqual(result["total_income"], 0)
        self.assertEqual(result["total_expenses"], 1300)
        self.assertEqual(result["net_cash_flow"], -1300)
        self.assertEqual(result["total_transfer_in"], 0)
        self.assertEqual(result["total_transfer_out"], 300)
        self.assertEqual(result["total_upi_received"], 1500)
        self.assertEqual(result["total_upi_sent"], 600)
