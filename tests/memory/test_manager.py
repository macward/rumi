"""Tests for MemoryManager."""

from pathlib import Path
from unittest.mock import AsyncMock, Mock

import pytest

from miniclaw.memory import Fact, FactExtractor, MemoryManager, MemoryStore


@pytest.fixture
def store(tmp_path: Path) -> MemoryStore:
    """Create a MemoryStore with a temporary database."""
    db_path = tmp_path / "test_memory.db"
    store = MemoryStore(db_path)
    store.init_db()
    yield store
    store.close()


@pytest.fixture
def manager(store: MemoryStore) -> MemoryManager:
    """Create a MemoryManager with the test store."""
    return MemoryManager(store)


class TestMemoryManagerLoad:
    """Tests for loading facts."""

    def test_load_all_empty(self, manager: MemoryManager):
        """load_all returns empty list when no facts."""
        assert manager.load_all() == []

    def test_load_all_returns_facts(self, manager: MemoryManager, store: MemoryStore):
        """load_all returns all stored facts."""
        store.save_fact(Fact(key="nombre", value="Lucas"))
        store.save_fact(Fact(key="trabajo", value="developer"))

        facts = manager.load_all()
        assert len(facts) == 2
        keys = {f.key for f in facts}
        assert keys == {"nombre", "trabajo"}

    def test_load_all_delegates_to_store(self):
        """load_all delegates to store.get_all()."""
        mock_store = Mock(spec=MemoryStore)
        mock_store.get_all.return_value = [Fact(key="test", value="value")]

        manager = MemoryManager(mock_store)
        result = manager.load_all()

        mock_store.get_all.assert_called_once()
        assert len(result) == 1


class TestMemoryManagerFormat:
    """Tests for formatting facts for prompt injection."""

    def test_format_empty_returns_empty_string(self, manager: MemoryManager):
        """format_for_prompt returns empty string when no facts."""
        result = manager.format_for_prompt([])
        assert result == ""

    def test_format_single_fact(self, manager: MemoryManager):
        """format_for_prompt formats a single fact correctly."""
        facts = [Fact(key="nombre", value="Lucas")]
        result = manager.format_for_prompt(facts)

        assert "<memory>" in result
        assert "</memory>" in result
        assert "- nombre: Lucas" in result
        assert "Lo que sabés del usuario:" in result

    def test_format_multiple_facts(self, manager: MemoryManager):
        """format_for_prompt formats multiple facts."""
        facts = [
            Fact(key="nombre", value="Lucas"),
            Fact(key="trabajo", value="developer"),
            Fact(key="ubicacion", value="Buenos Aires"),
        ]
        result = manager.format_for_prompt(facts)

        assert "- nombre: Lucas" in result
        assert "- trabajo: developer" in result
        assert "- ubicacion: Buenos Aires" in result

    def test_format_structure(self, manager: MemoryManager):
        """format_for_prompt produces correct XML structure."""
        facts = [Fact(key="nombre", value="Lucas")]
        result = manager.format_for_prompt(facts)

        # Check the structure
        lines = result.strip().split("\n")
        assert lines[0] == "<memory>"
        assert lines[1] == "Lo que sabés del usuario:"
        assert lines[-1] == "</memory>"

    def test_format_preserves_values_with_special_chars(self, manager: MemoryManager):
        """format_for_prompt handles special characters in values."""
        facts = [
            Fact(key="proyecto", value="mini-claw (agente con Docker)"),
            Fact(key="stack", value="Python, TypeScript & React"),
        ]
        result = manager.format_for_prompt(facts)

        assert "mini-claw (agente con Docker)" in result
        assert "Python, TypeScript & React" in result


class TestMemoryManagerExtraction:
    """Tests for fact extraction."""

    @pytest.mark.asyncio
    async def test_no_extractor_returns_empty(self, manager: MemoryManager):
        """Without extractor, extract_from_conversation returns empty."""
        messages = [{"role": "user", "content": "Test"}]
        facts = await manager.extract_from_conversation(messages)
        assert facts == []

    @pytest.mark.asyncio
    async def test_extraction_calls_extractor(self, store: MemoryStore):
        """Extractor is called with messages."""
        mock_extractor = AsyncMock(spec=FactExtractor)
        mock_extractor.extract = AsyncMock(return_value=[])

        manager = MemoryManager(store, extractor=mock_extractor)
        messages = [{"role": "user", "content": "Test"}]
        await manager.extract_from_conversation(messages)

        mock_extractor.extract.assert_called_once_with(messages)

    @pytest.mark.asyncio
    async def test_extracted_facts_are_saved(self, store: MemoryStore):
        """Extracted facts are saved to store."""
        extracted = [
            Fact(key="nombre", value="Lucas"),
            Fact(key="trabajo", value="developer"),
        ]
        mock_extractor = AsyncMock(spec=FactExtractor)
        mock_extractor.extract = AsyncMock(return_value=extracted)

        manager = MemoryManager(store, extractor=mock_extractor)
        messages = [{"role": "user", "content": "Me llamo Lucas y soy developer"}]
        result = await manager.extract_from_conversation(messages)

        assert len(result) == 2
        # Verify saved to store
        all_facts = store.get_all()
        assert len(all_facts) == 2
        keys = {f.key for f in all_facts}
        assert keys == {"nombre", "trabajo"}

    @pytest.mark.asyncio
    async def test_empty_extraction_not_saved(self, store: MemoryStore):
        """Empty extraction doesn't call save."""
        mock_extractor = AsyncMock(spec=FactExtractor)
        mock_extractor.extract = AsyncMock(return_value=[])

        manager = MemoryManager(store, extractor=mock_extractor)
        messages = [{"role": "user", "content": "Hola"}]
        result = await manager.extract_from_conversation(messages)

        assert result == []
        assert store.get_all() == []


class TestMemoryManagerExport:
    """Tests for module exports."""

    def test_exported_from_package(self):
        """MemoryManager is exported from memory package."""
        from miniclaw.memory import MemoryManager as ExportedManager

        assert ExportedManager is MemoryManager
