# Financial Variance Analysis Agent

An agent that compares financial results across two periods, flags accounts
whose balance changed materially, drills into transaction-level data to find
the actual drivers, and produces an Excel report with an evidence-backed
explanation for each material account. It remembers what it learns across
runs, so later analyses build on prior findings instead of starting cold.

This is the current implementation, living in this `v2/` folder. The
original, prior single-file version this replaces is kept in `../legacy/`
for reference. Run all commands below from inside `v2/`.

## Setup

```
cd v2
pip install -r requirements.txt
export ANTHROPIC_API_KEY=...
```

## Input data

The agent reads **one CSV** containing all transactions (expenses and income
together), with columns:

```
date_time, type, category, account, amount, currency, tags
```

`type` must be `"expense"` or `"income"`. The file can live anywhere on disk --
pass its path with `--data`. A bundled demo file is at
`data/sample_transactions.csv` (built by merging the original
`Expenses_clean.csv` / `Income_clean.csv` and adding a `type` column; see
`scripts/refresh_kaggle_data.py` to regenerate it from the source Kaggle
dataset, which is optional and not used at runtime).

## Run

```
python agent.py --data data/sample_transactions.csv --dataset expenses
python agent.py --data ~/Desktop/transactions.csv --dataset both \
    --period-a 2025-10 --period-b 2025-11 "focus on seasonal categories"
```

- `--dataset` is `expenses`, `income`, or `both` (default `both`).
- `--period-a`/`--period-b` default to the two most recent periods found in the file.
- The trailing free-text note is optional and only nudges narrative tone/emphasis
  in the explanations -- it never changes which accounts or periods get analyzed.

## Output

An Excel workbook at `reports/variance_report_<dataset>_<period_a>_vs_<period_b>.xlsx`
with two sheets:

- **Summary** -- one row per account: totals for both periods, $ and % change, a
  **Material** flag (an account is material if its change exceeds 10% *and* a
  minimum BYN floor), and a short explanation (populated only for material
  accounts). Material accounts are highlighted and link to their detail.
- **Drill-Down** -- for each material account: which category drove the
  variance and how unusual that category's move is relative to its own
  history, which specific accounts/tags concentrated the change and their %
  share, the supporting transactions, and the full explanation.

## How it learns across runs

Two files update on the project side as a side effect of each run (regardless
of where `--data` points):

- `data/derived/monthly_account_summary.csv` -- a regenerated cache, safe to delete.
- `memory/context.json` -- accumulates a log of past findings and freeform
  business-context notes the agent writes about specific accounts/categories
  (e.g. "acct_2 behaves like a shared account"). Every run reads this first,
  so running the same comparison twice should produce a sharper, more specific
  second explanation than the first.

## Architecture

```
agent.py             CLI, orchestration (which accounts are material), per-account LLM loop
tools.py             @beta_tool wrappers exposed to the Claude tool-use loop
analysis/
  data.py            CSV loading, period derivation, monthly summary
  account_variance.py  deterministic >10%-and-$-floor account materiality rule
  materiality.py     historical-volatility-aware category materiality scoring
  concentration.py   account/tag concentration analysis
report/
  excel_report.py    builds the Summary + Drill-Down workbook
memory/
  store.py           read/write memory/context.json
scripts/
  refresh_kaggle_data.py  optional data refresh, not on the run path
```
