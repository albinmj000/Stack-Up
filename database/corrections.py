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
    description_lower = str(description or "").lower()
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
        if merchant.lower() in description_lower:
            return {"merchant": merchant, "category": correction["category"]}
    return None
