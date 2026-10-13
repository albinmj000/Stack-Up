import re
import logging
import unicodedata
from datetime import datetime
from decimal import Decimal, InvalidOperation

from groq import APIConnectionError, APITimeoutError, RateLimitError
from services.analyzer import get_upi_activity
from services.correction_parser import process_correction_message
from services.ai_assistant import (
    calculate_emi_from_conversation,
    normalize_conversation_history,
    understand_financial_question,
)
from database.database import get_statement_transactions, get_user_transactions
from services.transaction_processor import rule_based_category


CATEGORY_ALIASES = {
    "groceries": "Food",
    "grocery": "Food",
    "food": "Food",
    "dining": "Food",
    "transport": "Transport",
    "transportation": "Transport",
    "travel": "Transport",
    "fuel": "Transport",
    "shopping": "Shopping",
    "entertainment": "Entertainment",
    "healthcare": "Healthcare",
    "health": "Healthcare",
    "medical": "Healthcare",
    "bills": "Bills & Utilities",
    "utilities": "Bills & Utilities",
    "bills & utilities": "Bills & Utilities",
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
    "upi received payments": "UPI Received",
    "income": "Income",
    "refund": "Refund",
    "refunds": "Refund",
    "other": "Other",
    "interest income": "Interest Income",
    "loan / credit": "Loan / Credit",
}

logger = logging.getLogger(__name__)


def detect_category(message):
    message_lower = message.lower()

    for keyword in sorted(CATEGORY_ALIASES, key=len, reverse=True):
        if keyword in message_lower:
            return CATEGORY_ALIASES[keyword]

    return None


def is_budget_planning_question(message):
    text = message.lower()
    asks_for_plan = any(
        phrase in text
        for phrase in (
            "how much can i save",
            "how much money can i save",
            "realistically save",
            "save every month",
            "save each month",
            "save monthly",
            "plan my budget",
            "budget without",
        )
    )
    has_savings_context = any(
        word in text for word in ("save", "saving", "savings", "budget")
    ) and any(
        word in text
        for word in ("income", "expense", "spend", "month", "monthly", "regular")
    )
    return asks_for_plan or has_savings_context


def requested_transaction_limit(message, default=10):
    match = re.search(r"\b(\d{1,2})\s+(?:largest|biggest|top)\b", message)
    if not match:
        match = re.search(r"\btop\s+(\d{1,2})\b", message)
    if not match:
        return default
    return min(50, max(1, int(match.group(1))))


def transaction_totals(transactions):
    totals = {
        "total_income": 0.0,
        "total_expenses": 0.0,
        "total_transfer_in": 0.0,
        "total_transfer_out": 0.0,
        "total_upi_received": 0.0,
        "total_upi_sent": 0.0,
        "total_unknown": 0.0,
    }
    for transaction in transactions:
        amount = abs(float(transaction.get("amount") or 0))
        transaction_type = str(
            transaction.get("transaction_type") or "unknown"
        ).lower()
        direction = str(transaction.get("type") or "").lower()
        category = str(transaction.get("category") or "").strip().casefold()
        upi_activity = get_upi_activity(transaction)
        if upi_activity == "received":
            totals["total_upi_received"] += amount
        elif upi_activity == "sent":
            totals["total_upi_sent"] += amount
        elif category == "transfer" or transaction_type == "transfer":
            if direction == "credit":
                totals["total_transfer_in"] += amount
            else:
                totals["total_transfer_out"] += amount
                totals["total_expenses"] += amount
        elif transaction_type == "income":
            totals["total_income"] += amount
        elif transaction_type == "expense":
            totals["total_expenses"] += amount
        else:
            totals["total_unknown"] += amount
    return {name: round(value, 2) for name, value in totals.items()}


def _normalized_transaction_date(value):
    text = str(value or "").strip()
    for date_format in (
        "%Y-%m-%d",
        "%d-%m-%Y",
        "%d/%m/%Y",
        "%d-%m-%y",
        "%d/%m/%y",
        "%d %b %Y",
        "%d %b %y",
    ):
        try:
            return datetime.strptime(text, date_format).date().isoformat()
        except ValueError:
            continue
    return text.casefold() or None


def _normalized_transaction_amount(value):
    try:
        return Decimal(str(value)).copy_abs().quantize(Decimal("0.01"))
    except (InvalidOperation, TypeError, ValueError):
        return None


def _transaction_overlap_keys(transaction):
    amount = _normalized_transaction_amount(transaction.get("amount"))
    direction = str(transaction.get("type") or "").strip().casefold()
    if amount is None or direction not in {"debit", "credit"}:
        return ()

    keys = []
    reference = unicodedata.normalize(
        "NFKC", str(transaction.get("reference") or "")
    ).casefold()
    reference = re.sub(r"[^a-z0-9]", "", reference)
    if reference and reference not in {"na", "none", "null", "0"}:
        keys.append(("reference", reference, direction, amount))

    transaction_date = _normalized_transaction_date(
        transaction.get("date") or transaction.get("transaction_date")
    )
    description = unicodedata.normalize(
        "NFKC", str(transaction.get("description") or "")
    ).casefold()
    description = re.sub(r"[^\w]+", " ", description, flags=re.UNICODE).strip()
    if transaction_date and description:
        keys.append(("details", transaction_date, direction, amount, description))
    return tuple(keys)


def deduplicate_overlapping_statement_transactions(transactions):
    """Drop matching rows only when they came from different statements."""
    occurrences_by_key_and_statement = {}
    deduplicated = []
    for transaction in transactions:
        statement_id = transaction.get("statement_id")
        if statement_id is None:
            deduplicated.append(transaction)
            continue

        keys = _transaction_overlap_keys(transaction)
        duplicate_in_another_statement = False
        for key in keys:
            scoped_key = (transaction.get("bank_account_id"), key)
            statement_occurrences = occurrences_by_key_and_statement.setdefault(
                scoped_key, {}
            )
            occurrence_number = statement_occurrences.get(statement_id, 0) + 1
            statement_occurrences[statement_id] = occurrence_number
            if any(
                other_statement != statement_id
                and count >= occurrence_number
                for other_statement, count in statement_occurrences.items()
            ):
                duplicate_in_another_statement = True
        if not duplicate_in_another_statement:
            deduplicated.append(transaction)
    return deduplicated


def spending_summary(transactions):
    totals = {}
    for transaction in transactions:
        description = str(transaction.get("description") or "")
        if (
            "upi" in description.lower()
            and rule_based_category(transaction)
            in ("Transfer", "UPI Sent", "UPI Received")
        ):
            continue
        if str(transaction.get("transaction_type") or "").lower() != "expense":
            continue
        category = transaction.get("category") or "Other"
        totals[category] = totals.get(category, 0.0) + abs(
            float(transaction.get("amount") or 0)
        )
    return {name: round(amount, 2) for name, amount in totals.items()}


def category_transactions(transactions, category):
    return [
        transaction for transaction in transactions
        if str(transaction.get("category") or "Other").lower() == category.lower()
    ]


def category_total(transactions, category):
    return round(sum(
        abs(float(transaction.get("amount") or 0))
        for transaction in category_transactions(transactions, category)
    ), 2)


def format_statement_summary(user_id, transactions=None):
    transactions = transactions if transactions is not None else get_user_transactions(user_id)
    totals = transaction_totals(transactions)
    spending = spending_summary(transactions)
    net = totals["total_income"] - totals["total_expenses"]

    lines = [
        "Here is your statement summary:",
        f"• Total income: INR {totals['total_income']:,.2f}",
        f"• Total expenses: INR {totals['total_expenses']:,.2f}",
        f"• Net cash flow: INR {net:,.2f}",
        f"• Transfers in: INR {totals['total_transfer_in']:,.2f}",
        f"• Transfers out: INR {totals['total_transfer_out']:,.2f}",
        f"• UPI received: INR {totals['total_upi_received']:,.2f}",
        f"• UPI sent: INR {totals['total_upi_sent']:,.2f}",
        "",
        "Spending by category:",
    ]

    if spending:
        lines.extend(
            f"• {category}: INR {amount:,.2f}"
            for category, amount in sorted(
                spending.items(), key=lambda item: item[1], reverse=True
            )
        )
    else:
        lines.append("• No categorized expenses found yet.")

    return lines, spending


def format_saving_guidance(user_id, focus_category=None, transactions=None):
    transactions = transactions if transactions is not None else get_user_transactions(user_id)
    spending = spending_summary(transactions)
    if not spending:
        return {
            "message": (
                "I don't have categorized expenses to review yet. Upload a statement "
                "or categorize a few transactions, and I can suggest ways to save "
                "based on your actual spending."
            ),
            "suggestions": [],
            "follow_up_questions": [
                "Where am I spending the most?",
                "Summarize my statement",
            ],
        }

    ranked = sorted(spending.items(), key=lambda item: item[1], reverse=True)
    selected = next(
        ((name, amount) for name, amount in ranked
         if focus_category and name.lower() == focus_category.lower()),
        None,
    )
    tips = {
        "Food": "Look at the largest food transactions first. Pick one easy change, such as planning takeaways in advance or setting a weekly dining limit.",
        "Transport": "Compare your frequent routes and group errands where practical. Keep necessary travel unchanged if alternatives are unsafe or unsuitable.",
        "Shopping": "Review recent purchases for items you could return, postpone, or buy at a lower price. A one-day pause can help with non-urgent buys.",
        "Bills & Utilities": "Check recurring bills and usage for plans or subscriptions you no longer need, and compare providers before renewing.",
        "Entertainment": "Review subscriptions and entertainment purchases. Keep the ones you use most and set a limit for the next statement period.",
        "Healthcare": "Don't skip needed care. Check bills, pharmacy prices, and insurance coverage for options that preserve your treatment.",
        "Loan / Credit": "Check due dates and fees first. Paying on time and comparing interest or balance-transfer terms may reduce avoidable costs.",
        "Bank Charges": "Review each fee and ask your bank whether a waiver or account with lower charges fits your usage.",
        "Cash Withdrawal": "Plan cash withdrawals and check whether your account has a lower-fee ATM or withdrawal option.",
        "Investment": "Check that recurring contributions fit your cash-flow needs and goals before changing them.",
        "Other": "Open these transactions and recategorize anything unclear. A clearer category can reveal which costs are actually adjustable.",
    }
    total_spending = sum(amount for _, amount in ranked if amount > 0)
    categories_to_show = [selected] if focus_category and selected else ranked[:3]
    suggestions = [
        {
            "category": category,
            "amount": round(amount, 2),
            "share": round((amount / total_spending) * 100, 1) if total_spending else 0,
            "tip": tips.get(
                category,
                "Review a few transactions in this category and choose one optional cost to reduce if it suits your situation.",
            ),
        }
        for category, amount in categories_to_show
    ]

    top_category, top_amount = ranked[0]
    message = (
        f"Absolutely, let's make this practical. I reviewed your categorized expenses "
        f"and {top_category} is your largest area at INR {top_amount:,.2f}. "
        "Here are a few ideas tied to your statement. Choose a category and we can "
        "look at its transactions together. UPI person-to-person transfers are excluded."
    )
    if focus_category and not selected:
        message = (
            f"I couldn't find categorized spending for {focus_category} in this statement. "
            f"Your largest tracked area is {top_category}; here are some ideas to start there."
        )

    focus = selected[0] if selected else top_category
    other = next((category for category, _ in ranked if category != focus), None)
    follow_ups = [
        f"Show all {focus} transactions",
        f"How can I reduce {focus} spending?",
        f"Give me tips for {other} spending" if other else "Where am I spending the most?",
    ]
    return {
        "message": message,
        "data": {
            "highest_spending_category": top_category,
            "category_totals": spending,
        },
        "suggestions": suggestions,
        "follow_up_questions": follow_ups,
    }


def statement_data_is_relevant(message, history):
    text = message.lower()
    personal_finance_phrases = (
        "my statement", "my transactions", "my spending", "my expenses",
        "my income", "my savings rate", "how much can i save",
        "how much money can i save", "realistically save", "save every month",
        "save each month", "save monthly", "plan my budget", "budget without",
        "save more money", "how can i save", "how do i save",
        "based on the statement", "from these transactions", "from my statement",
        "can i afford", "do i have enough money",
    )
    personal_finance_pattern = re.compile(
        r"\bmy\b.{0,40}\b(?:spend|spending|expense|expenses|income|budget|"
        r"saving|savings|statement|transaction|transactions|cash flow|balance|"
        r"finance|financial)\b"
        r"|\b(?:spend|spending|expense|expenses|income|budget|savings)\b"
        r".{0,30}\b(?:my|me)\b"
        r"|\bi\b.{0,30}\b(?:spend|spent|expenses|income|budget|savings)\b",
        re.IGNORECASE,
    )
    if any(phrase in text for phrase in personal_finance_phrases) or personal_finance_pattern.search(text):
        return True

    follow_up = bool(re.search(r"\b(it|that|those|them|these|there|what about)\b", text))
    if not follow_up:
        return False
    for turn in reversed(history[-6:]):
        if turn["role"] == "user":
            if (
                any(phrase in turn["text"].lower() for phrase in personal_finance_phrases)
                or personal_finance_pattern.search(turn["text"])
            ):
                return True
    return False


def _model_failure(message):
    return {
        "type": "unknown",
        "message": message,
    }


def _model_error_message(error):
    if isinstance(error, RateLimitError):
        return "The AI service is busy right now. Please try again shortly."
    if isinstance(error, (APITimeoutError, APIConnectionError)):
        return "The AI service did not respond in time. Please try again shortly."
    return "I couldn't answer that just now. Please try again shortly."


def handle_user_message(
    user_id,
    message,
    statement_id=None,
    statement_ids=None,
    history=None,
):
    history = normalize_conversation_history(history)
    message_lower = message.lower().strip()

    # 1. Corrections
    correction = process_correction_message(user_id, message)

    if correction:
        return {
            "type": "correction",
            "message": (
                f"Updated {correction['merchant']} "
                f"to {correction['category']}."
            ),
            "merchant": correction["merchant"],
            "category": correction["category"],
        }

    selected_statement_ids = statement_ids or (
        [statement_id] if statement_id is not None else None
    )
    if selected_statement_ids is None:
        transactions = get_user_transactions(user_id)
    else:
        transactions = [
            transaction
            for selected_id in selected_statement_ids
            for transaction in get_statement_transactions(user_id, selected_id)
        ]
        if len(selected_statement_ids) > 1:
            transactions = deduplicate_overlapping_statement_transactions(
                transactions
            )

    emi_result = calculate_emi_from_conversation(message, history)
    if emi_result is not None:
        return emi_result

    use_statement_data = statement_data_is_relevant(
        message_lower,
        history,
    )
    assistant_transactions = transactions if use_statement_data else []

    # Budget-planning questions need the AI to understand the whole request
    # before words like "income" or "expenses" can trigger category shortcuts.
    budget_planning_question = is_budget_planning_question(message_lower)
    if budget_planning_question:
        try:
            understood = understand_financial_question(
                message, assistant_transactions, history
            )
            return {
                "type": "ai_answer",
                "message": understood["answer"],
            }
        except Exception as error:
            logger.warning(
                "Ask Stack Up request failed (%s).", type(error).__name__
            )
            return _model_failure(_model_error_message(error))

    # 2. Transaction count
    count_phrases = [
        "how many transactions",
        "number of transactions",
        "transaction count",
        "transactions do i have",
        "transactions i have",
    ]

    if any(p in message_lower for p in count_phrases):
        count = len(transactions)
        return {
            "type": "query",
            "message": f"You have {count} transactions.",
            "data": {"transaction_count": count},
        }

    # A ranking request is more specific than broad phrases such as "my
    # spending". Return the actual largest expense rows instead of a total.
    ranking_terms = ("largest", "biggest", "top")
    transaction_terms = (
        "transaction", "withdrawal", "debit", "payment", "purchase",
        "spending", "expense",
    )
    if (
        any(term in message_lower for term in ranking_terms)
        and any(term in message_lower for term in transaction_terms)
    ):
        rows = transactions
        expenses = [
            row for row in rows
            if str(row.get("transaction_type") or "").lower() == "expense"
            and str(row.get("type") or "").lower() == "debit"
        ]
        limit = requested_transaction_limit(message_lower)
        largest = sorted(
            expenses,
            key=lambda row: abs(float(row.get("amount") or 0)),
            reverse=True,
        )[:limit]
        total = sum(abs(float(row.get("amount") or 0)) for row in largest)
        return {
            "type": "top_transactions",
            "message": (
                f"Here are your {len(largest)} largest expense transactions "
                f"(transfers excluded), totaling INR {total:,.2f}. "
                "These are the individual transactions contributing most to your spending."
                if largest
                else "I couldn't find any debit transactions classified as expenses."
            ),
            "transactions": largest,
            "data": {"count": len(largest), "total": round(total, 2)},
        }

    # 3. Highest-spending category
    highest_spending_phrases = [
        "where am i spending the most",
        "where am i spending most",
        "where do i spend the most",
        "where do i spend most",
        "what am i spending the most on",
        "which category do i spend the most on",
        "highest spending category",
        "biggest expense category",
        "where did i spend the most",
        "where did i spend most",
        "where have i spent the most",
        "where have i spent most",
        "which category has the highest spending",
        "rank my spending",
        "rank spending by category",
        "what category costs me the most",
    ]

    if any(p in message_lower for p in highest_spending_phrases):
        category_totals = spending_summary(transactions)

        if not category_totals:
            return {
                "type": "query",
                "message": (
                    "I couldn't find any categorized expenses "
                    "in this workspace."
                ),
                "data": {"category_totals": {}},
            }

        valid_totals = {}

        for category_name, value in category_totals.items():
            try:
                amount = float(value or 0)
            except (TypeError, ValueError):
                continue

            if amount > 0:
                valid_totals[str(category_name)] = amount

        if not valid_totals:
            return {
                "type": "query",
                "message": "I couldn't identify any expense totals yet.",
                "data": {"category_totals": {}},
            }

        ranked_totals = sorted(
            valid_totals.items(),
            key=lambda item: item[1],
            reverse=True,
        )
        category_name, amount = ranked_totals[0]
        ranking_lines = ["Your expenses by category, highest to lowest:"]
        ranking_lines.extend(
            f"{index}. {name}: INR {total:,.2f}"
            for index, (name, total) in enumerate(ranked_totals, start=1)
        )
        ranking_lines.append(
            f"Your highest spending category is {category_name} at INR {amount:,.2f}."
        )

        return {
            "type": "query",
            "message": "\n".join(ranking_lines),
            "data": {
                "highest_spending_category": category_name,
                "amount": round(amount, 2),
                "category_totals": {
                    name: round(total, 2)
                    for name, total in valid_totals.items()
                },
            },
        }

    # 4. Income
    income_phrases = [
        "total income",
        "how much income",
        "income did i receive",
        "income i received",
        "money did i receive",
        "money i received",
        "how much did i receive",
        "how much did i earn",
        "total earnings",
    ]

    if any(p in message_lower for p in income_phrases):
        totals = transaction_totals(transactions)
        income = totals["total_income"]

        return {
            "type": "query",
            "message": f"Your total income is ₹{income:.2f}.",
            "data": {"total_income": income},
        }

    # 5. Total expenses
    expense_phrases = [
        "total expenses",
        "total expense",
        "how much did i spend",
        "how much have i spent",
        "my expenses",
        "my spending",
    ]

    category = detect_category(message)

    if (
        any(p in message_lower for p in expense_phrases)
        and category is None
    ):
        totals = transaction_totals(transactions)
        expenses = totals["total_expenses"]

        return {
            "type": "query",
            "message": f"Your total expenses are ₹{expenses:.2f}.",
            "data": {"total_expenses": expenses},
        }

    # 6. Transfers
    transfer_phrases = [
        "how much did i transfer",
        "how much have i transferred",
        "total transfer",
        "total transfers",
        "transfer amount",
        "how much money did i transfer",
    ]

    if any(p in message_lower for p in transfer_phrases):
        totals = transaction_totals(transactions)
        transfer_total = (
            totals["total_transfer_in"]
            + totals["total_transfer_out"]
        )

        return {
            "type": "query",
            "message": f"Your total transfers are ₹{transfer_total:.2f}.",
            "data": {
                "total_transfer": round(transfer_total, 2),
                "transfer_in": totals["total_transfer_in"],
                "transfer_out": totals["total_transfer_out"],
            },
        }

    # Show matching rows when a user asks to see/list category transactions.
    list_intents = (
        "show", "list", "all", "payments", "transactions",
        "transaction", "details", "breakdown",
    )
    if category and any(intent in message_lower for intent in list_intents):
        matching = category_transactions(transactions, category)
        matching.reverse()
        return {
            "type": "category_transactions",
            "message": (
                f"Here are your {category} transactions ({len(matching)}):"
                if matching
                else f"I couldn't find any transactions in {category} yet."
            ),
            "category": category,
            "transactions": matching,
        }

    # 7. Specific category spending
    spending_keywords = [
        "spend", "spent", "spending",
        "expense", "expenses", "cost", "money",
    ]

    if category and any(
        keyword in message_lower for keyword in spending_keywords
    ) and not any(
        keyword in message_lower
        for keyword in ("save", "saving", "reduce", "cut", "less", "tip", "budget")
    ):
        total = category_total(transactions, category)

        return {
            "type": "query",
            "message": f"You spent ₹{total:.2f} on {category}.",
            "data": {"category": category, "amount": total},
        }

    # 8. Spending summary
    summary_phrases = [
        "spending summary",
        "expense summary",
        "where did i spend",
        "what did i spend",
        "summarize my monthly expenses",
        "summarize my expenses",
        "summarize my statement",
        "summarise my statement",
        "summrise my statement",
        "summarize my state ment",
        "summarise my state ment",
        "summrise my state ment",
        "summary of my statement",
        "summarize statement",
        "summarise statement",
    ]

    if any(p in message_lower for p in summary_phrases):
        summary_lines, spending = format_statement_summary(user_id, transactions)

        return {
            "type": "query",
            "message": "\n".join(summary_lines),
            "data": {"category_totals": spending},
        }

    # 9. Saving opportunities
    saving_phrases = [
        "how can i save more",
        "how do i save more",
        "saving opportunities",
        "save more money",
        "ways to save",
        "saving tips",
        "help me save",
        "tips to save",
        "spend less",
        "reduce expenses",
        "lower my expenses",
        "reduce my spending",
        "cut my spending",
    ]
    saving_category = detect_category(message)
    saving_action = any(
        word in message_lower
        for word in ("save", "saving", "reduce", "cut", "less", "tip", "budget")
    )
    if (
        any(p in message_lower for p in saving_phrases)
        or (saving_category and saving_action)
    ):
        return {
            "type": "saving_guidance",
            **format_saving_guidance(user_id, saving_category, transactions),
        }

    # 10. Natural-language questions not covered by exact calculations.
    try:
        understood = understand_financial_question(
            message, assistant_transactions, history
        )
        intent = understood.get("intent", "general")
        requested_category = understood.get("category") or detect_category(message)
        if isinstance(requested_category, str):
            requested_category = CATEGORY_ALIASES.get(
                requested_category.lower(), requested_category
            )
        valid_categories = {
            "Food", "Transport", "Shopping", "Bills & Utilities",
            "Entertainment", "Healthcare", "Loan / Credit", "Bank Charges",
            "Cash Withdrawal", "Investment", "Income", "Interest Income",
            "Refund", "Transfer", "Other",
            "UPI Sent", "UPI Received",
        }

        if (
            assistant_transactions
            and intent == "list_category"
            and requested_category in valid_categories
        ):
            matching = category_transactions(transactions, requested_category)
            matching.reverse()
            return {
                "type": "category_transactions",
                "message": (
                    f"Here are your {requested_category} transactions ({len(matching)}):"
                    if matching
                    else f"I couldn't find any transactions in {requested_category} yet."
                ),
                "category": requested_category,
                "transactions": matching,
            }

        if (
            assistant_transactions
            and intent == "category_total"
            and requested_category in valid_categories
        ):
            total = category_total(transactions, requested_category)
            return {
                "type": "query",
                "message": f"Your total for {requested_category} is INR {total:,.2f}.",
                "data": {"category": requested_category, "amount": total},
            }

        if assistant_transactions and intent == "summary":
            summary_lines, spending = format_statement_summary(user_id, transactions)
            return {
                "type": "query",
                "message": "\n".join(summary_lines),
                "data": {"category_totals": spending},
            }

        return {
            "type": "ai_answer",
            "message": understood["answer"],
        }
    except Exception as error:
        logger.warning(
            "Ask Stack Up request failed (%s).", type(error).__name__
        )
        return _model_failure(_model_error_message(error))
