# Manual

## Part 1 — How the code works

### The pipeline, step by step

```
CSV file  →  load + derive summary  →  flag material accounts  →  per-account
                                                                    Claude drill-down
                                                                        ↓
reports/*.xlsx  ←  assemble workbook  ←  structured findings  ←  memory read/write
```

1. **Load** (`analysis/data.py`) — `load_transactions()` reads your one combined
   CSV, validates its columns, and tags every row with a `period` (`YYYY-MM`)
   and a `dataset` (`expenses`/`income`, derived from the `type` column).

2. **Derive the monthly summary** — `derive_monthly_account_summary()` groups
   the raw rows into a `period × account × category` table and
   `materialize_summary()` writes it to `data/derived/monthly_account_summary.csv`.
   This is just a cache/inspection artifact; the agent doesn't read it back —
   everything downstream works off the in-memory transaction dataframe.

3. **Flag material accounts** (`analysis/account_variance.py`) —
   `compute_account_variance()` sums each account's transactions in period A
   vs. period B and flags it **material** if the change is over **10%** *and*
   above a **minimum BYN floor** (default 20). This is a plain, transparent
   business rule — no LLM involved yet — and it decides which accounts get a
   full drill-down at all.

4. **For each material account, run Claude's tool-use loop**
   (`agent.py::analyze_material_account`) — one `tool_runner` conversation per
   account, using the tools in `tools.py`:
   - `get_business_context` — recall prior notes/findings about this account.
   - `compare_categories` — which category within the account moved the most
     (ranked by **dollar impact**, annotated with a **materiality score**: `zscore`
     means the move is statistically unusual vs. that category's own history,
     `robust_ratio` means there wasn't enough history to say so, only that it's large).
   - `analyze_concentration` — which specific tags concentrate that category's
     change (e.g. "1 tag caused 87% of this"), with any opposite-direction
     ("offsetting") contributor called out separately.
   - `get_transactions` — the actual transaction rows as evidence.
   - `record_insight` — save any new, durable fact about the account's/category's
     business meaning for future runs.

   The model's job is to produce a **short, evidence-backed explanation**.
   The **structured data** for the report (category table, concentration
   breakdown, transactions) is computed directly in Python
   (`agent.py::_build_drilldown`), not parsed from the model's text — so the
   report is always well-formed regardless of what the model says.

5. **Memory** (`memory/store.py`) — every run appends a summary of what it
   found, and any `record_insight` notes the model made, to
   `memory/context.json`. The *next* run's `get_business_context` call reads
   this back, so explanations get sharper over time instead of starting cold.

6. **Assemble the Excel workbook** (`report/excel_report.py`) —
   `build_excel_report()` writes two sheets: **Summary** (one row per account)
   and **Drill-Down** (one detailed section per material account),
   cross-linked with clickable hyperlinks.

### File map

| File | Role |
|---|---|
| `agent.py` | CLI, orchestration, per-account system prompt |
| `tools.py` | The functions Claude can call |
| `analysis/data.py` | CSV loading, period/dataset derivation |
| `analysis/account_variance.py` | The >10%-and-$-floor materiality gate |
| `analysis/materiality.py` | Category-level "is this unusual" scoring |
| `analysis/concentration.py` | Which accounts/tags drove a category's change |
| `memory/store.py` | Reads/writes `memory/context.json` |
| `report/excel_report.py` | Builds the `.xlsx` report |

This is the current implementation, in this `v2/` folder. Run every command
below from inside `v2/`. The original single-file version it replaced is
kept in `../legacy/` for reference only -- it isn't used by anything here.

---

## Part 2 — How to use it

### 1. Install and set your API key

```bash
cd v2
pip install -r requirements.txt
export ANTHROPIC_API_KEY=sk-...
```

### 2. Point it at a transactions CSV

Any CSV, anywhere on disk, with these columns:

```
date_time, type, category, account, amount, currency, tags
```

`type` must be `expense` or `income`. A ready-made demo file is at
`data/sample_transactions.csv`.

### 3. Run it

```bash
# Demo data, expenses only, most recent two months
python agent.py --data data/sample_transactions.csv --dataset expenses

# Your own file, both datasets, specific periods, with a steering note
python agent.py --data ~/Desktop/transactions.csv --dataset both \
    --period-a 2025-10 --period-b 2025-11 "focus on seasonal categories"
```

| Flag | Meaning | Default |
|---|---|---|
| `--data` | Path to the transactions CSV | *(required)* |
| `--dataset` | `expenses`, `income`, or `both` | `both` |
| `--period-a` / `--period-b` | Periods to compare (`YYYY-MM`) | the two most recent in the file |
| trailing text | Optional note to steer explanation tone | *(none)* |

While it runs, you'll see a console trace of each tool call Claude makes per
material account.

### 4. Read the output

Open `reports/variance_report_<dataset>_<period_a>_vs_<period_b>.xlsx`:

- **Summary sheet** — every account, its balance in both periods, $ and %
  change, whether it's flagged **Material**, and a short explanation. Click a
  material account's name to jump to its detail.
- **Drill-Down sheet** — for each material account: the category that drove
  it, the specific tags that concentrated the change and their % share, the
  supporting transactions, and the full explanation.

### 5. Run it again

`memory/context.json` now holds what the agent learned. Run the same command
again (or a different period pair) and the new report's explanations can
reference what it found last time — that's the "gets sharper over multiple
runs" behavior. Delete `memory/context.json` (or reset it to
`{"schema_version": 1, "runs": [], "notes": []}`) if you want to start clean.
