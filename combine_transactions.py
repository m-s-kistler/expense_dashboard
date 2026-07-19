from pathlib import Path
import pandas as pd

# =========================================================
# CONFIG
# =========================================================

INPUT_FOLDER = r"./transactions"

OUTPUT_CSV = "combined_transactions_cleaned.csv"
OUTPUT_XLSX = "combined_transactions_cleaned.xlsx"
NEW_TRANSACTIONS_CSV = "new_transactions.csv"
NEW_TRANSACTIONS_XLSX = "new_transactions.xlsx"

# =========================================================
# HELPERS
# =========================================================

def money_to_number(series):
    """
    Converts money strings like:
        $123.45
        (123.45)
        -123.45
    into numeric floats.
    """

    return pd.to_numeric(
        series.astype(str)
        .str.replace(",", "", regex=False)
        .str.replace("$", "", regex=False)
        .str.replace("(", "-", regex=False)
        .str.replace(")", "", regex=False)
        .str.strip(),
        errors="coerce",
    )


# =========================================================
# CLEANERS
# =========================================================

def clean_corning(df):
    """
    Corning format:
        - Date = Effective Date
        - Description = Extended Description
        - Amount = Absolute Value
    """

    required_columns = [
        "Effective Date",
        "Amount",
        "Extended Description",
    ]

    for col in required_columns:
        if col not in df.columns:
            raise ValueError(
                f"Missing required column '{col}' "
                f"in Corning file.\n"
                f"Columns found: {list(df.columns)}"
            )

    cleaned = pd.DataFrame({
        "date": pd.to_datetime(
            df["Effective Date"],
            errors="coerce"
        ).dt.strftime("%m/%d/%Y"),

        "amount": money_to_number(
            df["Amount"]
        ).abs(),

        "description": (
            df["Extended Description"]
            .astype(str)
            .str.strip()
        ),

        "source": "Corning",
    })

    return cleaned.dropna(subset=["date", "amount"])


def clean_wells_fargo(df):
    """
    Wells Fargo format:
        Uses generic detection.
        Amounts converted to absolute value.
    """

    cols = {
        c.lower().strip(): c
        for c in df.columns
    }

    date_col = next(
        (
            orig
            for norm, orig in cols.items()
            if "date" in norm
        ),
        None
    )

    amount_col = next(
        (
            orig
            for norm, orig in cols.items()
            if "amount" in norm
        ),
        None
    )

    desc_col = next(
        (
            orig
            for norm, orig in cols.items()
            if "description" in norm
        ),
        None
    )

    if not all([date_col, amount_col, desc_col]):
        raise ValueError(
            "Could not detect required columns "
            f"in Wells Fargo file.\n"
            f"Columns found: {list(df.columns)}"
        )

    cleaned = pd.DataFrame({
        "date": pd.to_datetime(
            df[date_col],
            errors="coerce"
        ).dt.strftime("%m/%d/%Y"),

        "amount": money_to_number(
            df[amount_col]
        ).abs(),

        "description": (
            df[desc_col]
            .astype(str)
            .str.strip()
        ),

        "source": "Wells Fargo",
    })

    return cleaned.dropna(subset=["date", "amount"])


# =========================================================
# FILE PROCESSING
# =========================================================

def process_file(file_path):

    filename = file_path.name.lower()

    print(f"Processing: {file_path.name}")

    df = pd.read_csv(file_path)

    if filename.startswith("corning_"):
        return clean_corning(df)

    elif filename.startswith("wells_fargo_"):
        return clean_wells_fargo(df)

    else:
        print(f"Skipping unknown file format: {file_path.name}")
        return None


# =========================================================
# MAIN
# =========================================================

def main():

    input_path = Path(INPUT_FOLDER)

    if not input_path.exists():
        raise FileNotFoundError(
            f"Folder does not exist: {INPUT_FOLDER}"
        )

    csv_files = list(input_path.glob("*.csv"))

    if not csv_files:
        print("No CSV files found.")
        return

    # =====================================================
    # LOAD EXISTING TRANSACTIONS
    # =====================================================

    existing_transactions = None
    output_path = Path(OUTPUT_CSV)

    if output_path.exists():
        print(f"Loading existing file: {OUTPUT_CSV}")
        existing_transactions = pd.read_csv(OUTPUT_CSV)
        print(f"Found {len(existing_transactions)} existing transactions")
        print()

    # =====================================================
    # PROCESS NEW FILES
    # =====================================================

    all_transactions = []

    for file_path in csv_files:

        try:

            cleaned = process_file(file_path)

            if cleaned is not None:
                all_transactions.append(cleaned)

        except Exception as e:

            print()
            print(f"ERROR processing {file_path.name}")
            print(e)
            print()

    if not all_transactions:
        print("No valid transaction data found.")
        return

    # =====================================================
    # COMBINE NEW TRANSACTIONS
    # =====================================================

    new_batch = pd.concat(
        all_transactions,
        ignore_index=True
    )

    # =====================================================
    # MERGE WITH EXISTING (if available)
    # =====================================================

    if existing_transactions is not None:
        combined = pd.concat(
            [existing_transactions, new_batch],
            ignore_index=True
        )
    else:
        combined = new_batch

    # =====================================================
    # REMOVE DUPLICATES
    # =====================================================

    combined["description_clean"] = (
        combined["description"]
        .astype(str)
        .str.strip()
        .str.lower()
    )

    # Mark which transactions are duplicates
    combined["is_duplicate"] = combined.duplicated(
        subset=[
            "date",
            "amount",
            "description_clean",
        ],
        keep="first"
    )

    # Separate new transactions (not duplicates)
    new_transactions = combined[~combined["is_duplicate"]].copy()

    # Remove helper columns
    combined = combined.drop(
        columns=["description_clean", "is_duplicate"]
    )

    new_transactions = new_transactions.drop(
        columns=["description_clean", "is_duplicate"]
    )

    # =====================================================
    # IDENTIFY TRULY NEW TRANSACTIONS
    # =====================================================

    if existing_transactions is not None:
        # Only the transactions that weren't in the existing file
        new_count = len(new_transactions) - len(existing_transactions)
        if new_count < 0:
            new_count = 0
        # Get only the rows that are truly new
        new_only = new_transactions.tail(new_count)
    else:
        # Everything is new if no existing file
        new_only = new_transactions

    # =====================================================
    # SORT
    # =====================================================

    combined["date_sort"] = pd.to_datetime(
        combined["date"],
        format="%m/%d/%Y",
        errors="coerce"
    )

    combined = combined.sort_values(
        by="date_sort",
        ascending=False
    )

    combined = combined.drop(
        columns=["date_sort"]
    )

    if len(new_only) > 0:
        new_only["date_sort"] = pd.to_datetime(
            new_only["date"],
            format="%m/%d/%Y",
            errors="coerce"
        )

        new_only = new_only.sort_values(
            by="date_sort",
            ascending=False
        )

        new_only = new_only.drop(
            columns=["date_sort"]
        )

    # =====================================================
    # SAVE
    # =====================================================

    combined.to_csv(
        OUTPUT_CSV,
        index=False
    )

    combined.to_excel(
        OUTPUT_XLSX,
        index=False
    )

    if len(new_only) > 0:
        new_only.to_csv(
            NEW_TRANSACTIONS_CSV,
            index=False
        )

        new_only.to_excel(
            NEW_TRANSACTIONS_XLSX,
            index=False
        )

    # =====================================================
    # DONE
    # =====================================================

    print()
    print("=" * 60)
    print(f"Total unique transactions: {len(combined)}")
    print(f"New transactions found: {len(new_only)}")
    print("=" * 60)
    print(f"Combined CSV:  {OUTPUT_CSV}")
    print(f"Combined XLSX: {OUTPUT_XLSX}")
    if len(new_only) > 0:
        print(f"New CSV:       {NEW_TRANSACTIONS_CSV}")
        print(f"New XLSX:      {NEW_TRANSACTIONS_XLSX}")
    else:
        print("No new transactions to save separately.")
    print("=" * 60)


if __name__ == "__main__":
    main()