import tempfile
import unittest
from pathlib import Path

import pandas as pd

from expense_dashboard.bank_sync import (
    BankSyncError,
    PlaidClient,
    PlaidConfig,
    decrypt_access_token,
    encrypt_access_token,
    plaid_transactions_frame,
)
from expense_dashboard.db import (
    apply_bank_sync,
    connect,
    init_db,
    load_bank_connections,
    load_transactions,
    save_bank_connection,
)


class StubPlaidClient(PlaidClient):
    def __init__(self, responses):
        super().__init__(PlaidConfig("client", "secret"))
        self.responses = iter(responses)
        self.payloads = []

    def _post(self, endpoint, payload):
        self.payloads.append((endpoint, payload))
        return next(self.responses)


class BankSyncTests(unittest.TestCase):
    def test_access_token_round_trip_and_wrong_key_failure(self):
        encrypted = encrypt_access_token("access-sandbox-123", "local-key")

        self.assertNotIn("access-sandbox-123", encrypted)
        self.assertEqual(
            decrypt_access_token(encrypted, "local-key"), "access-sandbox-123"
        )
        with self.assertRaises(BankSyncError):
            decrypt_access_token(encrypted, "different-key")

    def test_sync_transactions_collects_all_pages_and_passes_cursor(self):
        client = StubPlaidClient(
            [
                {
                    "added": [{"transaction_id": "one"}],
                    "modified": [],
                    "removed": [],
                    "next_cursor": "page-2",
                    "has_more": True,
                },
                {
                    "added": [{"transaction_id": "two"}],
                    "modified": [{"transaction_id": "changed"}],
                    "removed": [{"transaction_id": "gone"}],
                    "next_cursor": "complete",
                    "has_more": False,
                },
            ]
        )

        added, modified, removed, cursor = client.sync_transactions("token")

        self.assertEqual([row["transaction_id"] for row in added], ["one", "two"])
        self.assertEqual(modified[0]["transaction_id"], "changed")
        self.assertEqual(removed, ["gone"])
        self.assertEqual(cursor, "complete")
        self.assertNotIn("cursor", client.payloads[0][1])
        self.assertEqual(client.payloads[1][1]["cursor"], "page-2")

    def test_transaction_conversion_skips_pending_and_prefers_merchant(self):
        rows = [
            {
                "transaction_id": "posted",
                "date": "2026-07-20",
                "authorized_date": "2026-07-19",
                "amount": -12.5,
                "merchant_name": "Corner Shop",
                "name": "Fallback",
                "pending": False,
            },
            {
                "transaction_id": "pending",
                "date": "2026-07-20",
                "amount": 4,
                "name": "Pending",
                "pending": True,
            },
        ]

        result = plaid_transactions_frame(rows, "Test Bank")

        self.assertEqual(result.to_dict("records"), [
            {
                "external_id": "posted",
                "date": "2026-07-19",
                "amount": 12.5,
                "description": "Corner Shop",
                "source": "Test Bank",
            }
        ])

    def test_database_sync_updates_and_removes_provider_transactions(self):
        with tempfile.TemporaryDirectory() as directory:
            conn = connect(Path(directory) / "test.sqlite3")
            try:
                init_db(conn)
                connection_id = save_bank_connection(
                    conn, "item-1", "Test Bank", "encrypted-token"
                )
                first = pd.DataFrame(
                    [{"external_id": "txn-1", "date": "2026-01-01", "amount": 10.0, "description": "Old", "source": "Test Bank"}]
                )
                apply_bank_sync(conn, connection_id, first, [], "cursor-1")
                changed = first.copy()
                changed.loc[0, "description"] = "Updated"
                apply_bank_sync(conn, connection_id, changed, [], "cursor-2")

                transactions = load_transactions(conn)
                connection = load_bank_connections(conn).iloc[0]
                self.assertEqual(len(transactions), 1)
                self.assertEqual(transactions.iloc[0]["description"], "Updated")
                self.assertEqual(connection["sync_cursor"], "cursor-2")

                apply_bank_sync(conn, connection_id, pd.DataFrame(), ["txn-1"], "cursor-3")
                self.assertTrue(load_transactions(conn).empty)
            finally:
                conn.close()


if __name__ == "__main__":
    unittest.main()
