import hashlib
import os
import re
import secrets
import sqlite3
import time
import uuid
from pathlib import Path

DATABASE_PATH = os.getenv("DB_PATH", "stack_up.db")


class PostgreSQLConnection:
    """Small compatibility layer so the existing queries work with psycopg."""

    def __init__(self, connection):
        self._connection = connection

    def __enter__(self):
        return self

    def __exit__(self, exc_type, exc_value, traceback):
        try:
            return self._connection.__exit__(exc_type, exc_value, traceback)
        finally:
            self._connection.close()

    def execute(self, sql, parameters=()):
        pragma = re.fullmatch(r"\s*PRAGMA\s+table_info\((\w+)\)\s*;?\s*", sql, re.IGNORECASE)
        if pragma:
            return self._connection.execute(
                "SELECT column_name AS name FROM information_schema.columns "
                "WHERE table_schema = current_schema() AND table_name = %s",
                (pragma.group(1).lower(),),
            )

        query = re.sub(
            r"\bINSERT\s+OR\s+IGNORE\s+INTO\b",
            "INSERT INTO",
            sql,
            flags=re.IGNORECASE,
        )
        ignored_conflicts = bool(
            re.search(r"\bINSERT\s+OR\s+IGNORE\s+INTO\b", sql, re.IGNORECASE)
        )
        query = re.sub(
            r"\bINTEGER\s+PRIMARY\s+KEY\s+AUTOINCREMENT\b",
            "BIGSERIAL PRIMARY KEY",
            query,
            flags=re.IGNORECASE,
        )
        query = re.sub(r"\bBLOB\b", "BYTEA", query, flags=re.IGNORECASE)
        query = query.replace("?", "%s")
        if ignored_conflicts:
            query = query.rstrip().rstrip(";") + " ON CONFLICT DO NOTHING"
        return self._connection.execute(query, parameters)


class SQLiteConnection:
    """Close local SQLite connections after their transaction context ends."""

    def __init__(self, connection):
        self._connection = connection

    def __enter__(self):
        return self

    def __exit__(self, exc_type, exc_value, traceback):
        try:
            return self._connection.__exit__(exc_type, exc_value, traceback)
        finally:
            self._connection.close()

    def execute(self, sql, parameters=()):
        return self._connection.execute(sql, parameters)


def get_connection():
    database_url = os.getenv("DATABASE_URL", "").strip()
    if database_url:
        import psycopg
        from psycopg.rows import dict_row

        if database_url.startswith("postgres://"):
            database_url = "postgresql://" + database_url[len("postgres://"):]
        connection = psycopg.connect(database_url, row_factory=dict_row)
        return PostgreSQLConnection(connection)

    database_path = Path(DATABASE_PATH)
    database_path.parent.mkdir(parents=True, exist_ok=True)
    connection = sqlite3.connect(str(database_path))
    connection.row_factory = sqlite3.Row
    return SQLiteConnection(connection)


def _insert_id(connection, sql, parameters):
    if os.getenv("DATABASE_URL", "").strip():
        row = connection.execute(sql.rstrip().rstrip(";") + " RETURNING id", parameters).fetchone()
        return row["id"]
    return connection.execute(sql, parameters).lastrowid


def create_users_table():
    with get_connection() as connection:
        connection.execute("""
            CREATE TABLE IF NOT EXISTS users (
                id INTEGER PRIMARY KEY AUTOINCREMENT,
                user_id TEXT UNIQUE NOT NULL,
                created_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP
            )
        """)
        columns = {
            row["name"]
            for row in connection.execute("PRAGMA table_info(users)").fetchall()
        }
        for column in ("email", "phone", "username", "password_hash"):
            if column not in columns:
                connection.execute(f"ALTER TABLE users ADD COLUMN {column} TEXT")
        connection.execute("CREATE UNIQUE INDEX IF NOT EXISTS users_email_unique ON users(email) WHERE email IS NOT NULL")
        connection.execute("CREATE UNIQUE INDEX IF NOT EXISTS users_phone_unique ON users(phone) WHERE phone IS NOT NULL")
        if os.getenv("DATABASE_URL", "").strip():
            connection.execute("CREATE UNIQUE INDEX IF NOT EXISTS users_username_unique ON users(LOWER(username)) WHERE username IS NOT NULL")
        else:
            connection.execute("CREATE UNIQUE INDEX IF NOT EXISTS users_username_unique ON users(username COLLATE NOCASE) WHERE username IS NOT NULL")


def create_auth_tables():
    with get_connection() as connection:
        connection.execute("""
            CREATE TABLE IF NOT EXISTS otp_challenges (
                id INTEGER PRIMARY KEY AUTOINCREMENT,
                contact TEXT NOT NULL,
                channel TEXT NOT NULL,
                code_hash TEXT NOT NULL,
                salt TEXT NOT NULL,
                create_account INTEGER NOT NULL DEFAULT 0,
                username TEXT,
                password_hash TEXT,
                created_at REAL NOT NULL,
                expires_at REAL NOT NULL,
                attempts INTEGER NOT NULL DEFAULT 0,
                consumed_at REAL
            )
        """)
        columns = {
            row["name"]
            for row in connection.execute("PRAGMA table_info(otp_challenges)").fetchall()
        }
        for column in ("username", "password_hash"):
            if column not in columns:
                connection.execute(f"ALTER TABLE otp_challenges ADD COLUMN {column} TEXT")
        connection.execute("CREATE INDEX IF NOT EXISTS otp_contact_created ON otp_challenges(contact, created_at)")
        connection.execute("""
            CREATE TABLE IF NOT EXISTS auth_sessions (
                token_hash TEXT PRIMARY KEY,
                user_id TEXT NOT NULL,
                created_at REAL NOT NULL,
                expires_at REAL NOT NULL
            )
        """)
        connection.execute("CREATE INDEX IF NOT EXISTS auth_sessions_user ON auth_sessions(user_id)")
        connection.execute("""
            CREATE TABLE IF NOT EXISTS auth_devices (
                device_hash TEXT PRIMARY KEY,
                active_user_id TEXT,
                created_at REAL NOT NULL,
                expires_at REAL NOT NULL
            )
        """)
        connection.execute("""
            CREATE TABLE IF NOT EXISTS auth_device_accounts (
                device_hash TEXT NOT NULL,
                user_id TEXT NOT NULL,
                added_at REAL NOT NULL,
                PRIMARY KEY (device_hash, user_id),
                FOREIGN KEY (device_hash) REFERENCES auth_devices(device_hash) ON DELETE CASCADE
            )
        """)
        connection.execute("CREATE INDEX IF NOT EXISTS auth_device_accounts_user ON auth_device_accounts(user_id)")
        connection.execute("""
            CREATE TABLE IF NOT EXISTS password_login_attempts (
                id INTEGER PRIMARY KEY AUTOINCREMENT,
                username_hash TEXT NOT NULL,
                created_at REAL NOT NULL
            )
        """)
        connection.execute("CREATE INDEX IF NOT EXISTS password_login_attempts_user_time ON password_login_attempts(username_hash, created_at)")


def can_request_otp(contact):
    now = time.time()
    with get_connection() as connection:
        recent = connection.execute("""
            SELECT COUNT(*) AS count, MAX(created_at) AS latest
            FROM otp_challenges
            WHERE contact = ? AND created_at > ?
        """, (contact, now - 3600)).fetchone()
    return recent["count"] < 5 and (recent["latest"] is None or now - recent["latest"] >= 60)


def _username_digest(username):
    return hashlib.sha256(str(username).strip().lower().encode()).hexdigest()


def can_attempt_password_login(username, max_attempts=10, window_seconds=900):
    cutoff = time.time() - window_seconds
    digest = _username_digest(username)
    with get_connection() as connection:
        count = connection.execute(
            "SELECT COUNT(*) AS count FROM password_login_attempts WHERE username_hash = ? AND created_at > ?",
            (digest, cutoff),
        ).fetchone()["count"]
        connection.execute(
            "DELETE FROM password_login_attempts WHERE created_at < ?",
            (time.time() - 24 * 3600,),
        )
    return count < max_attempts


def record_password_login_failure(username):
    with get_connection() as connection:
        connection.execute(
            "INSERT INTO password_login_attempts (username_hash, created_at) VALUES (?, ?)",
            (_username_digest(username), time.time()),
        )


def clear_password_login_failures(username):
    with get_connection() as connection:
        connection.execute(
            "DELETE FROM password_login_attempts WHERE username_hash = ?",
            (_username_digest(username),),
        )


def create_otp_challenge(contact, channel, code, create_account=False, username=None, password_hash=None):
    salt = secrets.token_hex(16)
    code_hash = hashlib.sha256(f"{salt}:{code}".encode()).hexdigest()
    now = time.time()
    with get_connection() as connection:
        challenge_id = _insert_id(connection, """
            INSERT INTO otp_challenges
                (contact, channel, code_hash, salt, create_account, username,
                 password_hash, created_at, expires_at)
            VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?)
        """, (
            contact, channel, code_hash, salt, int(create_account),
            username, password_hash, now, now + 600,
        ))
        return challenge_id


def invalidate_otp_challenge(challenge_id):
    with get_connection() as connection:
        connection.execute(
            "UPDATE otp_challenges SET consumed_at = ? WHERE id = ?",
            (time.time(), challenge_id),
        )


def verify_otp_challenge(contact, code):
    now = time.time()
    with get_connection() as connection:
        challenge = connection.execute("""
            SELECT id, code_hash, salt, attempts, create_account,
                   username, password_hash
            FROM otp_challenges
            WHERE contact = ? AND consumed_at IS NULL AND expires_at > ? AND attempts < 5
            ORDER BY id DESC LIMIT 1
        """, (contact, now)).fetchone()
        if challenge is None:
            return None
        code_hash = hashlib.sha256(
            f"{challenge['salt']}:{code}".encode()
        ).hexdigest()
        if not secrets.compare_digest(code_hash, challenge["code_hash"]):
            connection.execute(
                "UPDATE otp_challenges SET attempts = attempts + 1 WHERE id = ?",
                (challenge["id"],),
            )
            return None
        connection.execute(
            "UPDATE otp_challenges SET consumed_at = ? WHERE id = ?",
            (now, challenge["id"]),
        )
        return {
            "create_account": bool(challenge["create_account"]),
            "username": challenge["username"],
            "password_hash": challenge["password_hash"],
        }


def get_account_by_contact(contact, channel):
    column = "email" if channel == "email" else "phone"
    with get_connection() as connection:
        row = connection.execute(
            f"SELECT user_id, email, phone, username, password_hash FROM users WHERE {column} = ?",
            (contact,),
        ).fetchone()
    return dict(row) if row else None


def get_account_by_username(username):
    with get_connection() as connection:
        row = connection.execute(
            "SELECT user_id, email, phone, username, password_hash FROM users WHERE LOWER(username) = LOWER(?)",
            (username,),
        ).fetchone()
    return dict(row) if row else None


def create_account(contact, channel, username=None, password_hash=None):
    column = "email" if channel == "email" else "phone"
    user_id = uuid.uuid4().hex
    with get_connection() as connection:
        connection.execute(
            f"INSERT INTO users (user_id, {column}, username, password_hash) VALUES (?, ?, ?, ?)",
            (user_id, contact, username, password_hash),
        )
    return get_account_by_contact(contact, channel)


def add_account_credentials(contact, channel, username, password_hash):
    column = "email" if channel == "email" else "phone"
    with get_connection() as connection:
        cursor = connection.execute(
            f"UPDATE users SET username = ?, password_hash = ? WHERE {column} = ? AND username IS NULL AND password_hash IS NULL",
            (username, password_hash, contact),
        )
        return cursor.rowcount > 0


def create_auth_session(user_id, token, lifetime_seconds=30 * 24 * 3600):
    token_hash = hashlib.sha256(token.encode()).hexdigest()
    now = time.time()
    with get_connection() as connection:
        connection.execute(
            "INSERT INTO auth_sessions (token_hash, user_id, created_at, expires_at) VALUES (?, ?, ?, ?)",
            (token_hash, user_id, now, now + lifetime_seconds),
        )


def get_session_user(token):
    if not token:
        return None
    token_hash = hashlib.sha256(token.encode()).hexdigest()
    now = time.time()
    with get_connection() as connection:
        row = connection.execute("""
            SELECT u.user_id, u.email, u.phone, u.username
            FROM auth_sessions s JOIN users u ON u.user_id = s.user_id
            WHERE s.token_hash = ? AND s.expires_at > ?
        """, (token_hash, now)).fetchone()
    return dict(row) if row else None


def delete_auth_session(token):
    if not token:
        return
    token_hash = hashlib.sha256(token.encode()).hexdigest()
    with get_connection() as connection:
        connection.execute("DELETE FROM auth_sessions WHERE token_hash = ?", (token_hash,))


def remember_account_on_device(device_token, user_id, lifetime_seconds=30 * 24 * 3600):
    """Link an authenticated account to a random, HttpOnly device session."""
    now = time.time()
    if not device_token:
        device_token = secrets.token_urlsafe(32)
    device_hash = hashlib.sha256(device_token.encode()).hexdigest()

    with get_connection() as connection:
        device = connection.execute(
            "SELECT expires_at FROM auth_devices WHERE device_hash = ?",
            (device_hash,),
        ).fetchone()
        if device is None or device["expires_at"] <= now:
            connection.execute(
                "DELETE FROM auth_devices WHERE device_hash = ?",
                (device_hash,),
            )
            connection.execute(
                "INSERT INTO auth_devices (device_hash, active_user_id, created_at, expires_at) VALUES (?, ?, ?, ?)",
                (device_hash, user_id, now, now + lifetime_seconds),
            )
        else:
            connection.execute(
                "UPDATE auth_devices SET active_user_id = ?, expires_at = ? WHERE device_hash = ?",
                (user_id, now + lifetime_seconds, device_hash),
            )
        connection.execute(
            "INSERT OR IGNORE INTO auth_device_accounts (device_hash, user_id, added_at) VALUES (?, ?, ?)",
            (device_hash, user_id, now),
        )
    return device_token


def get_auth_device(device_token):
    if not device_token:
        return None
    device_hash = hashlib.sha256(device_token.encode()).hexdigest()
    now = time.time()
    with get_connection() as connection:
        row = connection.execute(
            "SELECT device_hash, active_user_id FROM auth_devices WHERE device_hash = ? AND expires_at > ?",
            (device_hash, now),
        ).fetchone()
    return dict(row) if row else None


def get_auth_device_user(device_token):
    device = get_auth_device(device_token)
    if not device or not device["active_user_id"]:
        return None
    with get_connection() as connection:
        row = connection.execute(
            "SELECT user_id, email, phone, username FROM users WHERE user_id = ?",
            (device["active_user_id"],),
        ).fetchone()
    return dict(row) if row else None


def list_auth_device_accounts(device_token):
    device = get_auth_device(device_token)
    if not device:
        return []
    with get_connection() as connection:
        rows = connection.execute("""
            SELECT u.user_id, u.email, u.phone, u.username,
                   CASE WHEN u.user_id = ? THEN 1 ELSE 0 END AS active
            FROM auth_device_accounts a
            JOIN users u ON u.user_id = a.user_id
            WHERE a.device_hash = ?
            ORDER BY a.added_at ASC
        """, (device["active_user_id"], device["device_hash"])).fetchall()
    return [dict(row) for row in rows]


def switch_auth_device_account(device_token, user_id):
    device = get_auth_device(device_token)
    if not device or not device["active_user_id"]:
        return None
    now = time.time()
    with get_connection() as connection:
        linked = connection.execute(
            "SELECT 1 FROM auth_device_accounts WHERE device_hash = ? AND user_id = ?",
            (device["device_hash"], user_id),
        ).fetchone()
        if not linked:
            return None
        connection.execute(
            "UPDATE auth_devices SET active_user_id = ?, expires_at = ? WHERE device_hash = ?",
            (user_id, now + 30 * 24 * 3600, device["device_hash"]),
        )
        row = connection.execute(
            "SELECT user_id, email, phone, username FROM users WHERE user_id = ?",
            (user_id,),
        ).fetchone()
    return dict(row) if row else None


def deactivate_auth_device(device_token):
    device = get_auth_device(device_token)
    if not device:
        return False
    with get_connection() as connection:
        connection.execute(
            "UPDATE auth_devices SET active_user_id = NULL WHERE device_hash = ?",
            (device["device_hash"],),
        )
    return True


def delete_auth_device(device_token):
    if not device_token:
        return
    device_hash = hashlib.sha256(device_token.encode()).hexdigest()
    with get_connection() as connection:
        connection.execute(
            "DELETE FROM auth_device_accounts WHERE device_hash = ?",
            (device_hash,),
        )
        connection.execute(
            "DELETE FROM auth_devices WHERE device_hash = ?",
            (device_hash,),
        )


def list_user_statements(user_id):
    with get_connection() as connection:
        rows = connection.execute("""
            SELECT s.id AS statement_id, s.filename, s.created_at,
                   (s.pdf_data IS NOT NULL) AS pdf_available,
                   COUNT(t.id) AS transaction_count
            FROM statements s
            LEFT JOIN transactions t ON t.statement_id = s.id AND t.user_id = s.user_id
            WHERE s.user_id = ?
            GROUP BY s.id
            HAVING COUNT(t.id) > 0
            ORDER BY s.created_at DESC, s.id DESC
        """, (user_id,)).fetchall()
    return [dict(row) for row in rows]


def create_transactions_table():
    with get_connection() as connection:
        connection.execute("""
            CREATE TABLE IF NOT EXISTS transactions (
                id INTEGER PRIMARY KEY AUTOINCREMENT,
                user_id TEXT NOT NULL,
                statement_id INTEGER,
                transaction_number INTEGER,
                date TEXT,
                description TEXT,
                reference TEXT,
                amount REAL,
                type TEXT,
                balance REAL,
                category TEXT,
                transaction_type TEXT,
                created_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP
            )
        """)


def add_statement_id_to_transactions():
    with get_connection() as connection:
        columns = [
            row["name"]
            for row in connection.execute(
                "PRAGMA table_info(transactions)"
            ).fetchall()
        ]

        if "statement_id" not in columns:
            connection.execute("""
                ALTER TABLE transactions
                ADD COLUMN statement_id INTEGER
            """)


def create_statements_table():
    with get_connection() as connection:
        connection.execute("""
            CREATE TABLE IF NOT EXISTS statements (
                id INTEGER PRIMARY KEY AUTOINCREMENT,
                user_id TEXT NOT NULL,
                file_hash TEXT NOT NULL,
                filename TEXT,
                pdf_data BLOB,
                created_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP,
                UNIQUE(user_id, file_hash)
            )
        """)
        columns = {
            row["name"]
            for row in connection.execute("PRAGMA table_info(statements)").fetchall()
        }
        if "pdf_data" not in columns:
            connection.execute("ALTER TABLE statements ADD COLUMN pdf_data BLOB")


def create_corrections_table():
    with get_connection() as connection:
        connection.execute("""
            CREATE TABLE IF NOT EXISTS merchant_corrections (
                id INTEGER PRIMARY KEY AUTOINCREMENT,
                user_id TEXT NOT NULL,
                merchant TEXT NOT NULL,
                category TEXT NOT NULL,
                created_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP,
                UNIQUE(user_id, merchant)
            )
        """)


def create_user(user_id):
    with get_connection() as connection:
        connection.execute(
            "INSERT OR IGNORE INTO users (user_id) VALUES (?)",
            (user_id,)
        )


def user_exists(user_id):
    with get_connection() as connection:
        result = connection.execute(
            "SELECT 1 FROM users WHERE user_id = ?",
            (user_id,)
        ).fetchone()
    return result is not None


def statement_exists(user_id, file_hash):
    with get_connection() as connection:
        result = connection.execute("""
            SELECT 1 FROM statements
            WHERE user_id = ? AND file_hash = ?
        """, (user_id, file_hash.lower())).fetchone()
    return result is not None


def save_statement(user_id, file_hash, filename):
    with get_connection() as connection:
        connection.execute("""
            INSERT OR IGNORE INTO statements
                (user_id, file_hash, filename)
            VALUES (?, ?, ?)
        """, (user_id, file_hash.lower(), filename))

        row = connection.execute("""
            SELECT id FROM statements
            WHERE user_id = ? AND file_hash = ?
        """, (user_id, file_hash.lower())).fetchone()

    return row["id"] if row else None


def get_statement_id(user_id, file_hash):
    with get_connection() as connection:
        row = connection.execute("""
            SELECT id FROM statements
            WHERE user_id = ? AND file_hash = ?
        """, (user_id, file_hash.lower())).fetchone()

    return row["id"] if row else None


def get_user_statements(user_id):
    with get_connection() as connection:
        rows = connection.execute("""
            SELECT id, user_id, file_hash, filename, created_at
            FROM statements
            WHERE user_id = ?
            ORDER BY created_at DESC
        """, (user_id,)).fetchall()

    return [dict(row) for row in rows]


def get_statement(user_id, statement_id):
    with get_connection() as connection:
        row = connection.execute("""
            SELECT id, user_id, file_hash, filename, created_at
            FROM statements
            WHERE user_id = ? AND id = ?
        """, (user_id, statement_id)).fetchone()

    return dict(row) if row else None


def delete_user_statement(user_id, statement_id):
    """Delete one owned statement and all of its saved transactions."""
    with get_connection() as connection:
        connection.execute(
            "DELETE FROM transactions WHERE user_id = ? AND statement_id = ?",
            (user_id, statement_id),
        )
        cursor = connection.execute(
            "DELETE FROM statements WHERE user_id = ? AND id = ?",
            (user_id, statement_id),
        )
        return cursor.rowcount > 0


def _insert_transactions(connection, user_id, statement_id, transactions):
    for transaction in transactions:
        connection.execute("""
            INSERT INTO transactions (
                user_id, statement_id, transaction_number,
                date, description, reference, amount, type,
                balance, category, transaction_type
            )
            VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
        """, (
            user_id,
            statement_id,
            transaction.get("transaction_number"),
            transaction.get("date"),
            transaction.get("description"),
            transaction.get("reference"),
            transaction.get("amount"),
            transaction.get("type"),
            transaction.get("balance"),
            transaction.get("category"),
            transaction.get("transaction_type")
        ))


def save_statement_with_transactions(user_id, file_hash, filename, transactions, pdf_data):
    """Create a statement, its original PDF, and transactions atomically."""
    with get_connection() as connection:
        insert_parameters = (user_id, file_hash.lower(), filename, pdf_data)
        if os.getenv("DATABASE_URL", "").strip():
            inserted = connection.execute(
                """
                INSERT INTO statements (user_id, file_hash, filename, pdf_data)
                VALUES (?, ?, ?, ?)
                ON CONFLICT(user_id, file_hash) DO NOTHING
                RETURNING id
                """,
                insert_parameters,
            ).fetchone()
            statement_id = inserted["id"] if inserted else None
        else:
            cursor = connection.execute(
                """
                INSERT OR IGNORE INTO statements (user_id, file_hash, filename, pdf_data)
                VALUES (?, ?, ?, ?)
                """,
                insert_parameters,
            )
            statement_id = cursor.lastrowid if cursor.rowcount else None

        if statement_id is None:
            row = connection.execute(
                "SELECT id FROM statements WHERE user_id = ? AND file_hash = ?",
                (user_id, file_hash.lower()),
            ).fetchone()
            return (row["id"] if row else None), False

        _insert_transactions(connection, user_id, statement_id, transactions)
        return statement_id, True


def save_transactions(user_id, statement_id, transactions):
    """Append transactions. Use replacement only for explicit reprocessing."""
    with get_connection() as connection:
        _insert_transactions(
            connection,
            user_id,
            statement_id,
            transactions,
        )


def replace_statement_transactions(user_id, statement_id, transactions, pdf_data=None):
    """
    Atomically replace rows for one user's specific statement.

    If any insert fails, SQLite rolls back the deletion and inserts.
    Transactions belonging to other statements are not changed.
    """
    if not transactions:
        raise ValueError(
            "Cannot replace saved transactions with an empty list."
        )

    with get_connection() as connection:
        statement = connection.execute("""
            SELECT 1 FROM statements
            WHERE id = ? AND user_id = ?
        """, (statement_id, user_id)).fetchone()

        if statement is None:
            raise ValueError(
                "The selected statement does not belong to this user."
            )

        connection.execute("""
            DELETE FROM transactions
            WHERE user_id = ? AND statement_id = ?
        """, (user_id, statement_id))

        if pdf_data is not None:
            connection.execute(
                "UPDATE statements SET pdf_data = ? WHERE id = ? AND user_id = ?",
                (pdf_data, statement_id, user_id),
            )

        _insert_transactions(
            connection,
            user_id,
            statement_id,
            transactions,
        )


def get_statement_pdf(user_id, statement_id):
    with get_connection() as connection:
        row = connection.execute(
            "SELECT filename, pdf_data FROM statements WHERE id = ? AND user_id = ?",
            (statement_id, user_id),
        ).fetchone()
    return dict(row) if row else None


def save_statement_pdf(user_id, statement_id, pdf_data):
    with get_connection() as connection:
        cursor = connection.execute(
            """
            UPDATE statements SET pdf_data = COALESCE(pdf_data, ?)
            WHERE id = ? AND user_id = ?
            """,
            (pdf_data, statement_id, user_id),
        )
        return cursor.rowcount > 0


def get_user_transactions(user_id):
    with get_connection() as connection:
        rows = connection.execute("""
            SELECT id, transaction_number, date, description, reference,
                   amount, type, balance, category, transaction_type,
                   statement_id
            FROM transactions
            WHERE user_id = ?
            ORDER BY id
        """, (user_id,)).fetchall()

    return [dict(row) for row in rows]


def get_statement_transactions(user_id, statement_id):
    with get_connection() as connection:
        rows = connection.execute("""
            SELECT id, transaction_number, date, description, reference,
                   amount, type, balance, category, transaction_type,
                   statement_id
            FROM transactions
            WHERE user_id = ? AND statement_id = ?
            ORDER BY id
        """, (user_id, statement_id)).fetchall()

    return [dict(row) for row in rows]


def update_transaction_category(user_id, transaction_id, category, transaction_type):
    return update_transaction_categories(
        user_id,
        [(transaction_id, category, transaction_type)],
    ) > 0


def update_transaction_categories(user_id, transaction_updates):
    """Update multiple owned transactions atomically."""
    with get_connection() as connection:
        updated_count = 0
        for transaction_id, category, transaction_type in transaction_updates:
            cursor = connection.execute("""
                UPDATE transactions
                SET category = ?, transaction_type = ?
                WHERE id = ? AND user_id = ?
            """, (category, transaction_type, transaction_id, user_id))
            updated_count += cursor.rowcount
    return updated_count


def get_saved_statement_data(user_id, file_hash):
    """Return an existing statement and its saved transactions."""
    statement_id = get_statement_id(user_id, file_hash)

    if statement_id is None:
        return None

    statement = get_statement(user_id, statement_id)
    transactions = get_statement_transactions(user_id, statement_id)

    return {
        "statement": statement,
        "transactions": transactions
    }


def initialize_database():
    create_users_table()
    create_auth_tables()
    create_statements_table()
    create_transactions_table()
    add_statement_id_to_transactions()
    create_corrections_table()


if __name__ == "__main__":
    initialize_database()
    print("Stack Up database initialized successfully.")
