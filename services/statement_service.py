import hashlib

from database.database import (
    save_statement,
    statement_exists,
    get_statement_id,
    get_statement,
    get_statement_transactions,
)


def calculate_file_hash(file_path):
    """Calculate the SHA-256 hash of a statement PDF."""
    sha256 = hashlib.sha256()

    with open(file_path, "rb") as file:
        for chunk in iter(
            lambda: file.read(1024 * 1024),
            b"",
        ):
            sha256.update(chunk)

    return sha256.hexdigest().lower()


def check_duplicate_statement(user_id, file_path):
    """Check whether this exact PDF was uploaded by this user."""
    file_hash = calculate_file_hash(file_path)

    return {
        "exists": statement_exists(user_id, file_hash),
        "file_hash": file_hash,
    }


def register_statement(user_id, file_path, filename):
    """Create a statement record or return its existing record."""
    file_hash = calculate_file_hash(file_path)

    existing_statement_id = get_statement_id(
        user_id,
        file_hash,
    )

    if existing_statement_id:
        return {
            "statement_id": existing_statement_id,
            "file_hash": file_hash,
            "created": False,
        }

    statement_id = save_statement(
        user_id,
        file_hash,
        filename,
    )

    return {
        "statement_id": statement_id,
        "file_hash": file_hash,
        "created": True,
    }


def get_saved_statement(user_id, file_hash):
    """Retrieve an existing statement and its saved transactions."""
    statement_id = get_statement_id(user_id, file_hash)

    if statement_id is None:
        return None

    return {
        "statement": get_statement(user_id, statement_id),
        "transactions": get_statement_transactions(
            user_id,
            statement_id,
        ),
    }