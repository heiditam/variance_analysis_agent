"""Optional: re-download the source Kaggle dataset and rebuild data/sample_transactions.csv.

Not on the main run path -- agent.py never imports this or touches the network.
Requires: pip install kagglehub, and Kaggle credentials configured
(~/.kaggle/kaggle.json or KAGGLE_USERNAME/KAGGLE_KEY).
"""

import os

import kagglehub
import pandas as pd

DATASET = "artemkabseu/financial-transactions-dataset-expenses-and-income"
OUT_PATH = os.path.join(os.path.dirname(os.path.dirname(os.path.abspath(__file__))), "data", "sample_transactions.csv")


def main() -> None:
    path = kagglehub.dataset_download(DATASET)

    expenses = pd.read_csv(os.path.join(path, "Expenses_clean.csv"))
    income = pd.read_csv(os.path.join(path, "Income_clean.csv"))
    expenses.insert(1, "type", "expense")
    income.insert(1, "type", "income")

    combined = pd.concat([expenses, income], ignore_index=True)
    combined = combined.sort_values("date_time").reset_index(drop=True)
    combined.to_csv(OUT_PATH, index=False)
    print(f"Wrote {len(combined)} rows to {OUT_PATH}")


if __name__ == "__main__":
    main()
