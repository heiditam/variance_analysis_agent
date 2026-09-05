# Explain the Change — Maximor Hackathon (Money Ops track)

An agent that compares financial results across periods, drills into
transaction-level data to find real drivers, and produces a concise,
evidence-backed explanation — and gets smarter about a business's
patterns the more it's run.

## Architecture

```
monthly_summary.csv ──► Stage A: variance_engine.py ──► ranked Variance list
                              (what changed, how much it matters)
                                      │
drill_transactions.csv ──► Stage B: drill_down.py ◄──┘
                              (why: which tag/account/txn drove it)
                                      │
                                      ▼
                          Stage D: memory_store.py
                          (has this driver shown up before? streak?)
                                      │
                                      ▼
                          Stage C: narrative.py
                          (renders the final 1-2 sentence explanation)
                                      │
                                      ▼
                              agent.py (orchestrator)
                                      │
                                      ▼
                                  report.md
```

## Why this beats naive "sort by pct_change"

The sample summary CSV illustrates the trap directly: `Gift`'s
`pct_change` column (0.54) looks unremarkable, but the raw series has a
**3,489 spike in September** sitting in the middle of otherwise
~$100/month values. A pipeline that only looks at the latest-month delta
column would miss this entirely.

`variance_engine.py` fixes this by:
1. Scanning **every** month in the series for anomalies (z-score vs.
   that category's own mean/std), not just the last column.
2. Separately scoring **materiality** (dollar size, normalized by the
   category's own typical volume) so small-base % swings don't
   dominate the ranking.
3. Picking whichever signal (anomaly vs. latest-month trend) is more
   extreme, and flagging *that* period as the one worth explaining.

## Why this beats "just show the top transaction"

`drill_down.py` doesn't just find the single biggest transaction — it
groups by a dimension (tags, account, category — configurable) and
reports:
- **share of period**: what % of the total this driver represents
  (the "three customers = 64% of the increase" pattern from the brief)
- **is_new**: whether this driver existed in the prior period at all
- **frequency vs. size**: e.g. Job's Nov increase came from txn count
  going 5→20 while avg size dropped 134→39 — a materially different
  story than "the same customer paid more"

## The "iterates and learns" layer

`memory_store.py` is a flat JSON log of `(category, period) -> top
driver`. Each agent run appends to it, so by the second and third run
the agent can say things like:

> "This is the 3rd consecutive month 'tag_4' has been the top driver
> of Job income."

or flag when a previously-dominant driver disappears. This is cheap to
build (no DB needed for a demo) but is exactly what turns a one-shot
analysis into something that "builds intuition about the underlying
business" across runs, per the brief.

## Running it

```bash
pip install pandas
python3 agent.py --summary data/monthly_summary.csv \
                  --drill data/drill_transactions.csv \
                  --dimension tags \
                  --top 5
```

Run `python3 demo_full_story.py` for the fully worked example on the
sample data (Job/November, with the 3-run memory streak simulation).

Run any stage standalone for debugging:
```bash
python3 variance_engine.py   # Stage A only
python3 drill_down.py        # Stage B only
python3 memory_store.py      # Stage D only
```

## Swapping in a real LLM for phrasing (optional, Stage C)

`narrative.py` has `render_template()` (deterministic, no API needed —
safe for a live demo) and `render_with_llm()`, which takes an injected
`call_llm_fn(prompt) -> str` so you can wire up the Claude API (or
anything else) without narrative.py needing to know about any SDK. The
prompt explicitly instructs the model to use only the numbers it's
given — it never sees raw transactions, so it can't invent figures.

```python
def call_llm_fn(prompt: str) -> str:
    import anthropic
    client = anthropic.Anthropic()
    msg = client.messages.create(
        model="claude-sonnet-4-6",
        max_tokens=200,
        messages=[{"role": "user", "content": prompt}],
    )
    return msg.content[0].text

explanation = render_with_llm(variance, drill, streak_note, call_llm_fn)
```

## Extending for the real hackathon dataset

- If your real transaction CSV uses a different grouping column than
  `tags` (e.g. `merchant`, `counterparty`), just pass
  `--dimension merchant`.
- If categories don't line up 1:1 between the summary and drill files
  (naming mismatches), add a normalization step before `drill_into()`.
- `_prior_period()` in `drill_down.py` currently assumes monthly
  granularity (`YYYY-MM`) — adjust if your periods are weekly/quarterly.
- For multi-account rollups, drill on `account` as a second pass after
  `tags` to show both "what kind of transaction" and "which account"
  drove it.

## File guide

| File | Purpose |
|---|---|
| `variance_engine.py` | Stage A — rank variances, catch mid-series anomalies |
| `drill_down.py` | Stage B — find transaction-level drivers per flagged period |
| `narrative.py` | Stage C — render the final explanation (template or LLM) |
| `memory_store.py` | Stage D — persist driver history, detect streaks/shifts |
| `agent.py` | Orchestrator — CLI entrypoint, wires A→B→C→D together |
| `demo_full_story.py` | Worked example + memory simulation for the demo |
| `data/` | Sample CSVs (your provided data) |
| `memory/driver_history.json` | Persisted state, grows across runs |
