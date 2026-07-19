from __future__ import annotations

from io import BytesIO, StringIO
from pathlib import Path

import pandas as pd


CANONICAL_COLUMNS = [
    "date",
    "amount",
    "description",
    "source",
]


def money_to_number(series: pd.Series) -> pd.Series:
    return pd.to_numeric(
        series.astype(str)
        .str.replace(",", "", regex=False)
        .str.replace("$", "", regex=False)
        .str.replace("(", "-", regex=False)
        .str.replace(")", "", regex=False)
        .str.strip(),
        errors="coerce",
    )


def clean_corning(df: pd.DataFrame) -> pd.DataFrame:
    required_columns = [
        "Effective Date",
        "Amount",
        "Extended Description",
    ]
    missing = [col for col in required_columns if col not in df.columns]
    if missing:
        raise ValueError(
            f"Missing required Corning columns: {missing}. "
            f"Columns found: {list(df.columns)}"
        )

    cleaned = pd.DataFrame(
        {
            "date": pd.to_datetime(df["Effective Date"], errors="coerce"),
            "amount": money_to_number(df["Amount"]).abs(),
            "description": df["Extended Description"].astype(str).str.strip(),
            "source": "Corning",
        }
    )
    return normalize_transactions(cleaned)


def clean_wells_fargo(df: pd.DataFrame) -> pd.DataFrame:
    cols = {c.lower().strip(): c for c in df.columns}
    date_col = next((orig for norm, orig in cols.items() if "date" in norm), None)
    amount_col = next((orig for norm, orig in cols.items() if "amount" in norm), None)
    desc_col = next(
        (orig for norm, orig in cols.items() if "description" in norm),
        None,
    )

    if not all([date_col, amount_col, desc_col]):
        raise ValueError(
            "Could not detect required Wells Fargo columns. "
            f"Columns found: {list(df.columns)}"
        )

    cleaned = pd.DataFrame(
        {
            "date": pd.to_datetime(df[date_col], errors="coerce"),
            "amount": money_to_number(df[amount_col]).abs(),
            "description": df[desc_col].astype(str).str.strip(),
            "source": "Wells Fargo",
        }
    )
    return normalize_transactions(cleaned)


def normalize_transactions(df: pd.DataFrame) -> pd.DataFrame:
    cleaned = df.copy()
    cleaned["date"] = pd.to_datetime(cleaned["date"], errors="coerce")
    cleaned["amount"] = pd.to_numeric(cleaned["amount"], errors="coerce")
    cleaned["description"] = cleaned["description"].fillna("").astype(str).str.strip()
    cleaned["source"] = cleaned["source"].fillna("Unknown").astype(str).str.strip()
    cleaned = cleaned.dropna(subset=["date", "amount"])
    cleaned = cleaned[cleaned["description"] != ""]
    cleaned["date"] = cleaned["date"].dt.strftime("%Y-%m-%d")
    return cleaned[CANONICAL_COLUMNS].reset_index(drop=True)


def deduplicate_transactions(df: pd.DataFrame) -> pd.DataFrame:
    cleaned = normalize_transactions(df)
    cleaned["description_clean"] = cleaned["description"].str.lower().str.strip()
    cleaned = cleaned.drop_duplicates(
        subset=["date", "amount", "description_clean"],
        keep="first",
    )
    return cleaned.drop(columns=["description_clean"]).reset_index(drop=True)


def read_csv_file(file_obj) -> pd.DataFrame:
    if isinstance(file_obj, (str, Path)):
        return pd.read_csv(file_obj)
    content = file_obj.getvalue() if hasattr(file_obj, "getvalue") else file_obj.read()
    if isinstance(content, bytes):
        return pd.read_csv(BytesIO(content))
    return pd.read_csv(StringIO(content))


def clean_transaction_file(file_obj, filename: str) -> pd.DataFrame:
    raw = read_csv_file(file_obj)
    lower_name = filename.lower()

    if lower_name.startswith("corning_"):
        return clean_corning(raw)
    if lower_name.startswith("wells_fargo_"):
        return clean_wells_fargo(raw)

    # Fall back to Wells Fargo style detection for generic bank exports.
    return clean_wells_fargo(raw)


def load_transaction_folder(folder: str | Path) -> pd.DataFrame:
    folder_path = Path(folder)
    frames = []
    for file_path in sorted(folder_path.glob("*.csv")):
        frames.append(clean_transaction_file(file_path, file_path.name))
    if not frames:
        return pd.DataFrame(columns=CANONICAL_COLUMNS)
    return deduplicate_transactions(pd.concat(frames, ignore_index=True))

