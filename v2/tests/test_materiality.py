import pandas as pd

from analysis.materiality import compute_materiality


def _rows(category, period_amounts):
    return [{"category": category, "period": p, "amount": a} for p, a in period_amounts.items()]


def test_zscore_path_for_category_with_enough_history():
    history = {
        "2025-01": 100.0, "2025-02": 102.0, "2025-03": 98.0, "2025-04": 101.0,
        "2025-05": 99.0, "2025-06": 103.0, "2025-07": 97.0, "2025-08": 100.0,
    }
    rows = _rows("Food", history)
    rows += [{"category": "Food", "period": "2025-09", "amount": 100.0}]
    rows += [{"category": "Food", "period": "2025-10", "amount": 400.0}]
    df = pd.DataFrame(rows)

    result = compute_materiality(df, "2025-09", "2025-10")
    row = result[result["category"] == "Food"].iloc[0]

    assert row["history_n"] == 8
    assert row["materiality_method"] == "zscore"
    assert 0.0 < row["materiality_score"] <= 1.0
    assert row["abs_change"] == 300.0


def test_sparse_category_falls_back_to_robust_ratio_without_crashing():
    df = pd.DataFrame([
        {"category": "Fines", "period": "2025-09", "amount": 10.0},
        {"category": "Fines", "period": "2025-10", "amount": 40.0},
    ])

    result = compute_materiality(df, "2025-09", "2025-10", min_history_for_zscore=6)
    row = result[result["category"] == "Fines"].iloc[0]

    assert row["history_n"] == 0
    assert row["materiality_method"] == "robust_ratio"
    assert row["materiality_score"] == 30.0 / 40.0


def test_zero_stdev_history_falls_back_instead_of_dividing_by_zero():
    history = {f"2025-{m:02d}": 50.0 for m in range(1, 9)}  # perfectly flat history
    rows = _rows("Rent", history)
    rows += [{"category": "Rent", "period": "2025-09", "amount": 50.0}]
    rows += [{"category": "Rent", "period": "2025-10", "amount": 80.0}]
    df = pd.DataFrame(rows)

    result = compute_materiality(df, "2025-09", "2025-10")
    row = result[result["category"] == "Rent"].iloc[0]

    assert row["materiality_method"] == "robust_ratio"
    assert row["materiality_score"] == row["materiality_score"]  # not NaN
