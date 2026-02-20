"""Tests for JSONL logging."""

import json
import tempfile
from pathlib import Path

import pytest

from rumi.logging import JSONLLogger, LogEntry


@pytest.fixture
def temp_log_dir():
    """Create a temporary directory for logs."""
    with tempfile.TemporaryDirectory() as tmpdir:
        yield Path(tmpdir)


@pytest.fixture
def logger(temp_log_dir: Path) -> JSONLLogger:
    return JSONLLogger(log_dir=temp_log_dir)


def test_log_entry_to_dict():
    """Test LogEntry excludes None values."""
    entry = LogEntry(timestamp="2024-01-01T00:00:00Z", event="test")
    data = entry.to_dict()

    assert "timestamp" in data
    assert "event" in data
    assert "chat_id" not in data  # None excluded
    assert "extra" not in data  # Empty dict excluded


def test_log_creates_file(logger: JSONLLogger):
    """Test that logging creates the log file."""
    logger.log("test_event")

    assert logger.log_path.exists()


def test_log_writes_jsonl(logger: JSONLLogger):
    """Test that logs are written in JSONL format."""
    logger.log("event1", chat_id="123")
    logger.log("event2", chat_id="456")

    with open(logger.log_path) as f:
        lines = f.readlines()

    assert len(lines) == 2

    entry1 = json.loads(lines[0])
    assert entry1["event"] == "event1"
    assert entry1["chat_id"] == "123"

    entry2 = json.loads(lines[1])
    assert entry2["event"] == "event2"


def test_log_command(logger: JSONLLogger):
    """Test logging a command execution."""
    logger.log_command(
        argv=["ls", "-la"],
        exit_code=0,
        duration_ms=150.5,
        container_id="abc123",
        truncated=False,
    )

    with open(logger.log_path) as f:
        entry = json.loads(f.readline())

    assert entry["event"] == "command"
    assert entry["argv"] == ["ls", "-la"]
    assert entry["exit_code"] == 0
    assert entry["duration_ms"] == 150.5
    assert entry["container_id"] == "abc123"


def test_log_tool_result(logger: JSONLLogger):
    """Test logging a tool result."""
    logger.log_tool_result(
        tool_name="bash",
        success=False,
        error="Command not allowed",
        duration_ms=10.0,
    )

    with open(logger.log_path) as f:
        entry = json.loads(f.readline())

    assert entry["event"] == "tool_result"
    assert entry["error"] == "Command not allowed"


def test_set_chat_id(logger: JSONLLogger):
    """Test that set_chat_id applies to subsequent logs."""
    logger.set_chat_id("session-42")
    logger.log("event1")
    logger.log("event2")

    with open(logger.log_path) as f:
        for line in f:
            entry = json.loads(line)
            assert entry["chat_id"] == "session-42"


def test_rotation(temp_log_dir: Path):
    """Test log rotation when max size is exceeded."""
    logger = JSONLLogger(log_dir=temp_log_dir, max_size_mb=0.001)  # ~1KB

    # Write enough to trigger rotation
    for i in range(100):
        logger.log(f"event_{i}", data="x" * 100)

    # Should have rotated files
    log_files = list(temp_log_dir.glob("logs*.jsonl"))
    assert len(log_files) >= 2


def test_extra_fields(logger: JSONLLogger):
    """Test that extra fields are included."""
    logger.log("custom", custom_field="value", another=123)

    with open(logger.log_path) as f:
        entry = json.loads(f.readline())

    assert entry["extra"]["custom_field"] == "value"
    assert entry["extra"]["another"] == 123
