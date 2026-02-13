"""Tests for the web_search tool."""

import pytest
from unittest.mock import AsyncMock, MagicMock, patch

from miniclaw.tools.web_search import WebSearchTool, reset_client


@pytest.fixture(autouse=True)
def reset_tavily_client():
    """Reset the cached Tavily client before each test."""
    reset_client()
    yield
    reset_client()


class TestWebSearchToolProperties:
    """Tests for WebSearchTool properties."""

    def test_name(self):
        tool = WebSearchTool()
        assert tool.name == "web_search"

    def test_description(self):
        tool = WebSearchTool()
        assert "search" in tool.description.lower()
        assert "web" in tool.description.lower()

    def test_parameters_schema(self):
        tool = WebSearchTool()
        params = tool.parameters
        assert params["type"] == "object"
        assert "query" in params["properties"]
        assert params["required"] == ["query"]

    def test_parameters_query(self):
        tool = WebSearchTool()
        query_param = tool.parameters["properties"]["query"]
        assert query_param["type"] == "string"

    def test_parameters_max_results(self):
        tool = WebSearchTool()
        max_results = tool.parameters["properties"]["max_results"]
        # Accepts both integer and string for LLM tolerance
        assert max_results["type"] == ["integer", "string"]

    def test_parameters_topic(self):
        tool = WebSearchTool()
        topic = tool.parameters["properties"]["topic"]
        assert topic["type"] == "string"
        assert "general" in topic["enum"]
        assert "news" in topic["enum"]
        assert "finance" in topic["enum"]


class TestWebSearchToolInit:
    """Tests for WebSearchTool initialization."""

    def test_default_max_results(self):
        tool = WebSearchTool()
        assert tool._max_results == 5

    def test_custom_max_results(self):
        tool = WebSearchTool(max_results=10)
        assert tool._max_results == 10

    def test_max_results_clamped_high(self):
        tool = WebSearchTool(max_results=50)
        assert tool._max_results == 20

    def test_max_results_clamped_low(self):
        tool = WebSearchTool(max_results=0)
        assert tool._max_results == 1

    def test_default_search_depth(self):
        tool = WebSearchTool()
        assert tool._search_depth == "basic"

    def test_custom_search_depth(self):
        tool = WebSearchTool(search_depth="advanced")
        assert tool._search_depth == "advanced"

    def test_default_include_answer(self):
        tool = WebSearchTool()
        assert tool._include_answer is True

    def test_custom_include_answer(self):
        tool = WebSearchTool(include_answer=False)
        assert tool._include_answer is False


class TestWebSearchToolFormatResults:
    """Tests for result formatting."""

    def test_format_with_answer(self):
        tool = WebSearchTool()
        response = {
            "answer": "The weather will be sunny.",
            "results": [],
        }
        output = tool._format_results(response)
        assert "## Answer" in output
        assert "The weather will be sunny." in output

    def test_format_with_results(self):
        tool = WebSearchTool()
        response = {
            "results": [
                {
                    "title": "Test Title",
                    "url": "https://example.com",
                    "content": "Test content",
                }
            ]
        }
        output = tool._format_results(response)
        assert "## Search Results" in output
        assert "### 1. Test Title" in output
        assert "URL: https://example.com" in output
        assert "Test content" in output

    def test_format_multiple_results(self):
        tool = WebSearchTool()
        response = {
            "results": [
                {"title": "First", "url": "https://first.com", "content": "First content"},
                {"title": "Second", "url": "https://second.com", "content": "Second content"},
            ]
        }
        output = tool._format_results(response)
        assert "### 1. First" in output
        assert "### 2. Second" in output

    def test_format_empty_results(self):
        tool = WebSearchTool()
        response = {"results": []}
        output = tool._format_results(response)
        assert output == "No results found."

    def test_format_no_results_key(self):
        tool = WebSearchTool()
        response = {}
        output = tool._format_results(response)
        assert output == "No results found."


class TestWebSearchToolExecute:
    """Tests for execute method."""

    @pytest.mark.asyncio
    async def test_empty_query_fails(self):
        tool = WebSearchTool()
        result = await tool.execute(query="")
        assert not result.success
        assert "empty" in result.error.lower()

    @pytest.mark.asyncio
    async def test_whitespace_query_fails(self):
        tool = WebSearchTool()
        result = await tool.execute(query="   ")
        assert not result.success
        assert "empty" in result.error.lower()

    @pytest.mark.asyncio
    async def test_missing_api_key(self, monkeypatch):
        monkeypatch.delenv("TAVILY_API_KEY", raising=False)

        # Mock the import to avoid actual dependency check
        with patch("miniclaw.tools.web_search._get_client") as mock_get:
            mock_get.side_effect = ValueError("TAVILY_API_KEY environment variable is required")

            tool = WebSearchTool()
            result = await tool.execute(query="test query")

            assert not result.success
            assert "TAVILY_API_KEY" in result.error

    @pytest.mark.asyncio
    async def test_successful_search(self, monkeypatch):
        monkeypatch.setenv("TAVILY_API_KEY", "test-key")

        mock_response = {
            "answer": "Test answer",
            "results": [
                {
                    "title": "Test Result",
                    "url": "https://test.com",
                    "content": "Test content here",
                }
            ],
            "response_time": 0.5,
        }

        mock_client = AsyncMock()
        mock_client.search = AsyncMock(return_value=mock_response)

        with patch("miniclaw.tools.web_search._get_client", return_value=mock_client):
            tool = WebSearchTool()
            result = await tool.execute(query="test query")

            assert result.success
            assert "Test answer" in result.output
            assert "Test Result" in result.output
            assert result.metadata["num_results"] == 1
            assert result.metadata["query"] == "test query"

    @pytest.mark.asyncio
    async def test_search_with_custom_max_results(self, monkeypatch):
        monkeypatch.setenv("TAVILY_API_KEY", "test-key")

        mock_client = AsyncMock()
        mock_client.search = AsyncMock(return_value={"results": []})

        with patch("miniclaw.tools.web_search._get_client", return_value=mock_client):
            tool = WebSearchTool()
            await tool.execute(query="test", max_results=10)

            mock_client.search.assert_called_once()
            call_kwargs = mock_client.search.call_args.kwargs
            assert call_kwargs["max_results"] == 10

    @pytest.mark.asyncio
    async def test_search_with_string_max_results(self, monkeypatch):
        """LLMs often pass numbers as strings - we should handle that."""
        monkeypatch.setenv("TAVILY_API_KEY", "test-key")

        mock_client = AsyncMock()
        mock_client.search = AsyncMock(return_value={"results": []})

        with patch("miniclaw.tools.web_search._get_client", return_value=mock_client):
            tool = WebSearchTool()
            await tool.execute(query="test", max_results="7")

            call_kwargs = mock_client.search.call_args.kwargs
            assert call_kwargs["max_results"] == 7  # Converted to int

    @pytest.mark.asyncio
    async def test_search_with_topic(self, monkeypatch):
        monkeypatch.setenv("TAVILY_API_KEY", "test-key")

        mock_client = AsyncMock()
        mock_client.search = AsyncMock(return_value={"results": []})

        with patch("miniclaw.tools.web_search._get_client", return_value=mock_client):
            tool = WebSearchTool()
            await tool.execute(query="stock prices", topic="finance")

            call_kwargs = mock_client.search.call_args.kwargs
            assert call_kwargs["topic"] == "finance"

    @pytest.mark.asyncio
    async def test_invalid_topic_defaults_to_general(self, monkeypatch):
        monkeypatch.setenv("TAVILY_API_KEY", "test-key")

        mock_client = AsyncMock()
        mock_client.search = AsyncMock(return_value={"results": []})

        with patch("miniclaw.tools.web_search._get_client", return_value=mock_client):
            tool = WebSearchTool()
            await tool.execute(query="test", topic="invalid")

            call_kwargs = mock_client.search.call_args.kwargs
            assert call_kwargs["topic"] == "general"

    @pytest.mark.asyncio
    async def test_search_exception_handling(self, monkeypatch):
        monkeypatch.setenv("TAVILY_API_KEY", "test-key")

        mock_client = AsyncMock()
        mock_client.search = AsyncMock(side_effect=Exception("API error"))

        with patch("miniclaw.tools.web_search._get_client", return_value=mock_client):
            tool = WebSearchTool()
            result = await tool.execute(query="test")

            assert not result.success
            assert "Search failed" in result.error
            assert "API error" in result.error


class TestWebSearchToolIntegration:
    """Integration-style tests (still mocked but testing full flow)."""

    @pytest.mark.asyncio
    async def test_full_search_flow(self, monkeypatch):
        monkeypatch.setenv("TAVILY_API_KEY", "test-key")

        mock_response = {
            "answer": "Madrid will have sunny weather on Thursday.",
            "results": [
                {
                    "title": "Weather Forecast Madrid",
                    "url": "https://weather.com/madrid",
                    "content": "Thursday: Sunny, 22°C, low humidity.",
                },
                {
                    "title": "Madrid Weather Weekly",
                    "url": "https://meteo.es/madrid",
                    "content": "Thursday forecast shows clear skies.",
                },
            ],
            "response_time": 0.8,
        }

        mock_client = AsyncMock()
        mock_client.search = AsyncMock(return_value=mock_response)

        with patch("miniclaw.tools.web_search._get_client", return_value=mock_client):
            tool = WebSearchTool(include_answer=True)
            result = await tool.execute(
                query="clima Madrid jueves",
                max_results=5,
                topic="general",
            )

            assert result.success

            # Check answer section
            assert "## Answer" in result.output
            assert "sunny weather" in result.output

            # Check results section
            assert "## Search Results" in result.output
            assert "Weather Forecast Madrid" in result.output
            assert "Madrid Weather Weekly" in result.output

            # Check metadata
            assert result.metadata["num_results"] == 2
            assert result.metadata["response_time"] == 0.8
