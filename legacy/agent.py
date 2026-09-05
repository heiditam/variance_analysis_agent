"""
Financial variance analysis agent.

Downloads the "financial-transactions-dataset-expenses-and-income" Kaggle dataset,
then uses Claude (tool use / agentic loop) to compare periods, surface the most
meaningful variances, drill into the underlying transactions, and produce a
concise, evidence-backed explanation of what changed and why.

Requires:
    pip install kagglehub pandas anthropic
    export ANTHROPIC_API_KEY=...   (or `ant auth login`)
    Kaggle credentials configured (~/.kaggle/kaggle.json or KAGGLE_USERNAME/KAGGLE_KEY)
"""

import sys
from typing import Literal, Optional

import kagglehub
import pandas as pd
import anthropic
from anthropic import beta_tool

MODEL = "claude-opus-5"

# ---------------------------------------------------------------------------
# Data loading
# ---------------------------------------------------------------------------

def load_data() -> dict[str, pd.DataFrame]:
    path = kagglehub.dataset_download(
        "artemkabseu/financial-transactions-dataset-expenses-and-income"
    )
    frames = {}
    for name, filename in [("expenses", "Expenses_clean.csv"), ("income", "Income_clean.csv")]:
        df = pd.read_csv(f"{path}/{filename}", parse_dates=["date_time"])
        df["period"] = df["date_time"].dt.to_period("M").astype(str)
        frames[name] = df
    return frames


DATA = load_data()

Dataset = Literal["expenses", "income"]


def _df(dataset: Dataset) -> pd.DataFrame:
    return DATA[dataset]


# ---------------------------------------------------------------------------
# Tools
# ---------------------------------------------------------------------------

@beta_tool
def list_periods(dataset: Dataset) -> str:
    """List every period (YYYY-MM) available for a dataset, with its total amount
    and transaction count. Use this first to see what periods exist and to spot
    an overall trend before picking two periods to compare.

    Args:
        dataset: Which dataset to inspect, "expenses" or "income".
    """
    df = _df(dataset)
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
def compare_categories(dataset: Dataset, period_a: str, period_b: str) -> str:
    """Compare category-level totals between two periods and return the variance
    for every category, sorted by absolute BYN change (largest first). This is
    the primary tool for spotting the most meaningful variances between periods.

    Args:
        dataset: Which dataset to compare, "expenses" or "income".
        period_a: Baseline period, formatted "YYYY-MM".
        period_b: Comparison period, formatted "YYYY-MM".
    """
    df = _df(dataset)
    for p in (period_a, period_b):
        if p not in df["period"].values:
            return f"Error: period '{p}' not found. Call list_periods first."

    grouped = df[df["period"].isin([period_a, period_b])].groupby(["category", "period"])["amount"].agg(
        total="sum", count="count"
    ).reset_index()

    pivot_total = grouped.pivot(index="category", columns="period", values="total").fillna(0.0)
    pivot_count = grouped.pivot(index="category", columns="period", values="count").fillna(0).astype(int)

    a = pivot_total.get(period_a, pd.Series(0.0, index=pivot_total.index))
    b = pivot_total.get(period_b, pd.Series(0.0, index=pivot_total.index))
    ca = pivot_count.get(period_a, pd.Series(0, index=pivot_count.index))
    cb = pivot_count.get(period_b, pd.Series(0, index=pivot_count.index))

    diff = b - a

    rows = []
    for cat in diff.abs().sort_values(ascending=False).index:
        pct = "new" if a[cat] == 0 else ("gone" if b[cat] == 0 else f"{(b[cat] - a[cat]) / a[cat] * 100:+.1f}%")
        rows.append(
            f"{cat}: {period_a}={a[cat]:.2f} ({ca[cat]} txns) -> {period_b}={b[cat]:.2f} "
            f"({cb[cat]} txns), change={diff[cat]:+.2f} BYN ({pct})"
        )
    return "\n".join(rows) if rows else "No categories found for these periods."


@beta_tool
def get_transactions(
    dataset: Dataset,
    period: str,
    category: Optional[str] = None,
    min_amount: Optional[float] = None,
    top_n: int = 20,
) -> str:
    """Drill into individual transactions for a period (optionally filtered by
    category and/or a minimum amount), sorted by amount descending. Use this to
    find the specific transactions driving a variance flagged by compare_categories
    -- e.g. whether a change came from a few large transactions or many small ones.

    Args:
        dataset: Which dataset to query, "expenses" or "income".
        period: Period to inspect, formatted "YYYY-MM".
        category: Optional category to filter by (as returned by compare_categories).
        min_amount: Optional minimum transaction amount (BYN) to filter by.
        top_n: Maximum number of transactions to return (default 20).
    """
    df = _df(dataset)
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


TOOLS = [list_periods, compare_categories, get_transactions]

SYSTEM_PROMPT = """You are a financial analyst agent working over a personal \
expenses/income dataset (currency: BYN). Given a request to explain what changed \
between two periods, you must:

1. Use list_periods to see what periods are available if you don't already know.
2. Use compare_categories to identify the categories with the largest variances \
(by absolute BYN change, not just percentage -- a 500% change on 2 BYN is noise).
3. For the 2-4 most significant variances, use get_transactions to drill into the \
underlying transactions and determine the actual driver (e.g. one large one-off \
purchase, a sustained increase in transaction frequency, a new category of spending).
4. Produce a concise, evidence-backed explanation: state each meaningful variance, \
its magnitude, and cite the specific transaction(s) or pattern that explains it. \
Do not speculate beyond what the data shows. Skip categories whose variance is \
immaterial in absolute terms.

Keep the final explanation tight -- a short paragraph or bullet list per variance, \
not a full report."""


def run(request: str) -> None:
    client = anthropic.Anthropic()
    runner = client.beta.messages.tool_runner(
        model=MODEL,
        max_tokens=16000,
        system=SYSTEM_PROMPT,
        tools=TOOLS,
        messages=[{"role": "user", "content": request}],
    )

    final_text = None
    for message in runner:
        for block in message.content:
            if block.type == "tool_use":
                print(f"[tool call] {block.name}({block.input})")
            elif block.type == "text":
                final_text = block.text

    print("\n--- Analysis ---\n")
    print(final_text or "(no text response)")


if __name__ == "__main__":
    default_request = (
        "Compare the two most recent months of expenses and the two most recent "
        "months of income. Identify the most meaningful variances and explain "
        "what changed and why, with evidence from the underlying transactions."
    )
    request = " ".join(sys.argv[1:]) or default_request
    run(request)
