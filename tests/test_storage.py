"""Tests for the persistence layer in ``storage``."""

from datetime import datetime

import pytest

import storage
from schemas import Batch, LogEntry

NOW = datetime(2026, 1, 15, 12, 0)


def make_batch(batch_id: str = "FB-001", **overrides) -> Batch:
    fields = dict(
        batch_id=batch_id,
        name=f"Batch {batch_id}",
        volume_l=3.0,
        start_date=NOW,
        expected_duration_days=21,
        original_gravity=1.090,
    )
    fields.update(overrides)
    return Batch(**fields)


@pytest.fixture
def store(tmp_path):
    return storage.SqliteStore(tmp_path / "nested" / "test.db")


class TestSqliteStore:
    def test_creates_parent_directories(self, store):
        assert store.path.exists()

    def test_is_persistent(self, store):
        assert store.persistent is True

    def test_empty_store(self, store):
        assert store.load_batches() == []
        assert not store.is_seeded()

    def test_save_and_load_round_trip(self, store):
        batch = make_batch(
            log=[LogEntry(timestamp=NOW, message="Pitched yeast")]
        )
        store.save_batch(batch)
        assert store.load_batches() == [batch]

    def test_save_updates_in_place_and_keeps_order(self, store):
        store.save_batch(make_batch("FB-001"))
        store.save_batch(make_batch("FB-002"))
        updated = make_batch("FB-001", name="Renamed")
        store.save_batch(updated)
        loaded = store.load_batches()
        assert [b.batch_id for b in loaded] == ["FB-001", "FB-002"]
        assert loaded[0].name == "Renamed"

    def test_delete(self, store):
        store.save_batch(make_batch("FB-001"))
        store.save_batch(make_batch("FB-002"))
        store.delete_batch("FB-001")
        assert [b.batch_id for b in store.load_batches()] == ["FB-002"]

    def test_deleting_a_missing_batch_is_a_no_op(self, store):
        store.delete_batch("nope")

    def test_seeded_flag_survives_reopening(self, store):
        store.mark_seeded()
        assert store.is_seeded()
        assert storage.SqliteStore(store.path).is_seeded()

    def test_data_survives_reopening(self, store):
        store.save_batch(make_batch())
        assert len(storage.SqliteStore(store.path).load_batches()) == 1


class TestNullStore:
    def test_keeps_nothing(self):
        null = storage.NullStore()
        null.save_batch(make_batch())
        null.mark_seeded()
        assert null.persistent is False
        assert null.load_batches() == []
        assert null.is_seeded() is False
        null.delete_batch("FB-001")


class TestMakeStore:
    def test_demo_flag_selects_null_store(self):
        store = storage.make_store({"FERMENTOPS_DEMO": "1"})
        assert isinstance(store, storage.NullStore)

    def test_db_path_override(self, tmp_path):
        path = tmp_path / "custom.db"
        store = storage.make_store({"FERMENTOPS_DB": str(path)})
        assert isinstance(store, storage.SqliteStore)
        assert store.path == path

    def test_demo_flag_must_be_exactly_one(self, tmp_path):
        env = {"FERMENTOPS_DEMO": "0", "FERMENTOPS_DB": str(tmp_path / "x.db")}
        assert isinstance(storage.make_store(env), storage.SqliteStore)

    def test_browser_runtime_uses_null_store(self, monkeypatch):
        monkeypatch.setattr(storage.sys, "platform", "emscripten")
        assert isinstance(storage.make_store({}), storage.NullStore)
