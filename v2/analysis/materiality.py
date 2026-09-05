"""Historical-volatility-aware materiality scoring for category-level variances.

Distinguishes a genuinely unusual swing (judged against a category's own
month-to-month history) from a merely large one, and degrades gracefully when
there isn't enough history to trust a standard-deviation estimate.
"""

import statistics
from typing import Optional

import pandas as pd

EPSILON = 1e-9


def _category_period_totals(df: pd.DataFrame, category: str) -> pd.Series:
    """All available per-period totals for one category, summed across accounts."""
    cat_df = df[df["category"] == category]
    return cat_df.groupby("period")["amount"].sum().sort_index()


def compute_materiality(
    df: pd.DataFrame,
    period_a: str,
    period_b: str,
    min_history_for_zscore: int = 6,
) -> pd.DataFrame:
    """For every category present in period_a or period_b, compute a materiality
    score relative to that category's own historical volatility.

    df is expected to already be scoped to the dataset (and optionally account)
    being analyzed -- this function doesn't filter by dataset/account itself.
    """
    two_periods = df[df["period"].isin([period_a, period_b])]
    categories = sorted(two_periods["category"].unique())

    rows = []
    for category in categories:
        all_totals = _category_period_totals(df, category)
        total_a = float(all_totals.get(period_a, 0.0))
        total_b = float(all_totals.get(period_b, 0.0))
        abs_change = total_b - total_a
        pct_change = None if total_a == 0 else abs_change / total_a

        history = all_totals.drop(index=[p for p in (period_a, period_b) if p in all_totals.index])
        history_n = len(history)

        materiality_score: float
        materiality_method: str

        if history_n >= min_history_for_zscore:
            deltas = history.diff().dropna()
            std = statistics.pstdev(deltas) if len(deltas) > 1 else 0.0
            if std > EPSILON:
                z_score = abs(abs_change) / std
                materiality_score = min(z_score / 3.0, 1.0)
                materiality_method = "zscore"
            else:
                materiality_score = abs(abs_change) / max(total_a, total_b, EPSILON)
                materiality_method = "robust_ratio"
        else:
            materiality_score = abs(abs_change) / max(total_a, total_b, EPSILON)
            materiality_method = "robust_ratio"

        rows.append(
            {
                "category": category,
                "total_a": total_a,
                "total_b": total_b,
                "abs_change": abs_change,
                "pct_change": pct_change,
                "history_n": history_n,
                "materiality_score": materiality_score,
                "materiality_method": materiality_method,
            }
        )

    result = pd.DataFrame(rows)
    if result.empty:
        return result
    # Sort by absolute dollar impact, not materiality_score: the small-sample
    # "robust_ratio" fallback caps at 1.0 for ANY category that fully appears/
    # disappears regardless of size, which would otherwise let a trivial-dollar
    # category outrank a much larger zscore-flagged move. materiality_score/
    # materiality_method remain in the output as an "is this unusual" annotation,
    # not the primary ranking signal.
    by_impact = result["abs_change"].abs().sort_values(ascending=False).index
    return result.reindex(by_impact).reset_index(drop=True)
