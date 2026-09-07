import tempfile
import unittest
from datetime import date
from pathlib import Path

from expense_dashboard.db import (
    add_obligation,
    connect,
    generate_paycheck_occurrences,
    init_db,
    load_income_sources,
    load_funding_rules,
    load_obligations,
    load_paycheck_allocations,
    load_paycheck_occurrences,
    link_allocation_transaction,
    seed_default_funding_rules,
    seed_default_income_sources,
    upsert_paycheck_allocation,
)
from expense_dashboard.paychecks import (
    biweekly_dates,
    choose_funding_paycheck,
    due_date_for_month,
    semi_monthly_dates,
)
from app import suggest_month_allocations


class PaycheckScheduleTests(unittest.TestCase):
    def test_semi_monthly_schedule_crosses_month_boundary(self):
        result = semi_monthly_dates(date(2026, 8, 10), date(2026, 9, 16), 1, 15)
        self.assertEqual(
            result,
            [date(2026, 8, 15), date(2026, 9, 1), date(2026, 9, 15)],
        )

    def test_corning_anchor_generates_fourteen_day_schedule(self):
        result = biweekly_dates(
            date(2026, 8, 1), date(2026, 9, 30), date(2026, 8, 21)
        )
        self.assertEqual(
            result,
            [
                date(2026, 8, 7),
                date(2026, 8, 21),
                date(2026, 9, 4),
                date(2026, 9, 18),
            ],
        )

    def test_prior_month_second_supports_best_egg_scenario(self):
        pay_dates = [
            date(2026, 8, 1),
            date(2026, 8, 15),
            date(2026, 9, 1),
            date(2026, 9, 15),
        ]
        due = due_date_for_month("2026-09", 8)
        self.assertEqual(
            choose_funding_paycheck(pay_dates, due, "previous_month_second"),
            date(2026, 8, 15),
        )


class PaycheckDatabaseTests(unittest.TestCase):
    def setUp(self):
        self.temp_dir = tempfile.TemporaryDirectory()
        self.conn = connect(Path(self.temp_dir.name) / "test.sqlite3")
        init_db(self.conn)

    def tearDown(self):
        self.conn.close()
        self.temp_dir.cleanup()

    def test_default_sources_and_occurrences_are_idempotent(self):
        self.assertEqual(seed_default_income_sources(self.conn), 2)
        self.assertEqual(seed_default_income_sources(self.conn), 0)
        sources = load_income_sources(self.conn)
        self.assertEqual(set(sources["name"]), {"Wells Fargo", "Corning"})

        first = generate_paycheck_occurrences(self.conn, "2026-08-01", "2026-09-30")
        second = generate_paycheck_occurrences(self.conn, "2026-08-01", "2026-09-30")
        self.assertEqual(first, 8)
        self.assertEqual(second, 0)
        self.assertEqual(len(load_paycheck_occurrences(self.conn)), 8)

    def test_default_funding_rules_follow_household_pattern(self):
        seed_default_income_sources(self.conn)
        add_obligation(self.conn, "Monthly Bills", "Mortgage", None, 1, 1000)
        add_obligation(self.conn, "Variable Expenses", "Groceries", None, None, 400)
        add_obligation(self.conn, "Debt", "Best Egg Loan", None, 8, 250)
        self.assertEqual(seed_default_funding_rules(self.conn), 3)
        rows = self.conn.execute(
            """
            SELECT o.name, s.name
            FROM obligation_funding_rules r
            JOIN obligations o ON o.id = r.obligation_id
            JOIN income_sources s ON s.id = r.income_source_id
            ORDER BY o.name
            """
        ).fetchall()
        self.assertEqual(
            [tuple(row) for row in rows],
            [
                ("Best Egg Loan", "Wells Fargo"),
                ("Groceries", "Corning"),
                ("Mortgage", "Wells Fargo"),
            ],
        )
        best_egg_id = self.conn.execute(
            "SELECT id FROM obligations WHERE name = 'Best Egg Loan'"
        ).fetchone()[0]
        rule = load_funding_rules(self.conn)
        self.assertEqual(
            rule[rule["obligation_id"].eq(best_egg_id)].iloc[0]["timing_rule"],
            "previous_month_second",
        )

    def test_allocation_can_be_partially_and_fully_reconciled(self):
        seed_default_income_sources(self.conn)
        add_obligation(self.conn, "Monthly Bills", "Internet", None, 10, 100)
        obligation_id = self.conn.execute(
            "SELECT id FROM obligations WHERE name = 'Internet'"
        ).fetchone()[0]
        generate_paycheck_occurrences(self.conn, "2026-08-01", "2026-08-31")
        occurrence_id = self.conn.execute(
            """
            SELECT p.id FROM paycheck_occurrences p
            JOIN income_sources s ON s.id = p.income_source_id
            WHERE s.name = 'Wells Fargo' AND p.scheduled_date = '2026-08-01'
            """
        ).fetchone()[0]
        upsert_paycheck_allocation(
            self.conn, occurrence_id, obligation_id, "2026-08", "2026-08-10", 100
        )
        self.conn.executemany(
            """
            INSERT INTO transactions (id, date, amount, description, source, category_type, category)
            VALUES (?, ?, ?, ?, ?, ?, ?)
            """,
            [
                ("tx-1", "2026-08-02", 40, "Internet partial", "Bank", "Monthly Bills", "Internet"),
                ("tx-2", "2026-08-03", 60, "Internet remainder", "Bank", "Monthly Bills", "Internet"),
            ],
        )
        self.conn.commit()
        allocation_id = int(load_paycheck_allocations(self.conn).iloc[0]["id"])
        link_allocation_transaction(self.conn, allocation_id, "tx-1", 40)
        partial = load_paycheck_allocations(self.conn).iloc[0]
        self.assertEqual(partial["status"], "partial")
        self.assertEqual(partial["paid_amount"], 40)
        link_allocation_transaction(self.conn, allocation_id, "tx-2", 60)
        paid = load_paycheck_allocations(self.conn).iloc[0]
        self.assertEqual(paid["status"], "paid")
        self.assertEqual(paid["paid_amount"], 100)

    def test_best_egg_suggestion_uses_prior_month_second_wells_fargo_check(self):
        seed_default_income_sources(self.conn)
        add_obligation(self.conn, "Debt", "Best Egg Loan", None, 8, 250)
        seed_default_funding_rules(self.conn)
        generate_paycheck_occurrences(self.conn, "2026-08-01", "2026-10-31")
        created = suggest_month_allocations(
            self.conn, load_obligations(self.conn), "2026-09"
        )
        self.assertEqual(created, 1)
        allocation = load_paycheck_allocations(self.conn).iloc[0]
        self.assertEqual(allocation["scheduled_date"], "2026-08-15")
        self.assertEqual(allocation["due_date"], "2026-09-08")
        self.assertEqual(allocation["budget_month"], "2026-09")

    def test_variable_budget_is_split_across_corning_checks_in_month(self):
        seed_default_income_sources(self.conn)
        add_obligation(self.conn, "Variable Expenses", "Groceries", None, None, 401)
        seed_default_funding_rules(self.conn)
        generate_paycheck_occurrences(self.conn, "2026-08-01", "2026-08-31")
        created = suggest_month_allocations(
            self.conn, load_obligations(self.conn), "2026-08"
        )
        self.assertEqual(created, 2)
        allocations = load_paycheck_allocations(self.conn)
        self.assertEqual(allocations["scheduled_date"].tolist(), ["2026-08-07", "2026-08-21"])
        self.assertEqual(allocations["allocated_amount"].tolist(), [200.5, 200.5])


if __name__ == "__main__":
    unittest.main()
