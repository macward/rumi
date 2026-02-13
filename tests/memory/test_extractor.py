"""Tests for FactExtractor."""

from unittest.mock import AsyncMock, Mock

import pytest

from miniclaw.memory import Fact, FactExtractor


@pytest.fixture
def mock_client() -> AsyncMock:
    """Create a mock Groq client."""
    return AsyncMock()


@pytest.fixture
def extractor(mock_client: AsyncMock) -> FactExtractor:
    """Create a FactExtractor with mock client."""
    return FactExtractor(mock_client)


def make_response(content: str) -> Mock:
    """Create a mock LLM response."""
    response = Mock()
    response.choices = [Mock()]
    response.choices[0].message.content = content
    return response


class TestFactExtractorInit:
    """Tests for FactExtractor initialization."""

    def test_default_model(self, mock_client: AsyncMock):
        """Default model is llama-3.1-70b-versatile."""
        extractor = FactExtractor(mock_client)
        assert extractor.model == "llama-3.1-70b-versatile"

    def test_custom_model(self, mock_client: AsyncMock):
        """Model can be customized."""
        extractor = FactExtractor(mock_client, model="custom-model")
        assert extractor.model == "custom-model"


class TestFactExtractorExtract:
    """Tests for the extract method."""

    @pytest.mark.asyncio
    async def test_empty_messages_returns_empty(self, extractor: FactExtractor):
        """Empty messages list returns empty facts."""
        facts = await extractor.extract([])
        assert facts == []

    @pytest.mark.asyncio
    async def test_valid_extraction(
        self, extractor: FactExtractor, mock_client: AsyncMock
    ):
        """Valid JSON response is parsed into facts."""
        mock_client.chat.completions.create = AsyncMock(
            return_value=make_response(
                '{"facts": [{"key": "nombre", "value": "Lucas"}, '
                '{"key": "trabajo", "value": "desarrollador"}]}'
            )
        )

        messages = [
            {"role": "user", "content": "Me llamo Lucas y soy desarrollador"},
        ]
        facts = await extractor.extract(messages)

        assert len(facts) == 2
        assert facts[0].key == "nombre"
        assert facts[0].value == "Lucas"
        assert facts[0].source == "auto"
        assert facts[1].key == "trabajo"
        assert facts[1].value == "desarrollador"

    @pytest.mark.asyncio
    async def test_empty_facts_list(
        self, extractor: FactExtractor, mock_client: AsyncMock
    ):
        """Empty facts list in response returns empty."""
        mock_client.chat.completions.create = AsyncMock(
            return_value=make_response('{"facts": []}')
        )

        messages = [{"role": "user", "content": "Hola"}]
        facts = await extractor.extract(messages)

        assert facts == []

    @pytest.mark.asyncio
    async def test_invalid_json_returns_empty(
        self, extractor: FactExtractor, mock_client: AsyncMock
    ):
        """Invalid JSON returns empty list."""
        mock_client.chat.completions.create = AsyncMock(
            return_value=make_response("not valid json")
        )

        messages = [{"role": "user", "content": "test"}]
        facts = await extractor.extract(messages)

        assert facts == []

    @pytest.mark.asyncio
    async def test_missing_facts_key_returns_empty(
        self, extractor: FactExtractor, mock_client: AsyncMock
    ):
        """Missing 'facts' key returns empty list."""
        mock_client.chat.completions.create = AsyncMock(
            return_value=make_response('{"data": []}')
        )

        messages = [{"role": "user", "content": "test"}]
        facts = await extractor.extract(messages)

        assert facts == []

    @pytest.mark.asyncio
    async def test_invalid_fact_items_skipped(
        self, extractor: FactExtractor, mock_client: AsyncMock
    ):
        """Invalid fact items are skipped."""
        mock_client.chat.completions.create = AsyncMock(
            return_value=make_response(
                '{"facts": [{"key": "nombre", "value": "Lucas"}, '
                '"invalid", {"bad": "item"}]}'
            )
        )

        messages = [{"role": "user", "content": "test"}]
        facts = await extractor.extract(messages)

        assert len(facts) == 1
        assert facts[0].key == "nombre"

    @pytest.mark.asyncio
    async def test_markdown_code_block_stripped(
        self, extractor: FactExtractor, mock_client: AsyncMock
    ):
        """Markdown code blocks are stripped from response."""
        mock_client.chat.completions.create = AsyncMock(
            return_value=make_response(
                '```json\n{"facts": [{"key": "nombre", "value": "Lucas"}]}\n```'
            )
        )

        messages = [{"role": "user", "content": "test"}]
        facts = await extractor.extract(messages)

        assert len(facts) == 1
        assert facts[0].key == "nombre"

    @pytest.mark.asyncio
    async def test_llm_error_returns_empty(
        self, extractor: FactExtractor, mock_client: AsyncMock
    ):
        """LLM errors return empty list."""
        mock_client.chat.completions.create = AsyncMock(
            side_effect=Exception("API error")
        )

        messages = [{"role": "user", "content": "test"}]
        facts = await extractor.extract(messages)

        assert facts == []


class TestFactExtractorFormatConversation:
    """Tests for conversation formatting."""

    def test_format_user_messages(self, extractor: FactExtractor):
        """User messages are prefixed with 'Usuario:'."""
        messages = [{"role": "user", "content": "Hola"}]
        result = extractor._format_conversation(messages)
        assert "Usuario: Hola" in result

    def test_format_assistant_messages(self, extractor: FactExtractor):
        """Assistant messages are prefixed with 'Asistente:'."""
        messages = [{"role": "assistant", "content": "Hola!"}]
        result = extractor._format_conversation(messages)
        assert "Asistente: Hola!" in result

    def test_system_messages_skipped(self, extractor: FactExtractor):
        """System messages are not included."""
        messages = [
            {"role": "system", "content": "You are a helpful assistant"},
            {"role": "user", "content": "Hola"},
        ]
        result = extractor._format_conversation(messages)
        assert "system" not in result.lower()
        assert "helpful assistant" not in result

    def test_tool_messages_skipped(self, extractor: FactExtractor):
        """Tool messages are not included."""
        messages = [
            {"role": "tool", "content": "result", "tool_call_id": "123"},
            {"role": "user", "content": "Hola"},
        ]
        result = extractor._format_conversation(messages)
        assert "tool" not in result.lower()


class TestFactExtractorExport:
    """Tests for module exports."""

    def test_exported_from_package(self):
        """FactExtractor is exported from memory package."""
        from miniclaw.memory import FactExtractor as ExportedExtractor

        assert ExportedExtractor is FactExtractor
