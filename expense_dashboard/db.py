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

        CREATE TABLE IF NOT EXISTS income_sources (
            id INTEGER PRIMARY KEY AUTOINCREMENT,
            name TEXT NOT NULL UNIQUE,
            owner TEXT NOT NULL DEFAULT '',
            schedule_type TEXT NOT NULL CHECK (
                schedule_type IN ('semi_monthly', 'biweekly')
            ),
            expected_amount REAL NOT NULL DEFAULT 0,
            semi_monthly_day_1 INTEGER,
            semi_monthly_day_2 INTEGER,
            biweekly_anchor_date TEXT,
            active INTEGER NOT NULL DEFAULT 1,
            created_at TEXT NOT NULL DEFAULT CURRENT_TIMESTAMP,
            updated_at TEXT NOT NULL DEFAULT CURRENT_TIMESTAMP
        );

        CREATE TABLE IF NOT EXISTS paycheck_occurrences (
            id INTEGER PRIMARY KEY AUTOINCREMENT,
            income_source_id INTEGER NOT NULL,
            scheduled_date TEXT NOT NULL,
            actual_date TEXT,
            expected_amount REAL NOT NULL DEFAULT 0,
            actual_amount REAL,
            matched_transaction_id TEXT,
            is_manual INTEGER NOT NULL DEFAULT 0,
            status TEXT NOT NULL DEFAULT 'planned' CHECK (
                status IN ('planned', 'received', 'skipped')
            ),
            created_at TEXT NOT NULL DEFAULT CURRENT_TIMESTAMP,
            updated_at TEXT NOT NULL DEFAULT CURRENT_TIMESTAMP,
            UNIQUE(income_source_id, scheduled_date),
            FOREIGN KEY (income_source_id) REFERENCES income_sources(id) ON DELETE CASCADE,
            FOREIGN KEY (matched_transaction_id) REFERENCES transactions(id) ON DELETE SET NULL
        );

        CREATE INDEX IF NOT EXISTS idx_paycheck_occurrences_date
            ON paycheck_occurrences(scheduled_date);

        CREATE TABLE IF NOT EXISTS obligation_funding_rules (
            obligation_id INTEGER PRIMARY KEY,
            income_source_id INTEGER NOT NULL,
            timing_rule TEXT NOT NULL DEFAULT 'previous_paycheck' CHECK (
                timing_rule IN (
                    'previous_paycheck',
                    'previous_month_second',
                    'same_month_first',
                    'same_month_second'
                )
            ),
            updated_at TEXT NOT NULL DEFAULT CURRENT_TIMESTAMP,
            FOREIGN KEY (obligation_id) REFERENCES obligations(id) ON DELETE CASCADE,
            FOREIGN KEY (income_source_id) REFERENCES income_sources(id) ON DELETE CASCADE
        );

        CREATE TABLE IF NOT EXISTS paycheck_allocations (
            id INTEGER PRIMARY KEY AUTOINCREMENT,
            paycheck_occurrence_id INTEGER NOT NULL,
            obligation_id INTEGER NOT NULL,
            budget_month TEXT NOT NULL,
            due_date TEXT,
            allocated_amount REAL NOT NULL DEFAULT 0,
            status TEXT NOT NULL DEFAULT 'planned' CHECK (
                status IN ('planned', 'partial', 'paid', 'skipped')
            ),
            note TEXT NOT NULL DEFAULT '',
            is_manual INTEGER NOT NULL DEFAULT 0,
            created_at TEXT NOT NULL DEFAULT CURRENT_TIMESTAMP,
            updated_at TEXT NOT NULL DEFAULT CURRENT_TIMESTAMP,
            UNIQUE(paycheck_occurrence_id, obligation_id, budget_month),
            FOREIGN KEY (paycheck_occurrence_id) REFERENCES paycheck_occurrences(id) ON DELETE CASCADE,
            FOREIGN KEY (obligation_id) REFERENCES obligations(id) ON DELETE CASCADE
        );

        CREATE INDEX IF NOT EXISTS idx_paycheck_allocations_month
            ON paycheck_allocations(budget_month);

        CREATE TABLE IF NOT EXISTS allocation_transactions (
            allocation_id INTEGER NOT NULL,
            transaction_id TEXT NOT NULL,
            applied_amount REAL NOT NULL,
            created_at TEXT NOT NULL DEFAULT CURRENT_TIMESTAMP,
            PRIMARY KEY (allocation_id, transaction_id),
            FOREIGN KEY (allocation_id) REFERENCES paycheck_allocations(id) ON DELETE CASCADE,
            FOREIGN KEY (transaction_id) REFERENCES transactions(id) ON DELETE CASCADE
        );
        """
    )
    _ensure_paycheck_columns(conn)
    conn.commit()


def _ensure_paycheck_columns(conn: sqlite3.Connection) -> None:
    columns = {
        row[1]
        for row in conn.execute("PRAGMA table_info(paycheck_occurrences)").fetchall()
    }
    if "is_manual" not in columns:
        conn.execute(
            "ALTER TABLE paycheck_occurrences ADD COLUMN is_manual INTEGER NOT NULL DEFAULT 0"
        )


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


def update_obligation_sort_orders(
    conn: sqlite3.Connection,
    obligation_ids: list[int],
) -> None:
    conn.executemany(
        """
        UPDATE obligations
        SET sort_order = ?,
            updated_at = CURRENT_TIMESTAMP
        WHERE id = ?
        """,
        [
            (sort_order, int(obligation_id))
            for sort_order, obligation_id in enumerate(obligation_ids, 1)
        ],
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


def seed_default_income_sources(conn: sqlite3.Connection) -> int:
    """Create the household's two editable paycheck schedules once."""
    before = conn.total_changes
    conn.executemany(
        """
        INSERT OR IGNORE INTO income_sources (
            name, owner, schedule_type, expected_amount,
            semi_monthly_day_1, semi_monthly_day_2, biweekly_anchor_date
        )
        VALUES (?, ?, ?, ?, ?, ?, ?)
        """,
        [
            ("Wells Fargo", "Me", "semi_monthly", 5800.0, 1, 15, None),
            ("Corning", "Kelly", "biweekly", 2700.0, None, None, "2026-08-21"),
        ],
    )
    inserted = conn.total_changes - before
    defaults_applied = conn.execute(
        "SELECT 1 FROM app_settings WHERE key = 'paycheck_default_amounts_v1'"
    ).fetchone()
    if not defaults_applied:
        conn.executemany(
            """
            UPDATE income_sources SET expected_amount = ?, updated_at = CURRENT_TIMESTAMP
            WHERE name = ? AND expected_amount = 0
            """,
            [(5800.0, "Wells Fargo"), (2700.0, "Corning")],
        )
        conn.execute(
            """
            UPDATE paycheck_occurrences
            SET expected_amount = (
                    SELECT expected_amount FROM income_sources
                    WHERE income_sources.id = paycheck_occurrences.income_source_id
                ),
                updated_at = CURRENT_TIMESTAMP
            WHERE expected_amount = 0 AND status = 'planned'
            """
        )
        conn.execute(
            "INSERT INTO app_settings (key, value) VALUES ('paycheck_default_amounts_v1', 'applied')"
        )
    conn.commit()
    return inserted


def load_income_sources(conn: sqlite3.Connection) -> pd.DataFrame:
    return pd.read_sql_query(
        """
        SELECT id, name, owner, schedule_type, expected_amount,
               semi_monthly_day_1, semi_monthly_day_2,
               biweekly_anchor_date, active
        FROM income_sources
        ORDER BY active DESC, id
        """,
        conn,
    )


def save_income_source(
    conn: sqlite3.Connection,
    source_id: int,
    name: str,
    owner: str,
    schedule_type: str,
    expected_amount: float,
    semi_monthly_day_1: int | None,
    semi_monthly_day_2: int | None,
    biweekly_anchor_date: str | None,
    active: bool,
) -> None:
    conn.execute(
        """
        UPDATE income_sources
        SET name = ?, owner = ?, schedule_type = ?, expected_amount = ?,
            semi_monthly_day_1 = ?, semi_monthly_day_2 = ?,
            biweekly_anchor_date = ?, active = ?, updated_at = CURRENT_TIMESTAMP
        WHERE id = ?
        """,
        (
            name.strip(), owner.strip(), schedule_type, float(expected_amount),
            semi_monthly_day_1, semi_monthly_day_2, biweekly_anchor_date,
            int(active), int(source_id),
        ),
    )
    conn.execute(
        """
        UPDATE paycheck_occurrences
        SET expected_amount = ?, updated_at = CURRENT_TIMESTAMP
        WHERE income_source_id = ? AND status = 'planned' AND is_manual = 0
        """,
        (float(expected_amount), int(source_id)),
    )
    conn.commit()


def generate_paycheck_occurrences(
    conn: sqlite3.Connection,
    start_date: str,
    end_date: str,
) -> int:
    from datetime import date

    from expense_dashboard.paychecks import generate_paycheck_dates

    sources = load_income_sources(conn)
    before = conn.total_changes
    for _, source in sources[sources["active"].astype(bool)].iterrows():
        source_dict = source.where(pd.notna(source), None).to_dict()
        dates = generate_paycheck_dates(
            source_dict, date.fromisoformat(start_date), date.fromisoformat(end_date)
        )
        conn.executemany(
            """
            INSERT OR IGNORE INTO paycheck_occurrences (
                income_source_id, scheduled_date, expected_amount
            ) VALUES (?, ?, ?)
            """,
            [
                (int(source["id"]), occurrence.isoformat(), float(source["expected_amount"]))
                for occurrence in dates
            ],
        )
    conn.commit()
    return conn.total_changes - before


def load_paycheck_occurrences(
    conn: sqlite3.Connection,
    start_date: str | None = None,
    end_date: str | None = None,
) -> pd.DataFrame:
    clauses: list[str] = []
    params: list[str] = []
    if start_date:
        clauses.append("p.scheduled_date >= ?")
        params.append(start_date)
    if end_date:
        clauses.append("p.scheduled_date <= ?")
        params.append(end_date)
    where = f"WHERE {' AND '.join(clauses)}" if clauses else ""
    return pd.read_sql_query(
        f"""
        SELECT p.id, p.income_source_id, s.name AS source_name, s.owner,
               p.scheduled_date, p.actual_date, p.expected_amount,
               p.actual_amount, p.matched_transaction_id, p.status, p.is_manual
        FROM paycheck_occurrences p
        JOIN income_sources s ON s.id = p.income_source_id
        {where}
        ORDER BY COALESCE(p.actual_date, p.scheduled_date), p.id
        """,
        conn,
        params=params,
    )


def update_paycheck_occurrence(
    conn: sqlite3.Connection,
    occurrence_id: int,
    actual_date: str | None,
    expected_amount: float,
    actual_amount: float | None,
    status: str,
) -> None:
    conn.execute(
        """
        UPDATE paycheck_occurrences
        SET actual_date = ?, expected_amount = ?, actual_amount = ?, status = ?,
            is_manual = 1, updated_at = CURRENT_TIMESTAMP
        WHERE id = ?
        """,
        (actual_date, float(expected_amount), actual_amount, status, int(occurrence_id)),
    )
    conn.commit()


def link_paycheck_transaction(
    conn: sqlite3.Connection,
    occurrence_id: int,
    transaction_id_value: str,
) -> None:
    transaction = conn.execute(
        "SELECT date, amount FROM transactions WHERE id = ?",
        (transaction_id_value,),
    ).fetchone()
    if not transaction:
        raise ValueError("Income transaction was not found.")
    conn.execute(
        """
        UPDATE paycheck_occurrences
        SET actual_date = ?, actual_amount = ?, matched_transaction_id = ?,
            status = 'received', is_manual = 1, updated_at = CURRENT_TIMESTAMP
        WHERE id = ?
        """,
        (transaction["date"], float(transaction["amount"]), transaction_id_value, int(occurrence_id)),
    )
    conn.commit()


def load_funding_rules(conn: sqlite3.Connection) -> pd.DataFrame:
    return pd.read_sql_query(
        """
        SELECT r.obligation_id, r.income_source_id, r.timing_rule,
               s.name AS source_name
        FROM obligation_funding_rules r
        JOIN income_sources s ON s.id = r.income_source_id
        ORDER BY r.obligation_id
        """,
        conn,
    )


def save_funding_rule(
    conn: sqlite3.Connection,
    obligation_id: int,
    income_source_id: int,
    timing_rule: str,
) -> None:
    conn.execute(
        """
        INSERT INTO obligation_funding_rules (
            obligation_id, income_source_id, timing_rule, updated_at
        ) VALUES (?, ?, ?, CURRENT_TIMESTAMP)
        ON CONFLICT(obligation_id) DO UPDATE SET
            income_source_id = excluded.income_source_id,
            timing_rule = excluded.timing_rule,
            updated_at = CURRENT_TIMESTAMP
        """,
        (int(obligation_id), int(income_source_id), timing_rule),
    )
    conn.commit()


def seed_default_funding_rules(conn: sqlite3.Connection) -> int:
    """Fill only missing rules using the household's stated funding pattern."""
    sources = {
        row["name"]: int(row["id"])
        for row in conn.execute("SELECT id, name FROM income_sources").fetchall()
    }
    wells_fargo_id = sources.get("Wells Fargo")
    corning_id = sources.get("Corning")
    if not wells_fargo_id or not corning_id:
        return 0
    before = conn.total_changes
    conn.execute(
        """
        INSERT OR IGNORE INTO obligation_funding_rules (
            obligation_id, income_source_id, timing_rule
        )
        SELECT id,
               CASE WHEN category_type = 'Variable Expenses' THEN ? ELSE ? END,
               CASE
                   WHEN lower(name) LIKE '%best egg%' THEN 'previous_month_second'
                   ELSE 'previous_paycheck'
               END
        FROM obligations
        WHERE category_type IN (
            'Variable Expenses', 'Monthly Bills', 'Debt', 'Savings', 'Non-Monthly Bills'
        )
        """,
        (corning_id, wells_fargo_id),
    )
    conn.commit()
    return conn.total_changes - before


def refresh_legacy_paycheck_suggestions(conn: sqlite3.Connection) -> int:
    """Remove only untouched v1 suggestions so improved rules can regenerate them."""
    migration_key = "paycheck_suggestions_v3"
    if conn.execute(
        "SELECT 1 FROM app_settings WHERE key = ?", (migration_key,)
    ).fetchone():
        return 0
    before = conn.total_changes
    conn.execute("DELETE FROM paycheck_allocations WHERE is_manual = 0")
    removed = conn.total_changes - before
    conn.execute(
        "INSERT INTO app_settings (key, value) VALUES (?, 'applied')",
        (migration_key,),
    )
    conn.commit()
    return removed


def load_paycheck_allocations(
    conn: sqlite3.Connection,
    start_date: str | None = None,
    end_date: str | None = None,
) -> pd.DataFrame:
    clauses: list[str] = []
    params: list[str] = []
    if start_date:
        clauses.append("p.scheduled_date >= ?")
        params.append(start_date)
    if end_date:
        clauses.append("p.scheduled_date <= ?")
        params.append(end_date)
    where = f"WHERE {' AND '.join(clauses)}" if clauses else ""
    return pd.read_sql_query(
        f"""
        SELECT a.id, a.paycheck_occurrence_id, a.obligation_id,
               a.budget_month, a.due_date, a.allocated_amount, a.status,
               a.note, a.is_manual, o.name AS obligation_name,
               o.category_type, p.scheduled_date, s.name AS source_name,
               COALESCE(SUM(at.applied_amount), 0) AS paid_amount
        FROM paycheck_allocations a
        JOIN obligations o ON o.id = a.obligation_id
        JOIN paycheck_occurrences p ON p.id = a.paycheck_occurrence_id
        JOIN income_sources s ON s.id = p.income_source_id
        LEFT JOIN allocation_transactions at ON at.allocation_id = a.id
        {where}
        GROUP BY a.id
        ORDER BY p.scheduled_date, o.category_type, o.sort_order, o.name
        """,
        conn,
        params=params,
    )


def upsert_paycheck_allocation(
    conn: sqlite3.Connection,
    paycheck_occurrence_id: int,
    obligation_id: int,
    budget_month: str,
    due_date: str | None,
    allocated_amount: float,
    status: str = "planned",
    note: str = "",
    is_manual: bool = True,
) -> None:
    conn.execute(
        """
        INSERT INTO paycheck_allocations (
            paycheck_occurrence_id, obligation_id, budget_month, due_date,
            allocated_amount, status, note, is_manual
        ) VALUES (?, ?, ?, ?, ?, ?, ?, ?)
        ON CONFLICT(paycheck_occurrence_id, obligation_id, budget_month) DO UPDATE SET
            due_date = excluded.due_date,
            allocated_amount = excluded.allocated_amount,
            status = excluded.status,
            note = excluded.note,
            is_manual = MAX(paycheck_allocations.is_manual, excluded.is_manual),
            updated_at = CURRENT_TIMESTAMP
        """,
        (
            int(paycheck_occurrence_id), int(obligation_id), budget_month, due_date,
            float(allocated_amount), status, note.strip(), int(is_manual),
        ),
    )
    conn.commit()


def update_paycheck_allocation(
    conn: sqlite3.Connection,
    allocation_id: int,
    paycheck_occurrence_id: int,
    allocated_amount: float,
    status: str,
    note: str,
) -> None:
    current = conn.execute(
        "SELECT paycheck_occurrence_id, obligation_id, budget_month FROM paycheck_allocations WHERE id = ?",
        (int(allocation_id),),
    ).fetchone()
    if not current:
        raise ValueError("Allocation was not found.")
    duplicate = conn.execute(
        """
        SELECT id, allocated_amount FROM paycheck_allocations
        WHERE paycheck_occurrence_id = ? AND obligation_id = ? AND budget_month = ?
          AND id <> ?
        """,
        (
            int(paycheck_occurrence_id), int(current["obligation_id"]),
            current["budget_month"], int(allocation_id),
        ),
    ).fetchone()
    if duplicate:
        conn.execute(
            """
            UPDATE paycheck_allocations
            SET allocated_amount = ?, status = ?, note = ?, is_manual = 1,
                updated_at = CURRENT_TIMESTAMP
            WHERE id = ?
            """,
            (
                float(duplicate["allocated_amount"]) + float(allocated_amount),
                status, note.strip(), int(duplicate["id"]),
            ),
        )
        conn.execute("DELETE FROM paycheck_allocations WHERE id = ?", (int(allocation_id),))
        conn.commit()
        return
    conn.execute(
        """
        UPDATE paycheck_allocations
        SET paycheck_occurrence_id = ?, allocated_amount = ?, status = ?, note = ?,
            is_manual = 1, updated_at = CURRENT_TIMESTAMP
        WHERE id = ?
        """,
        (int(paycheck_occurrence_id), float(allocated_amount), status, note.strip(), int(allocation_id)),
    )
    conn.commit()


def delete_paycheck_allocation(conn: sqlite3.Connection, allocation_id: int) -> None:
    conn.execute("DELETE FROM paycheck_allocations WHERE id = ?", (int(allocation_id),))
    conn.commit()


def link_allocation_transaction(
    conn: sqlite3.Connection,
    allocation_id: int,
    transaction_id_value: str,
    applied_amount: float,
) -> None:
    conn.execute(
        """
        INSERT INTO allocation_transactions (allocation_id, transaction_id, applied_amount)
        VALUES (?, ?, ?)
        ON CONFLICT(allocation_id, transaction_id) DO UPDATE SET
            applied_amount = excluded.applied_amount
        """,
        (int(allocation_id), transaction_id_value, float(applied_amount)),
    )
    allocated, paid = conn.execute(
        """
        SELECT a.allocated_amount, COALESCE(SUM(at.applied_amount), 0)
        FROM paycheck_allocations a
        LEFT JOIN allocation_transactions at ON at.allocation_id = a.id
        WHERE a.id = ? GROUP BY a.id
        """,
        (int(allocation_id),),
    ).fetchone()
    status = "paid" if paid >= allocated else ("partial" if paid > 0 else "planned")
    conn.execute(
        "UPDATE paycheck_allocations SET status = ?, is_manual = 1, updated_at = CURRENT_TIMESTAMP WHERE id = ?",
        (status, int(allocation_id)),
    )
    conn.commit()
