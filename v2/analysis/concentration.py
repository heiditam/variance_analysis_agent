"""Concentration analysis: which accounts/tags drove a category's variance.

Handles contributors that move opposite to the overall category trend
explicitly -- they're never counted as "driving" the change, but their
offsetting effect is surfaced separately so a >100% same-direction share
never gets reported without explanation.
"""

from typing import Literal, Optional

import pandas as pd

EPSILON = 1e-9


def compute_concentration(
    df: pd.DataFrame,
    category: str,
    period_a: str,
    period_b: str,
    dimension: Literal["account", "tags"] = "account",
    account: Optional[str] = None,
    max_contributors: int = 3,
) -> dict:
    """Concentration of a category's period_a -> period_b change among values of
    `dimension`. If `account` is given, the whole computation is restricted to
    that account's transactions first.
    """
    subset = df[(df["category"] == category) & (df["period"].isin([period_a, period_b]))]
    if account is not None:
        subset = subset[subset["account"] == account]

    totals = (
        subset.groupby([dimension, "period"])["amount"]
        .sum()
        .unstack("period")
        .reindex(columns=[period_a, period_b], fill_value=0.0)
        .fillna(0.0)
    )

    overall_a = float(totals[period_a].sum())
    overall_b = float(totals[period_b].sum())
    overall_change = overall_b - overall_a
    direction = "increase" if overall_change >= 0 else "decrease"

    contributors = []
    for key, row in totals.iterrows():
        total_a = float(row[period_a])
        total_b = float(row[period_b])
        delta = total_b - total_a
        same_direction = (delta >= 0) == (overall_change >= 0) and delta != 0

        share = None
        if abs(overall_change) > EPSILON:
            share = delta / overall_change

        contributors.append(
            {
                "key": key,
                "total_a": total_a,
                "total_b": total_b,
                "delta": delta,
                "same_direction": same_direction,
                "share_of_overall_change": share,
            }
        )

    contributors.sort(key=lambda c: abs(c["delta"]), reverse=True)

    same_direction_contributors = [c for c in contributors if c["same_direction"]]
    offsetting_contributors = [c for c in contributors if not c["same_direction"] and c["delta"] != 0]

    top_contributors = same_direction_contributors[:max_contributors]
    top_contributors_share = None
    if abs(overall_change) > EPSILON:
        top_contributors_share = sum(c["delta"] for c in top_contributors) / overall_change

    offsetting_share = None
    if abs(overall_change) > EPSILON:
        offsetting_share = sum(c["delta"] for c in offsetting_contributors) / overall_change

    return {
        "category": category,
        "dimension": dimension,
        "account": account,
        "overall_change": overall_change,
        "direction": direction,
        "contributors": contributors,
        "top_contributors": top_contributors,
        "top_contributors_share": top_contributors_share,
        "offsetting_contributors": offsetting_contributors,
        "offsetting_share": offsetting_share,
    }
