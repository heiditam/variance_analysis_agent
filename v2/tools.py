"""@beta_tool wrappers exposed to the Claude tool-use loop.

Data tools operate over a module-level dataframe set via set_data() before the
loop runs (the CSV path is a runtime CLI argument, so it can't be loaded at
import time). Memory tools read/write memory/context.json via memory/store.py.
"""

from datetime import datetime, timezone
from typing import Literal, Optional

import pandas as pd
from anthropic import beta_tool

from analysis.concentration import compute_concentration
from analysis.data import Dataset, filter_dataset
from analysis.materiality import compute_materiality
from memory import store as memory_store

_DF: Optional[pd.DataFrame] = None

Scope = Literal["account", "tags", "category", "general"]


def set_data(df: pd.DataFrame) -> None:
    """Register the loaded transactions dataframe for the tool functions to use."""
    global _DF
    _DF = df


def _dataset_df(dataset: Dataset, account: Optional[str] = None) -> pd.DataFrame:
    if _DF is None:
        raise RuntimeError("tools.set_data() must be called before running the tool loop.")
    df = filter_dataset(_DF, dataset)
    if account is not None:
        df = df[df["account"] == account]
    return df


@beta_tool
def list_periods(dataset: Dataset) -> str:
    """List every period (YYYY-MM) available for a dataset, with its total amount
    and transaction count. Use this first to see what periods exist and to spot
    an overall trend before picking two periods to compare.

    Args:
        dataset: Which dataset to inspect, "expenses" or "income".
    """
    df = _dataset_df(dataset)
    summary = (
        df.groupby("period")["amount"]
        .agg(total="sum", count="count")
        .reset_index()
        .sort_values("period")
    )
    lines = [
        f"{row.period}: total={row.total:.2f} BYN, transactions={row['count']}"
        for _, row in summary.iterrows()
    ]
    return "\n".join(lines)


@beta_tool
def compare_categories(
    dataset: Dataset,
    period_a: str,
    period_b: str,
    account: Optional[str] = None,
) -> str:
    """Compare category-level totals between two periods and return the variance
    for every category, ranked by absolute BYN impact. Each row also carries a
    materiality_score/materiality_method annotation -- "zscore" means the move is
    statistically unusual relative to that category's own history; "robust_ratio"
    means there wasn't enough history to say so, only that it's large. Use both:
    a big dollar change with "zscore" is your strongest signal; a big dollar
    change with "robust_ratio" is still worth citing but with that caveat.

    Args:
        dataset: Which dataset to compare, "expenses" or "income".
        period_a: Baseline period, formatted "YYYY-MM".
        period_b: Comparison period, formatted "YYYY-MM".
        account: Optional account to scope the comparison to (e.g. when drilling
            into why a specific account's balance changed). Omit for a
            whole-dataset comparison.
    """
    df = _dataset_df(dataset, account=account)
    for p in (period_a, period_b):
        if p not in df["period"].values:
            return f"Error: period '{p}' not found in this scope. Call list_periods first."

    materiality = compute_materiality(df, period_a, period_b)
    if materiality.empty:
        return "No categories found for these periods."

    lines = []
    for row in materiality.itertuples():
        pct = "new" if pd.isna(row.pct_change) else f"{row.pct_change * 100:+.1f}%"
        lines.append(
            f"{row.category}: {period_a}={row.total_a:.2f} -> {period_b}={row.total_b:.2f} "
            f"({pct}), change={row.abs_change:+.2f} BYN, materiality_score={row.materiality_score:.2f} "
            f"[{row.materiality_method}, history_n={row.history_n}]"
        )
    return "\n".join(lines)


@beta_tool
def analyze_concentration(
    dataset: Dataset,
    category: str,
    period_a: str,
    period_b: str,
    dimension: Literal["account", "tags"] = "account",
    account: Optional[str] = None,
    max_contributors: int = 3,
) -> str:
    """Find which specific accounts or transaction tags concentrate a category's
    change between two periods -- e.g. "2 of 3 accounts caused 74% of this
    increase". Contributors moving opposite to the overall trend are reported
    separately as offsetting, never counted as part of the "driving" share.

    Args:
        dataset: Which dataset to inspect, "expenses" or "income".
        category: The category to drill into (as returned by compare_categories).
        period_a: Baseline period, formatted "YYYY-MM".
        period_b: Comparison period, formatted "YYYY-MM".
        dimension: "account" to split by account, "tags" to split by transaction
            tag. Use "tags" when `account` is already set (splitting one account
            by account is meaningless).
        account: Optional account to restrict the whole analysis to first (e.g.
            once compare_categories has identified this category as the driver
            for one specific account).
        max_contributors: Maximum number of same-direction "driving" contributors
            to report (default 3).
    """
    df = _dataset_df(dataset)
    result = compute_concentration(
        df, category, period_a, period_b,
        dimension=dimension, account=account, max_contributors=max_contributors,
    )

    lines = [f"Category '{category}' overall change: {result['overall_change']:+.2f} BYN ({result['direction']})"]

    if result["top_contributors_share"] is not None:
        lines.append(f"Top {len(result['top_contributors'])} contributor(s) account for "
                      f"{result['top_contributors_share'] * 100:.1f}% of the change:")
    else:
        lines.append("Top contributors (overall change is ~0, shares undefined):")
    for c in result["top_contributors"]:
        share = "n/a" if c["share_of_overall_change"] is None else f"{c['share_of_overall_change'] * 100:.1f}%"
        lines.append(f"  {c['key']}: {c['total_a']:.2f} -> {c['total_b']:.2f} (delta={c['delta']:+.2f}, share={share})")

    if result["offsetting_contributors"]:
        offsetting_share = result["offsetting_share"]
        share_str = "n/a" if offsetting_share is None else f"{offsetting_share * 100:.1f}%"
        lines.append(f"Offsetting contributor(s) (moved opposite the overall trend, share={share_str}):")
        for c in result["offsetting_contributors"]:
            lines.append(f"  {c['key']}: {c['total_a']:.2f} -> {c['total_b']:.2f} (delta={c['delta']:+.2f})")

    return "\n".join(lines)


@beta_tool
def get_transactions(
    dataset: Dataset,
    period: str,
    category: Optional[str] = None,
    account: Optional[str] = None,
    min_amount: Optional[float] = None,
    top_n: int = 20,
) -> str:
    """Drill into individual transactions for a period (optionally filtered by
    category and/or account and/or a minimum amount), sorted by amount
    descending. Use this to cite the specific transactions that are the
    evidence for a variance/concentration finding.

    Args:
        dataset: Which dataset to query, "expenses" or "income".
        period: Period to inspect, formatted "YYYY-MM".
        category: Optional category to filter by.
        account: Optional account to filter by.
        min_amount: Optional minimum transaction amount (BYN) to filter by.
        top_n: Maximum number of transactions to return (default 20).
    """
    df = _dataset_df(dataset, account=account)
    subset = df[df["period"] == period]
    if category:
        subset = subset[subset["category"] == category]
    if min_amount is not None:
        subset = subset[subset["amount"] >= min_amount]
    if subset.empty:
        return "No transactions match this filter."

    subset = subset.sort_values("amount", ascending=False).head(top_n)
    lines = [
        f"{r.date_time.date()} | {r.category} | {r.account} | {r.amount:.2f} BYN | tag={r.tags}"
        for r in subset.itertuples()
    ]
    return "\n".join(lines)


@beta_tool
def get_business_context(
    dataset: Optional[Dataset] = None,
    scope: Optional[Scope] = None,
    key: Optional[str] = None,
) -> str:
    """Retrieve prior notes and past run findings from memory. Call this FIRST,
    before any other tool, to see what you already know about this dataset's
    accounts/tags/categories from previous runs -- e.g. known shared accounts,
    known multi-tag-per-employer patterns -- so you don't re-derive or
    contradict prior findings.

    Args:
        dataset: Optional dataset to filter notes by ("expenses" or "income").
        scope: Optional note scope to filter by ("account", "tags", "category",
            or "general").
        key: Optional specific account/tag/category value to filter by.
    """
    notes = memory_store.get_notes(dataset=dataset, scope=scope, key=key)
    recent_runs = memory_store.get_recent_runs(limit=3)

    lines = []
    if notes:
        lines.append("Prior notes:")
        for n in notes:
            lines.append(f"- [{n.get('scope')}:{n.get('key') or '-'}] {n.get('note')}")
    else:
        lines.append("No prior notes recorded yet for this scope.")

    if recent_runs:
        lines.append("\nRecent run summaries:")
        for r in recent_runs:
            explanation = (r.get("final_explanation") or "")[:200]
            lines.append(
                f"- {r.get('timestamp', '?')} [{r.get('dataset', '?')} {r.get('account', '?')} "
                f"{r.get('period_a', '?')} vs {r.get('period_b', '?')}]: {explanation}"
            )

    return "\n".join(lines)


@beta_tool
def record_insight(
    scope: Scope,
    note: str,
    dataset: Optional[Dataset] = None,
    key: Optional[str] = None,
) -> str:
    """Persist a durable, reusable business-context insight for future runs to
    build on -- e.g. that an account behaves like a shared account, or that a
    category's tags represent something specific. Call this at the END of your
    analysis, once per genuinely new, reusable insight -- not for the numeric
    findings themselves, which are already logged automatically.

    Args:
        scope: What the note is about -- "account", "tags", "category", or
            "general".
        note: The freeform insight text.
        dataset: Optional dataset this note applies to ("expenses" or "income").
        key: Optional specific account/tag/category value the note is about.
    """
    entry = {
        "timestamp": datetime.now(timezone.utc).isoformat(),
        "scope": scope,
        "key": key,
        "dataset": dataset,
        "note": note,
    }
    memory_store.append_note(entry)
    return "Insight recorded."


TOOLS = [
    list_periods,
    compare_categories,
    analyze_concentration,
    get_transactions,
    get_business_context,
    record_insight,
]
