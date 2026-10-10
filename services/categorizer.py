from services.ai_assistant import categorize_transactions_with_ai


# =========================================================
# GENERAL CATEGORY KEYWORDS
# =========================================================

CATEGORY_KEYWORDS = {

    "Food": [
        "restaurant",
        "food",
        "cafe",
        "coffee",
        "bakery",
        "swiggy",
        "zomato",
        "pizza"
    ],

    "Transport": [
        "uber",
        "ola",
        "rapido",
        "metro",
        "bus",
        "fuel",
        "petrol",
        "diesel",
        "parking",
        "toll"
    ],

    "Entertainment": [
        "netflix",
        "spotify",
        "prime video",
        "hotstar",
        "youtube",
        "movie",
        "cinema"
    ],

    "Healthcare": [
        "hospital",
        "clinic",
        "pharmacy",
        "medical",
        "medicine",
        "healthcare"
    ],

    "Bills & Utilities": [
        "electricity",
        "water bill",
        "gas bill",
        "mobile recharge",
        "recharge",
        "internet",
        "broadband",
        "utility"
    ],

    "Shopping": [
        "shopping",
        "mart",
        "supermarket",
        "mall",
        "amazon",
        "flipkart"
    ],

    "Bank Charges": [
        "bank charge",
        "service charge",
        "maintenance charge",
        "transaction charge",
        "atm charge",
        "chrg:",
        "rem chrg:"
    ],

    "Cash Withdrawal": [
        "cash withdrawal",
        "atm withdrawal",
        "cash wd"
    ]
}


# =========================================================
# RULE-BASED CATEGORIZATION
# =========================================================

def rule_based_category(transaction):

    description = transaction["description"].lower().strip()

    transaction_type = transaction["type"]


    # -----------------------------------------------------
    # INCOME
    # -----------------------------------------------------

    if transaction_type == "credit":

        income_keywords = [
            "salary",
            "payroll",
            "wages",
            "dividend"
        ]

        if any(
            keyword in description
            for keyword in income_keywords
        ):
            return "Income"

        if (
            "interest" in description
            or "int.pd" in description
        ):
            return "Interest Income"


    # -----------------------------------------------------
    # EXPLICIT TRANSFERS
    # -----------------------------------------------------

    transfer_keywords = [
        "transfer",
        "fund transfer",
        "self transfer",
        "own account",
        "account transfer"
    ]

    if any(
        keyword in description
        for keyword in transfer_keywords
    ):
        return "Transfer"


    # -----------------------------------------------------
    # GENERAL CATEGORIES
    # -----------------------------------------------------

    for category, keywords in CATEGORY_KEYWORDS.items():

        for keyword in keywords:

            if keyword in description:

                return category


    return None


# =========================================================
# TRANSACTION TYPE
# =========================================================

def determine_transaction_type(transaction, category):

    original_type = transaction["type"]


    # Credit transaction
    if original_type == "credit":

        if category == "Transfer":
            return "transfer"

        return "income"


    # Debit transaction
    if original_type == "debit":

        if category == "Transfer":
            return "transfer"

        return "expense"


    return "unknown"


# =========================================================
# MAIN CATEGORIZATION PIPELINE
# =========================================================

def categorize_transactions(transactions):

    categorized_transactions = []

    ai_transactions = []


    # -----------------------------------------------------
    # STEP 1 — RULE-BASED
    # -----------------------------------------------------

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


        else:

            ai_transactions.append(
                transaction
            )


        categorized_transactions.append(
            transaction
        )


    print(
        f"Rule-based categorized: "
        f"{len(transactions) - len(ai_transactions)}"
    )

    print(
        f"Needs AI: "
        f"{len(ai_transactions)}"
    )


    # -----------------------------------------------------
    # STEP 2 — AI
    # -----------------------------------------------------

    if ai_transactions:

        try:

            ai_results = categorize_transactions_with_ai(
                ai_transactions
            )


            category_map = {
                item["id"]: item["category"]
                for item in ai_results
            }


            for transaction in ai_transactions:

                transaction_id = transaction[
                    "transaction_number"
                ]


                category = category_map.get(
                    transaction_id,
                    "Other"
                )


                transaction["category"] = category

                transaction["transaction_type"] = (
                    determine_transaction_type(
                        transaction,
                        category
                    )
                )


        except Exception as e:

            print(
                "AI categorization failed."
            )

            print(
                f"Error: {e}"
            )


            for transaction in ai_transactions:

                transaction["category"] = "Other"

                transaction["transaction_type"] = (
                    determine_transaction_type(
                        transaction,
                        "Other"
                    )
                )


    return categorized_transactions