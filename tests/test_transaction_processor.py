import unittest
from unittest.mock import patch

from services import transaction_processor
from services.transaction_processor import transactions_for_same_counterparty
from services.transaction_processor import determine_transaction_type
from services.transaction_processor import normalize_upi_category


class CounterpartyTransactionTests(unittest.TestCase):
    def test_finds_all_matching_upi_counterparties_case_insensitively(self):
        selected = {
            "id": 1,
            "description": "UPI/P2M/111/Seeta Byreshwara Prov/UPI/BANK",
        }
        transactions = [
            selected,
            {
                "id": 2,
                "description": "UPI/P2M/222/seeta byreshwara prov/UPI/BANK",
            },
            {"id": 3, "description": "UPI/P2P/333/Someone Else/UPI/BANK"},
            {"id": 4, "description": "CARD/POS/Seeta Byreshwara Prov"},
        ]

        matches = transactions_for_same_counterparty(transactions, selected)

        self.assertEqual([item["id"] for item in matches], [1, 2])

    def test_non_upi_transaction_remains_a_single_transaction_update(self):
        selected = {"id": 1, "description": "CARD/POS/Some Merchant"}
        transactions = [
            selected,
            {"id": 2, "description": "CARD/POS/Some Merchant"},
        ]

        self.assertEqual(
            transactions_for_same_counterparty(transactions, selected),
            [selected],
        )

    def test_upi_received_is_income_and_upi_sent_remains_transfer(self):
        self.assertEqual(
            determine_transaction_type({"type": "credit"}, "UPI Received"),
            "income",
        )
        self.assertEqual(
            determine_transaction_type({"type": "debit"}, "UPI Sent"),
            "transfer",
        )

    def test_upi_category_and_type_follow_each_transaction_bank_direction(self):
        credit = {"type": "credit"}
        debit = {"type": "debit"}

        self.assertEqual(normalize_upi_category(credit, "UPI Received"), "UPI Received")
        self.assertEqual(normalize_upi_category(debit, "UPI Received"), "UPI Sent")
        self.assertEqual(normalize_upi_category(credit, "UPI Sent"), "UPI Received")
        self.assertEqual(normalize_upi_category(debit, "UPI Sent"), "UPI Sent")
        self.assertEqual(
            determine_transaction_type(debit, "UPI Received"),
            "transfer",
        )
        self.assertEqual(
            determine_transaction_type(credit, "UPI Sent"),
            "income",
        )

    def test_known_bank_direction_overrides_conflicting_upi_narration_marker(self):
        debit = {
            "type": "debit",
            "description": "UPI/P2P/123/Person/CR",
        }

        self.assertEqual(transaction_processor.upi_transfer_category(debit), "UPI Sent")

    @patch.object(
        transaction_processor,
        "find_correction_for_description",
        return_value={"category": "UPI Received"},
    )
    def test_saved_upi_received_correction_keeps_debits_as_upi_sent(self, _correction):
        transactions = [
            {
                "transaction_number": 1,
                "description": "UPI/P2P/123/Alex Kumar/UPI/BANK",
                "type": "credit",
            },
            {
                "transaction_number": 2,
                "description": "UPI/P2P/456/Alex Kumar/UPI/BANK",
                "type": "debit",
            },
        ]

        categorized = transaction_processor.categorize_transactions(
            transactions,
            user_id="user-a",
        )

        self.assertEqual(
            [(item["category"], item["transaction_type"]) for item in categorized],
            [("UPI Received", "income"), ("UPI Sent", "transfer")],
        )
