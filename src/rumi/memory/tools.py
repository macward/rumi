"""Memory tools for explicit fact management."""

from typing import Any

from ..tools.base import Tool, ToolResult
from .models import Fact
from .store import MemoryStore


class RememberTool(Tool):
    """Tool for saving explicit facts about the user."""

    def __init__(self, store: MemoryStore) -> None:
        """Initialize with a memory store.

        Args:
            store: The MemoryStore for persistence.
        """
        self.store = store

    @property
    def name(self) -> str:
        return "remember"

    @property
    def description(self) -> str:
        return (
            "Save a fact about the user for future reference. "
            "Use when the user explicitly asks to remember something."
        )

    @property
    def parameters(self) -> dict[str, Any]:
        return {
            "type": "object",
            "properties": {
                "key": {
                    "type": "string",
                    "description": (
                        "Category of the fact (e.g., 'nombre', 'trabajo', "
                        "'preferencia', 'proyecto')"
                    ),
                },
                "value": {
                    "type": "string",
                    "description": (
                        "The fact to remember, in third person "
                        "(e.g., 'trabaja en Google', 'prefiere TypeScript')"
                    ),
                },
            },
            "required": ["key", "value"],
        }

    async def execute(self, **kwargs: Any) -> ToolResult:
        """Save a fact to memory.

        Args:
            key: Category of the fact.
            value: The fact content.

        Returns:
            ToolResult with success status.
        """
        key = kwargs.get("key", "")
        value = kwargs.get("value", "")

        if not key or not value:
            return ToolResult(
                success=False,
                output="",
                error="Both 'key' and 'value' are required",
            )

        fact = Fact(key=key, value=value, source="explicit")
        saved = self.store.save_fact(fact)

        return ToolResult(
            success=True,
            output=f"Recordado: {saved.key} → {saved.value}",
        )


class ForgetTool(Tool):
    """Tool for removing facts about the user."""

    def __init__(self, store: MemoryStore) -> None:
        """Initialize with a memory store.

        Args:
            store: The MemoryStore for persistence.
        """
        self.store = store

    @property
    def name(self) -> str:
        return "forget"

    @property
    def description(self) -> str:
        return (
            "Remove stored facts about the user by category. "
            "Use when the user asks to forget something."
        )

    @property
    def parameters(self) -> dict[str, Any]:
        return {
            "type": "object",
            "properties": {
                "key": {
                    "type": "string",
                    "description": (
                        "Category of facts to forget (e.g., 'trabajo', 'ubicacion')"
                    ),
                },
            },
            "required": ["key"],
        }

    async def execute(self, **kwargs: Any) -> ToolResult:
        """Remove facts by key.

        Args:
            key: Category of facts to remove.

        Returns:
            ToolResult with count of removed facts.
        """
        key = kwargs.get("key", "")

        if not key:
            return ToolResult(
                success=False,
                output="",
                error="'key' is required",
            )

        count = self.store.delete_by_key(key)

        if count == 0:
            return ToolResult(
                success=True,
                output=f"No tenía nada guardado sobre '{key}'",
            )

        return ToolResult(
            success=True,
            output=f"Olvidado: {count} {'hecho' if count == 1 else 'hechos'} sobre '{key}'",
        )
