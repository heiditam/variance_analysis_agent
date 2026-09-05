import pytest

from agent import resolve_period_by_index

PERIODS = [f"2025-{m:02d}" for m in range(1, 12)]  # 2025-01 .. 2025-11, 11 periods


def test_resolves_first_and_last_index():
    assert resolve_period_by_index(PERIODS, 1) == "2025-01"
    assert resolve_period_by_index(PERIODS, 11) == "2025-11"


def test_resolves_middle_index():
    assert resolve_period_by_index(PERIODS, 6) == "2025-06"


def test_raises_clear_error_below_range():
    with pytest.raises(ValueError, match="out of range"):
        resolve_period_by_index(PERIODS, 0)


def test_raises_clear_error_above_range():
    with pytest.raises(ValueError, match="out of range"):
        resolve_period_by_index(PERIODS, 12)
