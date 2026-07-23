from __future__ import annotations

import hashlib
import sqlite3
from collections.abc import Sequence
from pathlib import Path

import pandas as pd


DB_PATH = Path("data/expense_dashboard.sqlite3")


def connect(db_path: Path = DB_PATH) -> sqlite3.Connection:
    db_path.parent.mkdir(parents=True, exist_ok=True)
    conn = sqlite3.connect(db_path)
    conn.row_factory = sqlite3.Row
    conn.execute("PRAGMA foreign_keys = ON")
    return conn


def init_db(conn: sqlite3.Connection) -> None:
    conn.executescript(
        """
        CREATE TABLE IF NOT EXISTS transactions (
            id TEXT PRIMARY KEY,
            date TEXT NOT NULL,
            amount REAL NOT NULL,
            description TEXT NOT NULL,
            source TEXT NOT NULL,
            category_type TEXT,
            category TEXT,
            notes TEXT,
            created_at TEXT NOT NULL DEFAULT CURRENT_TIMESTAMP
        );

        CREATE INDEX IF NOT EXISTS idx_transactions_date
            ON transactions(date);

        CREATE INDEX IF NOT EXISTS idx_transactions_category
            ON transactions(category_type, category);
        """
    )
    _migrate_obligations_table(conn)
    _ensure_transaction_columns(conn)
    _ensure_obligation_columns(conn)
    conn.executescript(
        """

        CREATE TABLE IF NOT EXISTS obligations (
            id INTEGER PRIMARY KEY AUTOINCREMENT,
            category_type TEXT NOT NULL CHECK (
                category_type IN (
                    'Income',
                    'Variable Expenses',
                    'Monthly Bills',
                    'Debt',
                    'Savings',
                    'Non-Monthly Bills'
                )
            ),
            name TEXT NOT NULL,
            month TEXT NOT NULL DEFAULT '',
            due_day INTEGER,
            expected_amount REAL NOT NULL DEFAULT 0,
            balance REAL NOT NULL DEFAULT 0,
            minimum_payment REAL NOT NULL DEFAULT 0,
            interest_rate REAL NOT NULL DEFAULT 0,
            sort_order INTEGER NOT NULL DEFAULT 0,
            created_at TEXT NOT NULL DEFAULT CURRENT_TIMESTAMP,
            updated_at TEXT NOT NULL DEFAULT CURRENT_TIMESTAMP,
            UNIQUE(category_type, name, month)
        );

        CREATE INDEX IF NOT EXISTS idx_obligations_type_name
            ON obligations(category_type, name);

        CREATE TABLE IF NOT EXISTS deleted_obligations (
            category_type TEXT NOT NULL,
            name TEXT NOT NULL,
            month TEXT NOT NULL DEFAULT '',
            deleted_at TEXT NOT NULL DEFAULT CURRENT_TIMESTAMP,
            PRIMARY KEY (category_type, name, month)
        );

        CREATE TABLE IF NOT EXISTS obligation_monthly_budgets (
            obligation_id INTEGER NOT NULL,
            month TEXT NOT NULL,
            expected_amount REAL NOT NULL,
            updated_at TEXT NOT NULL DEFAULT CURRENT_TIMESTAMP,
            PRIMARY KEY (obligation_id, month),
            FOREIGN KEY (obligation_id) REFERENCES obligations(id) ON DELETE CASCADE
        );

        CREATE INDEX IF NOT EXISTS idx_monthly_budgets_month
            ON obligation_monthly_budgets(month);

        CREATE TABLE IF NOT EXISTS app_settings (
            key TEXT PRIMARY KEY,
            value TEXT NOT NULL,
            updated_at TEXT NOT NULL DEFAULT CURRENT_TIMESTAMP
        );

        CREATE TABLE IF NOT EXISTS bank_connections (
            id INTEGER PRIMARY KEY AUTOINCREMENT,
            provider TEXT NOT NULL,
            item_id TEXT NOT NULL UNIQUE,
            institution_name TEXT NOT NULL,
            encrypted_access_token TEXT NOT NULL,
            sync_cursor TEXT,
            last_synced_at TEXT,
            created_at TEXT NOT NULL DEFAULT CURRENT_TIMESTAMP
        );
        """
    )
    conn.commit()


def _ensure_transaction_columns(conn: sqlite3.Connection) -> None:
    existing_columns = {
        row[1]
        for row in conn.execute("PRAGMA table_info(transactions)").fetchall()
    }
    for column_name, column_definition in {
        "excluded": "INTEGER NOT NULL DEFAULT 0",
        "split_parent_id": "TEXT",
        "bank_connection_id": "INTEGER",
        "external_id": "TEXT",
    }.items():
        if column_name not in existing_columns:
            conn.execute(
                f"ALTER TABLE transactions ADD COLUMN {column_name} {column_definition}"
            )
    conn.execute(
        """
        CREATE UNIQUE INDEX IF NOT EXISTS idx_transactions_external_id
        ON transactions(bank_connection_id, external_id)
        WHERE external_id IS NOT NULL
        """
    )
    conn.commit()


def _migrate_obligations_table(conn: sqlite3.Connection) -> None:
    table = conn.execute(
        """
        SELECT sql
        FROM sqlite_master
        WHERE type = 'table'
          AND name = 'obligations'
        """
    ).fetchone()
    if not table:
        return

    table_sql = table[0] or ""
    if (
        "Income" in table_sql
        and "Variable Expenses" in table_sql
        and "Savings" in table_sql
        and "month TEXT NOT NULL" in table_sql
    ):
        return

    conn.executescript(
        """
        ALTER TABLE obligations RENAME TO obligations_old;

        CREATE TABLE obligations (
            id INTEGER PRIMARY KEY AUTOINCREMENT,
            category_type TEXT NOT NULL CHECK (
                category_type IN (
                    'Income',
                    'Variable Expenses',
                    'Monthly Bills',
                    'Debt',
                    'Savings',
                    'Non-Monthly Bills'
                )
            ),
            name TEXT NOT NULL,
            month TEXT NOT NULL DEFAULT '',
            due_day INTEGER,
            expected_amount REAL NOT NULL DEFAULT 0,
            balance REAL NOT NULL DEFAULT 0,
            minimum_payment REAL NOT NULL DEFAULT 0,
            interest_rate REAL NOT NULL DEFAULT 0,
            sort_order INTEGER NOT NULL DEFAULT 0,
            created_at TEXT NOT NULL DEFAULT CURRENT_TIMESTAMP,
            updated_at TEXT NOT NULL DEFAULT CURRENT_TIMESTAMP,
            UNIQUE(category_type, name, month)
        );

        INSERT OR IGNORE INTO obligations (
            id,
            category_type,
            name,
            month,
            due_day,
            expected_amount,
            balance,
            minimum_payment,
            interest_rate,
            sort_order,
            created_at,
            updated_at
        )
        SELECT
            id,
            category_type,
            name,
            COALESCE(month, ''),
            due_day,
            expected_amount,
            COALESCE(balance, 0),
            COALESCE(minimum_payment, 0),
            COALESCE(interest_rate, 0),
            sort_order,
            created_at,
            updated_at
        FROM obligations_old;

        DROP TABLE obligations_old;
        """
    )
    conn.commit()


def _ensure_obligation_columns(conn: sqlite3.Connection) -> None:
    table_exists = conn.execute(
        """
        SELECT 1
        FROM sqlite_master
        WHERE type = 'table'
          AND name = 'obligations'
        """
    ).fetchone()
    if not table_exists:
        return

    existing_columns = {
        row[1]
        for row in conn.execute("PRAGMA table_info(obligations)").fetchall()
    }
    for column_name, column_definition in {
        "balance": "REAL NOT NULL DEFAULT 0",
        "minimum_payment": "REAL NOT NULL DEFAULT 0",
        "interest_rate": "REAL NOT NULL DEFAULT 0",
    }.items():
        if column_name not in existing_columns:
            conn.execute(
                f"ALTER TABLE obligations ADD COLUMN {column_name} {column_definition}"
            )
    conn.commit()


def transaction_id(row: pd.Series) -> str:
    key = "|".join(
        [
            str(row["date"]),
            f"{float(row['amount']):.2f}",
            str(row["description"]).strip().lower(),
        ]
    )
    return hashlib.sha256(key.encode("utf-8")).hexdigest()


def upsert_transactions(conn: sqlite3.Connection, df: pd.DataFrame) -> int:
    if df.empty:
        return 0

    rows = []
    for _, row in df.iterrows():
        rows.append(
            (
                transaction_id(row),
                row["date"],
                float(row["amount"]),
                row["description"],
                row["source"],
            )
        )

    before = conn.total_changes
    conn.executemany(
        """
        INSERT OR IGNORE INTO transactions (
            id, date, amount, description, source
        )
        VALUES (?, ?, ?, ?, ?)
        """,
        rows,
    )
    conn.commit()
    return conn.total_changes - before


def save_bank_connection(
    conn: sqlite3.Connection,
    item_id: str,
    institution_name: str,
    encrypted_access_token: str,
) -> int:
    conn.execute(
        """
        INSERT INTO bank_connections (
            provider, item_id, institution_name, encrypted_access_token
        ) VALUES ('plaid', ?, ?, ?)
        ON CONFLICT(item_id) DO UPDATE SET
            institution_name = excluded.institution_name,
            encrypted_access_token = excluded.encrypted_access_token
        """,
        (item_id, institution_name, encrypted_access_token),
    )
    conn.commit()
    return int(
        conn.execute(
            "SELECT id FROM bank_connections WHERE item_id = ?", (item_id,)
        ).fetchone()[0]
    )


def load_bank_connections(conn: sqlite3.Connection) -> pd.DataFrame:
    return pd.read_sql_query(
        """
        SELECT id, provider, item_id, institution_name, encrypted_access_token,
               sync_cursor, last_synced_at
        FROM bank_connections
        ORDER BY institution_name, id
        """,
        conn,
    )


def apply_bank_sync(
    conn: sqlite3.Connection,
    connection_id: int,
    transactions: pd.DataFrame,
    removed_external_ids: list[str],
    next_cursor: str,
) -> int:
    before = conn.total_changes
    for _, row in transactions.iterrows():
        local_id = hashlib.sha256(
            f"plaid|{connection_id}|{row['external_id']}".encode("utf-8")
        ).hexdigest()
        conn.execute(
            """
            INSERT INTO transactions (
                id, date, amount, description, source,
                bank_connection_id, external_id
            ) VALUES (?, ?, ?, ?, ?, ?, ?)
            ON CONFLICT(bank_connection_id, external_id)
            WHERE external_id IS NOT NULL
            DO UPDATE SET
                date = excluded.date,
                amount = excluded.amount,
                description = excluded.description,
                source = excluded.source
            """,
            (
                local_id,
                row["date"],
                float(row["amount"]),
                row["description"],
                row["source"],
                int(connection_id),
                row["external_id"],
            ),
        )
    if removed_external_ids:
        placeholders = ",".join("?" for _ in removed_external_ids)
        conn.execute(
            f"""
            DELETE FROM transactions
            WHERE bank_connection_id = ? AND external_id IN ({placeholders})
            """,
            (int(connection_id), *removed_external_ids),
        )
    conn.execute(
        """
        UPDATE bank_connections
        SET sync_cursor = ?, last_synced_at = CURRENT_TIMESTAMP
        WHERE id = ?
        """,
        (next_cursor, int(connection_id)),
    )
    conn.commit()
    return conn.total_changes - before - 1


def delete_bank_connection(conn: sqlite3.Connection, connection_id: int) -> None:
    conn.execute(
        "DELETE FROM transactions WHERE bank_connection_id = ?", (connection_id,)
    )
    conn.execute("DELETE FROM bank_connections WHERE id = ?", (connection_id,))
    conn.commit()


def add_transaction(
    conn: sqlite3.Connection,
    date: str,
    amount: float,
    description: str,
    source: str,
    category_type: str | None,
    category: str | None,
    notes: str | None = None,
) -> str:
    row = pd.Series(
        {
            "date": date,
            "amount": amount,
            "description": description,
        }
    )
    transaction_id_value = transaction_id(row)
    conn.execute(
        """
        INSERT OR IGNORE INTO transactions (
            id, date, amount, description, source, category_type, category, notes
        )
        VALUES (?, ?, ?, ?, ?, ?, ?, ?)
        """,
        (
            transaction_id_value,
            date,
            float(amount),
            description,
            source,
            category_type,
            category,
            notes,
        ),
    )
    conn.commit()
    return transaction_id_value


def split_transaction(
    conn: sqlite3.Connection,
    transaction_id_value: str,
    splits: Sequence[dict[str, object]],
) -> int:
    parent = conn.execute(
        """
        SELECT id, date, amount, description, source, notes
        FROM transactions
        WHERE id = ?
          AND excluded = 0
        """,
        (transaction_id_value,),
    ).fetchone()
    if not parent:
        return 0

    before = conn.total_changes
    conn.execute(
        """
        UPDATE transactions
        SET excluded = 1,
            notes = COALESCE(notes || CHAR(10), '') || 'Split into child transactions'
        WHERE id = ?
        """,
        (transaction_id_value,),
    )

    child_rows = []
    for index, split in enumerate(splits, start=1):
        child_key = "|".join(
            [
                transaction_id_value,
                str(index),
                str(split["date"]),
                f"{float(split['amount']):.2f}",
                str(split["description"]).strip().lower(),
            ]
        )
        child_rows.append(
            (
                hashlib.sha256(child_key.encode("utf-8")).hexdigest(),
                split["date"],
                float(split["amount"]),
                split["description"],
                split["source"],
                split["category_type"],
                split["category"],
                split.get("notes"),
                transaction_id_value,
            )
        )

    conn.executemany(
        """
        INSERT OR REPLACE INTO transactions (
            id,
            date,
            amount,
            description,
            source,
            category_type,
            category,
            notes,
            split_parent_id
        )
        VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?)
        """,
        child_rows,
    )
    conn.commit()
    return conn.total_changes - before


def update_transaction(
    conn: sqlite3.Connection,
    transaction_id_value: str,
    date: str,
    amount: float,
    description: str,
    source: str,
    category_type: str | None,
    category: str | None,
    notes: str | None = None,
) -> None:
    conn.execute(
        """
        UPDATE transactions
        SET date = ?,
            amount = ?,
            description = ?,
            source = ?,
            category_type = ?,
            category = ?,
            notes = ?
        WHERE id = ?
        """,
        (
            date,
            float(amount),
            description,
            source,
            category_type,
            category,
            notes,
            transaction_id_value,
        ),
    )
    conn.commit()


def ignore_transaction(conn: sqlite3.Connection, transaction_id_value: str) -> None:
    conn.execute(
        """
        UPDATE transactions
        SET excluded = 1,
            notes = COALESCE(notes || CHAR(10), '') || 'Ignored from dashboard totals'
        WHERE id = ?
        """,
        (transaction_id_value,),
    )
    conn.commit()


def set_transaction_ignored(
    conn: sqlite3.Connection,
    transaction_id_value: str,
    ignored: bool,
) -> None:
    conn.execute(
        """
        UPDATE transactions
        SET excluded = ?
        WHERE id = ?
        """,
        (1 if ignored else 0, transaction_id_value),
    )
    conn.commit()


def get_setting(conn: sqlite3.Connection, key: str, default: str = "") -> str:
    row = conn.execute(
        "SELECT value FROM app_settings WHERE key = ?",
        (key,),
    ).fetchone()
    return row["value"] if row else default


def set_setting(conn: sqlite3.Connection, key: str, value: str) -> None:
    conn.execute(
        """
        INSERT INTO app_settings (key, value, updated_at)
        VALUES (?, ?, CURRENT_TIMESTAMP)
        ON CONFLICT(key) DO UPDATE SET
            value = excluded.value,
            updated_at = CURRENT_TIMESTAMP
        """,
        (key, value),
    )
    conn.commit()


def load_transactions(
    conn: sqlite3.Connection,
    include_excluded: bool = False,
) -> pd.DataFrame:
    excluded_filter = "" if include_excluded else "WHERE excluded = 0"
    return pd.read_sql_query(
        f"""
        SELECT
            id,
            date,
            amount,
            description,
            source,
            COALESCE(category_type, 'Uncategorized') AS category_type,
            COALESCE(category, 'Uncategorized') AS category,
            notes,
            split_parent_id,
            excluded
        FROM transactions
        {excluded_filter}
        ORDER BY date DESC, amount DESC
        """,
        conn,
    )


def update_transaction_categories(
    conn: sqlite3.Connection,
    updates: list[tuple[str, str, str]],
) -> None:
    conn.executemany(
        """
        UPDATE transactions
        SET category_type = ?, category = ?
        WHERE id = ?
        """,
        [(category_type, category, transaction_id) for transaction_id, category_type, category in updates],
    )
    conn.commit()


def apply_category_matches(conn: sqlite3.Connection, matches: pd.DataFrame) -> int:
    if matches.empty:
        return 0

    before = conn.total_changes
    conn.executemany(
        """
        UPDATE transactions
        SET category_type = ?, category = ?
        WHERE id = ?
          AND category_type IS NULL
          AND category IS NULL
        """,
        [
            (row["category_type"], row["category"], row["id"])
            for _, row in matches.iterrows()
        ],
    )
    conn.commit()
    return conn.total_changes - before


def seed_obligations(conn: sqlite3.Connection, obligations: pd.DataFrame) -> int:
    if obligations.empty:
        return 0

    def value_or_zero(row: pd.Series, key: str) -> float:
        if key not in row or pd.isna(row[key]):
            return 0.0
        return float(row[key] or 0)

    before = conn.total_changes
    conn.executemany(
        """
        INSERT OR IGNORE INTO obligations (
            category_type,
            name,
            month,
            due_day,
            expected_amount,
            balance,
            minimum_payment,
            interest_rate,
            sort_order
        )
        SELECT ?, ?, ?, ?, ?, ?, ?, ?, ?
        WHERE NOT EXISTS (
            SELECT 1
            FROM deleted_obligations
            WHERE category_type = ?
              AND name = ?
              AND month = ?
        )
        """,
        [
            (
                row["category_type"],
                row["name"],
                row["month"] if "month" in row and pd.notna(row["month"]) else "",
                int(row["due_day"]) if pd.notna(row["due_day"]) else None,
                float(row["expected_amount"] or 0),
                value_or_zero(row, "balance"),
                value_or_zero(row, "minimum_payment"),
                value_or_zero(row, "interest_rate"),
                int(row["sort_order"] or 0),
                row["category_type"],
                row["name"],
                row["month"] if "month" in row and pd.notna(row["month"]) else "",
            )
            for _, row in obligations.iterrows()
        ],
    )
    conn.commit()
    return conn.total_changes - before


def sync_debt_details(conn: sqlite3.Connection, obligations: pd.DataFrame) -> int:
    if obligations.empty:
        return 0

    debt_rows = obligations[obligations["category_type"].eq("Debt")]
    if debt_rows.empty:
        return 0

    before = conn.total_changes

    def value_or_zero(row: pd.Series, key: str) -> float:
        if key not in row or pd.isna(row[key]):
            return 0.0
        return float(row[key] or 0)

    conn.executemany(
        """
        UPDATE obligations
        SET balance = ?,
            minimum_payment = ?,
            interest_rate = ?,
            updated_at = CURRENT_TIMESTAMP
        WHERE category_type = 'Debt'
          AND name = ?
          AND month = ''
        """,
        [
            (
                value_or_zero(row, "balance"),
                value_or_zero(row, "minimum_payment"),
                value_or_zero(row, "interest_rate"),
                row["name"],
            )
            for _, row in debt_rows.iterrows()
        ],
    )
    conn.commit()
    return conn.total_changes - before


def load_obligations(conn: sqlite3.Connection) -> pd.DataFrame:
    return pd.read_sql_query(
        """
        SELECT
            id,
            category_type,
            name,
            month,
            due_day,
            expected_amount,
            balance,
            minimum_payment,
            interest_rate,
            sort_order
        FROM obligations
        ORDER BY category_type, sort_order, name
        """,
        conn,
    )


def load_monthly_budgets(conn: sqlite3.Connection) -> pd.DataFrame:
    return pd.read_sql_query(
        """
        SELECT obligation_id, month, expected_amount
        FROM obligation_monthly_budgets
        ORDER BY month, obligation_id
        """,
        conn,
    )


def save_monthly_budgets(
    conn: sqlite3.Connection,
    month: str,
    amounts: dict[int, float],
) -> None:
    conn.executemany(
        """
        INSERT INTO obligation_monthly_budgets (
            obligation_id, month, expected_amount, updated_at
        )
        VALUES (?, ?, ?, CURRENT_TIMESTAMP)
        ON CONFLICT(obligation_id, month) DO UPDATE SET
            expected_amount = excluded.expected_amount,
            updated_at = CURRENT_TIMESTAMP
        """,
        [
            (int(obligation_id), month, float(amount))
            for obligation_id, amount in amounts.items()
        ],
    )
    conn.commit()


def add_obligation(
    conn: sqlite3.Connection,
    category_type: str,
    name: str,
    month: str | None,
    due_day: int | None,
    expected_amount: float,
    balance: float = 0,
    minimum_payment: float = 0,
    interest_rate: float = 0,
) -> None:
    normalized_month = month or ""
    conn.execute(
        """
        DELETE FROM deleted_obligations
        WHERE category_type = ? AND name = ? AND month = ?
        """,
        (category_type, name, normalized_month),
    )
    max_sort_order = conn.execute(
        "SELECT COALESCE(MAX(sort_order), 0) FROM obligations WHERE category_type = ?",
        (category_type,),
    ).fetchone()[0]
    conn.execute(
        """
        INSERT OR IGNORE INTO obligations (
            category_type,
            name,
            month,
            due_day,
            expected_amount,
            balance,
            minimum_payment,
            interest_rate,
            sort_order
        )
        VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?)
        """,
        (
            category_type,
            name,
            normalized_month,
            due_day,
            float(expected_amount),
            float(balance),
            float(minimum_payment),
            float(interest_rate),
            int(max_sort_order) + 1,
        ),
    )
    conn.commit()


def update_obligation(
    conn: sqlite3.Connection,
    obligation_id: int,
    category_type: str,
    name: str,
    month: str | None,
    due_day: int | None,
    expected_amount: float,
    balance: float = 0,
    minimum_payment: float = 0,
    interest_rate: float = 0,
) -> None:
    conn.execute(
        """
        UPDATE obligations
        SET category_type = ?,
            name = ?,
            month = ?,
            due_day = ?,
            expected_amount = ?,
            balance = ?,
            minimum_payment = ?,
            interest_rate = ?,
            updated_at = CURRENT_TIMESTAMP
        WHERE id = ?
        """,
        (
            category_type,
            name,
            month or "",
            due_day,
            float(expected_amount),
            float(balance),
            float(minimum_payment),
            float(interest_rate),
            obligation_id,
        ),
    )
    conn.commit()


def update_obligation_expected_amount(
    conn: sqlite3.Connection,
    obligation_id: int,
    expected_amount: float,
) -> None:
    conn.execute(
        """
        UPDATE obligations
        SET expected_amount = ?,
            updated_at = CURRENT_TIMESTAMP
        WHERE id = ?
        """,
        (float(expected_amount), int(obligation_id)),
    )
    conn.commit()


def delete_obligation(conn: sqlite3.Connection, obligation_id: int) -> None:
    conn.execute(
        """
        INSERT OR REPLACE INTO deleted_obligations (category_type, name, month)
        SELECT category_type, name, month
        FROM obligations
        WHERE id = ?
        """,
        (obligation_id,),
    )
    conn.execute("DELETE FROM obligations WHERE id = ?", (obligation_id,))
    conn.commit()
