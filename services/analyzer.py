from collections import defaultdict


def get_upi_activity(transaction):
    category = str(transaction.get("category") or "").strip().casefold()
    if category == "upi received":
        return "received"
    if category == "upi sent":
        return "sent"
    if category == "transfer" and "upi" in str(
        transaction.get("description") or ""
    ).casefold():
        direction = str(transaction.get("type") or "").strip().lower()
        if direction == "credit":
            return "received"
        if direction == "debit":
            return "sent"
    return None


def get_expense_amount(transaction):
    shared_share = transaction.get("shared_bill_owner_share")
    if shared_share is not None:
        try:
            return abs(float(shared_share))
        except (TypeError, ValueError):
            pass
    try:
        return abs(float(transaction.get("amount") or 0))
    except (TypeError, ValueError):
        return 0.0


def analyze_transactions(transactions):
    total_income = 0.0
    total_expenses = 0.0
    total_transfer_in = 0.0
    total_transfer_out = 0.0
    total_upi_received = 0.0
    total_upi_sent = 0.0
    total_unknown = 0.0

    category_totals = defaultdict(float)
    transaction_counts = defaultdict(int)

    for transaction in transactions:
        try:
            amount = abs(float(transaction.get("amount") or 0))
        except (TypeError, ValueError):
            continue

        transaction_type = str(
            transaction.get("transaction_type", "unknown")
        ).strip().lower()

        direction = str(
            transaction.get("type", "")
        ).strip().lower()

        category = str(
            transaction.get("category") or "Other"
        ).strip()

        upi_activity = get_upi_activity(transaction)
        if upi_activity == "received":
            total_upi_received += amount
            if transaction.get("income_included") in (True, 1):
                total_income += amount
        elif upi_activity == "sent":
            total_upi_sent += amount
        elif category.lower() == "transfer" or transaction_type == "transfer":
            if direction == "credit":
                total_transfer_in += amount
            else:
                total_transfer_out += amount
                total_expenses += amount

        elif transaction_type == "income":
            total_income += amount

        elif transaction_type == "expense":
            expense_amount = get_expense_amount(transaction)
            total_expenses += expense_amount

            # Only actual expenses contribute to spending categories.
            category_totals[category] += expense_amount
            transaction_counts[category] += 1

        else:
            total_unknown += amount

    net_cash_flow = total_income - total_expenses

    # Avoid misleading percentages when there is no income.
    savings_rate = (
        ((total_income - total_expenses) / total_income) * 100
        if total_income > 0
        else 0.0
    )

    return {
        "total_income": round(total_income, 2),
        "total_expenses": round(total_expenses, 2),
        "total_transfer_in": round(total_transfer_in, 2),
        "total_transfer_out": round(total_transfer_out, 2),
        "total_upi_received": round(total_upi_received, 2),
        "total_upi_sent": round(total_upi_sent, 2),
        "total_unknown": round(total_unknown, 2),
        "net_cash_flow": round(net_cash_flow, 2),
        "savings_rate": round(savings_rate, 2),
        "category_totals": {
            category: round(amount, 2)
            for category, amount in category_totals.items()
        },
        "transaction_counts": dict(transaction_counts),
    }