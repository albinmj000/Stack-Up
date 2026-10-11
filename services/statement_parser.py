import re
from decimal import Decimal, InvalidOperation
from pypdf import PdfReader


DATE_PATTERNS = [
    r"\d{2}\s+[A-Za-z]{3}\s+\d{4}",
    r"\d{1,2}\s+[A-Za-z]{3}\s+\d{2,4}",
    r"\d{2}[/-]\d{2}[/-]\d{4}",
    r"\d{2}[/-]\d{2}[/-]\d{2}",
    r"\d{4}[/-]\d{2}[/-]\d{2}",
]

# Matches monetary values with exactly two decimal places.
MONEY_PATTERN = re.compile(
    r"(?<![\w.])"
    r"\(?-?\s*(?:₹\s*)?"
    r"\d[\d,]*\.\d{2}"
    r"\)?"
    r"(?![\w.])"
)

OPENING_BALANCE_PATTERN = re.compile(
    r"Opening\s+Balance.*?"
    r"(?<![\w.])"
    r"(\d[\d,]*\.\d{2})"
    r"\s*$",
    re.IGNORECASE,
)


def extract_text_from_pdf(file_path):
    """Extract text from all pages of a PDF."""
    reader = PdfReader(file_path)
    pages = []

    for page in reader.pages:
        page_text = page.extract_text()
        if page_text:
            pages.append(page_text)

    return "\n".join(pages)


def normalize_line(line):
    return " ".join(line.strip().split())


def find_date_match(text):
    matches = []

    for pattern in DATE_PATTERNS:
        match = re.search(pattern, text, re.IGNORECASE)
        if match:
            matches.append(match)

    if not matches:
        return None

    return min(matches, key=lambda match: match.start())


def is_standalone_date(line):
    """Return whether a normalized line contains only a supported date."""
    return any(
        re.fullmatch(pattern, line, re.IGNORECASE)
        for pattern in DATE_PATTERNS
    )


def find_undelimited_date_start(line):
    """Find a transaction date at the start of a row without a row number."""
    for pattern in DATE_PATTERNS:
        match = re.match(rf"^({pattern})(?:\s+|$)", line, re.IGNORECASE)
        if match:
            return {
                "number": None,
                "date": match.group(1),
                "description": line[match.end():].strip(),
                "raw": line[match.end():].strip(),
            }
    return None


def find_transaction_start(line):
    """
    Identify a numbered transaction row whose date appears near
    the beginning of the line.
    """
    line = normalize_line(line)

    numbered = re.match(r"^(\d+)\s+(.+)$", line)
    if not numbered:
        return None

    number = int(numbered.group(1))
    remaining = numbered.group(2)

    date_match = find_date_match(remaining)

    if not date_match or date_match.start() > 35:
        return None

    return {
        "number": number,
        "date": date_match.group(),
        "description": remaining[date_match.end():].strip(),
        "raw": remaining[date_match.end():].strip(),
    }


def parse_amount(value):
    """Convert a monetary string to Decimal."""
    value = value.strip()
    # A negative sign must be directly attached to digits or enclosed in parentheses,
    # not a table column placeholder dash (e.g. '- 19.19' is positive 19.19).
    negative = bool(
        re.match(r"^-\d", value)
        or (value.startswith("(") and value.endswith(")"))
    )

    value = (
        value.replace("₹", "")
        .replace(",", "")
        .replace("(", "")
        .replace(")", "")
        .replace("-", "")
        .strip()
    )

    try:
        amount = Decimal(value)
        return -amount if negative else amount
    except InvalidOperation:
        return None


def extract_opening_balance(text):
    """
    Read the opening balance when it is present in the extracted
    statement text. Returns None when it cannot be identified.
    """
    for line in text.splitlines():
        if "opening balance" not in line.lower():
            continue

        line = normalize_line(line)
        matches = list(MONEY_PATTERN.finditer(line))

        if matches:
            val = matches[-1].group()
            amt = parse_amount(val)
            if amt is not None:
                if re.search(r"\b(?:dr|od)\b", line, re.IGNORECASE):
                    return -abs(amt)
                return abs(amt)

        # Some PDFs extract opening balances without decimal places.
        match = re.search(
            r"Opening\s+Balance.*?"
            r"(?<![\w.])(\d[\d,]*)\s*$",
            line,
            re.IGNORECASE,
        )

        if match:
            amt = parse_amount(match.group(1))
            if amt is not None:
                if re.search(r"\b(?:dr|od)\b", line, re.IGNORECASE):
                    return -abs(amt)
                return abs(amt)

    return None


def classify_transaction_from_balance(
    balance,
    previous_balance,
    amount,
):
    """
    Infer bank direction from the balance movement only when the
    movement agrees with the transaction amount.
    """
    if previous_balance is None or balance is None or amount is None:
        return "unknown"

    difference = balance - previous_balance
    expected_change = abs(amount)

    if abs(abs(difference) - expected_change) > Decimal("0.01"):
        return "unknown"

    if difference > 0:
        return "credit"

    if difference < 0:
        return "debit"

    return "unknown"


def extract_amounts(text):
    return list(MONEY_PATTERN.finditer(text))


IGNORE_PATTERNS = [
    re.compile(r"^Statement Generated on", re.IGNORECASE),
    re.compile(r"^Page \d+ of", re.IGNORECASE),
    re.compile(r"^#\s*Date\s*Description", re.IGNORECASE),
    re.compile(r"^Account (?:No\.|Type|Status|Statement)", re.IGNORECASE),
    re.compile(r"^CRN\s+\w+", re.IGNORECASE),
    re.compile(r"^Branch\s+\w+", re.IGNORECASE),
    re.compile(r"^Nominee Registered", re.IGNORECASE),
    re.compile(r"^Currency\s+INDIAN", re.IGNORECASE),
    re.compile(r"^Savings Account Transactions", re.IGNORECASE),
    re.compile(r"^Kotak Mahindra Bank", re.IGNORECASE),
    re.compile(r"^\d{1,3}$"),
]


def is_ignorable_line(line):
    return any(p.search(line) for p in IGNORE_PATTERNS)


def extract_transactions_from_text(text):
    lines = text.splitlines()
    transactions = []
    current = None

    previous_balance = extract_opening_balance(text)

    def finish_transaction(transaction):
        nonlocal previous_balance

        if transaction is None:
            return

        raw = normalize_line(transaction["raw"])
        money_matches = list(MONEY_PATTERN.finditer(raw))

        # The final two monetary values should be transaction amount
        # and running balance for the statement format supplied.
        if len(money_matches) < 2:
            return

        amount_match = money_matches[-2]
        balance_match = money_matches[-1]

        amount = parse_amount(amount_match.group())
        balance = parse_amount(balance_match.group())

        if amount is None or balance is None:
            return

        description = normalize_line(raw[:amount_match.start()])

        if not description:
            description = transaction["description"]

        reference_match = re.search(
            r"\b(?:UPI[-/ ]?\d+|IMPS[-/ ]?\d+|NEFT[-/ ]?\w+)\b",
            description,
            re.IGNORECASE,
        )

        reference = (
            reference_match.group()
            if reference_match
            else None
        )

        if reference_match:
            description = normalize_line(
                description.replace(reference_match.group(), "")
            )

        bank_type = classify_transaction_from_balance(
            balance=balance,
            previous_balance=previous_balance,
            amount=amount,
        )

        transactions.append({
            "transaction_number": transaction["number"],
            "date": transaction["date"],
            "description": description or "Bank transaction",
            "reference": reference,
            "amount": float(abs(amount)),
            "type": bank_type,
            "transaction_type": bank_type,
            "balance": float(balance),
        })

        # Advance the balance only after a transaction row has
        # been successfully parsed.
        previous_balance = balance

    for raw_line in lines:
        line = normalize_line(raw_line)

        if not line:
            continue

        if is_ignorable_line(line):
            continue

        # Axis Bank statements commonly put the transaction date on its own
        # line, followed by wrapped particulars and then amount/balance values.
        if is_standalone_date(line):
            finish_transaction(current)
            current = {
                "number": len(transactions) + 1,
                "date": line,
                "description": "",
                "raw": "",
            }
            continue

        if line.lower() in {
            "end of statement",
            "end of transactions",
        }:
            finish_transaction(current)
            current = None
            break

        transaction_start = find_transaction_start(line)
        if not transaction_start:
            # Some PDF extractors put the date and particulars on one line;
            # others put the date on a separate line.
            transaction_start = find_undelimited_date_start(line)

        if transaction_start:
            finish_transaction(current)

            current = {
                "number": transaction_start["number"] or len(transactions) + 1,
                "date": transaction_start["date"],
                "description": transaction_start["description"],
                "raw": transaction_start["raw"],
            }

        elif current is not None:
            # Append wrapped descriptions and reference lines to
            # the transaction currently being read.
            current["raw"] += " " + line

    finish_transaction(current)

    return transactions
