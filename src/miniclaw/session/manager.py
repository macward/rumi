"""Session manager for per-user state and concurrency control."""

import asyncio
import json
import time
from dataclasses import dataclass, field, asdict
from pathlib import Path
from typing import Any

from ..sandbox import SandboxManager


@dataclass
class SessionState:
    """State for a single session."""

    chat_id: str
    created_at: float = field(default_factory=time.time)
    last_activity: float = field(default_factory=time.time)
    container_id: str | None = None
    messages: list[dict[str, Any]] = field(default_factory=list)
    context: dict[str, Any] = field(default_factory=dict)

    def touch(self) -> None:
        """Update last activity timestamp."""
        self.last_activity = time.time()

    def is_expired(self, ttl_seconds: float) -> bool:
        """Check if session has expired based on TTL."""
        return (time.time() - self.last_activity) > ttl_seconds

    def to_dict(self) -> dict[str, Any]:
        """Convert to dictionary for serialization."""
        return asdict(self)

    @classmethod
    def from_dict(cls, data: dict[str, Any]) -> "SessionState":
        """Create from dictionary."""
        return cls(**data)


@dataclass
class SessionConfig:
    """Configuration for session manager."""

    sessions_dir: Path | None = None
    ttl_seconds: float = 3600  # 1 hour
    cleanup_interval: float = 300  # 5 minutes

    def __post_init__(self) -> None:
        if self.sessions_dir is None:
            self.sessions_dir = Path.home() / ".miniclaw" / "sessions"


class SessionManager:
    """Manages session state, locks, and lifecycle."""

    BUSY_MESSAGE = "⏳ Ya estoy trabajando en algo. Espera a que termine."

    def __init__(
        self,
        config: SessionConfig | None = None,
        sandbox: SandboxManager | None = None,
    ) -> None:
        self.config = config or SessionConfig()
        self.sandbox = sandbox
        self._sessions: dict[str, SessionState] = {}
        self._locks: dict[str, asyncio.Lock] = {}
        self._busy: set[str] = set()
        self._cleanup_task: asyncio.Task | None = None

        # Ensure sessions directory exists
        assert self.config.sessions_dir is not None
        self.config.sessions_dir.mkdir(parents=True, exist_ok=True)

    def _session_file(self, chat_id: str) -> Path:
        """Get the file path for a session."""
        assert self.config.sessions_dir is not None
        return self.config.sessions_dir / f"{chat_id}.json"

    def _load_session(self, chat_id: str) -> SessionState | None:
        """Load session from disk."""
        path = self._session_file(chat_id)
        if not path.exists():
            return None

        try:
            with open(path, "r", encoding="utf-8") as f:
                data = json.load(f)
                return SessionState.from_dict(data)
        except (json.JSONDecodeError, KeyError):
            return None

    def _save_session(self, session: SessionState) -> None:
        """Save session to disk."""
        path = self._session_file(session.chat_id)
        with open(path, "w", encoding="utf-8") as f:
            json.dump(session.to_dict(), f, indent=2)

    def _delete_session_file(self, chat_id: str) -> None:
        """Delete session file from disk."""
        path = self._session_file(chat_id)
        if path.exists():
            path.unlink()

    def get_session(self, chat_id: str) -> SessionState:
        """Get or create a session for chat_id."""
        if chat_id not in self._sessions:
            # Try loading from disk
            session = self._load_session(chat_id)
            if session is None:
                session = SessionState(chat_id=chat_id)
            self._sessions[chat_id] = session

        return self._sessions[chat_id]

    def get_lock(self, chat_id: str) -> asyncio.Lock:
        """Get the lock for a chat_id."""
        if chat_id not in self._locks:
            self._locks[chat_id] = asyncio.Lock()
        return self._locks[chat_id]

    def is_busy(self, chat_id: str) -> bool:
        """Check if a session is currently processing a request."""
        return chat_id in self._busy

    async def acquire(self, chat_id: str) -> tuple[bool, str | None]:
        """Try to acquire the session for processing.

        Returns (acquired, error_message).
        If busy, returns (False, busy_message).
        """
        if self.is_busy(chat_id):
            return False, self.BUSY_MESSAGE

        lock = self.get_lock(chat_id)

        # Non-blocking acquire
        if lock.locked():
            return False, self.BUSY_MESSAGE

        await lock.acquire()
        self._busy.add(chat_id)

        # Touch session
        session = self.get_session(chat_id)
        session.touch()

        return True, None

    def release(self, chat_id: str) -> None:
        """Release the session after processing."""
        self._busy.discard(chat_id)

        lock = self._locks.get(chat_id)
        if lock and lock.locked():
            lock.release()

        # Save session
        if chat_id in self._sessions:
            self._save_session(self._sessions[chat_id])

    def add_message(self, chat_id: str, role: str, content: str) -> None:
        """Add a message to the session history."""
        session = self.get_session(chat_id)
        session.messages.append({
            "role": role,
            "content": content,
            "timestamp": time.time(),
        })
        session.touch()

    def get_messages(
        self,
        chat_id: str,
        limit: int = 20,
        for_llm: bool = False,
    ) -> list[dict[str, Any]]:
        """Get message history for a session.

        Args:
            chat_id: The session identifier.
            limit: Maximum number of messages to return (most recent).
            for_llm: If True, return only role and content (Groq API format).

        Returns:
            List of message dictionaries.
        """
        if limit <= 0:
            return []

        messages = self.get_session(chat_id).messages[-limit:]

        if for_llm:
            return [{"role": m["role"], "content": m["content"]} for m in messages]

        return messages

    def set_context(self, chat_id: str, key: str, value: Any) -> None:
        """Set a context value for the session."""
        session = self.get_session(chat_id)
        session.context[key] = value
        session.touch()

    def get_context(self, chat_id: str, key: str, default: Any = None) -> Any:
        """Get a context value from the session."""
        return self.get_session(chat_id).context.get(key, default)

    async def destroy_session(self, chat_id: str) -> None:
        """Destroy a session and its container."""
        # Remove from memory
        if chat_id in self._sessions:
            del self._sessions[chat_id]

        # Remove lock
        if chat_id in self._locks:
            del self._locks[chat_id]

        # Remove busy flag
        self._busy.discard(chat_id)

        # Delete file
        self._delete_session_file(chat_id)

        # Destroy container
        if self.sandbox:
            self.sandbox.destroy_container(chat_id)

    async def cleanup_expired(self) -> int:
        """Clean up expired sessions. Returns count of cleaned sessions."""
        count = 0
        chat_ids = list(self._sessions.keys())

        for chat_id in chat_ids:
            session = self._sessions.get(chat_id)
            if session and session.is_expired(self.config.ttl_seconds):
                await self.destroy_session(chat_id)
                count += 1

        return count

    async def _cleanup_loop(self) -> None:
        """Background task for periodic cleanup."""
        while True:
            try:
                await asyncio.sleep(self.config.cleanup_interval)
                await self.cleanup_expired()
            except asyncio.CancelledError:
                break
            except Exception:
                pass  # Log but continue

    def start_cleanup_task(self) -> None:
        """Start the background cleanup task."""
        if self._cleanup_task is None or self._cleanup_task.done():
            self._cleanup_task = asyncio.create_task(self._cleanup_loop())

    def stop_cleanup_task(self) -> None:
        """Stop the background cleanup task."""
        if self._cleanup_task and not self._cleanup_task.done():
            self._cleanup_task.cancel()
