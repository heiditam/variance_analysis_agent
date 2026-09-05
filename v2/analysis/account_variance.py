"""Deterministic, transparent account-level materiality: >10% change and a $ floor."""

import pandas as pd

from analysis.data import Dataset, filter_dataset


def compute_account_variance(
    df: pd.DataFrame,
    dataset: Dataset,
    period_a: str,
    period_b: str,
    pct_threshold: float = 0.10,
    min_abs_change: float = 20.0,
) -> pd.DataFrame:
    """Per-account totals for period_a vs period_b, flagged material if the change
    exceeds pct_threshold AND min_abs_change. A brand-new account (total_a == 0)
    is always flagged material, with pct_change reported as None rather than
    dividing by zero.

    Returns one row per account: account, dataset, total_a, total_b, abs_change,
    pct_change, is_material -- sorted by abs_change descending.
    """
    subset = filter_dataset(df, dataset)
    subset = subset[subset["period"].isin([period_a, period_b])]

    totals = (
        subset.groupby(["account", "period"])["amount"]
        .sum()
        .unstack("period")
        .reindex(columns=[period_a, period_b], fill_value=0.0)
        .fillna(0.0)
    )

    rows = []
    for account, row in totals.iterrows():
        total_a = float(row[period_a])
        total_b = float(row[period_b])
        abs_change = total_b - total_a

        if total_a == 0:
            pct_change = None
            is_material = total_b != 0
        else:
            pct_change = abs_change / total_a
            is_material = abs(pct_change) >= pct_threshold and abs(abs_change) >= min_abs_change

        rows.append(
            {
                "account": account,
                "dataset": dataset,
                "total_a": total_a,
                "total_b": total_b,
                "abs_change": abs_change,
                "pct_change": pct_change,
                "is_material": is_material,
            }
        )

    result = pd.DataFrame(rows)
    if result.empty:
        return result
    return result.sort_values("abs_change", key=abs, ascending=False).reset_index(drop=True)
