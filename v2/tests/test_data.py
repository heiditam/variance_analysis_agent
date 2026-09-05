import pandas as pd

from analysis.data import derive_monthly_account_summary, materialize_summary, periods_available


def _fixture_df():
    return pd.DataFrame({
        "period": ["2025-01", "2025-01", "2025-02", "2025-02"],
        "dataset": ["expenses", "expenses", "expenses", "expenses"],
        "account": ["acct_1", "acct_1", "acct_1", "acct_2"],
        "category": ["Food", "Food", "Food", "Health"],
        "amount": [10.0, 20.0, 5.0, 100.0],
    })


def test_derive_monthly_account_summary_aggregates_correctly():
    summary = derive_monthly_account_summary(_fixture_df())

    jan_food = summary[(summary["period"] == "2025-01") & (summary["account"] == "acct_1") & (summary["category"] == "Food")]
    assert len(jan_food) == 1
    row = jan_food.iloc[0]
    assert row["total_amount"] == 30.0
    assert row["txn_count"] == 2
    assert row["avg_amount"] == 15.0

    feb_health = summary[(summary["period"] == "2025-02") & (summary["account"] == "acct_2")]
    assert feb_health.iloc[0]["total_amount"] == 100.0
    assert feb_health.iloc[0]["txn_count"] == 1


def test_materialize_summary_round_trips(tmp_path):
    summary = derive_monthly_account_summary(_fixture_df())
    out_path = materialize_summary(summary, out_dir=str(tmp_path))

    assert out_path == str(tmp_path / "monthly_account_summary.csv")
    reloaded = pd.read_csv(out_path)
    assert len(reloaded) == len(summary)
    assert set(reloaded.columns) == set(summary.columns)


def test_periods_available_sorted_unique():
    df = pd.DataFrame({"period": ["2025-02", "2025-01", "2025-02"]})
    assert periods_available(df) == ["2025-01", "2025-02"]
