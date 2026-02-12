"""JSONL logging for observability."""

import json
import os
from dataclasses import asdict, dataclass, field
from datetime import datetime, timezone
from pathlib import Path
from typing import Any


@dataclass
class LogEntry:
    """A single log entry."""

    timestamp: str
    event: str
    chat_id: str | None = None
    container_id: str | None = None
    argv: list[str] | None = None
    duration_ms: float | None = None
    exit_code: int | None = None
    truncated: bool = False
    stopped_reason: str | None = None
    error: str | None = None
    extra: dict[str, Any] = field(default_factory=dict)

    def to_dict(self) -> dict[str, Any]:
        """Convert to dict, excluding None values."""
        data = asdict(self)
        return {k: v for k, v in data.items() if v is not None and v != {} and v != []}


class JSONLLogger:
    """Logger that writes structured logs in JSONL format."""

    def __init__(
        self,
        log_dir: str | Path | None = None,
        filename: str = "logs.jsonl",
        max_size_mb: float = 10.0,
    ) -> None:
        if log_dir is None:
            log_dir = Path.home() / ".miniclaw" / "logs"
        self.log_dir = Path(log_dir)
        self.log_dir.mkdir(parents=True, exist_ok=True)
        self.filename = filename
        self.max_size_bytes = int(max_size_mb * 1024 * 1024)
        self._current_chat_id: str | None = None

    @property
    def log_path(self) -> Path:
        """Current log file path."""
        return self.log_dir / self.filename

    def set_chat_id(self, chat_id: str | None) -> None:
        """Set the current chat_id for all subsequent logs."""
        self._current_chat_id = chat_id

    def _rotate_if_needed(self) -> None:
        """Rotate log file if it exceeds max size."""
        if not self.log_path.exists():
            return

        if self.log_path.stat().st_size >= self.max_size_bytes:
            timestamp = datetime.now(timezone.utc).strftime("%Y%m%d_%H%M%S")
            rotated_name = f"{self.log_path.stem}_{timestamp}.jsonl"
            self.log_path.rename(self.log_dir / rotated_name)

    def _write(self, entry: LogEntry) -> None:
        """Write a log entry to the file."""
        self._rotate_if_needed()

        with open(self.log_path, "a", encoding="utf-8") as f:
            f.write(json.dumps(entry.to_dict()) + "\n")

    def log(
        self,
        event: str,
        *,
        chat_id: str | None = None,
        container_id: str | None = None,
        argv: list[str] | None = None,
        duration_ms: float | None = None,
        exit_code: int | None = None,
        truncated: bool = False,
        stopped_reason: str | None = None,
        error: str | None = None,
        **extra: Any,
    ) -> None:
        """Log an event."""
        entry = LogEntry(
            timestamp=datetime.now(timezone.utc).isoformat(),
            event=event,
            chat_id=chat_id or self._current_chat_id,
            container_id=container_id,
            argv=argv,
            duration_ms=duration_ms,
            exit_code=exit_code,
            truncated=truncated,
            stopped_reason=stopped_reason,
            error=error,
            extra=extra if extra else {},
        )
        self._write(entry)

    def log_tool_call(
        self,
        tool_name: str,
        args: dict[str, Any],
        *,
        chat_id: str | None = None,
        container_id: str | None = None,
    ) -> None:
        """Log a tool call."""
        self.log(
            "tool_call",
            chat_id=chat_id,
            container_id=container_id,
            tool_name=tool_name,
            tool_args=args,
        )

    def log_tool_result(
        self,
        tool_name: str,
        success: bool,
        *,
        chat_id: str | None = None,
        container_id: str | None = None,
        duration_ms: float | None = None,
        exit_code: int | None = None,
        truncated: bool = False,
        error: str | None = None,
    ) -> None:
        """Log a tool result."""
        self.log(
            "tool_result",
            chat_id=chat_id,
            container_id=container_id,
            duration_ms=duration_ms,
            exit_code=exit_code,
            truncated=truncated,
            error=error if not success else None,
            success=success,
            tool_name=tool_name,
        )

    def log_command(
        self,
        argv: list[str],
        exit_code: int,
        duration_ms: float,
        *,
        chat_id: str | None = None,
        container_id: str | None = None,
        truncated: bool = False,
    ) -> None:
        """Log a command execution."""
        self.log(
            "command",
            chat_id=chat_id,
            container_id=container_id,
            argv=argv,
            exit_code=exit_code,
            duration_ms=duration_ms,
            truncated=truncated,
        )

    def log_agent_stop(
        self,
        reason: str,
        *,
        chat_id: str | None = None,
        turns: int | None = None,
    ) -> None:
        """Log when the agent loop stops."""
        self.log(
            "agent_stop",
            chat_id=chat_id,
            stopped_reason=reason,
            turns=turns,
        )


# Global logger instance
_logger: JSONLLogger | None = None


def get_logger() -> JSONLLogger:
    """Get the global logger instance."""
    global _logger
    if _logger is None:
        _logger = JSONLLogger()
    return _logger


def configure_logger(log_dir: str | Path | None = None, max_size_mb: float = 10.0) -> JSONLLogger:
    """Configure and return the global logger."""
    global _logger
    _logger = JSONLLogger(log_dir=log_dir, max_size_mb=max_size_mb)
    return _logger
