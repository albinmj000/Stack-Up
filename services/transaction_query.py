from database.database import (
    get_user_transactions,
    get_statement_transactions
)
from services.analyzer import get_upi_activity
from services.transaction_processor import rule_based_category


def get_transactions_for_user(user_id):

    return get_user_transactions(user_id)


def get_transactions_for_statement(
    user_id,
    statement_id
):

    return get_statement_transactions(
        user_id,
        statement_id
    )


def get_transaction_count(user_id):

    transactions = get_user_transactions(
        user_id
    )

    return len(transactions)


def get_statement_transaction_count(
    user_id,
    statement_id
):

    transactions = get_statement_transactions(
        user_id,
        statement_id
    )

    return len(transactions)


def get_transaction_totals(user_id):

    transactions = get_user_transactions(
        user_id
    )

    total_income = 0.0
    total_expenses = 0.0
    total_transfer_in = 0.0
    total_transfer_out = 0.0
    total_upi_received = 0.0
    total_upi_sent = 0.0
    total_unknown = 0.0

    for transaction in transactions:

        amount = transaction["amount"]

        transaction_type = transaction.get(
            "transaction_type",
            "unknown"
        )
        category = str(transaction.get("category") or "").strip().casefold()
        upi_activity = get_upi_activity(transaction)

        if upi_activity == "received":

            total_upi_received += amount

        elif upi_activity == "sent":

            total_upi_sent += amount

        elif category == "transfer" or transaction_type == "transfer":

            if transaction["type"] == "credit":

                total_transfer_in += amount

            else:

                total_transfer_out += amount
                total_expenses += amount

        elif transaction_type == "income":

            total_income += amount

        elif transaction_type == "expense":

            total_expenses += amount

        elif transaction_type == "unknown":

            total_unknown += amount

    return {
        "total_income": round(
            total_income,
            2
        ),
        "total_expenses": round(
            total_expenses,
            2
        ),
        "total_transfer_in": round(
            total_transfer_in,
            2
        ),
        "total_transfer_out": round(
            total_transfer_out,
            2
        ),
        "total_upi_received": round(total_upi_received, 2),
        "total_upi_sent": round(total_upi_sent, 2),
        "total_unknown": round(
            total_unknown,
            2
        )
    }


def get_statement_totals(
    user_id,
    statement_id
):

    transactions = get_statement_transactions(
        user_id,
        statement_id
    )

    total_income = 0.0
    total_expenses = 0.0
    total_transfer_in = 0.0
    total_transfer_out = 0.0
    total_upi_received = 0.0
    total_upi_sent = 0.0
    total_unknown = 0.0

    for transaction in transactions:

        amount = transaction["amount"]

        transaction_type = transaction.get(
            "transaction_type",
            "unknown"
        )
        category = str(transaction.get("category") or "").strip().casefold()
        upi_activity = get_upi_activity(transaction)

        if upi_activity == "received":

            total_upi_received += amount

        elif upi_activity == "sent":

            total_upi_sent += amount

        elif category == "transfer" or transaction_type == "transfer":

            if transaction["type"] == "credit":

                total_transfer_in += amount

            else:

                total_transfer_out += amount
                total_expenses += amount

        elif transaction_type == "income":

            total_income += amount

        elif transaction_type == "expense":

            total_expenses += amount

        elif transaction_type == "unknown":

            total_unknown += amount

    return {
        "total_income": round(
            total_income,
            2
        ),
        "total_expenses": round(
            total_expenses,
            2
        ),
        "total_transfer_in": round(
            total_transfer_in,
            2
        ),
        "total_transfer_out": round(
            total_transfer_out,
            2
        ),
        "total_upi_received": round(total_upi_received, 2),
        "total_upi_sent": round(total_upi_sent, 2),
        "total_unknown": round(
            total_unknown,
            2
        )
    }


def get_category_totals(user_id):

    transactions = get_user_transactions(
        user_id
    )

    category_totals = {}

    for transaction in transactions:

        category = transaction.get(
            "category",
            "Other"
        )

        amount = transaction["amount"]

        if category not in category_totals:

            category_totals[category] = 0.0

        category_totals[category] += amount

    return {
        category: round(
            amount,
            2
        )
        for category, amount
        in category_totals.items()
    }


def get_statement_category_totals(
    user_id,
    statement_id
):

    transactions = get_statement_transactions(
        user_id,
        statement_id
    )

    category_totals = {}

    for transaction in transactions:

        category = transaction.get(
            "category",
            "Other"
        )

        amount = transaction["amount"]

        if category not in category_totals:

            category_totals[category] = 0.0

        category_totals[category] += amount

    return {
        category: round(
            amount,
            2
        )
        for category, amount
        in category_totals.items()
    }


def get_category_total(
    user_id,
    category
):

    transactions = get_user_transactions(
        user_id
    )

    total = 0.0

    for transaction in transactions:

        transaction_category = transaction.get(
            "category",
            "Other"
        )

        if (
            transaction_category.lower()
            == category.lower()
        ):

            total += transaction["amount"]

    return round(
        total,
        2
    )


def get_statement_category_total(
    user_id,
    statement_id,
    category
):

    transactions = get_statement_transactions(
        user_id,
        statement_id
    )

    total = 0.0

    for transaction in transactions:

        transaction_category = transaction.get(
            "category",
            "Other"
        )

        if (
            transaction_category.lower()
            == category.lower()
        ):

            total += transaction["amount"]

    return round(
        total,
        2
    )


def get_transactions_by_category(
    user_id,
    category
):

    transactions = get_user_transactions(
        user_id
    )

    matching_transactions = []

    for transaction in transactions:

        transaction_category = transaction.get(
            "category",
            "Other"
        )

        if (
            transaction_category.lower()
            == category.lower()
        ):

            matching_transactions.append(
                transaction
            )

    return matching_transactions


def get_statement_transactions_by_category(
    user_id,
    statement_id,
    category
):

    transactions = get_statement_transactions(
        user_id,
        statement_id
    )

    matching_transactions = []

    for transaction in transactions:

        transaction_category = transaction.get(
            "category",
            "Other"
        )

        if (
            transaction_category.lower()
            == category.lower()
        ):

            matching_transactions.append(
                transaction
            )

    return matching_transactions


def get_spending_summary(user_id):

    transactions = get_user_transactions(
        user_id
    )

    category_totals = {}

    for transaction in transactions:

        description = str(transaction.get("description") or "")
        if (
            "upi" in description.lower()
            and rule_based_category(transaction) in ("Transfer", "UPI Sent", "UPI Received")
        ):
            # Re-evaluate old rows with current UPI rules so previously
            # miscategorized person-to-person transfers don't inflate spend.
            continue

        if (
            transaction.get(
                "transaction_type"
            )
            != "expense"
        ):

            continue

        category = transaction.get(
            "category",
            "Other"
        )

        amount = transaction["amount"]

        if category not in category_totals:

            category_totals[category] = 0.0

        category_totals[category] += amount

    return {
        category: round(
            amount,
            2
        )
        for category, amount
        in category_totals.items()
    }


def get_statement_spending_summary(
    user_id,
    statement_id
):

    transactions = get_statement_transactions(
        user_id,
        statement_id
    )

    category_totals = {}

    for transaction in transactions:

        if (
            transaction.get(
                "transaction_type"
            )
            != "expense"
        ):

            continue

        category = transaction.get(
            "category",
            "Other"
        )

        amount = transaction["amount"]

        if category not in category_totals:

            category_totals[category] = 0.0

        category_totals[category] += amount

    return {
        category: round(
            amount,
            2
        )
        for category, amount
        in category_totals.items()
    }
