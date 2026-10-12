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

    @patch.object(message_handler, "get_user_transactions")
    def test_transaction_count_question(self, get_transactions):
        get_transactions.return_value = [{"id": index} for index in range(17)]
        result = message_handler.handle_user_message("user-1", "How many transactions do I have?")
        self.assertEqual(result["data"]["transaction_count"], 17)

    @patch.object(message_handler, "get_user_transactions")
    def test_total_expenses_question(self, get_transactions):
        get_transactions.return_value = [
            {"amount": 5000, "type": "debit", "transaction_type": "expense"},
            {"amount": 20000, "type": "credit", "transaction_type": "income"},
        ]
        result = message_handler.handle_user_message("user-1", "What are my total expenses?")
        self.assertEqual(result["data"]["total_expenses"], 5000)

    @patch.object(message_handler, "get_user_transactions")
    def test_category_total_question(self, get_transactions):
        get_transactions.return_value = [
            {"amount": 1250, "category": "Food", "type": "debit", "transaction_type": "expense"},
            {"amount": 300, "category": "Transport", "type": "debit", "transaction_type": "expense"},
        ]
        result = message_handler.handle_user_message("user-1", "How much did I spend on Food?")
        self.assertEqual(result["data"]["amount"], 1250)

    @patch.object(message_handler, "get_user_transactions")
    def test_list_category_question(self, get_transactions):
        get_transactions.return_value = [
            {"id": 1, "category": "Food"},
            {"id": 2, "category": "Food"},
            {"id": 3, "category": "Transport"},
        ]
        result = message_handler.handle_user_message("user-1", "Show all Food transactions")
        self.assertEqual(result["type"], "category_transactions")
        self.assertEqual(len(result["transactions"]), 2)

    @patch.object(message_handler, "get_user_transactions")
    def test_statement_summary_question(self, get_transactions):
        get_transactions.return_value = [
            {"amount": 1000, "type": "credit", "transaction_type": "income", "category": "Income"},
            {"amount": 50, "type": "debit", "transaction_type": "expense", "category": "Food"},
        ]
        result = message_handler.handle_user_message("user-1", "Summarize my statement")
        self.assertIn("INR 1,000.00", result["message"])
        self.assertIn("Food: INR 50.00", result["message"])

    @patch.object(message_handler, "get_user_transactions")
    def test_quick_saving_question(self, get_transactions):
        get_transactions.return_value = [
            {"amount": 200, "type": "debit", "transaction_type": "expense", "category": "Food", "description": "Cafe"},
        ]
        result = message_handler.handle_user_message("user-1", "How can I save more?")
        self.assertEqual(result["type"], "saving_guidance")
        self.assertIn("Food", result["message"])

    @patch.object(message_handler, "get_user_transactions", return_value=[])
    def test_general_question_without_statement(self, _transactions):
        result = message_handler.handle_user_message("user-1", "Can you help me plan?")
        self.assertIn("Upload a bank statement first", result["message"])

    @patch.object(message_handler, "get_user_transactions")
    @patch.object(message_handler, "get_statement_transactions")
    def test_statement_id_scopes_all_question_results(self, scoped_rows, all_rows):
        scoped_rows.return_value = [
            {"id": 10, "amount": 75, "type": "debit", "transaction_type": "expense", "category": "Food"},
        ]
        all_rows.return_value = [
            {"id": 10, "amount": 75, "type": "debit", "transaction_type": "expense", "category": "Food"},
            {"id": 11, "amount": 500, "type": "debit", "transaction_type": "expense", "category": "Food"},
        ]

        result = message_handler.handle_user_message(
            "user-1", "What are my total expenses?", statement_id=22
        )

        scoped_rows.assert_called_once_with("user-1", 22)
        all_rows.assert_not_called()
        self.assertEqual(result["data"]["total_expenses"], 75)

    @patch.object(message_handler, "get_statement_transactions")
    def test_multiple_statement_ids_combine_only_selected_statements(self, scoped_rows):
        scoped_rows.side_effect = [
            [{"amount": 75, "type": "debit", "transaction_type": "expense", "category": "Food"}],
            [{"amount": 125, "type": "debit", "transaction_type": "expense", "category": "Food"}],
        ]

        result = message_handler.handle_user_message(
            "user-1", "What are my total expenses?", statement_ids=[22, 23]
        )

        self.assertEqual(result["data"]["total_expenses"], 200)
        self.assertEqual(
            [call.args for call in scoped_rows.call_args_list],
            [("user-1", 22), ("user-1", 23)],
        )


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
