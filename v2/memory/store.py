"""Read/write memory/context.json -- the agent's cross-run business-context memory."""

import json
import os
import tempfile
from typing import Optional

MEMORY_PATH = os.path.join(os.path.dirname(os.path.dirname(os.path.abspath(__file__))), "memory", "context.json")


def read_context(path: str = MEMORY_PATH) -> dict:
    """Load the full memory dict. Tolerates a missing file by returning the empty
    seed structure without writing anything."""
    if not os.path.isfile(path):
        return {"schema_version": 1, "runs": [], "notes": []}
    with open(path, "r") as f:
        return json.load(f)


def get_notes(
    dataset: Optional[str] = None,
    scope: Optional[str] = None,
    key: Optional[str] = None,
    path: str = MEMORY_PATH,
) -> list[dict]:
    """Filtered view over context["notes"]."""
    notes = read_context(path).get("notes", [])
    if dataset is not None:
        notes = [n for n in notes if n.get("dataset") == dataset]
    if scope is not None:
        notes = [n for n in notes if n.get("scope") == scope]
    if key is not None:
        notes = [n for n in notes if n.get("key") == key]
    return notes


def get_recent_runs(limit: int = 3, path: str = MEMORY_PATH) -> list[dict]:
    """The most recent `limit` run summaries, most recent first."""
    runs = read_context(path).get("runs", [])
    return list(reversed(runs))[:limit]


def _atomic_write(context: dict, path: str) -> None:
    directory = os.path.dirname(path) or "."
    os.makedirs(directory, exist_ok=True)
    fd, tmp_path = tempfile.mkstemp(dir=directory, prefix=".context_", suffix=".json.tmp")
    try:
        with os.fdopen(fd, "w") as f:
            json.dump(context, f, indent=2)
        os.replace(tmp_path, path)
    except BaseException:
        if os.path.exists(tmp_path):
            os.remove(tmp_path)
        raise


def append_run_summary(run_summary: dict, path: str = MEMORY_PATH) -> None:
    """Read-modify-write: append run_summary to context["runs"], write back atomically."""
    context = read_context(path)
    context.setdefault("runs", []).append(run_summary)
    _atomic_write(context, path)


def append_note(note: dict, path: str = MEMORY_PATH) -> None:
    """Read-modify-write: append note to context["notes"], write back atomically."""
    context = read_context(path)
    context.setdefault("notes", []).append(note)
    _atomic_write(context, path)
