"""Base tool interface and registry."""

from abc import ABC, abstractmethod
from dataclasses import dataclass
from typing import Any


@dataclass
class ToolResult:
    """Result from tool execution."""

    success: bool
    output: str
    error: str | None = None
    metadata: dict[str, Any] | None = None


class Tool(ABC):
    """Base interface for all tools."""

    @property
    @abstractmethod
    def name(self) -> str:
        """Unique tool name."""
        ...

    @property
    @abstractmethod
    def description(self) -> str:
        """Tool description for LLM."""
        ...

    @property
    @abstractmethod
    def parameters(self) -> dict[str, Any]:
        """JSON Schema for tool parameters."""
        ...

    @abstractmethod
    async def execute(self, **kwargs: Any) -> ToolResult:
        """Execute the tool with given arguments."""
        ...

    def get_schema(self) -> dict[str, Any]:
        """Get tool schema for LLM function calling."""
        return {
            "type": "function",
            "function": {
                "name": self.name,
                "description": self.description,
                "parameters": self.parameters,
            },
        }

    def validate_args(self, args: dict[str, Any]) -> tuple[bool, str | None]:
        """Validate arguments against schema. Returns (valid, error_message)."""
        required = self.parameters.get("required", [])
        properties = self.parameters.get("properties", {})

        # Check required fields
        for field in required:
            if field not in args:
                return False, f"Missing required argument: {field}"

        # Check types (basic validation)
        for key, value in args.items():
            if key not in properties:
                continue
            expected_type = properties[key].get("type")
            if expected_type == "string" and not isinstance(value, str):
                return False, f"Argument '{key}' must be a string"
            if expected_type == "integer" and not isinstance(value, int):
                return False, f"Argument '{key}' must be an integer"
            if expected_type == "boolean" and not isinstance(value, bool):
                return False, f"Argument '{key}' must be a boolean"

        return True, None
