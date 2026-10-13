import unittest

from services.analyzer import analyze_transactions


class AnalyzerTests(unittest.TestCase):
    def test_user_selected_upi_credit_is_added_to_income(self):
        result = analyze_transactions([
            {
                "amount": 1500,
                "type": "credit",
                "category": "UPI Received",
                "transaction_type": "transfer",
                "income_included": True,
            },
            {
                "amount": 500,
                "type": "credit",
                "category": "UPI Received",
                "transaction_type": "transfer",
                "income_included": False,
            },
        ])

        self.assertEqual(result["total_income"], 1500)
        self.assertEqual(result["total_upi_received"], 2000)
        self.assertEqual(result["net_cash_flow"], 1500)

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

    def test_shared_expense_counts_only_owner_share(self):
        result = analyze_transactions([
            {
                "amount": 15000,
                "type": "debit",
                "category": "Bills & Utilities",
                "transaction_type": "expense",
                "shared_bill_owner_share": 7500,
            },
        ])

        self.assertEqual(result["total_expenses"], 7500)
        self.assertEqual(result["category_totals"]["Bills & Utilities"], 7500)
        self.assertEqual(result["net_cash_flow"], -7500)

    def test_only_marked_shared_bill_repayments_count_as_income(self):
        result = analyze_transactions([
            {
                "amount": 15000,
                "type": "debit",
                "category": "Bills & Utilities",
                "transaction_type": "expense",
                "shared_bill_owner_share": 7500,
                "shared_bill_repaid_amount": 5000,
            },
            {
                "amount": 10000,
                "type": "debit",
                "category": "Food",
                "transaction_type": "expense",
                "shared_bill_owner_share": 5000,
                "shared_bill_repaid_amount": 0,
            },
        ])

        self.assertEqual(result["total_income"], 5000)
        self.assertEqual(result["total_expenses"], 12500)
        self.assertEqual(result["net_cash_flow"], -7500)
