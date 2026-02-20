"""Tests for tool registry."""

import pytest

from rumi.tools import Tool, ToolResult, ToolRegistry


class EchoTool(Tool):
    """Simple echo tool for testing."""

    @property
    def name(self) -> str:
        return "echo"

    @property
    def description(self) -> str:
        return "Echoes the input message"

    @property
    def parameters(self) -> dict:
        return {
            "type": "object",
            "properties": {
                "message": {"type": "string", "description": "Message to echo"},
            },
            "required": ["message"],
        }

    async def execute(self, message: str) -> ToolResult:
        return ToolResult(success=True, output=message)


@pytest.fixture
def registry() -> ToolRegistry:
    return ToolRegistry()


@pytest.fixture
def echo_tool() -> EchoTool:
    return EchoTool()


def test_register_tool(registry: ToolRegistry, echo_tool: EchoTool) -> None:
    registry.register(echo_tool)
    assert "echo" in registry.list_tools()


def test_register_duplicate_raises(registry: ToolRegistry, echo_tool: EchoTool) -> None:
    registry.register(echo_tool)
    with pytest.raises(ValueError, match="already registered"):
        registry.register(echo_tool)


def test_get_tool(registry: ToolRegistry, echo_tool: EchoTool) -> None:
    registry.register(echo_tool)
    tool = registry.get("echo")
    assert tool is echo_tool


def test_get_unknown_tool(registry: ToolRegistry) -> None:
    assert registry.get("unknown") is None


def test_get_tools_schema(registry: ToolRegistry, echo_tool: EchoTool) -> None:
    registry.register(echo_tool)
    schemas = registry.get_tools_schema()
    assert len(schemas) == 1
    assert schemas[0]["type"] == "function"
    assert schemas[0]["function"]["name"] == "echo"


@pytest.mark.asyncio
async def test_dispatch_success(registry: ToolRegistry, echo_tool: EchoTool) -> None:
    registry.register(echo_tool)
    result = await registry.dispatch("echo", {"message": "hello"})
    assert result.success is True
    assert result.output == "hello"


@pytest.mark.asyncio
async def test_dispatch_unknown_tool(registry: ToolRegistry) -> None:
    result = await registry.dispatch("unknown", {})
    assert result.success is False
    assert "Unknown tool" in result.error


@pytest.mark.asyncio
async def test_dispatch_missing_required_arg(registry: ToolRegistry, echo_tool: EchoTool) -> None:
    registry.register(echo_tool)
    result = await registry.dispatch("echo", {})
    assert result.success is False
    assert "Missing required" in result.error


def test_validate_args_type_check(echo_tool: EchoTool) -> None:
    valid, error = echo_tool.validate_args({"message": 123})
    assert valid is False
    assert "must be a string" in error
