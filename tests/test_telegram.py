"""Tests for Telegram bot."""

import pytest

from rumi.agent import StopReason
from rumi.telegram.bot import (
    MAX_MESSAGE_LENGTH,
    escape_markdown,
    format_response,
    truncate_message,
)


class TestEscapeMarkdown:
    def test_escapes_special_chars(self):
        text = "Hello *world* and _underscore_"
        escaped = escape_markdown(text)
        assert r"\*" in escaped
        assert r"\_" in escaped

    def test_escapes_code_blocks(self):
        text = "Use `code` here"
        escaped = escape_markdown(text)
        assert r"\`" in escaped

    def test_plain_text_unchanged(self):
        text = "Hello world"
        assert escape_markdown(text) == text


class TestTruncateMessage:
    def test_short_message_unchanged(self):
        text = "Short message"
        assert truncate_message(text) == text

    def test_long_message_truncated(self):
        text = "x" * 5000
        result = truncate_message(text)
        assert len(result) <= MAX_MESSAGE_LENGTH
        assert "truncado" in result

    def test_exact_length_unchanged(self):
        text = "x" * MAX_MESSAGE_LENGTH
        assert truncate_message(text) == text


class TestFormatResponse:
    def test_complete_no_suffix(self):
        result = format_response("Hello", StopReason.COMPLETE, 1)
        assert result == "Hello"

    def test_max_turns_warning(self):
        result = format_response("Response", StopReason.MAX_TURNS, 10)
        assert "máximo de turnos" in result
        assert "10" in result

    def test_repeated_call_warning(self):
        result = format_response("Response", StopReason.REPEATED_CALL, 3)
        assert "loop" in result.lower()

    def test_errors_warning(self):
        result = format_response("Response", StopReason.CONSECUTIVE_ERRORS, 2)
        assert "errores" in result.lower()

    def test_long_response_truncated(self):
        long_text = "x" * 5000
        result = format_response(long_text, StopReason.COMPLETE, 1)
        assert len(result) <= MAX_MESSAGE_LENGTH


class TestTelegramBot:
    def test_requires_token(self):
        from rumi.telegram import TelegramBot

        with pytest.raises(ValueError, match="TELEGRAM_TOKEN"):
            TelegramBot(token=None)

    def test_creates_with_token(self, monkeypatch):
        from rumi.telegram import TelegramBot

        monkeypatch.setenv("GROQ_API_KEY", "test-key")
        bot = TelegramBot(token="test-token")
        assert bot.token == "test-token"
        assert bot.registry is not None
