"""
Financial variance analysis agent.

Reads a local combined transactions CSV (expenses + income, distinguished by a
`type` column), deterministically flags accounts whose balance moved more than
a materiality threshold between two periods, then uses Claude (tool use /
agentic loop) to drill into each material account's underlying categories,
tags, and transactions to explain what changed and why. Assembles the results
into an Excel workbook (Summary + Drill-Down sheets).

Requires:
    pip install -r requirements.txt
    export ANTHROPIC_API_KEY=...   (or `ant auth login`)

Usage (run from inside this v2/ directory):
    python agent.py --dataset expenses
    python agent.py --data ~/Desktop/transactions.csv --dataset both \\
        --period-a 2025-10 --period-b 2025-11 "focus on seasonal categories"

If --data is omitted, the agent looks for a file named `sample_transactions.csv`
on your Desktop (~/Desktop) instead -- searching it and its subfolders.
"""

import argparse
import os
import shutil
import sys
from datetime import datetime, timezone
from typing import Optional

import anthropic
import pandas as pd

import tools
from analysis.account_variance import compute_account_variance
from analysis.data import derive_monthly_account_summary, load_transactions, materialize_summary, periods_available
from memory import store as memory_store
from report.excel_report import build_excel_report, short_explanation

MODEL = "claude-opus-5"

# Anchor generated artifacts to this file's own directory, not the caller's CWD,
# so `data/derived/` and `reports/` always land inside this project regardless
# of where `python agent.py` is invoked from.
BASE_DIR = os.path.dirname(os.path.abspath(__file__))
DERIVED_DIR = os.path.join(BASE_DIR, "data", "derived")
REPORTS_DIR = os.path.join(BASE_DIR, "reports")

DEFAULT_DATA_FILENAME = "sample_transactions.csv"
DESKTOP_DIR = os.path.expanduser("~/Desktop")


def find_default_data_file(filename: str = DEFAULT_DATA_FILENAME, search_dir: str = DESKTOP_DIR) -> str:
    """Locate `filename` on the Desktop when --data isn't given: check
    <search_dir>/<filename> directly first, then fall back to a recursive
    search of <search_dir> in case it's tucked in a subfolder. Raises
    FileNotFoundError with a clear message if nothing is found."""
    direct_path = os.path.join(search_dir, filename)
    if os.path.isfile(direct_path):
        return direct_path

    if os.path.isdir(search_dir):
        for root, _dirs, files in os.walk(search_dir):
            if filename in files:
                return os.path.join(root, filename)

    raise FileNotFoundError(
        f"Could not find '{filename}' on your Desktop ({search_dir}) or in any of its "
        f"subfolders. Either place the file there, or pass its location explicitly with --data."
    )


def resolve_period_by_index(all_periods: list[str], index: int) -> str:
    """Resolve a 1-indexed position (as typed by the user -- e.g. 1 for the
    first period available, 11 for the eleventh) to the actual "YYYY-MM"
    period string. Raises a clear ValueError if out of range."""
    if index < 1 or index > len(all_periods):
        raise ValueError(
            f"Period index {index} is out of range -- this data has {len(all_periods)} "
            f"period(s), numbered 1 to {len(all_periods)} ({all_periods[0]} .. {all_periods[-1]})."
        )
    return all_periods[index - 1]


def copy_report_to_desktop(report_path: str, desktop_dir: str = DESKTOP_DIR) -> Optional[str]:
    """Copy the generated report to the Desktop too, for easy access alongside
    the project's own reports/ folder. Returns the copied path, or None if the
    Desktop isn't writable (this never fails the run -- the report already
    exists safely under reports/ regardless)."""
    try:
        os.makedirs(desktop_dir, exist_ok=True)
        dest = os.path.join(desktop_dir, os.path.basename(report_path))
        shutil.copy2(report_path, dest)
        return dest
    except OSError as e:
        print(f"Warning: could not copy report to Desktop ({e}). It's still saved at {report_path}.")
        return None


SYSTEM_PROMPT_TEMPLATE = """You are a financial analyst agent. You have been asked to explain \
why the '{account}' account in the '{dataset}' dataset changed between {period_a} and {period_b}. \
Its total moved from {total_a:.2f} BYN to {total_b:.2f} BYN ({pct_change}), which has already been \
flagged as material -- your job is to explain WHY, grounded in evidence.

1. Call get_business_context(dataset="{dataset}", scope="account", key="{account}") first -- review \
prior notes/findings about this specific account before looking at any new numbers.
2. Call compare_categories(dataset="{dataset}", period_a="{period_a}", period_b="{period_b}", \
account="{account}") -- ranked by absolute BYN impact, with each category annotated by a \
materiality_method: "zscore" means the move is statistically unusual vs. that category's own \
history; "robust_ratio" means there wasn't enough history to call it unusual, only that it's large. \
Pick the category with the biggest real dollar impact as your primary driver, and cite the \
materiality_method as supporting color, not as the selection criterion.
3. For the top 1-2 categories by dollar impact, call analyze_concentration(dataset="{dataset}", category=..., \
period_a="{period_a}", period_b="{period_b}", account="{account}", dimension="tags") -- read the \
top-contributors share and any offsetting share. If an offsetting contributor exists, you must \
mention it rather than reporting a >100% share with no explanation.
4. Call get_transactions(dataset="{dataset}", period="{period_b}", category=..., account="{account}", \
top_n=5) to cite concrete transaction-level evidence.
5. Produce a SHORT final answer: one or two sentences, in the style "X changed by Y%, driven by Z, \
with N contributors accounting for W%". Do not speculate beyond what the data shows.
6. Call record_insight for any new, durable, reusable finding about this account's or category's \
business meaning (e.g. "acct_2 behaves like a shared account") -- not for the numeric findings \
themselves, which are logged automatically. Only call this if you learned something genuinely new \
and reusable; it's fine to skip it.

{note_block}
Keep your final text answer tight -- one or two sentences, not a report."""


def _pct_str(pct: Optional[float]) -> str:
    return "new" if pd.isna(pct) else f"{pct * 100:+.1f}%"


def analyze_material_account(df, dataset: str, account: str, period_a: str, period_b: str,
                              total_a: float, total_b: float, pct_change: Optional[float],
                              note: str) -> tuple[str, dict]:
    """Run the Claude tool-use loop scoped to one material account; returns
    (final_explanation_text, structured_drilldown_data). The structured data is
    computed directly in Python (not parsed from the model's prose) so the
    Excel Drill-Down sheet is always well-formed regardless of what the model says.
    """
    note_block = f"Additional context from the user: {note}\n" if note else ""
    system_prompt = SYSTEM_PROMPT_TEMPLATE.format(
        account=account, dataset=dataset, period_a=period_a, period_b=period_b,
        total_a=total_a, total_b=total_b, pct_change=_pct_str(pct_change), note_block=note_block,
    )

    client = anthropic.Anthropic()
    runner = client.beta.messages.tool_runner(
        model=MODEL,
        max_tokens=8000,
        system=system_prompt,
        tools=tools.TOOLS,
        messages=[{"role": "user", "content": f"Explain the variance in account {account}."}],
    )

    final_text = None
    for message in runner:
        for block in message.content:
            if block.type == "tool_use":
                print(f"  [tool call] {block.name}({block.input})")
            elif block.type == "text":
                final_text = block.text

    explanation = final_text or "(no explanation generated)"
    drilldown = _build_drilldown(df, dataset, account, period_a, period_b, explanation)
    return explanation, drilldown


def _build_drilldown(df, dataset: str, account: str, period_a: str, period_b: str,
                      full_explanation: str) -> dict:
    from analysis.concentration import compute_concentration
    from analysis.data import filter_dataset
    from analysis.materiality import compute_materiality

    account_df = filter_dataset(df, dataset)
    account_df = account_df[account_df["account"] == account]

    materiality = compute_materiality(account_df, period_a, period_b)
    category_table = materiality.head(5).to_dict("records") if not materiality.empty else []

    concentration = None
    transactions = []
    if category_table:
        top_category = category_table[0]["category"]
        dataset_df = filter_dataset(df, dataset)
        concentration = compute_concentration(
            dataset_df, top_category, period_a, period_b,
            dimension="tags", account=account, max_contributors=3,
        )

        txn_subset = account_df[
            (account_df["category"] == top_category) & (account_df["period"] == period_b)
        ].sort_values("amount", ascending=False).head(5)
        transactions = [
            {"date": r.date_time.date(), "category": r.category, "tags": r.tags, "amount": r.amount}
            for r in txn_subset.itertuples()
        ]

    return {
        "category_table": category_table,
        "concentration": concentration,
        "transactions": transactions,
        "full_explanation": full_explanation,
    }


def run(csv_path: Optional[str], dataset_arg: str, period_a: Optional[str], period_b: Optional[str],
        period_start: Optional[int], period_end: Optional[int], note: str) -> None:
    if csv_path is None:
        csv_path = find_default_data_file()
        print(f"--data not given -- using '{csv_path}' found on your Desktop.")

    df = load_transactions(csv_path)
    summary = derive_monthly_account_summary(df)
    materialize_summary(summary, out_dir=DERIVED_DIR)
    tools.set_data(df)

    all_periods = periods_available(df)
    if len(all_periods) < 2:
        print("Not enough periods in the data to compare.")
        return

    indexed = "  ".join(f"{i + 1}:{p}" for i, p in enumerate(all_periods))
    print(f"Available periods: {indexed}")

    if period_start is not None or period_end is not None:
        if period_start is None or period_end is None:
            raise ValueError("Both --period-start and --period-end must be given together.")
        period_a = resolve_period_by_index(all_periods, period_start)
        period_b = resolve_period_by_index(all_periods, period_end)
        print(f"Using period range {period_start}..{period_end} -> comparing {period_a} vs {period_b} "
              f"(all periods in between count as history for materiality scoring).")
    elif period_a is None or period_b is None:
        period_a, period_b = all_periods[-2], all_periods[-1]

    datasets = ["expenses", "income"] if dataset_arg == "both" else [dataset_arg]

    all_rows = []
    all_drilldowns = {}

    for ds in datasets:
        account_variance = compute_account_variance(df, ds, period_a, period_b)
        if account_variance.empty:
            continue

        key_variances = []
        for row in account_variance.itertuples():
            explanation = ""
            if row.is_material:
                print(f"[analyzing] {ds} / {row.account} (change={row.abs_change:+.2f} BYN)")
                full_explanation, drilldown = analyze_material_account(
                    df, ds, row.account, period_a, period_b,
                    row.total_a, row.total_b, row.pct_change, note,
                )
                all_drilldowns[(ds, row.account)] = drilldown
                explanation = short_explanation(full_explanation)
                key_variances.append({
                    "account": row.account,
                    "abs_change": row.abs_change,
                    "pct_change": None if pd.isna(row.pct_change) else row.pct_change,
                    "top_category": drilldown["category_table"][0]["category"] if drilldown["category_table"] else None,
                    "final_explanation": full_explanation,
                })

            all_rows.append({
                "dataset": ds,
                "account": row.account,
                "total_a": row.total_a,
                "total_b": row.total_b,
                "abs_change": row.abs_change,
                "pct_change": row.pct_change,
                "is_material": row.is_material,
                "explanation": explanation,
            })

        if key_variances:
            memory_store.append_run_summary({
                "timestamp": datetime.now(timezone.utc).isoformat(),
                "request": note or "(default periods)",
                "dataset": ds,
                "period_a": period_a,
                "period_b": period_b,
                "key_variances": key_variances,
            })

    out_path = build_excel_report(all_rows, all_drilldowns, period_a, period_b, dataset_arg, out_dir=REPORTS_DIR)
    print(f"\nReport written to {out_path}")

    desktop_copy_path = copy_report_to_desktop(out_path)
    if desktop_copy_path:
        print(f"Also copied to {desktop_copy_path}")


def _parse_args(argv: list[str]) -> argparse.Namespace:
    parser = argparse.ArgumentParser(description="Financial variance analysis agent.")
    parser.add_argument(
        "--data", default=None,
        help="Path to the combined transactions CSV. If omitted, searches your "
             f"Desktop (~/Desktop) for a file named '{DEFAULT_DATA_FILENAME}'.",
    )
    parser.add_argument("--dataset", choices=["expenses", "income", "both"], default="both")
    parser.add_argument("--period-a", dest="period_a", default=None, help="Baseline period, YYYY-MM.")
    parser.add_argument("--period-b", dest="period_b", default=None, help="Comparison period, YYYY-MM.")
    parser.add_argument(
        "--period-start", dest="period_start", type=int, default=None,
        help="Baseline period as a 1-indexed position instead of YYYY-MM (e.g. 1 for the "
             "earliest period available). Use together with --period-end.",
    )
    parser.add_argument(
        "--period-end", dest="period_end", type=int, default=None,
        help="Comparison period as a 1-indexed position instead of YYYY-MM (e.g. 11 for "
             "the eleventh period available). Use together with --period-start.",
    )
    parser.add_argument("note", nargs="*", help="Optional free-text note to steer narrative emphasis.")
    return parser.parse_args(argv)


if __name__ == "__main__":
    args = _parse_args(sys.argv[1:])
    run(args.data, args.dataset, args.period_a, args.period_b,
        args.period_start, args.period_end, " ".join(args.note))
