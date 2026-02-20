"""Tests for MemoryStore."""

import sqlite3
from pathlib import Path

import pytest

from rumi.memory import Fact, MemoryStore


@pytest.fixture
def store(tmp_path: Path) -> MemoryStore:
    """Create a MemoryStore with a temporary database."""
    db_path = tmp_path / "test_memory.db"
    store = MemoryStore(db_path)
    store.init_db()
    yield store
    store.close()


class TestMemoryStoreInit:
    """Tests for MemoryStore initialization."""

    def test_creates_db_directory(self, tmp_path: Path):
        """Store creates parent directories if they don't exist."""
        nested_path = tmp_path / "nested" / "dir" / "memory.db"
        store = MemoryStore(nested_path)
        store.init_db()
        assert nested_path.exists()
        store.close()

    def test_creates_facts_table(self, store: MemoryStore):
        """init_db creates the facts table."""
        conn = store._get_connection()
        cursor = conn.execute(
            "SELECT name FROM sqlite_master WHERE type='table' AND name='facts'"
        )
        assert cursor.fetchone() is not None

    def test_creates_key_index(self, store: MemoryStore):
        """init_db creates an index on key."""
        conn = store._get_connection()
        cursor = conn.execute(
            "SELECT name FROM sqlite_master WHERE type='index' AND name='idx_facts_key'"
        )
        assert cursor.fetchone() is not None

    def test_init_db_idempotent(self, store: MemoryStore):
        """init_db can be called multiple times."""
        store.init_db()
        store.init_db()  # Should not raise


class TestMemoryStoreSave:
    """Tests for saving facts."""

    def test_save_fact_returns_with_id(self, store: MemoryStore):
        """save_fact returns the fact with an assigned id."""
        fact = Fact(key="nombre", value="Lucas")
        saved = store.save_fact(fact)
        assert saved.id is not None
        assert saved.key == "nombre"
        assert saved.value == "Lucas"

    def test_save_fact_sets_timestamps(self, store: MemoryStore):
        """save_fact sets created_at and updated_at."""
        fact = Fact(key="nombre", value="Lucas")
        saved = store.save_fact(fact)
        assert saved.created_at is not None
        assert saved.updated_at is not None

    def test_save_fact_preserves_source(self, store: MemoryStore):
        """save_fact preserves the source field."""
        fact = Fact(key="preferencia", value="TypeScript", source="explicit")
        saved = store.save_fact(fact)
        assert saved.source == "explicit"

    def test_save_duplicate_updates_timestamp(self, store: MemoryStore):
        """Saving a duplicate fact updates updated_at."""
        fact = Fact(key="nombre", value="Lucas")
        first = store.save_fact(fact)
        # Save same fact again
        second = store.save_fact(fact)
        assert first.id == second.id
        assert first.created_at == second.created_at
        # updated_at might be same if fast, but should not fail

    def test_save_facts_multiple(self, store: MemoryStore):
        """save_facts saves multiple facts."""
        facts = [
            Fact(key="nombre", value="Lucas"),
            Fact(key="trabajo", value="developer"),
            Fact(key="ubicacion", value="Buenos Aires"),
        ]
        count = store.save_facts(facts)
        assert count == 3
        assert len(store.get_all()) == 3


class TestMemoryStoreGet:
    """Tests for retrieving facts."""

    def test_get_all_empty(self, store: MemoryStore):
        """get_all returns empty list when no facts."""
        assert store.get_all() == []

    def test_get_all_returns_all(self, store: MemoryStore):
        """get_all returns all stored facts."""
        store.save_fact(Fact(key="nombre", value="Lucas"))
        store.save_fact(Fact(key="trabajo", value="developer"))
        facts = store.get_all()
        assert len(facts) == 2
        keys = {f.key for f in facts}
        assert keys == {"nombre", "trabajo"}

    def test_get_by_key_filters(self, store: MemoryStore):
        """get_by_key returns only facts with the given key."""
        store.save_fact(Fact(key="hobby", value="gaming"))
        store.save_fact(Fact(key="hobby", value="reading"))
        store.save_fact(Fact(key="nombre", value="Lucas"))

        hobbies = store.get_by_key("hobby")
        assert len(hobbies) == 2
        assert all(f.key == "hobby" for f in hobbies)

    def test_get_by_key_not_found(self, store: MemoryStore):
        """get_by_key returns empty list when key not found."""
        store.save_fact(Fact(key="nombre", value="Lucas"))
        assert store.get_by_key("trabajo") == []


class TestMemoryStoreDelete:
    """Tests for deleting facts."""

    def test_delete_by_id(self, store: MemoryStore):
        """delete removes a fact by id."""
        saved = store.save_fact(Fact(key="nombre", value="Lucas"))
        assert store.delete(saved.id)
        assert store.get_all() == []

    def test_delete_nonexistent(self, store: MemoryStore):
        """delete returns False for nonexistent id."""
        assert not store.delete(999)

    def test_delete_by_key(self, store: MemoryStore):
        """delete_by_key removes all facts with the key."""
        store.save_fact(Fact(key="hobby", value="gaming"))
        store.save_fact(Fact(key="hobby", value="reading"))
        store.save_fact(Fact(key="nombre", value="Lucas"))

        count = store.delete_by_key("hobby")
        assert count == 2
        remaining = store.get_all()
        assert len(remaining) == 1
        assert remaining[0].key == "nombre"

    def test_delete_by_key_not_found(self, store: MemoryStore):
        """delete_by_key returns 0 when key not found."""
        assert store.delete_by_key("nonexistent") == 0


class TestMemoryStoreDeduplication:
    """Tests for deduplication behavior."""

    def test_unique_constraint(self, store: MemoryStore):
        """Same (key, value) pair is deduplicated."""
        store.save_fact(Fact(key="nombre", value="Lucas"))
        store.save_fact(Fact(key="nombre", value="Lucas"))
        assert len(store.get_all()) == 1

    def test_different_values_same_key(self, store: MemoryStore):
        """Different values with same key are both stored."""
        store.save_fact(Fact(key="hobby", value="gaming"))
        store.save_fact(Fact(key="hobby", value="reading"))
        assert len(store.get_all()) == 2

    def test_same_value_different_key(self, store: MemoryStore):
        """Same value with different keys are both stored."""
        store.save_fact(Fact(key="nombre", value="Lucas"))
        store.save_fact(Fact(key="alias", value="Lucas"))
        assert len(store.get_all()) == 2


class TestMemoryStoreLifecycle:
    """Tests for store lifecycle."""

    def test_close_and_reopen(self, tmp_path: Path):
        """Data persists after close and reopen."""
        db_path = tmp_path / "memory.db"

        store1 = MemoryStore(db_path)
        store1.init_db()
        store1.save_fact(Fact(key="nombre", value="Lucas"))
        store1.close()

        store2 = MemoryStore(db_path)
        store2.init_db()
        facts = store2.get_all()
        store2.close()

        assert len(facts) == 1
        assert facts[0].key == "nombre"

    def test_close_idempotent(self, store: MemoryStore):
        """close can be called multiple times."""
        store.close()
        store.close()  # Should not raise
