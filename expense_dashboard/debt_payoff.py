from __future__ import annotations

from datetime import date

import pandas as pd


def add_months(start: date, months: int) -> date:
    month_index = start.month - 1 + months
    year = start.year + month_index // 12
    month = month_index % 12 + 1
    return date(year, month, 1)


def simulate_debt_payoff(
    debt_rows: pd.DataFrame,
    start_date: date | None = None,
    max_months: int = 600,
) -> tuple[pd.DataFrame, pd.DataFrame]:
    if start_date is None:
        start_date = date.today().replace(day=1)

    summary_rows = []
    schedule_rows = []

    for _, debt in debt_rows.iterrows():
        name = debt["name"]
        balance = float(debt.get("balance", 0) or 0)
        payment = float(debt.get("expected_amount", 0) or 0)
        rate = float(debt.get("interest_rate", 0) or 0)
        minimum_payment = float(debt.get("minimum_payment", 0) or 0)

        if balance <= 0:
            summary_rows.append(
                {
                    "name": name,
                    "balance": balance,
                    "budgeted_payment": payment,
                    "minimum_payment": minimum_payment,
                    "interest_rate": rate,
                    "months_to_payoff": 0,
                    "payoff_date": start_date,
                    "total_interest": 0.0,
                    "status": "Already paid",
                }
            )
            continue

        if payment <= 0:
            summary_rows.append(
                {
                    "name": name,
                    "balance": balance,
                    "budgeted_payment": payment,
                    "minimum_payment": minimum_payment,
                    "interest_rate": rate,
                    "months_to_payoff": None,
                    "payoff_date": None,
                    "total_interest": None,
                    "status": "No budgeted payment",
                }
            )
            continue

        current_balance = balance
        total_interest = 0.0
        payoff_month = None
        status = "Projected"

        for month_number in range(1, max_months + 1):
            interest = current_balance * (rate / 12)
            total_interest += interest
            amount_due = current_balance + interest
            actual_payment = min(payment, amount_due)
            principal = actual_payment - interest

            if principal <= 0:
                status = "Payment below monthly interest"
                break

            current_balance = max(current_balance - principal, 0)
            schedule_rows.append(
                {
                    "name": name,
                    "month": add_months(start_date, month_number - 1),
                    "payment": actual_payment,
                    "interest": interest,
                    "principal": principal,
                    "ending_balance": current_balance,
                }
            )

            if current_balance <= 0:
                payoff_month = month_number
                break
        else:
            status = f"More than {max_months} months"

        summary_rows.append(
            {
                "name": name,
                "balance": balance,
                "budgeted_payment": payment,
                "minimum_payment": minimum_payment,
                "interest_rate": rate,
                "months_to_payoff": payoff_month,
                "payoff_date": (
                    add_months(start_date, payoff_month - 1)
                    if payoff_month
                    else None
                ),
                "total_interest": total_interest if payoff_month else None,
                "status": status,
            }
        )

    return pd.DataFrame(summary_rows), pd.DataFrame(schedule_rows)
