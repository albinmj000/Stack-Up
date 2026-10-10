from services.statement_parser import (
    extract_text_from_pdf,
    extract_transactions_from_text
)

from services.categorizer import categorize_transaction
from services.analyzer import analyze_transactions


pdf_path = "bank_statement.pdf"

text = extract_text_from_pdf(pdf_path)

transactions = extract_transactions_from_text(text)


for transaction in transactions:
    transaction["category"] = categorize_transaction(transaction)


analysis = analyze_transactions(transactions)


print("\n===== STACK UP FINANCIAL ANALYSIS =====\n")

print("Total money in:", analysis["total_money_in"])
print("Total money out:", analysis["total_money_out"])
print("Transfer in:", analysis["total_transfer_in"])
print("Transfer out:", analysis["total_transfer_out"])
print("Known expenses:", analysis["total_known_expenses"])
print("Unclassified:", analysis["total_unclassified"])
print("Net account change:", analysis["net_account_change"])


print("\n===== CATEGORY TOTALS =====\n")

for category, amount in analysis["category_totals"].items():
    print(f"{category}: {amount}")


print("\n========================================")

print("\n===== UNCLASSIFIED TRANSACTIONS =====\n")

for transaction in transactions:
    if transaction["category"] == "Other":
        print(
            transaction["transaction_number"],
            "|",
            transaction["date"],
            "|",
            transaction["description"],
            "|",
            transaction["amount"]
        )
print("\n===== OTHER TRANSACTIONS BY TYPE =====\n")

for transaction in transactions:
    if transaction["category"] == "Other":
        print(
            transaction["transaction_number"],
            "|",
            transaction["description"],
            "|",
            transaction["amount"]
        )        