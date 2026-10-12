import unittest
from types import SimpleNamespace
from unittest.mock import patch

from services import ai_assistant, message_handler


class MessageHandlerTests(unittest.TestCase):
    def setUp(self):
        self.correction_patch = patch.object(
            message_handler, "process_correction_message", return_value=None
        )
        self.correction_patch.start()

    def tearDown(self):
        self.correction_patch.stop()

    @patch.object(message_handler, "get_user_transactions")
    @patch.object(message_handler, "understand_financial_question")
    def test_budget_question_is_ai_answer_even_if_model_suggests_category_list(
        self, understand, get_transactions
    ):
        get_transactions.return_value = [{"amount": 100, "type": "debit"}]
        understand.return_value = {
            "intent": "list_category",
            "category": "Income",
            "answer": "Use the statement surplus to set a savings target.",
        }

        result = message_handler.handle_user_message(
            "user-1",
            "Based on my income, realistically how much can I save in a month?",
        )

        self.assertEqual(result["type"], "ai_answer")
        self.assertEqual(
            result["message"],
            "Use the statement surplus to set a savings target.",
        )

    @patch.object(message_handler, "get_user_transactions")
    def test_largest_expense_question_returns_sorted_rows_and_excludes_transfers(
        self, get_transactions
    ):
        get_transactions.return_value = [
            {"id": 1, "amount": 400, "type": "debit", "transaction_type": "expense", "description": "Cafe"},
            {"id": 2, "amount": 900, "type": "debit", "transaction_type": "expense", "description": "Rent"},
            {"id": 3, "amount": 700, "type": "debit", "transaction_type": "transfer", "description": "Own account transfer"},
            {"id": 4, "amount": 1200, "type": "credit", "transaction_type": "income", "description": "Salary"},
            {"id": 5, "amount": 650, "type": "debit", "transaction_type": "expense", "description": "Travel"},
        ]

        result = message_handler.handle_user_message(
            "user-1",
            "Find my 2 largest withdrawals and explain which transactions contribute most to my spending",
        )

        self.assertEqual(result["type"], "top_transactions")
        self.assertEqual([row["id"] for row in result["transactions"]], [2, 5])
        self.assertEqual(result["data"], {"count": 2, "total": 1550.0})
        self.assertIn("transfers excluded", result["message"])

    @patch.object(message_handler, "get_transaction_count", return_value=17)
    def test_transaction_count_question(self, _count):
        result = message_handler.handle_user_message("user-1", "How many transactions do I have?")
        self.assertEqual(result["data"]["transaction_count"], 17)

    @patch.object(message_handler, "get_transaction_totals")
    def test_total_expenses_question(self, totals):
        totals.return_value = {"total_income": 20000, "total_expenses": 5000}
        result = message_handler.handle_user_message("user-1", "What are my total expenses?")
        self.assertEqual(result["data"]["total_expenses"], 5000)

    @patch.object(message_handler, "get_category_total", return_value=1250)
    def test_category_total_question(self, total):
        result = message_handler.handle_user_message("user-1", "How much did I spend on Food?")
        total.assert_called_once_with("user-1", "Food")
        self.assertEqual(result["data"]["amount"], 1250)

    @patch.object(message_handler, "get_transactions_by_category")
    def test_list_category_question(self, rows):
        rows.return_value = [{"id": 1, "category": "Food"}, {"id": 2, "category": "Food"}]
        result = message_handler.handle_user_message("user-1", "Show all Food transactions")
        self.assertEqual(result["type"], "category_transactions")
        self.assertEqual(len(result["transactions"]), 2)

    @patch.object(message_handler, "format_statement_summary")
    def test_statement_summary_question(self, summary):
        summary.return_value = (["Income: INR 1000"], {"Food": 50})
        result = message_handler.handle_user_message("user-1", "Summarize my statement")
        self.assertEqual(result["message"], "Income: INR 1000")

    @patch.object(message_handler, "format_saving_guidance")
    def test_quick_saving_question(self, guidance):
        guidance.return_value = {"message": "Review your largest categories.", "suggestions": []}
        result = message_handler.handle_user_message("user-1", "How can I save more?")
        self.assertEqual(result["type"], "saving_guidance")
        guidance.assert_called_once_with("user-1", None)

    @patch.object(message_handler, "get_user_transactions", return_value=[])
    def test_general_question_without_statement(self, _transactions):
        result = message_handler.handle_user_message("user-1", "Can you help me plan?")
        self.assertIn("Upload a bank statement first", result["message"])


class FinancialQuestionPromptTests(unittest.TestCase):
    @patch.object(ai_assistant, "get_client")
    def test_prompt_uses_compact_recent_rows_and_full_statement_totals(self, get_client):
        response = SimpleNamespace(
            choices=[SimpleNamespace(message=SimpleNamespace(
                content='{"intent":"general","category":null,"answer":"Your spending is summarized."}'
            ))]
        )
        create = get_client.return_value.chat.completions.create
        create.return_value = response
        transactions = [
            {
                "id": index,
                "date": "2026-09-30",
                "description": "Merchant " + ("x" * 150),
                "amount": 100,
                "balance": 900,
                "type": "debit",
                "category": "Food",
                "transaction_type": "expense",
            }
            for index in range(100)
        ]

        result = ai_assistant.understand_financial_question("How can I budget?", transactions)

        self.assertEqual(result["intent"], "general")
        prompt = create.call_args.kwargs["messages"][0]["content"]
        self.assertIn('"expense":10000.0', prompt)
        self.assertIn('"amount_inr":100', prompt)
        self.assertIn("Recent transaction details omitted: 70", prompt)
        self.assertNotIn("x" * 101, prompt)


if __name__ == "__main__":
    unittest.main()
