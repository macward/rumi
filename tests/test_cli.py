"""Tests for CLI."""

import os
import pytest

from rumi.cli import CLI
from rumi.agent import StopReason


@pytest.fixture
def cli(monkeypatch) -> CLI:
    monkeypatch.setenv("GROQ_API_KEY", "test-key")
    return CLI()


def test_new_chat_id(cli: CLI) -> None:
    """Test chat ID generation."""
    assert cli.chat_id.startswith("cli-")
    assert len(cli.chat_id) == 12  # "cli-" + 8 hex chars


@pytest.mark.asyncio
async def test_reset_changes_chat_id(cli: CLI) -> None:
    """Test that reset generates a new chat_id."""
    old_id = cli.chat_id
    await cli._reset()
    assert cli.chat_id != old_id
    assert cli.chat_id.startswith("cli-")


@pytest.mark.asyncio
async def test_handle_command_exit(cli: CLI) -> None:
    """Test exit commands return False."""
    assert await cli._handle_command("/exit") is False


@pytest.mark.asyncio
async def test_handle_command_quit(cli: CLI) -> None:
    """Test quit commands return False."""
    assert await cli._handle_command("/quit") is False


@pytest.mark.asyncio
async def test_handle_command_help(cli: CLI) -> None:
    """Test help command returns True."""
    assert await cli._handle_command("/help") is True


@pytest.mark.asyncio
async def test_handle_command_reset(cli: CLI) -> None:
    """Test reset command returns True."""
    old_id = cli.chat_id
    assert await cli._handle_command("/reset") is True
    assert cli.chat_id != old_id


def test_format_response_complete(cli: CLI) -> None:
    """Test response formatting for complete runs."""
    output = cli._format_response("Hello!", StopReason.COMPLETE, 1)
    assert "Hello!" in output
    assert "Stopped" not in output


def test_format_response_stopped(cli: CLI) -> None:
    """Test response formatting when stopped early."""
    output = cli._format_response("Partial", StopReason.MAX_TURNS, 5)
    assert "Partial" in output
    assert "Stopped: max_turns" in output
    assert "turns: 5" in output
