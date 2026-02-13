"""Tests for memory data models."""

import pytest

from miniclaw.memory import Fact
from miniclaw.memory.models import Fact as FactFromModels


class TestFact:
    """Tests for the Fact dataclass."""

    def test_create_minimal(self):
        """Fact can be created with just key and value."""
        fact = Fact(key="nombre", value="Lucas")
        assert fact.key == "nombre"
        assert fact.value == "Lucas"

    def test_default_values(self):
        """Fact has correct default values."""
        fact = Fact(key="trabajo", value="desarrollador")
        assert fact.id is None
        assert fact.source == "auto"
        assert fact.created_at is None
        assert fact.updated_at is None

    def test_explicit_source(self):
        """Fact can be created with explicit source."""
        fact = Fact(key="preferencia", value="TypeScript", source="explicit")
        assert fact.source == "explicit"

    def test_with_all_fields(self):
        """Fact can be created with all fields."""
        fact = Fact(
            key="ubicacion",
            value="Buenos Aires",
            id=42,
            source="auto",
            created_at="2026-01-01T00:00:00",
            updated_at="2026-01-02T00:00:00",
        )
        assert fact.id == 42
        assert fact.created_at == "2026-01-01T00:00:00"
        assert fact.updated_at == "2026-01-02T00:00:00"

    def test_immutable(self):
        """Fact is immutable (frozen)."""
        fact = Fact(key="nombre", value="Lucas")
        with pytest.raises(AttributeError):
            fact.key = "otro"  # type: ignore[misc]

    def test_equality(self):
        """Facts with same values are equal."""
        fact1 = Fact(key="nombre", value="Lucas")
        fact2 = Fact(key="nombre", value="Lucas")
        assert fact1 == fact2

    def test_hashable(self):
        """Frozen dataclass is hashable."""
        fact = Fact(key="nombre", value="Lucas")
        # Should not raise
        hash(fact)
        # Can be used in sets
        facts_set = {fact}
        assert fact in facts_set

    def test_export_from_package(self):
        """Fact is exported from memory package."""
        assert Fact is FactFromModels
