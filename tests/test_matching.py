import unittest

import pandas as pd

from expense_dashboard.matching import (
    description_score,
    match_workbook_categories,
    normalize_description,
)


class MatchingTests(unittest.TestCase):
    def test_normalize_description_removes_dates_and_long_reference_numbers(self):
        result = normalize_description("STORE #42 07/04/2026 REF 123456789")

        self.assertEqual(result, "store 42 ref")

    def test_description_score_rewards_exact_and_contained_descriptions(self):
        self.assertEqual(description_score("ACME MARKET", "acme market"), 1.0)
        self.assertEqual(description_score("ACME", "Acme Market"), 0.95)
        self.assertEqual(description_score("", "Acme"), 0.0)

    def test_matches_only_uncategorized_transactions_with_date_and_amount_match(self):
        transactions = pd.DataFrame(
            [
                {
                    "id": "match-me",
                    "date": "2026-05-01",
                    "amount": 25.0,
                    "description": "Acme Market 12345678",
                    "category_type": "Uncategorized",
                },
                {
                    "id": "already-done",
                    "date": "2026-05-01",
                    "amount": 25.0,
                    "description": "Acme Market",
                    "category_type": "Variable Expenses",
                },
            ]
        )
        workbook = pd.DataFrame(
            [
                {
                    "date": "2026-05-01",
                    "amount": 25.0,
                    "description": "ACME MARKET",
                    "category_type": "Variable Expenses",
                    "category": "Groceries",
                    "month": "May",
                    "workbook_row": 70,
                }
            ]
        )

        result = match_workbook_categories(transactions, workbook)

        self.assertEqual(result["id"].tolist(), ["match-me"])
        self.assertEqual(result.iloc[0]["category"], "Groceries")
        self.assertEqual(result.iloc[0]["match_score"], 1.0)

    def test_does_not_reuse_one_workbook_row_for_two_transactions(self):
        transactions = pd.DataFrame(
            [
                {"id": "one", "date": "2026-01-01", "amount": 5.0, "description": "Cafe", "category_type": "Uncategorized"},
                {"id": "two", "date": "2026-01-01", "amount": 5.0, "description": "Cafe", "category_type": "Uncategorized"},
            ]
        )
        workbook = pd.DataFrame(
            [{"date": "2026-01-01", "amount": 5.0, "description": "Cafe", "category_type": "Variable Expenses", "category": "Restaurants", "month": "January", "workbook_row": 1}]
        )

        result = match_workbook_categories(transactions, workbook)

        self.assertEqual(len(result), 1)


if __name__ == "__main__":
    unittest.main()
