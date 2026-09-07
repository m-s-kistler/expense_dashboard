# Paycheck Planning

The Paycheck Plan complements the calendar-month dashboard. It records which
paycheck is intended to fund an expense without changing the expense's due date,
budget month, or transaction category.

## Initial household defaults

- Wells Fargo: semi-monthly on the 1st and 15th, $5,800 expected per check.
- Corning: every 14 days from August 21, 2026, $2,700 expected per check.
- Monthly bills, debt, savings, and non-monthly bills default to Wells Fargo.
- Variable expenses default to Corning and are split evenly across the Corning
  checks occurring in the selected month.
- An obligation whose name contains `Best Egg` defaults to the second Wells Fargo
  check in the month before its due month.

All schedules, amounts, and funding rules are editable under **Setup > Paycheck
planning setup**. Changing one paycheck occurrence does not change the recurrence
rule.

## Monthly workflow

1. Select **Monthly** and the month to plan in the sidebar.
2. Open **Paycheck Plan**. Missing paycheck occurrences and suggested allocations
   are generated without replacing manual assignments.
3. Review expected income, allocated expenses, available funds, and unassigned
   expenses.
4. Move an allocation, change its amount, add a note, or split part of it onto a
   second paycheck as needed.
5. Match received income to its income transaction.
6. Apply categorized expense transactions to allocations. Partial payments remain
   partial until their applied total reaches the allocation.

The calendar dashboard includes a Paycheck funding summary for the selected month.

## Status and reconciliation

- `planned`: no applied expense transaction yet.
- `partial`: applied transactions total less than the allocation.
- `paid`: applied transactions meet or exceed the allocation.
- `skipped`: the allocation is intentionally not being paid from that check.

Due dates remain independent of payment dates. For example, a Best Egg payment
funded and paid from August 15 can satisfy the allocation for a September 8 due date.

## Data safety

The schema migration is additive. Existing obligations, monthly overrides,
transactions, categorization, imports, and debt-payoff data are retained. The new
tables are `income_sources`, `paycheck_occurrences`,
`obligation_funding_rules`, `paycheck_allocations`, and
`allocation_transactions`.
