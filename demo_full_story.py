"""
Demo: the full A -> B -> C -> D story on the case where we actually have
both summary AND transaction-level data (Job, Nov 2025), then simulates
3 consecutive monthly runs to show the memory/streak layer kick in.
"""
import pandas as pd
from variance_engine import compute_variances
from drill_down import drill_into
from narrative import render_template
from memory_store import MemoryStore
import os

summary_df = pd.read_csv("data/monthly_summary.csv")
txns_df = pd.read_csv("data/drill_transactions.csv")

# --- Single-period deep dive: Job, latest month (has real drill data) ---
variances = compute_variances(summary_df, top_n=5)
job_variance = next(v for v in variances if v.category == "Job")

# Force the "trend" (latest month) view for Job since that's what we have
# transaction data for, separately from whichever period Stage A flagged
# as the statistical anomaly (2025-06, no drill data available for it).
latest_period = "2025-11"
job_variance.flagged_period = latest_period
job_variance.flagged_value = job_variance.series[latest_period]
job_variance.reason = "trend"

drill = drill_into(txns_df, category="Job", period=latest_period, dimension="tags")

demo_mem_path = "memory/_demo_full_story.json"
if os.path.exists(demo_mem_path):
    os.remove(demo_mem_path)
store = MemoryStore(path=demo_mem_path)

print("=" * 70)
print("SINGLE RUN: Job, November 2025")
print("=" * 70)
store.record(drill)
streak = store.streak_note("Job")
print(render_template(job_variance, drill, streak))

print()
print("=" * 70)
print("SIMULATING 3 CONSECUTIVE MONTHLY RUNS (memory/intuition building)")
print("=" * 70)
os.remove(demo_mem_path)
store = MemoryStore(path=demo_mem_path)

# Simulate the agent having been run in Sep, Oct, Nov, each time tag_4
# being a growing driver -- this is what "learning across runs" looks like.
from drill_down import Driver, DrillResult
simulated_runs = [
    ("2025-09", "tag_4", 0.10),
    ("2025-10", "tag_4", 0.28),
    ("2025-11", "tag_4", 0.442),
]
for period, key, share in simulated_runs:
    d = DrillResult(
        category="Job", period=period, total_amount=800, prior_period=None,
        prior_total=None, txn_count=15, prior_txn_count=None,
        avg_txn_size=53, prior_avg_txn_size=None,
        top_drivers=[Driver(dimension="tags", key=key, amount=800 * share,
                             share_of_period=share, is_new=(period == "2025-09"),
                             prior_amount=0.0)],
    )
    store.record(d)
    note = store.streak_note("Job")
    print(f"[{period}] top driver = {key} ({share:.0%} of total) -> {note}")

os.remove(demo_mem_path)
