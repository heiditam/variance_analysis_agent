"""
Stage C — Narrative Generator
==============================
Turns the structured output of Stage A (Variance) + Stage B (DrillResult)
+ Stage D (memory streak note) into the "what changed, why, what's
driving it" sentence.

Two modes:
  - render_template(): deterministic, no external calls, always works.
    This is the safe fallback for a live demo.
  - render_with_llm(): sends ONLY the computed stats (never raw
    transactions) to an LLM to phrase it more naturally. The LLM is
    given no room to invent numbers — it's told to use exactly the
    figures it's handed.

Judges care about "evidence-backed" — both modes cite the same
underlying numbers, the LLM just phrases it better.
"""

from __future__ import annotations
from typing import Optional
from variance_engine import Variance
from drill_down import DrillResult


def render_template(variance: Variance, drill: Optional[DrillResult], streak_note: Optional[str]) -> str:
    direction = "increased" if variance.latest_delta >= 0 else "decreased"
    pct = f"{variance.latest_pct_change:.0%}" if variance.latest_pct_change is not None else "an unclear amount"

    if variance.reason == "anomaly":
        headline = (
            f"{variance.category}: an unusual spike occurred in {variance.flagged_period} "
            f"(value {variance.flagged_value:,.0f}, vs. a typical month of "
            f"{variance.baseline_mean:,.0f} +/- {variance.baseline_std:,.0f})."
        )
    else:
        headline = (
            f"{variance.category} {direction} by {pct} in {variance.flagged_period} "
            f"({variance.latest_delta:+,.0f} vs. prior month)."
        )

    driver_sentence = ""
    if drill and drill.top_drivers:
        top = drill.top_drivers[0]
        new_flag = " (a new driver not seen last period)" if top.is_new else ""
        driver_sentence = (
            f" This was primarily driven by '{top.key}', which accounted for "
            f"{top.share_of_period:.0%} of the total{new_flag}."
        )
        if len(drill.top_drivers) > 1:
            others = ", ".join(f"'{d.key}' ({d.share_of_period:.0%})" for d in drill.top_drivers[1:])
            driver_sentence += f" Other contributors: {others}."
        if drill.txn_count and drill.prior_txn_count:
            if drill.txn_count != drill.prior_txn_count:
                driver_sentence += (
                    f" Transaction volume went from {drill.prior_txn_count} to {drill.txn_count} "
                    f"(avg size {drill.prior_avg_txn_size:,.0f} -> {drill.avg_txn_size:,.0f})."
                )

    streak_sentence = f" {streak_note}" if streak_note else ""

    return headline + driver_sentence + streak_sentence


def render_with_llm(variance: Variance, drill: Optional[DrillResult], streak_note: Optional[str],
                     call_llm_fn) -> str:
    """
    call_llm_fn: a function(prompt: str) -> str that hits your LLM of
    choice (Claude API, etc). Kept as an injected dependency so this
    module has no hard dependency on any particular SDK/key.
    """
    facts = {
        "category": variance.category,
        "type": variance.type_,
        "flagged_period": variance.flagged_period,
        "flagged_value": variance.flagged_value,
        "baseline_mean": variance.baseline_mean,
        "baseline_std": variance.baseline_std,
        "latest_delta": variance.latest_delta,
        "latest_pct_change": variance.latest_pct_change,
        "reason": variance.reason,
        "top_drivers": [
            {"key": d.key, "share_of_period": d.share_of_period, "is_new": d.is_new}
            for d in (drill.top_drivers if drill else [])
        ],
        "streak_note": streak_note,
    }
    prompt = (
        "You are a financial variance analyst. Using ONLY the facts in this JSON "
        "(do not invent any numbers not present here), write 1-2 concise sentences "
        "explaining what changed and why, in the style: "
        "'Revenue increased 18%, primarily driven by a 32% increase in enterprise "
        "accounts, with three customers accounting for 64% of the increase.'\n\n"
        f"FACTS: {facts}"
    )
    return call_llm_fn(prompt)
