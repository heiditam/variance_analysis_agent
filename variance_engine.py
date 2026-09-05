"""
Stage A — Variance Engine
=========================
Takes a monthly summary CSV (one row per category, one column per month)
and produces a ranked list of the most *meaningful* variances.

Key design decision: we do NOT just trust the `delta` / `pct_change`
columns that may already be in the file. Two reasons:

1. Those columns often only compare the *last two* months, which can bury
   a real anomaly that happened mid-series (e.g. a one-off spike three
   months ago).
2. pct_change is misleading on small or volatile bases (going from $6 to
   $95 is a huge % but may not matter; going from $938 to $670 is a
   smaller % but may matter more in dollar terms).

So we recompute two independent signals per category and combine them:

- materiality_score: dollar-size of the swing, normalized against the
  category's own typical volume (so a $500 swing on a $50/month category
  is scored higher than a $500 swing on a $5,000/month category).
- anomaly_score: how many standard deviations the most extreme month is
  from that category's own mean (z-score), scanning the *whole* series,
  not just the last column.

The combined ranking surfaces both "this got a lot bigger recently" and
"something weird happened somewhere in this window" cases.
"""

from __future__ import annotations
import pandas as pd
import numpy as np
from dataclasses import dataclass, field
from typing import List, Optional


@dataclass
class Variance:
    category: str
    type_: str
    flagged_period: str          # the month we think is most important to explain
    flagged_value: float
    baseline_mean: float
    baseline_std: float
    materiality_score: float
    anomaly_score: float
    combined_score: float
    latest_delta: float
    latest_pct_change: Optional[float]
    reason: str                  # "anomaly" or "trend" — which signal triggered it
    series: dict = field(default_factory=dict)  # full month->value series, for downstream use


def _month_columns(df: pd.DataFrame) -> List[str]:
    """Return column names that look like YYYY-MM, in chronological order."""
    cols = [c for c in df.columns if len(c) == 7 and c[4] == "-" and c[:4].isdigit()]
    return sorted(cols)


def compute_variances(df: pd.DataFrame, top_n: int = 5) -> List[Variance]:
    """
    df: monthly summary dataframe with columns
        type, category, <YYYY-MM>..., delta, is_new, pct_change, n_transactions
    Returns the top_n variances ranked by combined_score, descending.
    """
    month_cols = _month_columns(df)
    if len(month_cols) < 2:
        raise ValueError("Need at least 2 month columns to compute variance.")

    latest_month = month_cols[-1]
    prior_month = month_cols[-2]

    results: List[Variance] = []

    # Normalize materiality across categories using total absolute volume,
    # so one giant category doesn't automatically dominate every ranking.
    total_abs_volume = df[month_cols].abs().sum().sum() or 1.0

    for _, row in df.iterrows():
        series = row[month_cols].astype(float)
        mean = series.mean()
        std = series.std(ddof=0) or 1e-9  # avoid div by zero for flat series

        # Anomaly signal: scan every month, find the single most extreme one
        z_scores = (series - mean).abs() / std
        anomaly_month = z_scores.idxmax()
        anomaly_z = z_scores.max()

        # Trend signal: latest vs prior month, normalized by category's own volume
        latest_val = series[latest_month]
        prior_val = series[prior_month]
        latest_delta = latest_val - prior_val
        materiality = abs(latest_delta) / total_abs_volume * len(df)  # scaled so avg ~1.0

        # Decide which period is actually worth explaining:
        # if the anomaly month IS the latest month, they agree -> use it.
        # if anomaly is buried mid-series and is more extreme than the
        # latest-month move, flag the anomaly month instead (this is what
        # catches the "Gift spiked in September" case).
        latest_z = z_scores[latest_month]
        if anomaly_z > latest_z * 1.5 and anomaly_month != latest_month:
            flagged_period = anomaly_month
            flagged_value = series[anomaly_month]
            reason = "anomaly"
            combined = anomaly_z  # anomaly-driven ranking uses z-score directly
        else:
            flagged_period = latest_month
            flagged_value = latest_val
            reason = "trend"
            combined = materiality + latest_z * 0.5  # blend size + how unusual it is

        pct_change = row.get("pct_change")
        results.append(Variance(
            category=row["category"],
            type_=row["type"],
            flagged_period=flagged_period,
            flagged_value=float(flagged_value),
            baseline_mean=float(mean),
            baseline_std=float(std),
            materiality_score=float(materiality),
            anomaly_score=float(anomaly_z),
            combined_score=float(combined),
            latest_delta=float(latest_delta),
            latest_pct_change=float(pct_change) if pd.notna(pct_change) else None,
            reason=reason,
            series={k: float(v) for k, v in series.items()},
        ))

    results.sort(key=lambda v: v.combined_score, reverse=True)
    return results[:top_n]


if __name__ == "__main__":
    df = pd.read_csv("data/monthly_summary.csv")
    for v in compute_variances(df):
        print(f"{v.category:20s} | flagged={v.flagged_period} value={v.flagged_value:>8.1f} "
              f"| reason={v.reason:8s} | score={v.combined_score:6.2f} "
              f"| mean={v.baseline_mean:7.1f} std={v.baseline_std:6.1f}")
