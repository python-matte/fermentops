"""Persistence for FermentOps batches.

Two interchangeable stores share one interface:

* :class:`SqliteStore` keeps every batch as a JSON document in a local SQLite
  file (kept out of git). Used when running the app for real.
* :class:`NullStore` persists nothing. Used for the public demo
  (``FERMENTOPS_DEMO=1``) so visitors get a private sandbox and cannot touch
  anyone's real data.
"""

import os
import sys
from contextlib import contextmanager
from pathlib import Path
from typing import TYPE_CHECKING, Iterator, List, Mapping, Union

from schemas import Batch

if TYPE_CHECKING:  # sqlite3 is imported lazily; see SqliteStore._connect
    import sqlite3

DEFAULT_DB_PATH = Path(__file__).parent / "data" / "fermentops.db"

_SCHEMA = """
CREATE TABLE IF NOT EXISTS batches (
    batch_id TEXT PRIMARY KEY,
    data     TEXT NOT NULL
);
CREATE TABLE IF NOT EXISTS meta (
    key   TEXT PRIMARY KEY,
    value TEXT NOT NULL
);
"""


class SqliteStore:
    """Stores each :class:`Batch` as one JSON row, in creation order."""

    persistent = True

    def __init__(self, path: Union[str, Path]) -> None:
        self.path = Path(path)
        self.path.parent.mkdir(parents=True, exist_ok=True)
        with self._connect() as conn:
            conn.executescript(_SCHEMA)

    @contextmanager
    def _connect(self) -> "Iterator[sqlite3.Connection]":
        # Imported here, not at module level: the in-browser (Pyodide) build
        # never touches SQLite and does not ship the module by default.
        import sqlite3

        conn = sqlite3.connect(self.path)
        try:
            with conn:  # commit on success, roll back on error
                yield conn
        finally:
            conn.close()

    def load_batches(self) -> List[Batch]:
        with self._connect() as conn:
            rows = conn.execute(
                "SELECT data FROM batches ORDER BY rowid"
            ).fetchall()
        return [Batch.model_validate_json(data) for (data,) in rows]

    def save_batch(self, batch: Batch) -> None:
        """Insert or update a batch (an update keeps its position)."""
        with self._connect() as conn:
            conn.execute(
                "INSERT INTO batches (batch_id, data) VALUES (?, ?) "
                "ON CONFLICT(batch_id) DO UPDATE SET data = excluded.data",
                (batch.batch_id, batch.model_dump_json()),
            )

    def delete_batch(self, batch_id: str) -> None:
        with self._connect() as conn:
            conn.execute("DELETE FROM batches WHERE batch_id = ?", (batch_id,))

    def is_seeded(self) -> bool:
        with self._connect() as conn:
            row = conn.execute(
                "SELECT value FROM meta WHERE key = 'seeded'"
            ).fetchone()
        return row is not None

    def mark_seeded(self) -> None:
        with self._connect() as conn:
            conn.execute(
                "INSERT OR REPLACE INTO meta (key, value) "
                "VALUES ('seeded', '1')"
            )


class NullStore:
    """A store that keeps nothing; the session holds all data."""

    persistent = False

    def load_batches(self) -> List[Batch]:
        return []

    def save_batch(self, batch: Batch) -> None:
        pass

    def delete_batch(self, batch_id: str) -> None:
        pass

    def is_seeded(self) -> bool:
        return False

    def mark_seeded(self) -> None:
        pass


Store = Union[SqliteStore, NullStore]


def make_store(env: Mapping[str, str] = os.environ) -> Store:
    """Pick a store from the environment.

    ``FERMENTOPS_DEMO=1`` selects the non-persistent demo store, as does
    running in the browser (Pyodide / stlite, where there is no real disk to
    persist to). Otherwise the SQLite file at ``FERMENTOPS_DB`` (default
    ``data/fermentops.db``) is used.
    """
    if env.get("FERMENTOPS_DEMO") == "1" or sys.platform == "emscripten":
        return NullStore()
    return SqliteStore(env.get("FERMENTOPS_DB", DEFAULT_DB_PATH))
