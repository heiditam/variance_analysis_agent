"""
Explain the Change — Agent Orchestrator
========================================
Ties together:
  Stage A (variance_engine)  -> what changed & how much it matters
  Stage B (drill_down)       -> why it changed, transaction-level drivers
  Stage C (narrative)        -> plain-English, evidence-backed explanation
  Stage D (memory_store)     -> continuity/intuition across repeated runs

Usage:
    python3 agent.py --summary data/monthly_summary.csv \
                      --drill data/drill_transactions.csv \
                      --dimension tags \
                      --top 5

Design notes for judges / teammates:
  - Every sentence in the output can be traced back to a specific
    number in the input CSVs — nothing is invented.
  - Re-running this script on the same drill_transactions.csv will
    start showing streak notes (Stage D) after 2+ periods of history
    accumulate in memory/driver_history.json.
  - dimension can be swapped ('tags' -> 'account') depending on what
    your transaction data actually breaks out by.
"""

from __future__ import annotations
import argparse
import pandas as pd

from variance_engine import compute_variances
from drill_down import drill_into
from narrative import render_template
from memory_store import MemoryStore


def run(summary_path: str, drill_path: str, dimension: str = "tags",
        top_n: int = 5, memory_path: str = "memory/driver_history.json") -> str:
    summary_df = pd.read_csv(summary_path)
    txns_df = pd.read_csv(drill_path)
    store = MemoryStore(path=memory_path)

    variances = compute_variances(summary_df, top_n=top_n)

    lines = ["# Explain the Change — Report\n"]
    for v in variances:
        drill = None
        has_txns = ((txns_df["category"] == v.category) & (txns_df["period"] == v.flagged_period)).any()
        if has_txns:
            drill = drill_into(txns_df, category=v.category, period=v.flagged_period, dimension=dimension)
            store.record(drill)

        streak_note = store.streak_note(v.category) if drill else None
        explanation = render_template(v, drill, streak_note)

        lines.append(f"## {v.category} ({v.type_})")
        lines.append(explanation)
        if not has_txns:
            lines.append("_(no transaction-level data available for this period — "
                          "summary-level signal only)_")
        lines.append("")

    return "\n".join(lines)


if __name__ == "__main__":
    parser = argparse.ArgumentParser(description="Explain the Change agent")
    parser.add_argument("--summary", default="data/monthly_summary.csv")
    parser.add_argument("--drill", default="data/drill_transactions.csv")
    parser.add_argument("--dimension", default="tags", help="column to group drivers by, e.g. tags or account")
    parser.add_argument("--top", type=int, default=5)
    parser.add_argument("--memory", default="memory/driver_history.json")
    args = parser.parse_args()

    report = run(args.summary, args.drill, args.dimension, args.top, args.memory)
    print(report)
