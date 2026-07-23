import tempfile
import unittest
from pathlib import Path

import pandas as pd

from expense_dashboard.db import (
    add_obligation,
    connect,
    delete_obligation,
    init_db,
    load_obligations,
    seed_obligations,
)


class ObligationTests(unittest.TestCase):
    def setUp(self):
        self.temp_dir = tempfile.TemporaryDirectory()
        self.conn = connect(Path(self.temp_dir.name) / "test.sqlite3")
        init_db(self.conn)

    def tearDown(self):
        self.conn.close()
        self.temp_dir.cleanup()

    @staticmethod
    def workbook_rows():
        return pd.DataFrame(
            [
                {
                    "category_type": "Monthly Bills",
                    "name": "Internet",
                    "month": "",
                    "due_day": 10,
                    "expected_amount": 80.0,
                    "sort_order": 1,
                }
            ]
        )

    def test_deleted_seeded_bill_is_not_recreated(self):
        rows = self.workbook_rows()
        self.assertEqual(seed_obligations(self.conn, rows), 1)
        bill_id = int(load_obligations(self.conn).iloc[0]["id"])

        delete_obligation(self.conn, bill_id)
        self.assertEqual(seed_obligations(self.conn, rows), 0)

        self.assertTrue(load_obligations(self.conn).empty)

    def test_manually_readding_bill_clears_deletion_marker(self):
        rows = self.workbook_rows()
        seed_obligations(self.conn, rows)
        bill_id = int(load_obligations(self.conn).iloc[0]["id"])
        delete_obligation(self.conn, bill_id)

        add_obligation(self.conn, "Monthly Bills", "Internet", None, 10, 90.0)
        self.assertEqual(len(load_obligations(self.conn)), 1)


if __name__ == "__main__":
    unittest.main()
