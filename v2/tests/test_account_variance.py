import pandas as pd

from analysis.account_variance import compute_account_variance


def _txn(period, dataset, account, amount):
    return {"period": period, "dataset": dataset, "account": account, "amount": amount}


def test_flags_material_accounts_over_threshold_and_floor():
    df = pd.DataFrame([
        # acct_1: 100 -> 150, +50% and +50 BYN -> material
        _txn("2025-10", "expenses", "acct_1", 100.0),
        _txn("2025-11", "expenses", "acct_1", 150.0),
        # acct_2: 100 -> 105, +5% -> not material (below pct threshold)
        _txn("2025-10", "expenses", "acct_2", 100.0),
        _txn("2025-11", "expenses", "acct_2", 105.0),
        # acct_3: 10 -> 15, +50% but only +5 BYN -> not material (below $ floor)
        _txn("2025-10", "expenses", "acct_3", 10.0),
        _txn("2025-11", "expenses", "acct_3", 15.0),
    ])

    result = compute_account_variance(df, "expenses", "2025-10", "2025-11", pct_threshold=0.10, min_abs_change=20.0)
    flags = dict(zip(result["account"], result["is_material"]))

    assert flags["acct_1"] is True
    assert flags["acct_2"] is False
    assert flags["acct_3"] is False


def test_new_account_is_always_material_without_divide_by_zero():
    df = pd.DataFrame([
        _txn("2025-10", "expenses", "acct_1", 100.0),
        _txn("2025-11", "expenses", "acct_1", 100.0),
        _txn("2025-11", "expenses", "acct_2", 50.0),  # brand new this period
    ])

    result = compute_account_variance(df, "expenses", "2025-10", "2025-11")
    acct_2 = result[result["account"] == "acct_2"].iloc[0]

    assert bool(acct_2["is_material"]) is True
    assert pd.isna(acct_2["pct_change"])  # None coerces to NaN through the DataFrame
    assert acct_2["total_a"] == 0.0
    assert acct_2["total_b"] == 50.0
