# Workbook Analysis

Source workbook: `Finance Dashboard and Annual Budget System.xlsx`

## Project Assets

The workspace also contains bank transaction source files and an existing cleaning script:

| Path | Purpose |
|---|---|
| `transactions/corning_20260718.csv` | Bank transaction export |
| `transactions/wells_fargo_20260718.csv` | Bank transaction export |
| `combine_transactions.py` | Existing Python script for loading, cleaning, and deduplicating transactions |

These files are important for the new app because the dashboard should ingest cleaned bank transactions, then map those rows into the budget categories currently represented in the workbook.

Workbook category reuse has been implemented in the local app:

| Source | Matching behavior |
|---|---|
| Monthly workbook transaction trackers | Extract rows `68:1001` from each month sheet |
| Local SQLite transactions | Match only uncategorized rows |
| Required match fields | Exact transaction date and exact amount |
| Flexible match field | Description similarity, including cases where workbook descriptions have manual notes appended |

Initial match result: `1,225` local transactions were categorized from workbook data; `157` remained uncategorized.

## Sheet Index

| # | Sheet | State | Formula count | Chart count | Notes |
|---:|---|---|---:|---:|---|
| 1 | Setup | visible | 586 | 0 | Source lists/configuration for monthly sheets |
| 2 | Start Here | visible | 0 | 0 | Intro/instructions |
| 3 | Annual Dashboard | visible | 4,959 | 12 | Year-level summaries and charts |
| 4 | January | visible | 1,591 | 2 | Monthly budget, transactions, spending breakdown |
| 5-15 | February-December | visible | ~2,100-2,300 each | 2 each | Same monthly pattern as January |
| 16 | SavingsSinking Funds | visible | 322 | 20 | Savings/sinking fund tracking and charts |
| 17 | Debt | visible | 62,348 | 0 | Detailed debt model |
| 18 | Debt Payoff Dashboard | visible | 814 | 3 | Debt payoff summary/charts |
| 19 | Net Worth | visible | 1,256 | 3 | Net worth tracking/charts |
| 20 | Additional Data | hidden | 1,134 | 0 | Helper data |
| 21 | Transaction Logs Dropdown Data | hidden | 7,320 | 0 | Dropdown/helper data |
| 22 | Aggregated Transaction Log Data | hidden | 31,104 | 0 | Cross-month transaction aggregation |

## January Sheet

The `January` sheet appears to be the monthly template used by the other month sheets.

### Main Sections

| Range | Section | Purpose |
|---|---|---|
| `E3:J15` | Budget overview | Summary of budgeted vs actual by major category |
| `E17:J40` | Income | Budgeted and actual income lines |
| `L17:T64` | Variable Expenses | Category budgets, actual spend, and remaining budget |
| `V17:AB64` | Monthly Bills | Recurring bill descriptions, due dates, budgeted amounts, and actuals |
| `AD17:AK40` | Non-Monthly Bills | Ad hoc/non-recurring bills |
| `E42:J64` | Savings | Sinking/savings categories |
| `AD42:AK64` | Debt | Debt payment categories |
| `E66:AC1001` | Transaction Tracker | Date, amount, category, sub-category, and description entries |
| `AD66:AK1001` | Spending Breakdown | Aggregated category spending and percentages |

### Key Formulas

The top summary is driven by row totals from the lower sections:

| Cell | Meaning | Formula |
|---|---|---|
| `H9` | Budgeted variable expenses | `O64` |
| `J9` | Actual variable expenses | `Q64` |
| `H10` | Budgeted bills | `Z64+AI40` |
| `J10` | Actual bills | `AB64+AK40` |
| `H11` | Budgeted debt | `AI64` |
| `J11` | Actual debt | `AK64` |
| `H12` | Budgeted savings | `H64` |
| `J12` | Actual savings | `J64` |
| `H13` | Budgeted income | `H40` |
| `J13` | Actual income | `J40` |
| `H15` | Budgeted remaining | `H14+H13-H12-H11-H10-H9` |
| `J15` | Actual remaining | `J14+J13-J12-J11-J10-J9` |
| `M5` | Left to budget | `H13+H14-R5` |
| `R5` | Total budgeted | `SUM(H9:H12)` |
| `M12` | Left to spend | `J13+J14-R12` |
| `R12` | Total spent | `SUM(J9:J12)` |

Actuals are mostly calculated from the transaction tracker with `SUMIFS`:

| Area | Example | Formula pattern |
|---|---|---|
| Income actuals | `J19` | `SUMIFS($H$68:$H1001,$I$68:$I1001,"="&"Income",$L$68:L1001,"="&E19)` |
| Variable expense actuals | `Q19` | `SUMIFS($H$68:$H1001,$I$68:$I1001,"="&"Variable Expenses",$L$68:$L1001,"="&L19)` |
| Monthly bill actuals | `AB19` | `SUMIFS($H$68:$H1001,$I$68:$I1001,"="&"Monthly Bills",$L$68:$L1001,"="&W19)` |
| Non-monthly bill actuals | `AK19` | `SUMIFS($H$68:$H1001,$I$68:$I1001,"="&"Non-Monthly Bills",$L$68:$L1001,"="&AE19)` |
| Savings actuals | `J44` | `SUMIFS($H$68:$H1001,$I$68:$I1001,"="&"Savings",$L$68:$L1001,"="&E44)` |
| Debt actuals | `AK44` | `SUMIFS($H$68:$H1001,$I$68:$I1001,"="&"Debt",$L$68:$L1001,"="&AE44)` |

Budget category names and planned amounts mostly come from `Setup`, for example:

| January area | Source pattern |
|---|---|
| Income descriptions | `Setup!B7:B...` |
| Income budgeted amounts | `Setup!E7:E...` |
| Variable expense categories | `Setup!H7:H...` |
| Variable expense budgets | `Setup!M7:M...` |
| Monthly bill descriptions | `Setup!R7:R...` |
| Monthly bill due dates | `Setup!W7:W...` |
| Monthly bill budgeted amounts | `Setup!Y7:Y...` |
| Savings categories | `Setup!B57:B...` |
| Savings budgeted amounts | `Setup!E57:E...` |
| Debt descriptions | `Setup!B82:B...` |
| Debt due dates | `Setup!F82:F...` |
| Debt planned payments | `Setup!I82:I...` |

### Charts

`January` has two charts:

| Chart XML | Source ranges | Meaning |
|---|---|---|
| `xl/charts/chart13.xml` | `January!$F$9:$F$13`, `January!$H$9:$H$14`, `January!$J$9:$J$14` | Budgeted vs actual summary by category |
| `xl/charts/chart14.xml` | `January!$AE$7:$AE$10`, `January!$AF$7:$AF$10` | Expense breakdown by major category |

### Dashboard Implications

For the new app, the monthly sheet translates cleanly into normalized data:

| Concept | App model |
|---|---|
| Transaction tracker rows | `transactions` table/imported CSV rows |
| Category/sub-category columns | Categorization rules plus editable transaction category fields |
| Setup-driven budget rows | `budget_categories` and `monthly_budget_allocations` |
| Actual spend formulas | Database/groupby queries equivalent to current `SUMIFS` |
| Budget overview | Monthly summary API/view model |
| Spending breakdown chart | Group transactions by category/sub-category and calculate share of total |

The most important behavior to preserve is not the literal spreadsheet layout. It is the transaction-to-category aggregation logic currently implemented through `SUMIFS`.

## Setup Sheet

The `Setup` sheet is the workbook's main configuration/source-data sheet. The monthly sheets pull most category names, budgeted amounts, due dates, and debt metadata from here.

### Main Sections

| Range | Section | Purpose |
|---|---|---|
| `B2:R3` | Workbook identity | Dashboard title and owner name |
| `H2:H3` | Currency | Currency symbol used across workbook; monthly sheets reference `Setup!$H$3` |
| `B5:E52` | Income | Income descriptions and budgeted amounts |
| `H5:M52` | Variable Expenses | Variable expense category descriptions and budgeted amounts |
| `R5:Y52` | Monthly Bills | Recurring bill descriptions, due day, and budgeted amount |
| `B55:W77` | Savings | Sinking fund categories, goals, starting amount, dates, and recommended savings |
| `B80:V104` | Debt | Debt accounts, due dates, planned payment, balances, minimums, and interest rates |
| `B107:AW131` | Non-Monthly Bills | Ad hoc/non-recurring bills by month, with due day and budgeted amount columns |

### Setup-Driven Monthly Data

These are the most important mappings into the month sheets:

| Setup range | Meaning | Example monthly destination |
|---|---|---|
| `B7:B27` | Income descriptions | `January!E19:E39` |
| `E7:E27` | Income budgeted amounts | `January!H19:H39` |
| `H7:H51` | Variable expense categories | `January!L19:L63` |
| `M7:M51` | Variable expense budgets | `January!O19:O63` |
| `R7:R51` | Monthly bill descriptions | `January!W19:W63` |
| `W7:W51` | Monthly bill due day | `January!X19:X63` |
| `Y7:Y51` | Monthly bill budgeted amounts | `January!Z19:Z63` |
| `B57:B76` | Savings/sinking fund names | `January!E44:E63` |
| `E57:E76` | Monthly savings budgeted amount | `January!H44:H63` |
| `B82:B101` | Debt account names | `January!AE44:AE63` |
| `F82:F101` | Debt due day | `January!AF44:AF63` |
| `I82:I101` | Debt planned monthly payment | `January!AI44:AI63` |

### Setup Totals

| Cell | Meaning | Formula |
|---|---|---|
| `E52` | Total planned income | `SUM(E7:F27)` |
| `M52` | Total planned variable expenses | `SUM(M7:P51)` |
| `Y52` | Total planned monthly bills | `SUM(Y7:Y51)` |
| `E77` | Total planned monthly savings | `SUM(E57:E76)` |
| `I77` | Total savings goals | `SUM(I57:I76)` |
| `K77` | Total savings starting amounts | `SUM(K57:N76)` |
| `W77` | Total recommended monthly savings | `SUM(W57:Y76)` |
| `I102` | Total planned debt payment budget | `SUM(I82:I101)` |
| `K102` | Total debt balance | `SUM(K82:O101)` |
| `Q102` | Total minimum debt payments | `SUM(Q82:U101)` |
| `L104` | Total minimum payment helper | `Q102` |
| `V104` | Additional monthly payment helper | `H3` |

### Savings Formula Behavior

The savings section includes calculated planning fields:

| Field | Formula behavior |
|---|---|
| Recommended monthly savings | `(Total Savings Goal - Starting Amount) / Months Until Finish` |
| Months until finish | `DATEDIF(Start Date, Finish Line, "M")` |

Example formulas:

```excel
W57 = IF(T57="",,(I57-K57)/Z57)
Z57 = IFERROR(DATEDIF(O57,T57,"M"),"")
```

### Non-Monthly Bills Layout

The non-monthly bill section uses a wide month-by-month layout:

| Month | Due column | Budget column |
|---|---|---|
| January | `F` | `H` |
| February | `J` | `L` |
| March | `R` | `T` |
| April | `V` | `X` |
| May | `Z` | `AA` |
| June | `AC` | `AD` |
| July | `AF` | `AG` |
| August | `AI` | `AJ` |
| September | `AL` | `AM` |
| October | `AO` | `AP` |
| November | `AR` | `AS` |
| December | `AU` | `AV` |

The app should normalize this wide layout into rows like:

| Field | Example |
|---|---|
| bill_name | `Progesterone` |
| month | `January` |
| due_day | `1` |
| budgeted_amount | `162.00` |

### App Model Implications

`Setup` should become editable configuration tables in the app:

| Workbook section | Suggested table/model |
|---|---|
| Income | `income_sources` |
| Variable Expenses | `budget_categories` with type `variable_expense` |
| Monthly Bills | `bills` with recurrence `monthly` |
| Non-Monthly Bills | `bills` or `planned_expenses` with month-specific schedules |
| Savings | `sinking_funds` |
| Debt | `debt_accounts` |
| Currency/owner/title | `settings` |

This suggests the import strategy should read `Setup` once to seed app configuration, then import each monthly transaction tracker as transaction data.

## Aggregated Transaction Log Data Sheet

The hidden `Aggregated Transaction Log Data` sheet is the workbook's normalized transaction aggregation layer. It pulls rows from each monthly sheet's transaction tracker into one year-level transaction table.

### Structure

| Column | Header | Meaning |
|---|---|---|
| `A` | Month | Excel serial date for the month represented by the source sheet |
| `B` | Date | Transaction date from the month sheet |
| `D` | Currency symbol | Usually references `Setup!$H$3` / cached `$` |
| `E` | Amount | Transaction amount |
| `F` | Category | Major category, such as `Income`, `Monthly Bills`, `Non-Monthly Bills`, `Variable Expenses`, `Savings`, or `Debt` |
| `I` | Subcategory | Budget line / bill / debt / savings fund name |

The sheet has 5,201 rows and 25,919 formulas. Most formulas are direct references into monthly transaction trackers.

### Formula Behavior

The aggregation logic is a stacked copy/reference pattern:

```excel
B34 = January!E100
D34 = January!G100
E34 = January!H100
F34 = January!I100
I34 = January!L100
```

The same pattern repeats in row blocks for each month:

```excel
B466 = February!E100
D466 = February!G100
E466 = February!H100
F466 = February!I100
I466 = February!L100
```

So the workbook is not doing complex transformation here. It is flattening each monthly transaction tracker into a combined table.

### Monthly Source Mapping

For each month sheet, the relevant transaction tracker columns are:

| Monthly sheet column | Aggregated column | App field |
|---|---|---|
| `E` | `B` | `date` |
| `G` | `D` | `currency_symbol` |
| `H` | `E` | `amount` |
| `I` | `F` | `category` |
| `L` | `I` | `subcategory` |
| `O` | not visible in initial aggregate sample | `description` on monthly sheet |

The app should not need this hidden sheet directly. In Python, we can produce the same result by reading every monthly transaction tracker range and concatenating rows into one `transactions` dataframe/table.

### Python Rebuild Notes

Equivalent Python behavior:

```python
MONTH_SHEETS = [
    "January", "February", "March", "April", "May", "June",
    "July", "August", "September", "October", "November", "December",
]

TRANSACTION_COLUMNS = {
    "E": "date",
    "H": "amount",
    "I": "category",
    "L": "subcategory",
    "O": "description",
}
```

For each month:

1. Read rows `68:1001` from the monthly sheet.
2. Keep rows with a date and amount.
3. Add a normalized `month` field from the source sheet name or transaction date.
4. Normalize category/subcategory text by trimming whitespace.
5. Concatenate all months into one transaction table.

This should become the app's canonical transaction source, replacing `Aggregated Transaction Log Data`.

## Transaction Logs Dropdown Data Sheet

The hidden `Transaction Logs Dropdown Data` sheet supports category/subcategory dropdowns on the monthly transaction trackers.

### Purpose

The sheet defines valid subcategories for each major transaction category:

| Major category | Example subcategories |
|---|---|
| `Income` | `Kelly 1st Paycheck`, `Kelly 2nd Paycheck`, `Matt 1st Pay Check`, `Matt 2nd Paycheck`, `Cell Phone Reimbursement`, `Misc` |
| `Savings` | `Yearly Taxes`, `Christmas Presents`, `Vacation Fund`, `Emergency Fund`, birthday funds, `Misc Savings (Extra)` |
| `Variable Expenses` | `Groceries`, `Restaurants`, `Kids Sports`, `Medical`, `Entertainment`, `Home Expenses`, `Shopping`, `Gas`, `Donations`, `Dog Expenses`, `Car Expenses`, `Kids School Supplies`, `Spa/Aesthetics/Nails`, `Work Expenses`, `Travel`, `Taxes` |
| `Monthly Bills` | `Mortgage`, `Water/Sewer`, `Gas/ Peidmont`, `Electric/ Duke`, insurance, vehicles, subscriptions, transfers, and other recurring bills |
| `Non-Monthly Bills` | `Progesterone`, `Advanced Labs`, `HOA`, `Tirzepatide`, `Botox`, `Skylight Calendar`, `Greenlight Transfers`, `Calm App - Apple`, etc. |
| `Debt` | `Bank of America Visa`, `Citi Bank`, `Wells Fargo Visa`, `Lowes`, `Best Egg`, `Wells Fargo Reflect`, `Ameris Bank Loan`, `Heloc` |

### Formula Behavior

The workbook uses lookup formulas to return the valid subcategory list for the selected category in a monthly transaction row.

Example formula pattern:

```excel
I35 = IFNA(
  TRANSPOSE(
    INDEX($B$4:$G$48,,MATCH(January!I100,$B$3:$G$3,0))
  ),
)
```

Meaning:

1. Look at the transaction's selected major category, such as `January!I100`.
2. Match that category against the category headers in the dropdown data sheet.
3. Return the corresponding list of valid subcategories.
4. Transpose it into a row so Excel can use it for dropdown validation.

### Python Rebuild Notes

In the app, this should become a direct relationship instead of a hidden helper sheet:

```python
CATEGORY_TYPES = [
    "Income",
    "Savings",
    "Variable Expenses",
    "Monthly Bills",
    "Non-Monthly Bills",
    "Debt",
]
```

Recommended models:

| Model | Purpose |
|---|---|
| `category_types` | Major category names, equivalent to the dropdown headers |
| `categories` or `budget_lines` | Subcategory/budget line names, linked to one category type |
| `transactions.category_type_id` | Selected major category |
| `transactions.category_id` | Selected subcategory/budget line |

The UI should filter the subcategory dropdown based on the selected major category. This replaces the Excel `INDEX`/`MATCH`/`TRANSPOSE` helper formulas.
