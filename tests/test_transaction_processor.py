import unittest

from services.transaction_processor import transactions_for_same_counterparty


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
