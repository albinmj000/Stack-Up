import re

from database.database import get_connection


def save_correction(user_id, merchant, category):
    with get_connection() as connection:
        connection.execute(
            """
            INSERT INTO merchant_corrections (user_id, merchant, category)
            VALUES (?, ?, ?)
            ON CONFLICT(user_id, merchant)
            DO UPDATE SET category = excluded.category
            """,
            (user_id, merchant, category),
        )


def get_correction(user_id, merchant):
    with get_connection() as connection:
        row = connection.execute(
            """
            SELECT category
            FROM merchant_corrections
            WHERE user_id = ? AND merchant = ?
            """,
            (user_id, merchant),
        ).fetchone()
    return row["category"] if row else None


def find_correction_for_description(user_id, description):
    parts = [
        part.strip()
        for part in re.split(r"[/\\]", str(description or ""))
    ]
    counterparty = ""
    for index, part in enumerate(parts[:-1]):
        if part.upper() != "UPI":
            continue

        next_part = parts[index + 1]
        if next_part.upper() in {"P2M", "P2A", "P2P", "P2B"}:
            if index + 3 < len(parts):
                counterparty = parts[index + 3]
        else:
            counterparty = next_part
        break

    if not counterparty:
        return None

    with get_connection() as connection:
        corrections = connection.execute(
            """
            SELECT merchant, category
            FROM merchant_corrections
            WHERE user_id = ?
            """,
            (user_id,),
        ).fetchall()

    for correction in corrections:
        merchant = correction["merchant"]
        # Match the actual UPI counterparty exactly. Substring matching can
        # apply a saved correction for the payment mode (for example P2M) to
        # every unrelated UPI transaction.
        if merchant.strip().casefold() == counterparty.casefold():
            return {"merchant": merchant, "category": correction["category"]}
    return None


def list_user_corrections(user_id):
    with get_connection() as connection:
        rows = connection.execute(
            """
            SELECT merchant, category, created_at
            FROM merchant_corrections
            WHERE user_id = ?
            ORDER BY LOWER(merchant)
            """,
            (user_id,),
        ).fetchall()
    return [dict(row) for row in rows]
