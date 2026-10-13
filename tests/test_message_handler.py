import os
import json
import unittest
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

    @patch.object(message_handler, "understand_financial_question")
    @patch.object(message_handler, "get_user_transactions", return_value=[])
    def test_general_question_without_statement(self, _transactions, understand):
        understand.return_value = {
            "intent": "general",
            "category": None,
            "answer": "A computer program follows instructions to perform tasks.",
        }
        result = message_handler.handle_user_message("user-1", "Can you help me plan?")
        self.assertEqual(result["type"], "ai_answer")
        self.assertIn("computer program", result["message"])
        understand.assert_called_once_with("Can you help me plan?", [], [])

    @patch.object(message_handler, "understand_financial_question")
    @patch.object(message_handler, "get_user_transactions")
    def test_general_technical_question_avoids_statement_data(
        self, get_transactions, understand
    ):
        get_transactions.return_value = [
            {"amount": 500, "type": "debit", "transaction_type": "expense"}
        ]
        understand.return_value = {
            "intent": "general",
            "category": None,
            "answer": "Review the code path and its tests.",
        }

        result = message_handler.handle_user_message(
            "user-1", "What changes should I make to this code?"
        )

        self.assertEqual(result["type"], "ai_answer")
        understand.assert_called_once_with(
            "What changes should I make to this code?", [], []
        )

    @patch.object(message_handler, "understand_financial_question")
    @patch.object(message_handler, "get_user_transactions")
    def test_general_question_does_not_send_selected_statement_data(
        self, get_transactions, understand
    ):
        get_transactions.return_value = [
            {"amount": 500, "type": "debit", "transaction_type": "expense"}
        ]
        understand.return_value = {
            "intent": "general",
            "category": None,
            "answer": "Photosynthesis converts light into chemical energy.",
        }

        result = message_handler.handle_user_message(
            "user-1", "Explain photosynthesis."
        )

        self.assertEqual(result["type"], "ai_answer")
        understand.assert_called_once_with("Explain photosynthesis.", [], [])

    @patch.object(message_handler, "understand_financial_question")
    @patch.object(message_handler, "get_user_transactions", return_value=[])
    def test_conversation_context_is_isolated_between_requests(
        self, _transactions, understand
    ):
        understand.return_value = {
            "intent": "general",
            "category": None,
            "answer": "Okay.",
        }
        first_history = [{"role": "user", "text": "The phone costs ₹90,000."}]
        second_history = [{"role": "user", "text": "My course costs ₹20,000."}]

        message_handler.handle_user_message(
            "user-1", "What do you think?", history=first_history
        )
        message_handler.handle_user_message(
            "user-2", "What do you think?", history=second_history
        )

        self.assertEqual(
            understand.call_args_list[0].args[2],
            first_history,
        )
        self.assertEqual(
            understand.call_args_list[1].args[2],
            second_history,
        )
        self.assertNotIn("course", understand.call_args_list[0].args[2][0]["text"])
        self.assertNotIn("phone", understand.call_args_list[1].args[2][0]["text"])

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
    @staticmethod
    def response_with_content(content):
        return SimpleNamespace(
            choices=[SimpleNamespace(message=SimpleNamespace(content=content))]
        )

    @patch.object(ai_assistant, "get_client")
    def test_prompt_uses_compact_recent_rows_and_full_statement_totals(self, get_client):
        response = self.response_with_content(
            '{"intent":"general","category":null,"answer":"Your spending is summarized."}'
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
        self.assertEqual(create.call_args.kwargs["response_format"], {"type": "json_object"})
        prompt = create.call_args.kwargs["messages"][0]["content"]
        self.assertIn('"expense":10000.0', prompt)
        self.assertIn('"amount_inr":100', prompt)
        self.assertIn("Recent transaction details omitted: 70", prompt)
        self.assertNotIn("x" * 101, prompt)

    @patch.object(ai_assistant, "get_client")
    def test_financial_answer_preserves_multiline_text(self, get_client):
        answer = "Your statement shows a surplus.\nTry setting aside a fixed amount after essentials."
        get_client.return_value.chat.completions.create.return_value = (
            self.response_with_content(json.dumps({
                "intent": "general",
                "category": None,
                "answer": answer,
            }))
        )

        result = ai_assistant.understand_financial_question(
            "How can I save?", [{"amount": 100, "type": "debit", "date": "2026-01-01"}]
        )

        self.assertTrue(result["answer"].endswith(answer))

    @patch.object(ai_assistant, "get_client")
    def test_financial_answer_preserves_quotation_marks(self, get_client):
        answer = 'Try the "pay yourself first" approach.'
        get_client.return_value.chat.completions.create.return_value = (
            self.response_with_content(json.dumps({
                "intent": "general",
                "category": None,
                "answer": answer,
            }))
        )

        result = ai_assistant.understand_financial_question(
            "How can I save?", [{"amount": 100, "type": "debit", "date": "2026-01-01"}]
        )

        self.assertTrue(result["answer"].endswith(answer))

    @patch.object(message_handler, "get_user_transactions")
    @patch.object(ai_assistant, "get_client")
    def test_malformed_ai_json_returns_existing_fallback(self, get_client, get_transactions):
        get_client.return_value.chat.completions.create.return_value = (
            self.response_with_content(
                '{"intent":"general","category":null,"answer":"First line\nSecond line"}'
            )
        )
        get_transactions.return_value = [
            {
                "amount": 100,
                "type": "debit",
                "transaction_type": "expense",
                "category": "Food",
                "date": "2026-01-01",
            }
        ]

        result = message_handler.handle_user_message(
            "user-1",
            "Based on my income, realistically how much can I save in a month?",
        )

        self.assertEqual(result["type"], "unknown")
        self.assertEqual(
            result["message"],
            "I couldn't answer that just now. Please try again shortly.",
        )


class EmiCalculationTests(unittest.TestCase):
    def test_follow_up_price_correction_is_used_for_emi(self):
        result = ai_assistant.calculate_emi_from_conversation(
            "Calculate EMI for 12 months at 12% annual interest.",
            [
                {"role": "user", "text": "The iPhone costs ₹1,00,000."},
                {"role": "assistant", "text": "Understood."},
                {"role": "user", "text": "Actually, it's ₹90,000."},
            ],
        )

        self.assertEqual(result["data"]["principal"], 90_000)
        self.assertEqual(result["data"]["months"], 12)
        self.assertAlmostEqual(result["data"]["monthly_emi"], 7_996.39, places=2)
        self.assertIn("latest purchase amount you provided", result["message"])

    def test_emi_requests_missing_user_inputs_instead_of_guessing(self):
        result = ai_assistant.calculate_emi_from_conversation(
            "What is the EMI?", [{"role": "user", "text": "The phone costs ₹90,000."}]
        )

        self.assertIn("annual interest rate", result["message"])
        self.assertIn("repayment period", result["message"])
        self.assertNotIn("data", result)


class AssistantErrorTests(unittest.TestCase):
    def test_timeout_has_a_clear_retry_message(self):
        error = message_handler.APITimeoutError(request=None)

        self.assertIn("did not respond in time", message_handler._model_error_message(error))


class WebSearchTests(unittest.TestCase):
    @patch.dict(os.environ, {"TAVILY_API_KEY": "test-key"})
    @patch.object(ai_assistant.urllib.request, "urlopen")
    def test_tavily_search_returns_retrieved_sources(self, urlopen):
        response = urlopen.return_value.__enter__.return_value
        response.read.return_value = json.dumps({
            "results": [{
                "title": "Product specifications",
                "url": "https://example.test/product",
                "content": "Retrieved specification snippet.",
            }]
        }).encode()

        sources = ai_assistant.search_web("current product specifications")

        self.assertEqual(sources[0]["title"], "Product specifications")
        request = urlopen.call_args.args[0]
        payload = json.loads(request.data.decode())
        self.assertEqual(payload["query"], "current product specifications")
        self.assertEqual(payload["search_depth"], "basic")
        self.assertEqual(urlopen.call_args.kwargs["timeout"], 8)

    @patch.object(ai_assistant, "search_web", side_effect=ai_assistant.WebSearchError("Unavailable"))
    @patch.object(ai_assistant, "get_client")
    def test_search_failure_does_not_claim_current_facts(self, get_client, _search):
        get_client.return_value.chat.completions.create.return_value = (
            FinancialQuestionPromptTests.response_with_content(json.dumps({
                "intent": "general",
                "category": None,
                "answer": "The current price is ₹90,000.",
                "needs_search": True,
                "search_query": "current phone price",
            }))
        )

        result = ai_assistant.understand_financial_question(
            "What is the current phone price?"
        )

        self.assertEqual(result["sources"], [])
        self.assertIn("couldn't verify current information", result["answer"])
        self.assertNotIn("₹90,000", result["answer"])
        get_client.return_value.chat.completions.create.assert_called_once()

    @patch.object(ai_assistant, "search_web")
    @patch.object(ai_assistant, "get_client")
    def test_search_answer_includes_only_retrieved_source_urls(self, get_client, search):
        search.return_value = [{
            "title": "Product source",
            "url": "https://example.test/source",
            "content": "Official product information.",
        }]
        get_client.return_value.chat.completions.create.side_effect = [
            FinancialQuestionPromptTests.response_with_content(json.dumps({
                "intent": "general",
                "category": None,
                "answer": "Searching.",
                "needs_search": True,
                "search_query": "latest product specification",
            })),
            FinancialQuestionPromptTests.response_with_content(
                '{"answer":"The retrieved source lists the requested specification."}'
            ),
        ]

        result = ai_assistant.understand_financial_question(
            "What are the latest specifications?"
        )

        self.assertIn("Current information retrieved from web search", result["answer"])
        self.assertIn("https://example.test/source", result["answer"])
        self.assertEqual(result["sources"][0]["url"], "https://example.test/source")


if __name__ == "__main__":
    unittest.main()
