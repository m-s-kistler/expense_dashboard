import unittest

import pandas as pd

from expense_dashboard.importer import (
    clean_corning,
    clean_wells_fargo,
    deduplicate_transactions,
    money_to_number,
    normalize_transactions,
)


class ImporterTests(unittest.TestCase):
    def test_money_to_number_handles_common_currency_formats(self):
        values = pd.Series(["$1,234.56", "(45.67)", " 8 ", "invalid"])

        result = money_to_number(values)

        self.assertEqual(result.iloc[0], 1234.56)
        self.assertEqual(result.iloc[1], -45.67)
        self.assertEqual(result.iloc[2], 8.0)
        self.assertTrue(pd.isna(result.iloc[3]))

    def test_normalize_transactions_drops_invalid_and_blank_rows(self):
        raw = pd.DataFrame(
            {
                "date": ["2026-01-02", "not-a-date", "2026-01-03"],
                "amount": ["12.50", "4.00", "3.00"],
                "description": ["  Coffee Shop  ", "Invalid date", "   "],
                "source": [None, "Bank", "Bank"],
            }
        )

        result = normalize_transactions(raw)

        self.assertEqual(result.to_dict("records"), [
            {
                "date": "2026-01-02",
                "amount": 12.5,
                "description": "Coffee Shop",
                "source": "Unknown",
            }
        ])

    def test_clean_corning_uses_absolute_amounts(self):
        raw = pd.DataFrame(
            {
                "Effective Date": ["07/04/2026"],
                "Amount": ["($19.25)"],
                "Extended Description": ["  Grocery Store  "],
            }
        )

        result = clean_corning(raw)

        self.assertEqual(result.iloc[0].to_dict(), {
            "date": "2026-07-04",
            "amount": 19.25,
            "description": "Grocery Store",
            "source": "Corning",
        })

    def test_clean_wells_fargo_detects_columns_case_insensitively(self):
        raw = pd.DataFrame(
            {
                "Posting DATE": ["2026-03-09"],
                "Transaction Amount": [-42.0],
                "DESCRIPTION": ["Fuel"],
            }
        )

        result = clean_wells_fargo(raw)

        self.assertEqual(result.iloc[0]["source"], "Wells Fargo")
        self.assertEqual(result.iloc[0]["amount"], 42.0)

    def test_missing_bank_columns_raise_a_helpful_error(self):
        with self.assertRaisesRegex(ValueError, "required Wells Fargo columns"):
            clean_wells_fargo(pd.DataFrame({"Date": ["2026-01-01"]}))

    def test_deduplicate_transactions_ignores_description_case(self):
        rows = pd.DataFrame(
            {
                "date": ["2026-02-01", "2026-02-01", "2026-02-01"],
                "amount": [10, 10, 11],
                "description": ["Coffee", " coffee ", "Coffee"],
                "source": ["A", "B", "A"],
            }
        )

        result = deduplicate_transactions(rows)

        self.assertEqual(len(result), 2)
        self.assertEqual(result.iloc[0]["source"], "A")


if __name__ == "__main__":
    unittest.main()
