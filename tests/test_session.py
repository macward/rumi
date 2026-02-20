"""Tests for session manager."""

import asyncio
import tempfile
import time
from pathlib import Path

import pytest

from rumi.session import SessionConfig, SessionManager, SessionState


@pytest.fixture
def temp_sessions_dir():
    """Create a temporary sessions directory."""
    with tempfile.TemporaryDirectory() as tmpdir:
        yield Path(tmpdir)


@pytest.fixture
def session_manager(temp_sessions_dir: Path) -> SessionManager:
    config = SessionConfig(sessions_dir=temp_sessions_dir, ttl_seconds=1.0)
    return SessionManager(config)


class TestSessionState:
    def test_create(self):
        state = SessionState(chat_id="test-123")
        assert state.chat_id == "test-123"
        assert state.messages == []
        assert state.context == {}

    def test_touch_updates_activity(self):
        state = SessionState(chat_id="test")
        old_time = state.last_activity
        time.sleep(0.01)
        state.touch()
        assert state.last_activity > old_time

    def test_is_expired(self):
        state = SessionState(chat_id="test")
        state.last_activity = time.time() - 100
        assert state.is_expired(ttl_seconds=50) is True
        assert state.is_expired(ttl_seconds=200) is False

    def test_serialization(self):
        state = SessionState(chat_id="test", container_id="abc")
        state.messages.append({"role": "user", "content": "hi"})
        state.context["key"] = "value"

        data = state.to_dict()
        restored = SessionState.from_dict(data)

        assert restored.chat_id == "test"
        assert restored.container_id == "abc"
        assert len(restored.messages) == 1
        assert restored.context["key"] == "value"


class TestSessionManager:
    def test_get_session_creates_new(self, session_manager: SessionManager):
        session = session_manager.get_session("new-chat")
        assert session.chat_id == "new-chat"

    def test_get_session_returns_same(self, session_manager: SessionManager):
        s1 = session_manager.get_session("chat")
        s2 = session_manager.get_session("chat")
        assert s1 is s2

    def test_add_message(self, session_manager: SessionManager):
        session_manager.add_message("chat", "user", "hello")
        session_manager.add_message("chat", "assistant", "hi!")

        messages = session_manager.get_messages("chat")
        assert len(messages) == 2
        assert messages[0]["content"] == "hello"
        assert messages[1]["role"] == "assistant"

    def test_context(self, session_manager: SessionManager):
        session_manager.set_context("chat", "key", "value")
        assert session_manager.get_context("chat", "key") == "value"
        assert session_manager.get_context("chat", "missing", "default") == "default"

    def test_get_messages_limit(self, session_manager: SessionManager):
        # Add 10 messages
        for i in range(10):
            session_manager.add_message("chat", "user", f"msg-{i}")

        # Get last 5
        messages = session_manager.get_messages("chat", limit=5)
        assert len(messages) == 5
        assert messages[0]["content"] == "msg-5"
        assert messages[4]["content"] == "msg-9"

    def test_get_messages_for_llm(self, session_manager: SessionManager):
        session_manager.add_message("chat", "user", "hello")
        session_manager.add_message("chat", "assistant", "hi!")

        # With for_llm=True, should exclude timestamp
        messages = session_manager.get_messages("chat", for_llm=True)
        assert len(messages) == 2
        assert messages[0] == {"role": "user", "content": "hello"}
        assert messages[1] == {"role": "assistant", "content": "hi!"}
        assert "timestamp" not in messages[0]

    def test_get_messages_limit_and_for_llm(self, session_manager: SessionManager):
        # Add 10 messages
        for i in range(10):
            session_manager.add_message("chat", "user", f"msg-{i}")

        # Get last 3 in LLM format
        messages = session_manager.get_messages("chat", limit=3, for_llm=True)
        assert len(messages) == 3
        assert messages[0] == {"role": "user", "content": "msg-7"}
        assert "timestamp" not in messages[0]

    def test_get_messages_limit_zero_returns_empty(self, session_manager: SessionManager):
        session_manager.add_message("chat", "user", "hello")
        messages = session_manager.get_messages("chat", limit=0)
        assert messages == []

    def test_get_messages_limit_negative_returns_empty(self, session_manager: SessionManager):
        session_manager.add_message("chat", "user", "hello")
        messages = session_manager.get_messages("chat", limit=-5)
        assert messages == []

    def test_get_messages_limit_exceeds_count(self, session_manager: SessionManager):
        # Add only 3 messages
        for i in range(3):
            session_manager.add_message("chat", "user", f"msg-{i}")

        # Request 100, should get all 3
        messages = session_manager.get_messages("chat", limit=100)
        assert len(messages) == 3

    def test_get_messages_empty_history(self, session_manager: SessionManager):
        messages = session_manager.get_messages("chat")
        assert messages == []


@pytest.mark.asyncio
class TestConcurrency:
    async def test_acquire_release(self, session_manager: SessionManager):
        acquired, error = await session_manager.acquire("chat")
        assert acquired is True
        assert error is None

        session_manager.release("chat")

    async def test_busy_returns_message(self, session_manager: SessionManager):
        await session_manager.acquire("chat")

        # Try to acquire again
        acquired, error = await session_manager.acquire("chat")
        assert acquired is False
        assert "estoy trabajando" in error

        session_manager.release("chat")

    async def test_release_allows_reacquire(self, session_manager: SessionManager):
        await session_manager.acquire("chat")
        session_manager.release("chat")

        acquired, error = await session_manager.acquire("chat")
        assert acquired is True


@pytest.mark.asyncio
class TestPersistence:
    async def test_save_and_load(self, temp_sessions_dir: Path):
        config = SessionConfig(sessions_dir=temp_sessions_dir)
        manager1 = SessionManager(config)

        # Add data
        manager1.add_message("chat", "user", "hello")
        manager1.set_context("chat", "key", "value")
        await manager1.acquire("chat")
        manager1.release("chat")  # This saves

        # Create new manager and load
        manager2 = SessionManager(config)
        session = manager2.get_session("chat")

        assert len(session.messages) == 1
        assert session.context["key"] == "value"


@pytest.mark.asyncio
class TestCleanup:
    async def test_cleanup_expired(self, temp_sessions_dir: Path):
        config = SessionConfig(sessions_dir=temp_sessions_dir, ttl_seconds=0.1)
        manager = SessionManager(config)

        # Create sessions
        manager.get_session("session1")
        manager.get_session("session2")

        # Wait for expiry
        await asyncio.sleep(0.2)

        count = await manager.cleanup_expired()
        assert count == 2

    async def test_destroy_session(self, session_manager: SessionManager):
        session_manager.get_session("to-delete")
        session_manager.add_message("to-delete", "user", "hi")

        await session_manager.destroy_session("to-delete")

        # Session should be new/empty
        session = session_manager.get_session("to-delete")
        assert len(session.messages) == 0
