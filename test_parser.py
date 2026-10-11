"""Manual PDF parser demo; unittest discovery should only import this file."""

from pathlib import Path

from services.analyzer import analyze_transactions
from services.categorizer import rule_based_category
from services.statement_parser import (
    extract_text_from_pdf,
    extract_transactions_from_text,
)


def main():
    pdf_path = Path("bank_statement.pdf")
    if not pdf_path.is_file():
        raise SystemExit(
            "Place a readable bank_statement.pdf in the project root to run this parser demo."
        )

    text = extract_text_from_pdf(str(pdf_path))
    transactions = extract_transactions_from_text(text)
    for transaction in transactions:
        transaction["category"] = rule_based_category(transaction) or "Other"

    analysis = analyze_transactions(transactions)
    print("\n===== STACK UP FINANCIAL ANALYSIS =====\n")
    for key in (
        "total_money_in",
        "total_money_out",
        "total_transfer_in",
        "total_transfer_out",
        "total_known_expenses",
        "total_unclassified",
        "net_account_change",
    ):
        print(f"{key.replace('_', ' ').title()}:", analysis[key])

    print("\n===== CATEGORY TOTALS =====\n")
    for category, amount in analysis["category_totals"].items():
        print(f"{category}: {amount}")

    print("\n===== OTHER TRANSACTIONS =====\n")
    for transaction in transactions:
        if transaction["category"] == "Other":
            print(
                transaction.get("transaction_number"),
                "|", transaction.get("date"),
                "|", transaction.get("description"),
                "|", transaction.get("amount"),
            )


if __name__ == "__main__":
    main()
