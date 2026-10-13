import re
from services.ai_assistant import categorize_transactions_with_ai
from database.corrections import find_correction_for_description


CATEGORY_KEYWORDS = {
    "Food": [
        "restaurant", "food", "cafe", "coffee", "bakery", "bakes", "baker",
        "swiggy", "zomato", "pizza", "burger", "mandi", "thattukada", "canteen",
        "tea", "chai", "juice", "sweets", "dhaba", "biryani", "mess", "kitchen",
        "milma", "dairy", "bhel", "dilkush", "snack", "falooda", "ice cream",
        "kfc", "mcdonald", "subway", "domino", "eatery", "barbeque", "biriyani",
        "shawarma", "parotta", "tiffin", "meals", "refreshment", "tasty",
        "chutney", "bistro", "dine", "dining", "cool bar", "catering", "hotel",
        "bake", "restaur", "vegeta", "caffe", "moche"
    ],
    "Transport": [
        "uber", "ola", "rapido", "metro", "bus", "fuel", "fuels", "petrol",
        "diesel", "parking", "toll", "redbus", "irctc", "railway", "train",
        "auto", "petroleum", "fastag", "makemytrip", "goibibo", "flight",
        "airlines", "travels", "cab", "taxi", "transport", "indigo", "air india"
    ],
    "Shopping": [
        "shopping", "mart", "supermarket", "mall", "amazon", "flipkart",
        "store", "super", "provisions", "fancy", "stationary", "stationery",
        "clothing", "textiles", "dress", "zepto", "blinkit", "instamart",
        "bigbasket", "meesho", "myntra", "retail", "silks", "sarees",
        "jewellery", "thangamaligai", "fashion", "bazaar", "hypermarket",
        "footwear", "shoes", "opticals", "bookstore", "books", "electronics",
        "trends", "pantaloons", "zudio", "max fashion", "hardware", "appliances"
    ],
    "Bills & Utilities": [
        "electricity", "water bill", "gas bill", "mobile recharge", "recharge",
        "internet", "broadband", "utility", "airtel", "jio", "vi", "bsnl",
        "bescom", "kseb", "tneb", "billdesk", "paytm bill", "dth", "tata play",
        "dish tv", "cylinder", "indane", "hp gas", "bharat gas", "piped gas"
    ],
    "Entertainment": [
        "netflix", "spotify", "prime video", "hotstar", "youtube", "movie",
        "cinema", "theatre", "theater", "pvr", "inox", "bookmyshow",
        "google play", "play store", "gaming", "steam", "playstation", "sony liv"
    ],
    "Healthcare": [
        "hospital", "clinic", "pharmacy", "medical", "medicals", "medicine",
        "healthcare", "lab", "diagnostics", "apollo", "medplus", "dental",
        "doctor", "health", "druggist", "chemist", "ayur"
    ],
    "Loan / Credit": [
        "slice", "pocketly", "cred", "kreditbee", "emi", "loan", "repayment",
        "credit card", "finance", "bajaj finance", "muthoot", "manappuram"
    ],
    "Bank Charges": [
        "bank charge", "service charge", "maintenance charge", "transaction charge",
        "atm charge", "chrg:", "rem chrg:", "gst", "cgst", "sgst", "charges",
        "consolidated charges", "folio charges", "annual fee"
    ],
    "Cash Withdrawal": [
        "cash withdrawal", "atm withdrawal", "cash wd", "atm with",
        "self-switch at nfs", "self-switch at cashnt"
    ],
    "Investment": [
        "zerodha", "groww", "upstox", "mutual fund", "sip", "nse", "bse"
    ]
}


INCOME_KEYWORDS = [
    "salary", "payroll", "wages", "dividend"
]

INTEREST_KEYWORDS = [
    "interest", "int.pd"
]

TRANSFER_KEYWORDS = [
    "transfer", "fund transfer", "self transfer",
    "own account", "account transfer"
]

REFUND_KEYWORDS = [
    "refund", "reversal", "reversed", "cashback"
]


def extract_counterparty(description):
    """Extract clean entity/merchant or person name from UPI narration."""
    if not description:
        return ""
    parts = [part.strip() for part in re.split(r"[/\\]", str(description))]
    for index, part in enumerate(parts[:-1]):
        if part.upper() != "UPI":
            continue

        next_part = parts[index + 1]
        if next_part.upper() in {"P2M", "P2A", "P2P", "P2B"}:
            # Axis and other bank narrations commonly use
            # UPI/P2M/<reference>/<merchant>/UPI/<bank>.
            if index + 3 < len(parts):
                return parts[index + 3].strip()
        else:
            return next_part.strip()
    return str(description).strip()


def transactions_for_same_counterparty(transactions, transaction):
    """Return this UPI transaction and other UPI rows for the same exact party."""
    description = str(transaction.get("description") or "")
    if not re.search(r"\bupi\b", description, re.IGNORECASE):
        return [transaction]

    counterparty = extract_counterparty(description).strip().casefold()
    if not counterparty:
        return [transaction]

    matches = [
        item
        for item in transactions
        if re.search(r"\bupi\b", str(item.get("description") or ""), re.IGNORECASE)
        and extract_counterparty(item.get("description")).strip().casefold() == counterparty
    ]
    return matches or [transaction]


def keyword_matches(keyword, text):
    """Avoid matching short merchant words inside a person's name."""
    keyword = str(keyword).strip().lower()
    text = str(text or "").lower()
    if not keyword:
        return False

    # Short names such as "vi" and "bus" must match whole tokens. Longer
    # keywords may match the beginning of a word (for example "restaur" in
    # "restaurant") but still must begin at a word boundary.
    if len(keyword) <= 3:
        pattern = rf"(?<!\w){re.escape(keyword)}(?!\w)"
    else:
        pattern = rf"(?<!\w){re.escape(keyword)}\w*"
    return bool(re.search(pattern, text, re.IGNORECASE))


def upi_transfer_category(transaction):
    """Label a person-to-person UPI transfer using its bank direction."""
    direction = str(transaction.get("type") or "").lower().strip()
    description = str(transaction.get("description") or "")
    if direction == "credit" or re.search(r"\b(?:CR|CREDIT)\b", description, re.IGNORECASE):
        return "UPI Received"
    return "UPI Sent"


def rule_based_category(transaction):
    description = str(transaction.get("description") or "").lower().strip()
    counterparty = extract_counterparty(description).lower()
    original_type = str(transaction.get("type") or "").lower().strip()

    # UPI payments between people are transfers, even when the narration does
    # not contain the word "transfer". Check known merchant categories first
    # so UPI payments to shops remain ordinary expenses.
    is_upi = bool(re.search(r"\bupi\b", description, re.IGNORECASE))

    # Use the parser's debit/credit direction as the first check.
    if original_type == "credit":
        if any(word in description for word in INCOME_KEYWORDS):
            return "Income"

        if any(word in description for word in INTEREST_KEYWORDS):
            return "Interest Income"

        if any(word in description for word in REFUND_KEYWORDS):
            return "Refund"

        if is_upi:
            return "UPI Received"

        if any(word in description for word in TRANSFER_KEYWORDS):
            return "Transfer"

        # In Indian personal UPI accounts, incoming credits are funds received (income / inflow)
        return "Income"

    if original_type == "debit":
        if any(word in description for word in TRANSFER_KEYWORDS):
            return "Transfer"

        for category, keywords in CATEGORY_KEYWORDS.items():
            if any(
                keyword_matches(word, counterparty)
                or keyword_matches(word, description)
                for word in keywords
            ):
                return category

        if is_upi:
            return upi_transfer_category(transaction)

        return None

    # Balance reconciliation can leave the direction unknown on statements
    # without a usable opening balance. UPI-to-UPI movement is still a
    # transfer unless the narration matched a known merchant rule above.
    if is_upi:
        return upi_transfer_category(transaction)

    # If the bank direction is unknown, do not guess.
    return None


def determine_transaction_type(transaction, category):
    original_type = str(transaction.get("type") or "").lower().strip()

    if category in ("Transfer", "UPI Sent", "UPI Received"):
        return "transfer"

    if category == "Refund":
        return "income"

    if category in ("Income", "Interest Income"):
        return "income"

    if original_type == "credit":
        return "income"

    if original_type == "debit":
        return "expense"

    return "unknown"


def categorize_transactions(transactions, user_id=None):
    categorized_transactions = []
    ai_transactions = []

    corrections_count = 0
    rules_count = 0

    for transaction in transactions:
        description = str(transaction.get("description") or "")
        category = None

        if user_id:
            correction = find_correction_for_description(
                user_id,
                description
            )

            if correction:
                category = correction["category"]
                if category in ("UPI Sent", "UPI Received"):
                    category = upi_transfer_category(transaction)
                transaction["category"] = category
                transaction["transaction_type"] = determine_transaction_type(
                    transaction, category
                )
                corrections_count += 1
                categorized_transactions.append(transaction)
                continue

        category = rule_based_category(transaction)

        if category:
            transaction["category"] = category
            transaction["transaction_type"] = determine_transaction_type(
                transaction, category
            )
            rules_count += 1
        else:
            ai_transactions.append(transaction)

        categorized_transactions.append(transaction)

    print(f"User corrections applied: {corrections_count}")
    print(f"Rule-based categorized: {rules_count}")
    print(f"Needs AI: {len(ai_transactions)}")

    if ai_transactions:
        try:
            ai_results = categorize_transactions_with_ai(ai_transactions)

            ai_map = {
                item.get("id"): item
                for item in ai_results
                if item.get("id") is not None
            }

            for transaction in ai_transactions:
                original_type = str(transaction.get("type") or "").lower().strip()
                transaction_id = transaction.get("transaction_number")
                ai_result = ai_map.get(transaction_id)

                if ai_result:
                    ai_category = ai_result.get("category", "Other")
                    fallback_type = {
                        "debit": "expense",
                        "credit": "income",
                    }.get(original_type, "unknown")
                    ai_type = str(
                        ai_result.get("transaction_type", fallback_type)
                    ).lower().strip()

                    # Do not allow AI to contradict a known bank direction.
                    if original_type == "debit" and ai_type == "income":
                        ai_type = "expense"
                    elif original_type == "credit" and ai_type == "expense":
                        ai_type = "income"

                    if ai_category in ("Transfer", "UPI Sent", "UPI Received"):
                        ai_type = "transfer"
                    elif ai_category in ("Income", "Interest Income"):
                        ai_type = "income"

                    transaction["category"] = ai_category
                    transaction["transaction_type"] = ai_type

                else:
                    transaction["category"] = "Other"
                    transaction["transaction_type"] = {
                        "debit": "expense",
                        "credit": "income",
                    }.get(original_type, "unknown")

        except Exception as error:
            print("AI categorization failed.")
            print(f"Error: {error}")

            for transaction in ai_transactions:
                original_type = str(transaction.get("type") or "").lower().strip()
                transaction["category"] = "Other"
                transaction["transaction_type"] = {
                    "debit": "expense",
                    "credit": "income",
                }.get(original_type, "unknown")

    return categorized_transactions
