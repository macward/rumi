"""Tests for memory tools."""

from pathlib import Path

import pytest

from miniclaw.memory import Fact, ForgetTool, MemoryStore, RememberTool


@pytest.fixture
def store(tmp_path: Path) -> MemoryStore:
    """Create a MemoryStore with a temporary database."""
    db_path = tmp_path / "test_memory.db"
    store = MemoryStore(db_path)
    store.init_db()
    yield store
    store.close()


class TestRememberTool:
    """Tests for RememberTool."""

    def test_name(self, store: MemoryStore):
        """Tool name is 'remember'."""
        tool = RememberTool(store)
        assert tool.name == "remember"

    def test_has_description(self, store: MemoryStore):
        """Tool has a description."""
        tool = RememberTool(store)
        assert len(tool.description) > 0

    def test_parameters_schema(self, store: MemoryStore):
        """Tool has correct parameter schema."""
        tool = RememberTool(store)
        params = tool.parameters
        assert params["type"] == "object"
        assert "key" in params["properties"]
        assert "value" in params["properties"]
        assert params["required"] == ["key", "value"]

    @pytest.mark.asyncio
    async def test_saves_fact(self, store: MemoryStore):
        """Remember tool saves a fact."""
        tool = RememberTool(store)
        result = await tool.execute(key="nombre", value="Lucas")

        assert result.success
        assert "Recordado" in result.output
        assert "nombre" in result.output
        assert "Lucas" in result.output

        # Verify stored
        facts = store.get_all()
        assert len(facts) == 1
        assert facts[0].key == "nombre"
        assert facts[0].value == "Lucas"
        assert facts[0].source == "explicit"

    @pytest.mark.asyncio
    async def test_missing_key_fails(self, store: MemoryStore):
        """Remember fails without key."""
        tool = RememberTool(store)
        result = await tool.execute(value="Lucas")

        assert not result.success
        assert "required" in result.error.lower()

    @pytest.mark.asyncio
    async def test_missing_value_fails(self, store: MemoryStore):
        """Remember fails without value."""
        tool = RememberTool(store)
        result = await tool.execute(key="nombre")

        assert not result.success
        assert "required" in result.error.lower()

    @pytest.mark.asyncio
    async def test_empty_key_fails(self, store: MemoryStore):
        """Remember fails with empty key."""
        tool = RememberTool(store)
        result = await tool.execute(key="", value="Lucas")

        assert not result.success

    @pytest.mark.asyncio
    async def test_empty_value_fails(self, store: MemoryStore):
        """Remember fails with empty value."""
        tool = RememberTool(store)
        result = await tool.execute(key="nombre", value="")

        assert not result.success


class TestForgetTool:
    """Tests for ForgetTool."""

    def test_name(self, store: MemoryStore):
        """Tool name is 'forget'."""
        tool = ForgetTool(store)
        assert tool.name == "forget"

    def test_has_description(self, store: MemoryStore):
        """Tool has a description."""
        tool = ForgetTool(store)
        assert len(tool.description) > 0

    def test_parameters_schema(self, store: MemoryStore):
        """Tool has correct parameter schema."""
        tool = ForgetTool(store)
        params = tool.parameters
        assert params["type"] == "object"
        assert "key" in params["properties"]
        assert params["required"] == ["key"]

    @pytest.mark.asyncio
    async def test_deletes_facts(self, store: MemoryStore):
        """Forget tool deletes facts by key."""
        # Setup
        store.save_fact(Fact(key="hobby", value="gaming"))
        store.save_fact(Fact(key="hobby", value="reading"))
        store.save_fact(Fact(key="nombre", value="Lucas"))

        tool = ForgetTool(store)
        result = await tool.execute(key="hobby")

        assert result.success
        assert "Olvidado" in result.output
        assert "2" in result.output

        # Verify only hobby deleted
        facts = store.get_all()
        assert len(facts) == 1
        assert facts[0].key == "nombre"

    @pytest.mark.asyncio
    async def test_single_fact_grammar(self, store: MemoryStore):
        """Forget uses correct grammar for single fact."""
        store.save_fact(Fact(key="nombre", value="Lucas"))

        tool = ForgetTool(store)
        result = await tool.execute(key="nombre")

        assert result.success
        assert "1 hecho" in result.output

    @pytest.mark.asyncio
    async def test_multiple_facts_grammar(self, store: MemoryStore):
        """Forget uses correct grammar for multiple facts."""
        store.save_fact(Fact(key="hobby", value="gaming"))
        store.save_fact(Fact(key="hobby", value="reading"))

        tool = ForgetTool(store)
        result = await tool.execute(key="hobby")

        assert result.success
        assert "2 hechos" in result.output

    @pytest.mark.asyncio
    async def test_nonexistent_key_succeeds(self, store: MemoryStore):
        """Forget succeeds even if key doesn't exist."""
        tool = ForgetTool(store)
        result = await tool.execute(key="nonexistent")

        assert result.success
        assert "No tenía nada guardado" in result.output

    @pytest.mark.asyncio
    async def test_missing_key_fails(self, store: MemoryStore):
        """Forget fails without key."""
        tool = ForgetTool(store)
        result = await tool.execute()

        assert not result.success
        assert "required" in result.error.lower()

    @pytest.mark.asyncio
    async def test_empty_key_fails(self, store: MemoryStore):
        """Forget fails with empty key."""
        tool = ForgetTool(store)
        result = await tool.execute(key="")

        assert not result.success


class TestToolExports:
    """Tests for module exports."""

    def test_remember_exported(self):
        """RememberTool is exported from memory package."""
        from miniclaw.memory import RememberTool as Exported

        assert Exported is RememberTool

    def test_forget_exported(self):
        """ForgetTool is exported from memory package."""
        from miniclaw.memory import ForgetTool as Exported

        assert Exported is ForgetTool
