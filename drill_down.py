"""
Stage B — Drill-Down Engine
===========================
Given a flagged (category, period) from Stage A, find the actual
transaction-level drivers: which tag/account contributed the most,
whether it's a new or recurring driver, and whether the change is
about transaction *size* or transaction *frequency*.

This is what turns "Job income went up" into "driven by tag_4,
which accounted for 44% of the total".
"""

from __future__ import annotations
import pandas as pd
from dataclasses import dataclass, field
from typing import List, Optional


@dataclass
class Driver:
    dimension: str          # which column we grouped by, e.g. "tags" or "account"
    key: str                # the specific value, e.g. "tag_4"
    amount: float
    share_of_period: float  # this driver's amount / total period amount
    is_new: bool            # did this key appear in the prior period at all?
    prior_amount: float     # what this same key contributed in the prior period


@dataclass
class DrillResult:
    category: str
    period: str
    total_amount: float
    prior_period: Optional[str]
    prior_total: Optional[float]
    txn_count: int
    prior_txn_count: Optional[int]
    avg_txn_size: float
    prior_avg_txn_size: Optional[float]
    top_drivers: List[Driver] = field(default_factory=list)


def _prior_period(period: str) -> str:
    """2025-11 -> 2025-10, 2025-01 -> 2024-12."""
    year, month = map(int, period.split("-"))
    if month == 1:
        return f"{year - 1}-12"
    return f"{year}-{month - 1:02d}"


def drill_into(
    txns: pd.DataFrame,
    category: str,
    period: str,
    dimension: str = "tags",
    top_k: int = 3,
) -> DrillResult:
    """
    txns: transaction-level dataframe with at least
        category, period, amount, and the grouping `dimension` column
        (e.g. 'tags' or 'account').
    """
    prior = _prior_period(period)

    cur = txns[(txns["category"] == category) & (txns["period"] == period)]
    prev = txns[(txns["category"] == category) & (txns["period"] == prior)]

    total_amount = cur["amount"].sum()
    prior_total = prev["amount"].sum() if len(prev) else None
    txn_count = len(cur)
    prior_txn_count = len(prev) if len(prev) else None
    avg_txn_size = total_amount / txn_count if txn_count else 0.0
    prior_avg_txn_size = (prior_total / prior_txn_count) if prior_txn_count else None

    grouped_cur = cur.groupby(dimension)["amount"].sum().sort_values(ascending=False)
    grouped_prev = prev.groupby(dimension)["amount"].sum() if len(prev) else pd.Series(dtype=float)

    drivers: List[Driver] = []
    for key, amount in grouped_cur.head(top_k).items():
        prior_amount = float(grouped_prev.get(key, 0.0))
        drivers.append(Driver(
            dimension=dimension,
            key=str(key),
            amount=float(amount),
            share_of_period=float(amount / total_amount) if total_amount else 0.0,
            is_new=(key not in grouped_prev.index),
            prior_amount=prior_amount,
        ))

    return DrillResult(
        category=category,
        period=period,
        total_amount=float(total_amount),
        prior_period=prior if len(prev) else None,
        prior_total=float(prior_total) if prior_total is not None else None,
        txn_count=txn_count,
        prior_txn_count=prior_txn_count,
        avg_txn_size=float(avg_txn_size),
        prior_avg_txn_size=float(prior_avg_txn_size) if prior_avg_txn_size is not None else None,
        top_drivers=drivers,
    )


if __name__ == "__main__":
    txns = pd.read_csv("data/drill_transactions.csv")
    result = drill_into(txns, category="Job", period="2025-11", dimension="tags")
    print(f"Category={result.category} period={result.period}")
    print(f"  total={result.total_amount} prior_total={result.prior_total} "
          f"txn_count={result.txn_count} prior_txn_count={result.prior_txn_count}")
    print(f"  avg_txn_size={result.avg_txn_size:.1f} prior_avg={result.prior_avg_txn_size}")
    for d in result.top_drivers:
        print(f"  driver {d.key:8s} amount={d.amount:6.1f} share={d.share_of_period:.1%} "
              f"is_new={d.is_new} prior_amount={d.prior_amount}")
