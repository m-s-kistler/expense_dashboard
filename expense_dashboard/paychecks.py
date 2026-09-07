from __future__ import annotations

import calendar
import math
from dataclasses import dataclass
from datetime import date, timedelta
from typing import Iterable


SUPPORTED_FUNDING_TYPES = (
    "Variable Expenses",
    "Monthly Bills",
    "Debt",
    "Savings",
    "Non-Monthly Bills",
)


@dataclass(frozen=True)
class PaycheckDate:
    scheduled_date: date


def _clamped_day(year: int, month: int, day: int) -> date:
    return date(year, month, min(max(int(day), 1), calendar.monthrange(year, month)[1]))


def semi_monthly_dates(
    start: date,
    end: date,
    first_day: int = 1,
    second_day: int = 15,
) -> list[date]:
    """Return scheduled semi-monthly dates, inclusive of start and end."""
    if end < start:
        return []
    cursor = date(start.year, start.month, 1)
    result: list[date] = []
    while cursor <= end:
        for day in sorted({first_day, second_day}):
            candidate = _clamped_day(cursor.year, cursor.month, day)
            if start <= candidate <= end:
                result.append(candidate)
        if cursor.month == 12:
            cursor = date(cursor.year + 1, 1, 1)
        else:
            cursor = date(cursor.year, cursor.month + 1, 1)
    return sorted(set(result))


def biweekly_dates(start: date, end: date, anchor: date) -> list[date]:
    """Return every-fourteen-day occurrences aligned to an anchor payday."""
    if end < start:
        return []
    delta_days = (start - anchor).days
    steps = delta_days // 14
    candidate = anchor + timedelta(days=steps * 14)
    while candidate < start:
        candidate += timedelta(days=14)
    result: list[date] = []
    while candidate <= end:
        result.append(candidate)
        candidate += timedelta(days=14)
    return result


def generate_paycheck_dates(source: dict, start: date, end: date) -> list[date]:
    schedule_type = str(source.get("schedule_type", "")).lower()
    if schedule_type == "semi_monthly":
        return semi_monthly_dates(
            start,
            end,
            int(source.get("semi_monthly_day_1") or 1),
            int(source.get("semi_monthly_day_2") or 15),
        )
    if schedule_type == "biweekly":
        anchor_value = source.get("biweekly_anchor_date")
        if not anchor_value:
            return []
        anchor = (
            anchor_value
            if isinstance(anchor_value, date)
            else date.fromisoformat(str(anchor_value))
        )
        return biweekly_dates(start, end, anchor)
    return []


def due_date_for_month(month: str, due_day: int | None) -> date | None:
    if due_day is None or (isinstance(due_day, float) and math.isnan(due_day)) or not due_day:
        return None
    year, month_number = (int(value) for value in month.split("-"))
    return _clamped_day(year, month_number, int(due_day))


def choose_funding_paycheck(
    pay_dates: Iterable[date],
    due_date: date | None,
    timing_rule: str,
) -> date | None:
    """Choose a suggested paycheck while leaving manual assignments authoritative."""
    dates = sorted(set(pay_dates))
    if not dates:
        return None
    if due_date is None:
        return dates[0]

    on_or_before = [pay_date for pay_date in dates if pay_date <= due_date]
    if timing_rule == "previous_paycheck":
        return on_or_before[-1] if on_or_before else dates[0]
    if timing_rule == "previous_month_second":
        previous_month = due_date.month - 1 or 12
        previous_year = due_date.year - 1 if due_date.month == 1 else due_date.year
        candidates = [
            pay_date
            for pay_date in dates
            if pay_date.year == previous_year and pay_date.month == previous_month
        ]
        return candidates[-1] if candidates else (on_or_before[-1] if on_or_before else dates[0])
    if timing_rule == "same_month_first":
        candidates = [
            pay_date
            for pay_date in dates
            if pay_date.year == due_date.year and pay_date.month == due_date.month
        ]
        return candidates[0] if candidates else (on_or_before[-1] if on_or_before else dates[0])
    if timing_rule == "same_month_second":
        candidates = [
            pay_date
            for pay_date in dates
            if pay_date.year == due_date.year and pay_date.month == due_date.month
        ]
        return candidates[1] if len(candidates) > 1 else (candidates[0] if candidates else None)
    return on_or_before[-1] if on_or_before else dates[0]
