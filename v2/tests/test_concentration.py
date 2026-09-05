import pandas as pd

from analysis.concentration import compute_concentration


def _txn(period, category, account, tags, amount):
    return {"period": period, "category": category, "account": account, "tags": tags, "amount": amount}


def test_offsetting_contributor_excluded_from_top_contributors_and_reported_separately():
    df = pd.DataFrame([
        # Food overall: 100 -> 600 (change=+500), acct_1 drives it, acct_2 offsets a bit
        _txn("2025-10", "Food", "acct_1", "tag_1", 50.0),
        _txn("2025-11", "Food", "acct_1", "tag_1", 600.0),
        _txn("2025-10", "Food", "acct_2", "tag_2", 50.0),
        _txn("2025-11", "Food", "acct_2", "tag_2", 0.0),
    ])
    df = df[df["amount"] != 0.0]  # acct_2 has zero in Nov -> no row for that period

    result = compute_concentration(df, "Food", "2025-10", "2025-11", dimension="account", max_contributors=3)

    assert result["overall_change"] == 500.0
    assert result["direction"] == "increase"

    top_keys = [c["key"] for c in result["top_contributors"]]
    assert "acct_1" in top_keys
    assert "acct_2" not in top_keys

    offsetting_keys = [c["key"] for c in result["offsetting_contributors"]]
    assert "acct_2" in offsetting_keys
    assert result["offsetting_share"] is not None
    assert result["offsetting_share"] < 0


def test_overall_change_zero_returns_none_shares_without_crashing():
    df = pd.DataFrame([
        # Net-flat category: acct_1 up 50, acct_2 down 50 -> overall_change == 0
        _txn("2025-10", "Food", "acct_1", "tag_1", 100.0),
        _txn("2025-11", "Food", "acct_1", "tag_1", 150.0),
        _txn("2025-10", "Food", "acct_2", "tag_2", 100.0),
        _txn("2025-11", "Food", "acct_2", "tag_2", 50.0),
    ])

    result = compute_concentration(df, "Food", "2025-10", "2025-11")

    assert result["overall_change"] == 0.0
    assert result["top_contributors_share"] is None
    assert result["offsetting_share"] is None
    for c in result["contributors"]:
        assert c["share_of_overall_change"] is None


def test_new_category_total_a_zero_works():
    df = pd.DataFrame([
        _txn("2025-11", "Clothes", "acct_1", "tag_1", 80.0),
    ])
    result = compute_concentration(df, "Clothes", "2025-10", "2025-11")
    assert result["overall_change"] == 80.0
    assert result["contributors"][0]["total_a"] == 0.0


def test_account_scoping_restricts_computation():
    df = pd.DataFrame([
        _txn("2025-10", "Food", "acct_1", "tag_1", 100.0),
        _txn("2025-11", "Food", "acct_1", "tag_1", 200.0),
        _txn("2025-10", "Food", "acct_1", "tag_2", 100.0),
        _txn("2025-11", "Food", "acct_1", "tag_2", 100.0),
        _txn("2025-10", "Food", "acct_2", "tag_3", 500.0),
        _txn("2025-11", "Food", "acct_2", "tag_3", 500.0),
    ])

    result = compute_concentration(df, "Food", "2025-10", "2025-11", dimension="tags", account="acct_1")

    assert result["overall_change"] == 100.0  # only acct_1's change, acct_2 excluded
    assert result["account"] == "acct_1"
