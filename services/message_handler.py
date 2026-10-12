import re

from services.correction_parser import process_correction_message
from services.ai_assistant import understand_financial_question
from database.database import get_user_transactions

from services.transaction_query import (
    get_transaction_count,
    get_category_total,
    get_transaction_totals,
    get_spending_summary,
    get_transactions_by_category,
)


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
            "plan my budget",
            "budget without",
            "what changes should i make",
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


def format_statement_summary(user_id):
    totals = get_transaction_totals(user_id)
    spending = get_spending_summary(user_id)
    net = totals["total_income"] - totals["total_expenses"]

    lines = [
        "Here is your statement summary:",
        f"• Total income: INR {totals['total_income']:,.2f}",
        f"• Total expenses: INR {totals['total_expenses']:,.2f}",
        f"• Net cash flow: INR {net:,.2f}",
        f"• Transfers in: INR {totals['total_transfer_in']:,.2f}",
        f"• Transfers out: INR {totals['total_transfer_out']:,.2f}",
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


def format_saving_guidance(user_id, focus_category=None):
    spending = get_spending_summary(user_id)
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
def handle_user_message(user_id, message):
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

    # Budget-planning questions need the AI to understand the whole request
    # before words like "income" or "expenses" can trigger category shortcuts.
    budget_planning_question = is_budget_planning_question(message_lower)
    if budget_planning_question:
        transactions = get_user_transactions(user_id)
        if not transactions:
            return {
                "type": "query",
                "message": "Upload a bank statement first, and I can help plan a budget from your transactions.",
            }
        try:
            understood = understand_financial_question(message, transactions)
            return {
                "type": "ai_answer",
                "message": understood["answer"],
            }
        except Exception as error:
            print(f"Ask Stack Up response failed: {error}")
            return {
                "type": "unknown",
                "message": (
                    "I couldn't prepare a budget answer just now. Please try again "
                    "later, or ask about a specific total or spending category."
                ),
            }

    # 2. Transaction count
    count_phrases = [
        "how many transactions",
        "number of transactions",
        "transaction count",
        "transactions do i have",
        "transactions i have",
    ]

    if any(p in message_lower for p in count_phrases):
        count = get_transaction_count(user_id)
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
        rows = get_user_transactions(user_id)
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
        # get_spending_summary returns {category: amount, ...}
        category_totals = get_spending_summary(user_id)

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
        totals = get_transaction_totals(user_id)
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
        totals = get_transaction_totals(user_id)
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
        totals = get_transaction_totals(user_id)
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
        matching = get_transactions_by_category(user_id, category)
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
        total = get_category_total(user_id, category)

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
        summary_lines, spending = format_statement_summary(user_id)

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
            **format_saving_guidance(user_id, saving_category),
        }

    # 10. Natural-language questions not covered by exact calculations.
    transactions = get_user_transactions(user_id)
    if not transactions:
        return {
            "type": "query",
            "message": "Upload a bank statement first, and I can answer questions about your transactions.",
        }

    try:
        understood = understand_financial_question(message, transactions)
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

        if intent == "list_category" and requested_category in valid_categories:
            matching = get_transactions_by_category(user_id, requested_category)
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

        if intent == "category_total" and requested_category in valid_categories:
            total = get_category_total(user_id, requested_category)
            return {
                "type": "query",
                "message": f"Your total for {requested_category} is INR {total:,.2f}.",
                "data": {"category": requested_category, "amount": total},
            }

        if intent == "summary":
            summary_lines, spending = format_statement_summary(user_id)
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
        print(f"Ask Stack Up response failed: {error}")
        return {
            "type": "unknown",
            "message": (
                "I couldn't answer that just now. Try asking about your spending, "
                "a merchant, or a category, and check that the AI service is available."
            ),
        }
