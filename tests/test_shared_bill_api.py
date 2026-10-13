import asyncio
import unittest
from unittest.mock import patch

from fastapi import HTTPException

from backend import main


class SharedBillApiTests(unittest.TestCase):
    def setUp(self):
        self.transaction = {
            "id": 12,
            "amount": 150,
            "type": "debit",
            "transaction_type": "expense",
            "category": "Bills & Utilities",
        }
        self.auth_patch = patch.object(
            main, "authenticated_account", return_value={"user_id": "user-a"}
        )
        self.auth_patch.start()
        self.addCleanup(self.auth_patch.stop)

    def invoke(self, payload):
        return asyncio.run(main.create_shared_bill(None, payload))

    def payload(self):
        return {
            "transaction_id": 12,
            "title": "Dinner",
            "owner_share": 50,
            "participants": [
                {"name": "Alex", "share_amount": 60},
                {"name": "Sam", "share_amount": 40},
            ],
        }

    @patch.object(main, "list_user_shared_bills", return_value=[])
    @patch.object(main, "create_user_shared_bill")
    @patch.object(main, "get_user_transactions")
    def test_create_accepts_valid_split_with_cents(
        self, get_transactions, create_bill, _list_bills
    ):
        get_transactions.return_value = [self.transaction]

        result = self.invoke(self.payload())

        self.assertEqual(result, {"status": "success", "shared_bills": []})
        create_bill.assert_called_once_with(
            "user-a",
            12,
            "Dinner",
            50,
            [
                {"name": "Alex", "share_amount": 60},
                {"name": "Sam", "share_amount": 40},
            ],
        )

    @patch.object(main, "create_user_shared_bill")
    @patch.object(main, "get_user_transactions")
    def test_create_rejects_shares_that_do_not_match_payment(
        self, get_transactions, create_bill
    ):
        get_transactions.return_value = [self.transaction]
        payload = self.payload()
        payload["owner_share"] = 51

        with self.assertRaises(HTTPException) as raised:
            self.invoke(payload)

        self.assertEqual(raised.exception.status_code, 400)
        create_bill.assert_not_called()

    @patch.object(main, "get_user_transactions")
    def test_create_rejects_upi_or_non_owned_transactions(self, get_transactions):
        get_transactions.return_value = []
        with self.assertRaises(HTTPException) as missing:
            self.invoke(self.payload())
        self.assertEqual(missing.exception.status_code, 404)

        get_transactions.return_value = [{
            **self.transaction,
            "category": "UPI Sent",
        }]
        with self.assertRaises(HTTPException) as invalid_type:
            self.invoke(self.payload())
        self.assertEqual(invalid_type.exception.status_code, 400)

    @patch.object(main, "get_user_transactions")
    def test_create_rejects_amounts_with_more_than_two_decimal_places(
        self, get_transactions
    ):
        get_transactions.return_value = [self.transaction]
        payload = self.payload()
        payload["owner_share"] = 50.001

        with self.assertRaises(HTTPException) as raised:
            self.invoke(payload)

        self.assertEqual(raised.exception.status_code, 400)
