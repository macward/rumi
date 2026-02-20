"""Conversation logger for detailed analysis.

Logs complete conversations to logs/ directory in the project root.
Each session gets its own file with all messages, tool calls, and responses.
"""

import json
import os
from datetime import datetime, timezone
from pathlib import Path
from typing import Any


class ConversationLogger:
    """Logs complete conversations for analysis."""

    def __init__(self, log_dir: Path | str | None = None) -> None:
        """Initialize the conversation logger.

        Args:
            log_dir: Directory to store logs. Defaults to ./logs in cwd.
        """
        if log_dir is None:
            # Default to logs/ in current working directory
            log_dir = Path.cwd() / "logs"
        self.log_dir = Path(log_dir)
        self.log_dir.mkdir(parents=True, exist_ok=True)
        self._current_file: Path | None = None
        self._session_id: str | None = None

    def _get_log_file(self, chat_id: str) -> Path:
        """Get log file path for a chat session."""
        date_str = datetime.now().strftime("%Y-%m-%d")
        return self.log_dir / f"{date_str}_{chat_id}.jsonl"

    def _write(self, chat_id: str, entry: dict[str, Any]) -> None:
        """Write an entry to the log file."""
        entry["timestamp"] = datetime.now(timezone.utc).isoformat()
        entry["chat_id"] = chat_id

        log_file = self._get_log_file(chat_id)
        with open(log_file, "a", encoding="utf-8") as f:
            f.write(json.dumps(entry, ensure_ascii=False) + "\n")

    def log_user_message(self, chat_id: str, content: str) -> None:
        """Log a user message."""
        self._write(chat_id, {
            "event": "user_message",
            "role": "user",
            "content": content,
        })

    def log_assistant_message(self, chat_id: str, content: str) -> None:
        """Log an assistant message (final response)."""
        self._write(chat_id, {
            "event": "assistant_message",
            "role": "assistant",
            "content": content,
        })

    def log_tool_call(
        self,
        chat_id: str,
        tool_name: str,
        tool_args: dict[str, Any],
        tool_call_id: str | None = None,
    ) -> None:
        """Log a tool call from the LLM."""
        self._write(chat_id, {
            "event": "tool_call",
            "tool_name": tool_name,
            "tool_args": tool_args,
            "tool_call_id": tool_call_id,
        })

    def log_tool_result(
        self,
        chat_id: str,
        tool_name: str,
        success: bool,
        output: str,
        error: str | None = None,
        tool_call_id: str | None = None,
        duration_ms: float | None = None,
    ) -> None:
        """Log the result of a tool execution."""
        entry = {
            "event": "tool_result",
            "tool_name": tool_name,
            "success": success,
            "output": output[:2000] if output else "",  # Truncate long outputs
            "tool_call_id": tool_call_id,
        }
        if error:
            entry["error"] = error
        if duration_ms is not None:
            entry["duration_ms"] = duration_ms

        self._write(chat_id, entry)

    def log_llm_request(
        self,
        chat_id: str,
        model: str,
        messages_count: int,
        has_tools: bool,
    ) -> None:
        """Log an LLM API request."""
        self._write(chat_id, {
            "event": "llm_request",
            "model": model,
            "messages_count": messages_count,
            "has_tools": has_tools,
        })

    def log_llm_response(
        self,
        chat_id: str,
        has_content: bool,
        tool_calls_count: int,
        finish_reason: str | None = None,
    ) -> None:
        """Log an LLM API response."""
        self._write(chat_id, {
            "event": "llm_response",
            "has_content": has_content,
            "tool_calls_count": tool_calls_count,
            "finish_reason": finish_reason,
        })

    def log_error(self, chat_id: str, error: str, context: str | None = None) -> None:
        """Log an error."""
        entry = {
            "event": "error",
            "error": error,
        }
        if context:
            entry["context"] = context
        self._write(chat_id, entry)

    def log_session_start(self, chat_id: str) -> None:
        """Log session start."""
        self._write(chat_id, {"event": "session_start"})

    def log_session_end(self, chat_id: str, reason: str = "normal") -> None:
        """Log session end."""
        self._write(chat_id, {"event": "session_end", "reason": reason})

    def log_agent_stop(
        self,
        chat_id: str,
        stop_reason: str,
        turns: int,
        tool_calls_total: int,
    ) -> None:
        """Log when agent loop stops."""
        self._write(chat_id, {
            "event": "agent_stop",
            "stop_reason": stop_reason,
            "turns": turns,
            "tool_calls_total": tool_calls_total,
        })


# Global instance
_conversation_logger: ConversationLogger | None = None


def get_conversation_logger(log_dir: Path | str | None = None) -> ConversationLogger:
    """Get or create the global conversation logger."""
    global _conversation_logger
    if _conversation_logger is None:
        _conversation_logger = ConversationLogger(log_dir=log_dir)
    return _conversation_logger


def reset_conversation_logger() -> None:
    """Reset the global conversation logger (for testing)."""
    global _conversation_logger
    _conversation_logger = None
