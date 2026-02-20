"""Integration tests for memory system."""

from pathlib import Path
from unittest.mock import AsyncMock, Mock, patch

import pytest

from rumi.memory import (
    Fact,
    FactExtractor,
    ForgetTool,
    MemoryManager,
    MemoryStore,
    RememberTool,
)
from rumi.agent.loop import AgentLoop
from rumi.tools import ToolRegistry


@pytest.fixture
def memory_system(tmp_path: Path):
    """Create a complete memory system for testing."""
    db_path = tmp_path / "test_memory.db"
    store = MemoryStore(db_path)
    store.init_db()

    mock_client = AsyncMock()
    extractor = FactExtractor(mock_client)
    manager = MemoryManager(store, extractor=extractor)

    yield {
        "store": store,
        "extractor": extractor,
        "manager": manager,
        "mock_client": mock_client,
    }

    store.close()


class TestMemorySystemIntegration:
    """Integration tests for the complete memory system."""

    def test_tools_registered_with_store(self, memory_system):
        """Memory tools can be registered and use the shared store."""
        store = memory_system["store"]

        registry = ToolRegistry()
        registry.register(RememberTool(store))
        registry.register(ForgetTool(store))

        # Verify tools registered
        tool_names = registry.list_tools()
        assert "remember" in tool_names
        assert "forget" in tool_names

    @pytest.mark.asyncio
    async def test_remember_and_forget_flow(self, memory_system):
        """Remember saves facts, forget removes them."""
        store = memory_system["store"]

        remember = RememberTool(store)
        forget = ForgetTool(store)

        # Remember some facts
        await remember.execute(key="nombre", value="Lucas")
        await remember.execute(key="hobby", value="gaming")
        await remember.execute(key="hobby", value="reading")

        assert len(store.get_all()) == 3

        # Forget hobbies
        result = await forget.execute(key="hobby")
        assert "2 hechos" in result.output

        # Only nombre remains
        remaining = store.get_all()
        assert len(remaining) == 1
        assert remaining[0].key == "nombre"

    @pytest.mark.asyncio
    async def test_memory_in_agent_loop(self, memory_system):
        """Memory is injected into agent loop."""
        store = memory_system["store"]
        manager = memory_system["manager"]

        # Pre-populate some facts
        store.save_fact(Fact(key="nombre", value="Lucas"))
        store.save_fact(Fact(key="trabajo", value="developer"))

        registry = ToolRegistry()

        # Mock LLM client
        mock_groq = AsyncMock()
        mock_response = Mock()
        mock_response.choices = [Mock()]
        mock_response.choices[0].message.tool_calls = None
        mock_response.choices[0].message.content = "Hola Lucas!"
        mock_groq.chat.completions.create = AsyncMock(return_value=mock_response)

        loop = AgentLoop(registry, groq_client=mock_groq, memory=manager)
        await loop.run("Hola")

        # Verify memory was injected
        call_args = mock_groq.chat.completions.create.call_args
        system_prompt = call_args.kwargs["messages"][0]["content"]
        assert "<memory>" in system_prompt
        assert "- nombre: Lucas" in system_prompt
        assert "- trabajo: developer" in system_prompt

    @pytest.mark.asyncio
    async def test_extraction_at_session_end(self, memory_system):
        """Facts are extracted and saved at session end."""
        store = memory_system["store"]
        manager = memory_system["manager"]
        mock_client = memory_system["mock_client"]

        # Setup extractor to return facts
        mock_response = Mock()
        mock_response.choices = [Mock()]
        mock_response.choices[0].message.content = (
            '{"facts": [{"key": "proyecto", "value": "rumi"}]}'
        )
        mock_client.chat.completions.create = AsyncMock(return_value=mock_response)

        registry = ToolRegistry()

        # Mock LLM for agent
        mock_groq = AsyncMock()
        agent_response = Mock()
        agent_response.choices = [Mock()]
        agent_response.choices[0].message.tool_calls = None
        agent_response.choices[0].message.content = "Ok!"
        mock_groq.chat.completions.create = AsyncMock(return_value=agent_response)

        loop = AgentLoop(registry, groq_client=mock_groq, memory=manager)

        # Simulate conversation
        messages = [
            {"role": "user", "content": "Estoy trabajando en rumi"},
            {"role": "assistant", "content": "Qué interesante!"},
        ]

        # End session
        facts = await loop.on_session_end(messages)

        assert len(facts) == 1
        assert facts[0].key == "proyecto"
        assert facts[0].value == "rumi"

        # Verify saved to store
        all_facts = store.get_all()
        assert len(all_facts) == 1

    @pytest.mark.asyncio
    async def test_full_lifecycle(self, memory_system):
        """Test complete memory lifecycle: load, use tools, extract."""
        store = memory_system["store"]
        manager = memory_system["manager"]
        mock_client = memory_system["mock_client"]

        # 1. Start with some existing facts
        store.save_fact(Fact(key="nombre", value="Lucas"))

        # 2. Use remember tool during conversation
        remember = RememberTool(store)
        await remember.execute(key="preferencia", value="TypeScript")

        # 3. Verify both facts exist
        assert len(store.get_all()) == 2

        # 4. Setup extraction
        mock_response = Mock()
        mock_response.choices = [Mock()]
        mock_response.choices[0].message.content = (
            '{"facts": [{"key": "trabajo", "value": "en startup"}]}'
        )
        mock_client.chat.completions.create = AsyncMock(return_value=mock_response)

        # 5. Extract at session end
        messages = [{"role": "user", "content": "Trabajo en una startup"}]
        await manager.extract_from_conversation(messages)

        # 6. All three facts should exist
        all_facts = store.get_all()
        assert len(all_facts) == 3
        keys = {f.key for f in all_facts}
        assert keys == {"nombre", "preferencia", "trabajo"}
