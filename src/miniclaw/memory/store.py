"""SQLite storage for memory facts."""

import sqlite3
from pathlib import Path

from .models import Fact


class MemoryStore:
    """Persistent storage for facts using SQLite.

    Facts are stored in a local SQLite database with deduplication
    based on (key, value) pairs.
    """

    def __init__(self, db_path: Path) -> None:
        """Initialize the store with a database path.

        Args:
            db_path: Path to the SQLite database file.
        """
        self.db_path = db_path
        self._conn: sqlite3.Connection | None = None

    def _get_connection(self) -> sqlite3.Connection:
        """Get or create the database connection."""
        if self._conn is None:
            self.db_path.parent.mkdir(parents=True, exist_ok=True)
            self._conn = sqlite3.connect(self.db_path)
            self._conn.row_factory = sqlite3.Row
        return self._conn

    def init_db(self) -> None:
        """Create the facts table if it doesn't exist."""
        conn = self._get_connection()
        conn.execute("""
            CREATE TABLE IF NOT EXISTS facts (
                id          INTEGER PRIMARY KEY AUTOINCREMENT,
                key         TEXT NOT NULL,
                value       TEXT NOT NULL,
                source      TEXT NOT NULL DEFAULT 'auto',
                created_at  TEXT NOT NULL DEFAULT (datetime('now')),
                updated_at  TEXT NOT NULL DEFAULT (datetime('now')),
                UNIQUE(key, value)
            )
        """)
        conn.execute("CREATE INDEX IF NOT EXISTS idx_facts_key ON facts(key)")
        conn.commit()

    def save_fact(self, fact: Fact) -> Fact:
        """Save a fact to the database.

        If a fact with the same (key, value) exists, updates its updated_at.

        Args:
            fact: The fact to save.

        Returns:
            The fact with its assigned id.
        """
        conn = self._get_connection()
        cursor = conn.execute(
            """
            INSERT INTO facts (key, value, source)
            VALUES (?, ?, ?)
            ON CONFLICT(key, value) DO UPDATE SET
                updated_at = datetime('now')
            RETURNING id, created_at, updated_at
            """,
            (fact.key, fact.value, fact.source),
        )
        row = cursor.fetchone()
        conn.commit()
        return Fact(
            id=row["id"],
            key=fact.key,
            value=fact.value,
            source=fact.source,
            created_at=row["created_at"],
            updated_at=row["updated_at"],
        )

    def save_facts(self, facts: list[Fact]) -> int:
        """Save multiple facts to the database.

        Args:
            facts: List of facts to save.

        Returns:
            Number of facts saved (including updates).
        """
        count = 0
        for fact in facts:
            self.save_fact(fact)
            count += 1
        return count

    def get_all(self) -> list[Fact]:
        """Get all facts from the database.

        Returns:
            List of all stored facts.
        """
        conn = self._get_connection()
        cursor = conn.execute(
            "SELECT id, key, value, source, created_at, updated_at FROM facts"
        )
        return [self._row_to_fact(row) for row in cursor.fetchall()]

    def get_by_key(self, key: str) -> list[Fact]:
        """Get facts filtered by key.

        Args:
            key: The key to filter by.

        Returns:
            List of facts with the given key.
        """
        conn = self._get_connection()
        cursor = conn.execute(
            "SELECT id, key, value, source, created_at, updated_at FROM facts WHERE key = ?",
            (key,),
        )
        return [self._row_to_fact(row) for row in cursor.fetchall()]

    def delete(self, fact_id: int) -> bool:
        """Delete a fact by its id.

        Args:
            fact_id: The id of the fact to delete.

        Returns:
            True if a fact was deleted, False otherwise.
        """
        conn = self._get_connection()
        cursor = conn.execute("DELETE FROM facts WHERE id = ?", (fact_id,))
        conn.commit()
        return cursor.rowcount > 0

    def delete_by_key(self, key: str) -> int:
        """Delete all facts with a given key.

        Args:
            key: The key of facts to delete.

        Returns:
            Number of facts deleted.
        """
        conn = self._get_connection()
        cursor = conn.execute("DELETE FROM facts WHERE key = ?", (key,))
        conn.commit()
        return cursor.rowcount

    def close(self) -> None:
        """Close the database connection."""
        if self._conn is not None:
            self._conn.close()
            self._conn = None

    def _row_to_fact(self, row: sqlite3.Row) -> Fact:
        """Convert a database row to a Fact."""
        return Fact(
            id=row["id"],
            key=row["key"],
            value=row["value"],
            source=row["source"],
            created_at=row["created_at"],
            updated_at=row["updated_at"],
        )
