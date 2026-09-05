"""
Stage D — Memory / Iteration Layer
===================================
This is what lets the agent "build intuition over multiple runs" instead
of re-deriving everything from scratch every time.

After each run, we append a record per (category, period) noting who the
top driver was. On the *next* run, we can look back at this history and
say things like:

    "This is the 3rd consecutive month tag_4 has been the top driver
     of Job income."

or

    "Unlike the last 2 months, Public Transport's top driver changed
     from acct_1 to acct_2 this period."

Storage is a flat JSON file so it's trivial to inspect/demo — swap for
a real DB later if needed.
"""

from __future__ import annotations
import json
import os
from dataclasses import asdict
from typing import Optional
from drill_down import DrillResult


class MemoryStore:
    def __init__(self, path: str = "memory/driver_history.json"):
        self.path = path
        os.makedirs(os.path.dirname(path), exist_ok=True)
        if os.path.exists(path):
            with open(path) as f:
                self._data = json.load(f)
        else:
            self._data = {}  # category -> list of {period, top_driver, top_share}

    def record(self, drill: DrillResult) -> None:
        history = self._data.setdefault(drill.category, [])
        # avoid duplicate entries if the same period is re-run
        history = [h for h in history if h["period"] != drill.period]
        top = drill.top_drivers[0] if drill.top_drivers else None
        history.append({
            "period": drill.period,
            "top_driver": top.key if top else None,
            "top_share": top.share_of_period if top else None,
        })
        history.sort(key=lambda h: h["period"])
        self._data[drill.category] = history
        self._save()

    def streak_note(self, category: str) -> Optional[str]:
        """Return a human-readable note about driver continuity, if any."""
        history = self._data.get(category, [])
        if len(history) < 2:
            return None

        current = history[-1]["top_driver"]
        streak = 0
        for h in reversed(history):
            if h["top_driver"] == current:
                streak += 1
            else:
                break

        if streak >= 2:
            return f"This is the {streak}{_ordinal_suffix(streak)} consecutive month '{current}' has been the top driver."
        prev = history[-2]["top_driver"]
        if prev and prev != current:
            return f"The top driver changed from '{prev}' last period to '{current}' this period."
        return None

    def _save(self) -> None:
        with open(self.path, "w") as f:
            json.dump(self._data, f, indent=2)


def _ordinal_suffix(n: int) -> str:
    if 10 <= n % 100 <= 20:
        return "th"
    return {1: "st", 2: "nd", 3: "rd"}.get(n % 10, "th")


if __name__ == "__main__":
    # quick demo: simulate 3 runs to show the streak logic kick in
    from drill_down import Driver, DrillResult

    store = MemoryStore(path="memory/_demo_history.json")
    for period, driver_key in [("2025-09", "tag_4"), ("2025-10", "tag_4"), ("2025-11", "tag_4")]:
        d = DrillResult(
            category="Job", period=period, total_amount=800, prior_period=None,
            prior_total=None, txn_count=10, prior_txn_count=None,
            avg_txn_size=80, prior_avg_txn_size=None,
            top_drivers=[Driver(dimension="tags", key=driver_key, amount=350,
                                 share_of_period=0.44, is_new=False, prior_amount=300)],
        )
        store.record(d)
        print(period, "->", store.streak_note("Job"))
