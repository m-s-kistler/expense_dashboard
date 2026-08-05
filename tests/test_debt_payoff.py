import unittest
from datetime import date

import pandas as pd

from expense_dashboard.debt_payoff import (
    add_months,
    simulate_accelerated_debt_payoff,
    simulate_debt_payoff,
)


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

    def test_accelerated_payoff_rolls_paid_debt_budget_forward(self):
        debts = pd.DataFrame(
            [
                {"name": "First", "balance": 100, "expected_amount": 50, "interest_rate": 0},
                {"name": "Second", "balance": 300, "expected_amount": 50, "interest_rate": 0},
            ]
        )

        result, schedule = simulate_accelerated_debt_payoff(
            debts,
            extra_payment=50,
            start_date=date(2026, 1, 1),
        )

        self.assertEqual(result["months_to_payoff"], 3)
        self.assertEqual(result["payoff_date"], date(2026, 3, 1))
        self.assertEqual(schedule["payment"].tolist(), [150.0, 150.0, 100.0])
        self.assertEqual(schedule.iloc[-1]["ending_balance"], 0.0)

    def test_accelerated_payoff_uses_dataframe_order_as_priority(self):
        debts = pd.DataFrame(
            [
                {"name": "First", "balance": 50, "expected_amount": 0, "interest_rate": 0},
                {"name": "Second", "balance": 100, "expected_amount": 0, "interest_rate": 0},
            ]
        )

        result, schedule = simulate_accelerated_debt_payoff(
            debts,
            extra_payment=50,
            start_date=date(2026, 1, 1),
        )

        self.assertEqual(result["months_to_payoff"], 3)
        self.assertEqual(schedule["ending_balance"].tolist(), [100.0, 50.0, 0.0])


if __name__ == "__main__":
    unittest.main()
