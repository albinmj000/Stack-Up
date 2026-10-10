from services.statement_parser import (
    extract_text_from_pdf,
    extract_transactions_from_text
)

from services.transaction_processor import (
    rule_based_category,
    determine_transaction_type
)

from services.analyzer import analyze_transactions


text = extract_text_from_pdf(
    "bank_statement.pdf"
)

transactions = extract_transactions_from_text(
    text
)


categorized = []

rules_count = 0
ai_count = 0


for transaction in transactions:

    category = rule_based_category(
        transaction
    )

    if category:

        transaction["category"] = category

        transaction["transaction_type"] = (
            determine_transaction_type(
                transaction,
                category
            )
        )

        rules_count += 1

    else:

        transaction["category"] = "Other"

        transaction["transaction_type"] = "unknown"

        ai_count += 1

    categorized.append(
        transaction
    )


analysis = analyze_transactions(
    categorized
)


print()
print("================================")
print("STACK UP FULL PDF TEST")
print("================================")

print(
    "Total transactions:",
    len(transactions)
)

print(
    "Handled by rules:",
    rules_count
)

print(
    "Would need AI:",
    ai_count
)

print()
print("Analysis without AI:")
print(analysis)

print()
print("================================")