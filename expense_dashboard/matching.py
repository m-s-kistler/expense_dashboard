from __future__ import annotations

from difflib import SequenceMatcher
import re

import pandas as pd


def normalize_description(value: object) -> str:
    text = str(value or "").lower()
    text = re.sub(r"\b\d{1,2}/\d{1,2}/\d{2,4}\b", " ", text)
    text = re.sub(r"\b\d{6,}\b", " ", text)
    text = re.sub(r"[^a-z0-9]+", " ", text)
    return re.sub(r"\s+", " ", text).strip()


def description_score(left: str, right: str) -> float:
    left_norm = normalize_description(left)
    right_norm = normalize_description(right)
    if not left_norm or not right_norm:
        return 0.0
    if left_norm == right_norm:
        return 1.0
    if left_norm in right_norm or right_norm in left_norm:
        return 0.95

    left_tokens = set(left_norm.split())
    right_tokens = set(right_norm.split())
    if left_tokens and right_tokens:
        token_score = len(left_tokens & right_tokens) / len(left_tokens | right_tokens)
    else:
        token_score = 0.0

    sequence_score = SequenceMatcher(None, left_norm, right_norm).ratio()
    return max(token_score, sequence_score)


def match_workbook_categories(
    transactions: pd.DataFrame,
    workbook_transactions: pd.DataFrame,
    threshold: float = 0.62,
) -> pd.DataFrame:
    if transactions.empty or workbook_transactions.empty:
        return pd.DataFrame(
            columns=[
                "id",
                "category_type",
                "category",
                "match_score",
                "workbook_description",
            ]
        )

    candidates = transactions[
        transactions["category_type"].fillna("Uncategorized").eq("Uncategorized")
    ].copy()
    if candidates.empty:
        return pd.DataFrame()

    candidates["amount_key"] = candidates["amount"].round(2)
    workbook = workbook_transactions.copy()
    workbook["amount_key"] = workbook["amount"].round(2)

    matches = []
    used_transaction_ids = set()
    used_workbook_indexes = set()

    for _, transaction in candidates.iterrows():
        exact_pool = workbook[
            (workbook["date"] == transaction["date"])
            & (workbook["amount_key"] == transaction["amount_key"])
        ]
        if exact_pool.empty:
            continue

        scored = []
        for workbook_index, workbook_row in exact_pool.iterrows():
            if workbook_index in used_workbook_indexes:
                continue
            score = description_score(
                transaction["description"],
                workbook_row["description"],
            )
            scored.append((score, workbook_index, workbook_row))

        if not scored:
            continue

        score, workbook_index, workbook_row = max(scored, key=lambda item: item[0])
        if score < threshold or transaction["id"] in used_transaction_ids:
            continue

        matches.append(
            {
                "id": transaction["id"],
                "date": transaction["date"],
                "amount": transaction["amount"],
                "description": transaction["description"],
                "category_type": workbook_row["category_type"],
                "category": workbook_row["category"],
                "match_score": round(score, 4),
                "workbook_month": workbook_row["month"],
                "workbook_row": workbook_row["workbook_row"],
                "workbook_description": workbook_row["description"],
            }
        )
        used_transaction_ids.add(transaction["id"])
        used_workbook_indexes.add(workbook_index)

    return pd.DataFrame(matches).sort_values(
        ["match_score", "date"],
        ascending=[False, False],
    )

