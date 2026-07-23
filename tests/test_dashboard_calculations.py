import unittest

import pandas as pd

from app import (
    budget_actuals,
    budget_summary,
    categorized_transactions,
    resolve_monthly_budgets,
)


class DashboardCalculationTests(unittest.TestCase):
    def setUp(self):
        self.transactions = pd.DataFrame(
            [
                {"amount": 1000.0, "category_type": "Income", "category": "Paycheck"},
                {"amount": 200.0, "category_type": "Monthly Bills", "category": "Rent"},
                {"amount": 75.0, "category_type": "Uncategorized", "category": "Uncategorized"},
                {"amount": 25.0, "category_type": "Monthly Bills", "category": "Uncategorized"},
            ]
        )
        self.obligations = pd.DataFrame(
            [
                {"id": 1, "category_type": "Income", "name": "Paycheck", "month": "", "expected_amount": 1000.0},
                {"id": 2, "category_type": "Monthly Bills", "name": "Rent", "month": "", "expected_amount": 500.0},
            ]
        )

    def test_categorized_transactions_excludes_incomplete_rows(self):
        result = categorized_transactions(self.transactions)
        self.assertEqual(result["amount"].tolist(), [1000.0, 200.0])

    def test_budget_summary_excludes_uncategorized_amounts(self):
        summary = budget_summary(self.transactions, self.obligations, "Monthly", "2026-07")
        self.assertEqual(summary["total_spent"], 200.0)
        self.assertEqual(summary["left_to_spend"], 300.0)

    def test_budget_actuals_excludes_uncategorized_amounts(self):
        actuals = budget_actuals(self.transactions, self.obligations, "Monthly", "2026-07")
        rent = actuals[actuals["category"].eq("Rent")].iloc[0]
        self.assertEqual(rent["actual"], 200.0)

    def test_monthly_income_override_is_used(self):
        overrides = pd.DataFrame(
            [{"obligation_id": 1, "month": "2026-07", "expected_amount": 1250.0}]
        )

        resolved = resolve_monthly_budgets(
            self.obligations, overrides, "Monthly", "2026-07"
        )

        income = resolved[resolved["category_type"].eq("Income")].iloc[0]
        self.assertEqual(income["expected_amount"], 1250.0)

    def test_full_year_income_uses_monthly_overrides_and_defaults(self):
        overrides = pd.DataFrame(
            [
                {"obligation_id": 1, "month": "2026-01", "expected_amount": 1200.0},
                {"obligation_id": 1, "month": "2026-02", "expected_amount": 800.0},
            ]
        )

        resolved = resolve_monthly_budgets(
            self.obligations, overrides, "Full year", "2026-07"
        )

        income = resolved[resolved["category_type"].eq("Income")].iloc[0]
        self.assertEqual(income["expected_amount"], 1000.0)


if __name__ == "__main__":
    unittest.main()
