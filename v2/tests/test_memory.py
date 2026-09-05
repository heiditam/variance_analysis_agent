import os

from memory import store as memory_store


def test_append_run_summary_appends_not_overwrites(tmp_path):
    path = str(tmp_path / "context.json")

    memory_store.append_run_summary({"timestamp": "t1", "dataset": "expenses"}, path=path)
    memory_store.append_run_summary({"timestamp": "t2", "dataset": "income"}, path=path)

    context = memory_store.read_context(path=path)
    assert len(context["runs"]) == 2
    assert context["runs"][0]["timestamp"] == "t1"
    assert context["runs"][1]["timestamp"] == "t2"


def test_append_note_appends_not_overwrites(tmp_path):
    path = str(tmp_path / "context.json")

    memory_store.append_note({"scope": "account", "key": "acct_1", "note": "n1"}, path=path)
    memory_store.append_note({"scope": "account", "key": "acct_2", "note": "n2"}, path=path)

    context = memory_store.read_context(path=path)
    assert len(context["notes"]) == 2


def test_read_context_missing_file_returns_empty_seed_without_creating_file(tmp_path):
    path = str(tmp_path / "does_not_exist.json")

    context = memory_store.read_context(path=path)

    assert context == {"schema_version": 1, "runs": [], "notes": []}
    assert not os.path.exists(path)


def test_get_notes_filters_by_dataset_scope_and_key(tmp_path):
    path = str(tmp_path / "context.json")
    memory_store.append_note({"scope": "account", "key": "acct_1", "dataset": "expenses", "note": "a"}, path=path)
    memory_store.append_note({"scope": "category", "key": "Food", "dataset": "expenses", "note": "b"}, path=path)
    memory_store.append_note({"scope": "account", "key": "acct_1", "dataset": "income", "note": "c"}, path=path)

    result = memory_store.get_notes(dataset="expenses", scope="account", key="acct_1", path=path)

    assert len(result) == 1
    assert result[0]["note"] == "a"
