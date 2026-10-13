from collections import defaultdict


def analyze_transactions(transactions):
    total_income = 0.0
    total_expenses = 0.0
    total_transfer_in = 0.0
    total_transfer_out = 0.0
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

        if category.casefold() == "upi received":
            total_income += amount

        elif category.lower() == "transfer" or transaction_type == "transfer":
            if direction == "credit":
                total_transfer_in += amount
            else:
                total_transfer_out += amount
                total_expenses += amount

        elif transaction_type == "income":
            total_income += amount

        elif transaction_type == "expense":
            total_expenses += amount

            # Only actual expenses contribute to spending categories.
            category_totals[category] += amount
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
        "total_unknown": round(total_unknown, 2),
        "net_cash_flow": round(net_cash_flow, 2),
        "savings_rate": round(savings_rate, 2),
        "category_totals": {
            category: round(amount, 2)
            for category, amount in category_totals.items()
        },
        "transaction_counts": dict(transaction_counts),
    }