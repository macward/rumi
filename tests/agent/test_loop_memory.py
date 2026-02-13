"""Tests for AgentLoop memory integration."""

from pathlib import Path
from unittest.mock import AsyncMock, Mock, patch

import pytest

from miniclaw.agent.loop import AgentLoop, AgentConfig, AgentResult, StopReason
from miniclaw.memory import Fact, FactExtractor, MemoryManager, MemoryStore
from miniclaw.tools import ToolRegistry


@pytest.fixture
def store(tmp_path: Path) -> MemoryStore:
    """Create a MemoryStore with a temporary database."""
    db_path = tmp_path / "test_memory.db"
    store = MemoryStore(db_path)
    store.init_db()
    yield store
    store.close()


@pytest.fixture
def memory_manager(store: MemoryStore) -> MemoryManager:
    """Create a MemoryManager with the test store."""
    return MemoryManager(store)


@pytest.fixture
def registry() -> ToolRegistry:
    """Create an empty tool registry."""
    return ToolRegistry()


class TestAgentLoopMemoryInit:
    """Tests for AgentLoop memory initialization."""

    def test_memory_default_none(self, registry: ToolRegistry):
        """Memory defaults to None."""
        with patch.dict("os.environ", {"GROQ_API_KEY": "test"}):
            loop = AgentLoop(registry)
            assert loop.memory is None

    def test_memory_can_be_set(
        self, registry: ToolRegistry, memory_manager: MemoryManager
    ):
        """Memory can be set via constructor."""
        with patch.dict("os.environ", {"GROQ_API_KEY": "test"}):
            loop = AgentLoop(registry, memory=memory_manager)
            assert loop.memory is memory_manager


class TestAgentLoopMemoryInjection:
    """Tests for memory injection into system prompt."""

    @pytest.mark.asyncio
    async def test_no_memory_manager_no_injection(self, registry: ToolRegistry):
        """Without memory manager, no memory block is added."""
        mock_client = AsyncMock()
        mock_response = Mock()
        mock_response.choices = [Mock()]
        mock_response.choices[0].message.tool_calls = None
        mock_response.choices[0].message.content = "Hello!"
        mock_client.chat.completions.create = AsyncMock(return_value=mock_response)

        loop = AgentLoop(registry, groq_client=mock_client)
        await loop.run("Hi")

        call_args = mock_client.chat.completions.create.call_args
        messages = call_args.kwargs["messages"]
        system_prompt = messages[0]["content"]

        assert "<memory>" not in system_prompt

    @pytest.mark.asyncio
    async def test_empty_memory_no_injection(
        self, registry: ToolRegistry, memory_manager: MemoryManager
    ):
        """With empty memory, no memory block is added."""
        mock_client = AsyncMock()
        mock_response = Mock()
        mock_response.choices = [Mock()]
        mock_response.choices[0].message.tool_calls = None
        mock_response.choices[0].message.content = "Hello!"
        mock_client.chat.completions.create = AsyncMock(return_value=mock_response)

        loop = AgentLoop(registry, groq_client=mock_client, memory=memory_manager)
        await loop.run("Hi")

        call_args = mock_client.chat.completions.create.call_args
        messages = call_args.kwargs["messages"]
        system_prompt = messages[0]["content"]

        assert "<memory>" not in system_prompt

    @pytest.mark.asyncio
    async def test_memory_injected_into_prompt(
        self, registry: ToolRegistry, memory_manager: MemoryManager, store: MemoryStore
    ):
        """With facts, memory block is added to system prompt."""
        store.save_fact(Fact(key="nombre", value="Lucas"))
        store.save_fact(Fact(key="trabajo", value="developer"))

        mock_client = AsyncMock()
        mock_response = Mock()
        mock_response.choices = [Mock()]
        mock_response.choices[0].message.tool_calls = None
        mock_response.choices[0].message.content = "Hello Lucas!"
        mock_client.chat.completions.create = AsyncMock(return_value=mock_response)

        loop = AgentLoop(registry, groq_client=mock_client, memory=memory_manager)
        await loop.run("Hi")

        call_args = mock_client.chat.completions.create.call_args
        messages = call_args.kwargs["messages"]
        system_prompt = messages[0]["content"]

        assert "<memory>" in system_prompt
        assert "- nombre: Lucas" in system_prompt
        assert "- trabajo: developer" in system_prompt
        assert "</memory>" in system_prompt

    @pytest.mark.asyncio
    async def test_memory_loaded_each_run(
        self, registry: ToolRegistry, memory_manager: MemoryManager, store: MemoryStore
    ):
        """Memory is loaded fresh on each run."""
        mock_client = AsyncMock()
        mock_response = Mock()
        mock_response.choices = [Mock()]
        mock_response.choices[0].message.tool_calls = None
        mock_response.choices[0].message.content = "Hello!"
        mock_client.chat.completions.create = AsyncMock(return_value=mock_response)

        loop = AgentLoop(registry, groq_client=mock_client, memory=memory_manager)

        # First run - no facts
        await loop.run("Hi")
        call_args = mock_client.chat.completions.create.call_args
        system_prompt_1 = call_args.kwargs["messages"][0]["content"]
        assert "<memory>" not in system_prompt_1

        # Add a fact
        store.save_fact(Fact(key="nombre", value="Lucas"))

        # Second run - should include the fact
        await loop.run("Hi again")
        call_args = mock_client.chat.completions.create.call_args
        system_prompt_2 = call_args.kwargs["messages"][0]["content"]
        assert "<memory>" in system_prompt_2
        assert "- nombre: Lucas" in system_prompt_2


class TestAgentLoopSessionEnd:
    """Tests for on_session_end hook."""

    @pytest.mark.asyncio
    async def test_no_memory_returns_empty(self, registry: ToolRegistry):
        """Without memory manager, on_session_end returns empty list."""
        mock_client = AsyncMock()
        loop = AgentLoop(registry, groq_client=mock_client)

        messages = [{"role": "user", "content": "Test"}]
        result = await loop.on_session_end(messages)

        assert result == []

    @pytest.mark.asyncio
    async def test_calls_memory_extraction(
        self, registry: ToolRegistry, store: MemoryStore
    ):
        """on_session_end calls memory extraction."""
        mock_extractor = AsyncMock(spec=FactExtractor)
        mock_extractor.extract = AsyncMock(
            return_value=[Fact(key="nombre", value="Lucas")]
        )
        memory_manager = MemoryManager(store, extractor=mock_extractor)

        mock_client = AsyncMock()
        loop = AgentLoop(registry, groq_client=mock_client, memory=memory_manager)

        messages = [{"role": "user", "content": "Me llamo Lucas"}]
        result = await loop.on_session_end(messages)

        assert len(result) == 1
        assert result[0].key == "nombre"
        mock_extractor.extract.assert_called_once_with(messages)

    @pytest.mark.asyncio
    async def test_saves_extracted_facts(
        self, registry: ToolRegistry, store: MemoryStore
    ):
        """on_session_end saves extracted facts to store."""
        mock_extractor = AsyncMock(spec=FactExtractor)
        mock_extractor.extract = AsyncMock(
            return_value=[
                Fact(key="nombre", value="Lucas"),
                Fact(key="trabajo", value="developer"),
            ]
        )
        memory_manager = MemoryManager(store, extractor=mock_extractor)

        mock_client = AsyncMock()
        loop = AgentLoop(registry, groq_client=mock_client, memory=memory_manager)

        messages = [{"role": "user", "content": "Me llamo Lucas y soy developer"}]
        await loop.on_session_end(messages)

        # Verify facts saved
        all_facts = store.get_all()
        assert len(all_facts) == 2
        keys = {f.key for f in all_facts}
        assert keys == {"nombre", "trabajo"}

    @pytest.mark.asyncio
    async def test_no_extractor_returns_empty(
        self, registry: ToolRegistry, memory_manager: MemoryManager
    ):
        """With memory but no extractor, returns empty list."""
        mock_client = AsyncMock()
        loop = AgentLoop(registry, groq_client=mock_client, memory=memory_manager)

        messages = [{"role": "user", "content": "Test"}]
        result = await loop.on_session_end(messages)

        assert result == []
