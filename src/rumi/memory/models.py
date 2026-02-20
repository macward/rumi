"""Data models for the memory system."""

from dataclasses import dataclass


@dataclass(frozen=True)
class Fact:
    """A fact stored in memory about the user.

    Attributes:
        key: Category of the fact (e.g., 'nombre', 'trabajo', 'preferencia').
        value: The fact content in third person.
        id: Database ID, None for new facts.
        source: 'auto' for LLM-extracted, 'explicit' for user-requested.
        created_at: ISO timestamp when created.
        updated_at: ISO timestamp when last updated.
    """

    key: str
    value: str
    id: int | None = None
    source: str = "auto"
    created_at: str | None = None
    updated_at: str | None = None
