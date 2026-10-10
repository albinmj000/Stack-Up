import re

from database.corrections import save_correction


CATEGORY_ALIASES = {

    "food": "Food",
    "groceries": "Food",
    "grocery": "Food",

    "transport": "Transport",
    "travel": "Transport",

    "shopping": "Shopping",

    "entertainment": "Entertainment",

    "healthcare": "Healthcare",
    "health": "Healthcare",
    "medical": "Healthcare",

    "bills": "Bills & Utilities",
    "utilities": "Bills & Utilities",

    "bank charges": "Bank Charges",
    "bank charge": "Bank Charges",

    "cash withdrawal": "Cash Withdrawal",

    "investment": "Investment",

    "loan": "Loan / Credit",
    "credit": "Loan / Credit",

    "transfer": "Transfer",

    "upi sent": "UPI Sent",
    "upi send": "UPI Sent",
    "upi received": "UPI Received",

    "income": "Income",

    "other": "Other"
}


def parse_correction_message(message):

    message = message.strip()

    pattern = re.compile(
        r"^change\s+(.+?)\s+to\s+(.+?)$",
        re.IGNORECASE
    )

    match = pattern.match(message)

    if not match:

        return None

    merchant = match.group(1).strip()

    category_text = (
        match.group(2)
        .strip()
        .lower()
    )

    category = CATEGORY_ALIASES.get(
        category_text
    )

    if not category:

        return None

    return {
        "merchant": merchant,
        "category": category
    }


def process_correction_message(
    user_id,
    message
):

    correction = parse_correction_message(
        message
    )

    if not correction:

        return None

    save_correction(
        user_id,
        correction["merchant"],
        correction["category"]
    )

    return correction
