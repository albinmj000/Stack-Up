import os
import json
import unittest
import unittest
from types import SimpleNamespace
from unittest.mock import patch

from services import ai_assistant, message_handler


class TransactionTotalTests(unittest.TestCase):
    def test_user_selected_upi_credit_counts_as_income(self):
        totals = message_handler.transaction_totals([
            {
                "amount": 1500,
                "type": "credit",
                "category": "UPI Received",
                "transaction_type": "transfer",
                "income_included": 1,
            },
        ])

        self.assertEqual(totals["total_income"], 1500)
        self.assertEqual(totals["total_upi_received"], 1500)

    def test_upi_activity_is_separate_in_assistant_totals(self):
        totals = message_handler.transaction_totals([
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
                "transaction_type": "income",
            },
        ])

        self.assertEqual(totals["total_income"], 0)
        self.assertEqual(totals["total_expenses"], 200)
        self.assertEqual(totals["total_transfer_in"], 0)
        self.assertEqual(totals["total_transfer_out"], 200)
        self.assertEqual(totals["total_upi_received"], 1500)
        self.assertEqual(totals["total_upi_sent"], 500)

    def test_shared_expense_uses_owner_share_in_assistant_summaries(self):
        transaction = {
            "amount": 15000,
            "type": "debit",
            "category": "Bills & Utilities",
            "transaction_type": "expense",
            "shared_bill_owner_share": 7500,
        }

        totals = message_handler.transaction_totals([transaction])
        spending = message_handler.spending_summary([transaction])

        self.assertEqual(totals["total_expenses"], 7500)
        self.assertEqual(spending["Bills & Utilities"], 7500)

    def test_received_shared_bill_repayments_count_as_assistant_income(self):
        totals = message_handler.transaction_totals([
            {
                "amount": 15000,
                "type": "debit",
                "category": "Bills & Utilities",
                "transaction_type": "expense",
                "shared_bill_owner_share": 7500,
                "shared_bill_repaid_amount": 5000,
            },
        ])

        self.assertEqual(totals["total_income"], 5000)
        self.assertEqual(totals["total_expenses"], 7500)


class OverlappingStatementDeduplicationTests(unittest.TestCase):
    def test_shared_bill_owner_share_is_preserved_when_overlapping_rows_deduplicate(self):
        transactions = [
            {
                "id": 1,
                "statement_id": 10,
                "bank_account_id": 7,
                "date": "2026-09-18",
                "description": "Rent payment",
                "amount": 15000,
                "type": "debit",
                "transaction_type": "expense",
                "category": "Bills & Utilities",
            },
            {
                "id": 2,
                "statement_id": 11,
                "bank_account_id": 7,
                "date": "2026-09-18",
                "description": "Rent payment",
                "amount": 15000,
                "type": "debit",
                "transaction_type": "expense",
                "category": "Bills & Utilities",
                "shared_bill_owner_share": 7500,
                "shared_bill_id": 4,
                "shared_bill_repaid_amount": 5000,
            },
        ]

        result = message_handler.deduplicate_overlapping_statement_transactions(
            transactions
        )

        self.assertEqual(len(result), 1)
        self.assertEqual(result[0]["shared_bill_owner_share"], 7500)
        self.assertEqual(result[0]["shared_bill_id"], 4)
        self.assertEqual(result[0]["shared_bill_repaid_amount"], 5000)

    def test_keeps_manual_income_choice_when_duplicate_is_in_other_statement(self):
        transactions = [
            {
                "id": 1,
                "statement_id": 10,
                "bank_account_id": 7,
                "date": "2026-09-18",
                "description": "UPI/P2P/ALICE/UPI",
                "amount": 8000,
                "type": "credit",
                "category": "UPI Received",
                "transaction_type": "transfer",
                "income_included": 0,
            },
            {
                "id": 2,
                "statement_id": 11,
                "bank_account_id": 7,
                "date": "2026-09-18",
                "description": "UPI P2P ALICE UPI",
                "amount": 8000,
                "type": "credit",
                "category": "UPI Received",
                "transaction_type": "transfer",
                "income_included": 1,
            },
        ]

        result = message_handler.deduplicate_overlapping_statement_transactions(
            transactions
        )

        self.assertEqual(len(result), 1)
        self.assertTrue(result[0]["income_included"])

    def test_deduplicates_reference_and_normalized_details_across_statements(self):
        transactions = [
            {
                "id": 1,
                "statement_id": 10,
                "date": "18-09-2026",
                "description": "UPI/P2M/Shop/Tea",
                "reference": "UPI-123456",
                "amount": 250,
                "type": "debit",
            },
            {
                "id": 2,
                "statement_id": 11,
                "date": "2026-09-18",
                "description": "UPI P2M Shop Tea",
                "reference": "upi/123456",
                "amount": 250.00,
                "type": "debit",
            },
            {
                "id": 3,
                "statement_id": 10,
                "date": "19-09-2026",
                "description": "Cafe Central",
                "reference": None,
                "amount": 80,
                "type": "debit",
            },
            {
                "id": 4,
                "statement_id": 11,
                "date": "19/09/2026",
                "description": "  CAFE   CENTRAL ",
                "reference": None,
                "amount": 80.0,
                "type": "debit",
            },
        ]

        result = message_handler.deduplicate_overlapping_statement_transactions(
            transactions
        )

        self.assertEqual([item["id"] for item in result], [1, 3])

    def test_preserves_identical_transactions_within_one_statement(self):
        transactions = [
            {
                "id": 1,
                "statement_id": 10,
                "date": "18-09-2026",
                "description": "Cafe Central",
                "amount": 80,
                "type": "debit",
            },
            {
                "id": 2,
                "statement_id": 10,
                "date": "18-09-2026",
                "description": "Cafe Central",
                "amount": 80,
                "type": "debit",
            },
            {
                "id": 3,
                "statement_id": 11,
                "date": "18-09-2026",
                "description": "Cafe Central",
                "amount": 80,
                "type": "debit",
            },
        ]

        result = message_handler.deduplicate_overlapping_statement_transactions(
            transactions
        )

        self.assertEqual([item["id"] for item in result], [1, 2])

    def test_keeps_matching_transactions_from_different_bank_accounts(self):
        first = {
            "id": 1,
            "statement_id": 10,
            "bank_account_id": 20,
            "date": "18-09-2026",
            "description": "Cafe Central",
            "reference": "same-reference",
            "amount": 80,
            "type": "debit",
        }
        second = {
            **first,
            "id": 2,
            "statement_id": 11,
            "bank_account_id": 21,
        }

        result = message_handler.deduplicate_overlapping_statement_transactions(
            [first, second]
        )

        self.assertEqual([item["id"] for item in result], [1, 2])

    def test_preserves_maximum_repeat_count_across_overlapping_statements(self):
        def transaction(transaction_id, statement_id):
            return {
                "id": transaction_id,
                "statement_id": statement_id,
                "date": "18-09-2026",
                "description": "Cafe Central",
                "amount": 80,
                "type": "debit",
            }

        transactions = [
            transaction(1, 10),
            transaction(2, 10),
            transaction(3, 11),
            transaction(4, 11),
            transaction(5, 11),
        ]

        result = message_handler.deduplicate_overlapping_statement_transactions(
            transactions
        )

        self.assertEqual([item["id"] for item in result], [1, 2, 5])

    def test_selected_statement_combination_uses_deduplicated_rows(self):
        statement_a = [
            {
                "id": 1,
                "statement_id": 10,
                "date": "18-09-2026",
                "description": "Salary",
                "reference": "NEFT123",
                "amount": 1000,
                "type": "credit",
                "transaction_type": "income",
            }
        ]
        statement_b = [
            {
                **statement_a[0],
                "id": 2,
                "statement_id": 11,
            },
            {
                "id": 3,
                "statement_id": 11,
                "date": "20-09-2026",
                "description": "Other income",
                "reference": "NEFT456",
                "amount": 500,
                "type": "credit",
                "transaction_type": "income",
            },
        ]

        with (
            patch.object(message_handler, "get_statement_transactions") as get_rows,
            patch.object(message_handler, "understand_financial_question") as understand,
            patch.object(message_handler, "process_correction_message", return_value=None),
        ):
            get_rows.side_effect = [statement_a, statement_b]
            understand.return_value = {
                "intent": "general",
                "category": None,
                "answer": "Combined income summary.",
            }

            result = message_handler.handle_user_message(
                "user-a",
                "How much is my income from both statements?",
                statement_ids=[10, 11],
            )

        self.assertEqual(result["type"], "ai_answer")
        context_transactions = understand.call_args.args[1]
        self.assertEqual(len(context_transactions), 2)
        self.assertEqual(sum(row["amount"] for row in context_transactions), 1500)


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
    @patch.object(message_handler, "understand_financial_question")
    def test_monthly_savings_question_receives_account_transactions(
        self, understand, get_transactions
    ):
        account_transactions = [
            {
                "amount": 12000,
                "type": "credit",
                "transaction_type": "income",
                "category": "Income",
            },
            {
                "amount": 5000,
                "type": "debit",
                "transaction_type": "expense",
                "category": "Bills & Utilities",
            },
        ]
        get_transactions.return_value = account_transactions
        understand.return_value = {
            "intent": "general",
            "category": None,
            "answer": "Your saved transactions can help estimate that.",
        }

        result = message_handler.handle_user_message(
            "user-1",
            "Will I be able to save 6000 monthly according to expenses?",
        )

        self.assertEqual(result["type"], "ai_answer")
        self.assertEqual(
            understand.call_args.args[1],
            account_transactions,
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
            {"amount": 2500, "type": "debit", "transaction_type": "transfer"},
            {"amount": 20000, "type": "credit", "transaction_type": "income"},
        ]
        result = message_handler.handle_user_message("user-1", "What are my total expenses?")
        self.assertEqual(result["data"]["total_expenses"], 7500)

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

    @patch.object(message_handler, "understand_financial_question")
    @patch.object(message_handler, "get_user_transactions")
    def test_merchant_spend_question_returns_exact_rows_and_debit_total(
        self, get_transactions, understand
    ):
        get_transactions.return_value = [
            {
                "id": 1,
                "date": "12-09-2026",
                "description": "UPI/P2M/111/Thalassery Food Court/UPI/BANK",
                "amount": 350,
                "type": "debit",
                "transaction_type": "expense",
            },
            {
                "id": 2,
                "date": "13-09-2026",
                "description": "UPI/P2M/222/Thalassery Food Court/UPI/BANK",
                "amount": 150,
                "type": "debit",
                "transaction_type": "expense",
            },
            {
                "id": 3,
                "date": "14-09-2026",
                "description": "UPI/P2A/333/Thalassery Food Court/UPI/BANK",
                "amount": 500,
                "type": "credit",
                "transaction_type": "income",
            },
            {
                "id": 4,
                "description": "UPI/P2M/444/Other Restaurant/UPI/BANK",
                "amount": 900,
                "type": "debit",
                "transaction_type": "expense",
            },
        ]

        result = message_handler.handle_user_message(
            "user-1",
            "How much did I totally spend in Thalasseri restaurant?",
        )

        self.assertEqual(result["type"], "transaction_search")
        self.assertEqual(result["data"]["spent_total"], 500)
        self.assertEqual(result["data"]["debit_count"], 2)
        self.assertEqual(result["data"]["transaction_count"], 3)
        self.assertEqual(
            [row["id"] for row in result["transactions"]],
            [3, 2, 1],
        )
        understand.assert_not_called()

    @patch.object(message_handler, "get_user_transactions")
    def test_follow_up_lists_matching_transactions_for_previous_counterparty(
        self, get_transactions
    ):
        get_transactions.return_value = [
            {
                "id": 1,
                "description": "UPI/P2M/111/Thalassery Food Court/UPI/BANK",
                "amount": 350,
                "type": "debit",
                "transaction_type": "expense",
            },
            {
                "id": 2,
                "description": "UPI/P2M/222/Thalassery Food Court/UPI/BANK",
                "amount": 150,
                "type": "debit",
                "transaction_type": "expense",
            },
        ]

        result = message_handler.handle_user_message(
            "user-1",
            "Show all transactions to that UPI sender",
            history=[
                {
                    "role": "user",
                    "text": "How much did I spend at Thalasseri restaurant?",
                },
                {
                    "role": "assistant",
                    "text": "You spent ₹500 at Thalassery Food Court.",
                },
            ],
        )

        self.assertEqual(result["type"], "transaction_search")
        self.assertEqual([row["id"] for row in result["transactions"]], [2, 1])
        self.assertEqual(result["data"]["spent_total"], 500)

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
    def test_prompt_marks_manually_included_upi_as_income(self, get_client):
        get_client.return_value.chat.completions.create.return_value = (
            self.response_with_content(
                '{"intent":"general","category":null,"answer":"Income includes selected credits."}'
            )
        )
        ai_assistant.understand_financial_question(
            "What is my income?",
            [{
                "amount": 1500,
                "type": "credit",
                "category": "UPI Received",
                "transaction_type": "transfer",
                "income_included": 1,
            }],
        )

        prompt = get_client.return_value.chat.completions.create.call_args.kwargs[
            "messages"
        ][0]["content"]
        self.assertIn('"income":1500.0', prompt)
        self.assertIn('"included_in_income":true', prompt)

    @patch.object(ai_assistant, "get_client")
    def test_prompt_counts_only_received_shared_bill_repayments_as_income(
        self, get_client
    ):
        get_client.return_value.chat.completions.create.return_value = (
            self.response_with_content(
                '{"intent":"general","category":null,"answer":"Received repayments are income."}'
            )
        )
        ai_assistant.understand_financial_question(
            "How much income did I receive?",
            [{
                "amount": 15000,
                "type": "debit",
                "category": "Bills & Utilities",
                "transaction_type": "expense",
                "shared_bill_owner_share": 7500,
                "shared_bill_repaid_amount": 5000,
            }],
        )

        prompt = get_client.return_value.chat.completions.create.call_args.kwargs[
            "messages"
        ][0]["content"]

        self.assertIn('"income":5000.0', prompt)
        self.assertIn('"shared_bill_repaid_amount_inr":5000.0', prompt)
        self.assertIn("marks them as repaid", prompt)

    @patch.object(ai_assistant, "get_client")
    def test_prompt_reports_upi_activity_separately_from_income(self, get_client):
        get_client.return_value.chat.completions.create.return_value = (
            self.response_with_content(
                '{"intent":"general","category":null,"answer":"UPI totals are separate."}'
            )
        )
        transactions = [
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
        ]

        ai_assistant.understand_financial_question(
            "What is my income?", transactions
        )

        prompt = get_client.return_value.chat.completions.create.call_args.kwargs[
            "messages"
        ][0]["content"]
        self.assertIn('"upi_received":1500.0', prompt)
        self.assertIn('"upi_sent":500.0', prompt)
        self.assertIn("excluded from income", prompt)

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
