import unittest
from datetime import date

import pandas as pd

from expense_dashboard.debt_payoff import add_months, simulate_debt_payoff


class DebtPayoffTests(unittest.TestCase):
    def test_add_months_crosses_year_boundary_and_returns_first_day(self):
        self.assertEqual(add_months(date(2026, 11, 20), 3), date(2027, 2, 1))

    def test_zero_interest_payoff_schedule(self):
        debts = pd.DataFrame(
            [{"name": "Card", "balance": 100, "expected_amount": 30, "interest_rate": 0, "minimum_payment": 20}]
        )

        summary, schedule = simulate_debt_payoff(debts, date(2026, 1, 1))

        self.assertEqual(summary.iloc[0]["months_to_payoff"], 4)
        self.assertEqual(summary.iloc[0]["payoff_date"], date(2026, 4, 1))
        self.assertEqual(summary.iloc[0]["total_interest"], 0.0)
        self.assertEqual(schedule["payment"].tolist(), [30.0, 30.0, 30.0, 10.0])
        self.assertEqual(schedule.iloc[-1]["ending_balance"], 0.0)

    def test_already_paid_and_unbudgeted_debts_have_clear_statuses(self):
        debts = pd.DataFrame(
            [
                {"name": "Paid", "balance": 0, "expected_amount": 10},
                {"name": "No payment", "balance": 100, "expected_amount": 0},
            ]
        )

        summary, schedule = simulate_debt_payoff(debts, date(2026, 6, 1))

        self.assertEqual(summary["status"].tolist(), ["Already paid", "No budgeted payment"])
        self.assertTrue(schedule.empty)

    def test_payment_below_interest_is_detected(self):
        debts = pd.DataFrame(
            [{"name": "Expensive", "balance": 1000, "expected_amount": 5, "interest_rate": 0.12}]
        )

        summary, schedule = simulate_debt_payoff(debts, date(2026, 1, 1))

        self.assertEqual(summary.iloc[0]["status"], "Payment below monthly interest")
        self.assertTrue(schedule.empty)


if __name__ == "__main__":
    unittest.main()
