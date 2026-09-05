import os

import pytest

from agent import find_default_data_file


def test_finds_file_directly_in_search_dir(tmp_path):
    target = tmp_path / "sample_transactions.csv"
    target.write_text("date_time,type,category,account,amount,currency,tags\n")

    result = find_default_data_file(filename="sample_transactions.csv", search_dir=str(tmp_path))

    assert result == str(target)


def test_finds_file_in_a_subfolder(tmp_path):
    subfolder = tmp_path / "Downloads" / "exports"
    subfolder.mkdir(parents=True)
    target = subfolder / "sample_transactions.csv"
    target.write_text("date_time,type,category,account,amount,currency,tags\n")

    result = find_default_data_file(filename="sample_transactions.csv", search_dir=str(tmp_path))

    assert result == str(target)


def test_raises_clear_error_when_not_found(tmp_path):
    with pytest.raises(FileNotFoundError, match="Could not find"):
        find_default_data_file(filename="sample_transactions.csv", search_dir=str(tmp_path))


def test_raises_clear_error_when_search_dir_missing(tmp_path):
    missing_dir = str(tmp_path / "does_not_exist")

    with pytest.raises(FileNotFoundError, match="Could not find"):
        find_default_data_file(filename="sample_transactions.csv", search_dir=missing_dir)
