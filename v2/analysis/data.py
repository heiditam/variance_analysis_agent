"""Load a combined transactions CSV and derive the monthly account/category summary."""

import os
from typing import Literal

import pandas as pd

Dataset = Literal["expenses", "income"]

REQUIRED_COLUMNS = ["date_time", "type", "category", "account", "amount", "currency", "tags"]
TYPE_TO_DATASET = {"expense": "expenses", "income": "income"}


def load_transactions(csv_path: str) -> pd.DataFrame:
    """Read one combined transactions CSV from an arbitrary path.

    Expected columns: date_time, type, category, account, amount, currency, tags,
    with `type` in {"expense", "income"}. Raises a clear error if the file is
    missing or malformed rather than silently mis-bucketing rows.
    """
    if not os.path.isfile(csv_path):
        raise FileNotFoundError(
            f"Transactions CSV not found at '{csv_path}'. Pass a valid path via --data "
            "(see scripts/refresh_kaggle_data.py to regenerate the bundled sample)."
        )

    df = pd.read_csv(csv_path, parse_dates=["date_time"])

    missing = [c for c in REQUIRED_COLUMNS if c not in df.columns]
    if missing:
        raise ValueError(
            f"'{csv_path}' is missing required column(s): {missing}. "
            f"Expected columns: {REQUIRED_COLUMNS}"
        )

    df["type"] = df["type"].astype(str).str.strip().str.lower()
    bad_types = sorted(set(df["type"]) - set(TYPE_TO_DATASET))
    if bad_types:
        raise ValueError(
            f"'{csv_path}' has unexpected value(s) in the 'type' column: {bad_types}. "
            f"Expected only {sorted(TYPE_TO_DATASET)}."
        )

    df["dataset"] = df["type"].map(TYPE_TO_DATASET)
    df["period"] = df["date_time"].dt.to_period("M").astype(str)
    return df


def filter_dataset(df: pd.DataFrame, dataset: Dataset) -> pd.DataFrame:
    """Restrict the combined dataframe to one dataset ("expenses" or "income")."""
    return df[df["dataset"] == dataset]


def derive_monthly_account_summary(df: pd.DataFrame) -> pd.DataFrame:
    """Group by (period, dataset, account, category) and aggregate totals/counts."""
    summary = (
        df.groupby(["period", "dataset", "account", "category"])["amount"]
        .agg(total_amount="sum", txn_count="count", avg_amount="mean")
        .reset_index()
        .sort_values(["dataset", "period", "account", "category"])
    )
    return summary


def materialize_summary(summary: pd.DataFrame, out_dir: str = "data/derived") -> str:
    """Write the derived summary to out_dir, overwriting on every call. Returns the path."""
    os.makedirs(out_dir, exist_ok=True)
    out_path = os.path.join(out_dir, "monthly_account_summary.csv")
    summary.to_csv(out_path, index=False)
    return out_path


def periods_available(df: pd.DataFrame) -> list[str]:
    """Sorted unique period strings ("YYYY-MM") present in df."""
    return sorted(df["period"].unique())
