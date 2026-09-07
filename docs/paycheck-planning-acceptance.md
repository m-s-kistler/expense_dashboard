# Paycheck Planning Acceptance Scenarios

These scenarios define the initial behavioral baseline for paycheck-based planning.
Dollar amounts are intentionally omitted until the income-source and allocation setup
is entered in the application.

## Wells Fargo semi-monthly schedule

- Wells Fargo represents the user's income.
- Paychecks recur on the 1st and 15th of each month.
- These paychecks primarily fund monthly bills, debt, and non-monthly bills.
- Each generated paycheck remains independently editable when its actual date or
  amount differs from the schedule.

## Corning biweekly schedule

- Corning represents Kelly's income.
- Paychecks recur every 14 days from a configured anchor payday.
- These paychecks primarily fund variable expenses.
- The schedule must correctly produce months with two or three Corning paychecks and
  continue across month and year boundaries.

## Best Egg early-payment scenario

- The Best Egg loan retains a due date on the 8th.
- It can be assigned to the second Wells Fargo paycheck in the preceding month.
- Paying it in the preceding month must not change its contractual due date or cause
  it to appear unpaid for the intended due period.
- The plan must show both the funding paycheck and the due period.

## Manual planning adjustments

- An obligation can be moved to a different paycheck without changing its due date.
- An obligation can be split across multiple paychecks.
- A paycheck can have an occurrence-specific date or amount override.
- Manual allocations must survive regeneration of future paycheck occurrences.

## Reconciliation and balances

- Each paycheck shows expected income, allocated expenses, actual payments, and the
  remaining amount.
- Overallocated paychecks and unassigned obligations are clearly identified.
- A categorized transaction can satisfy an allocation in full or in part.
- Existing monthly budget, transaction categorization, import, and debt-payoff
  behavior remains available.
