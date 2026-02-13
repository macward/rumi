"""Web search tool using Tavily API."""

import os
from typing import Any

from .base import Tool, ToolResult

# Lazy import to avoid requiring tavily-python when not using this tool
_tavily_client = None


def _get_client():
    """Get or create the Tavily async client."""
    global _tavily_client
    if _tavily_client is None:
        try:
            from tavily import AsyncTavilyClient
        except ImportError:
            raise ImportError(
                "tavily-python is required for web_search. "
                "Install it with: pip install tavily-python"
            )

        api_key = os.getenv("TAVILY_API_KEY")
        if not api_key:
            raise ValueError("TAVILY_API_KEY environment variable is required")

        _tavily_client = AsyncTavilyClient(api_key=api_key)

    return _tavily_client


class WebSearchTool(Tool):
    """Tool for searching the web using Tavily API.

    Tavily is a search API optimized for AI agents, returning clean
    and relevant results instead of raw HTML.
    """

    def __init__(
        self,
        max_results: int = 5,
        search_depth: str = "basic",
        include_answer: bool = True,
    ) -> None:
        """Initialize the web search tool.

        Args:
            max_results: Maximum number of results to return (1-20).
            search_depth: "basic" for fast results, "advanced" for deeper search.
            include_answer: Whether to include an AI-generated answer summary.
        """
        self._max_results = min(max(1, max_results), 20)
        self._search_depth = search_depth
        self._include_answer = include_answer

    @property
    def name(self) -> str:
        return "web_search"

    @property
    def description(self) -> str:
        return (
            "Search the web for current information. Returns relevant results "
            "with titles, snippets, and URLs. Use this for questions about "
            "recent events, weather, news, or any information that may have "
            "changed since training."
        )

    @property
    def parameters(self) -> dict[str, Any]:
        return {
            "type": "object",
            "properties": {
                "query": {
                    "type": "string",
                    "description": "The search query. Be specific for better results.",
                },
                "max_results": {
                    "type": "integer",
                    "description": "Number of results to return (1-20, default 5)",
                    "minimum": 1,
                    "maximum": 20,
                },
                "topic": {
                    "type": "string",
                    "description": "Search topic: 'general', 'news', or 'finance'",
                    "enum": ["general", "news", "finance"],
                },
            },
            "required": ["query"],
        }

    def _format_results(self, response: dict[str, Any]) -> str:
        """Format Tavily response for LLM consumption."""
        lines = []

        # Include AI-generated answer if available
        if response.get("answer"):
            lines.append("## Answer")
            lines.append(response["answer"])
            lines.append("")

        # Format search results
        results = response.get("results", [])
        if results:
            lines.append("## Search Results")
            lines.append("")

            for i, result in enumerate(results, 1):
                title = result.get("title", "No title")
                url = result.get("url", "")
                content = result.get("content", "No content")

                lines.append(f"### {i}. {title}")
                lines.append(f"URL: {url}")
                lines.append(f"{content}")
                lines.append("")

        if not lines:
            return "No results found."

        return "\n".join(lines)

    async def execute(
        self,
        query: str,
        max_results: int | None = None,
        topic: str = "general",
        **kwargs: Any,
    ) -> ToolResult:
        """Execute a web search.

        Args:
            query: The search query.
            max_results: Override default max results.
            topic: Search topic (general, news, finance).

        Returns:
            ToolResult with formatted search results.
        """
        if not query or not query.strip():
            return ToolResult(
                success=False,
                output="",
                error="Search query cannot be empty",
            )

        # Validate topic
        if topic not in ("general", "news", "finance"):
            topic = "general"

        # Use provided max_results or default
        num_results = max_results if max_results is not None else self._max_results
        num_results = min(max(1, num_results), 20)

        try:
            client = _get_client()

            response = await client.search(
                query=query.strip(),
                search_depth=self._search_depth,
                topic=topic,
                max_results=num_results,
                include_answer=self._include_answer,
            )

            output = self._format_results(response)

            return ToolResult(
                success=True,
                output=output,
                metadata={
                    "query": query,
                    "num_results": len(response.get("results", [])),
                    "response_time": response.get("response_time"),
                },
            )

        except ImportError as e:
            return ToolResult(
                success=False,
                output="",
                error=str(e),
            )
        except ValueError as e:
            return ToolResult(
                success=False,
                output="",
                error=str(e),
            )
        except Exception as e:
            return ToolResult(
                success=False,
                output="",
                error=f"Search failed: {e}",
            )


def reset_client() -> None:
    """Reset the cached client (useful for testing)."""
    global _tavily_client
    _tavily_client = None
