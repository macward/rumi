"""Tool registry for managing and dispatching tools."""

from typing import Any

from .base import Tool, ToolResult


class ToolRegistry:
    """Registry for available tools."""

    def __init__(self) -> None:
        self._tools: dict[str, Tool] = {}

    def register(self, tool: Tool) -> None:
        """Register a tool."""
        if tool.name in self._tools:
            raise ValueError(f"Tool '{tool.name}' already registered")
        self._tools[tool.name] = tool

    def unregister(self, name: str) -> None:
        """Unregister a tool by name."""
        if name in self._tools:
            del self._tools[name]

    def get(self, name: str) -> Tool | None:
        """Get a tool by name."""
        return self._tools.get(name)

    def list_tools(self) -> list[str]:
        """List all registered tool names."""
        return list(self._tools.keys())

    def get_tools_schema(self) -> list[dict[str, Any]]:
        """Get schemas for all tools (for LLM function calling)."""
        return [tool.get_schema() for tool in self._tools.values()]

    async def dispatch(self, tool_name: str, args: dict[str, Any]) -> ToolResult:
        """Dispatch a tool call by name with arguments."""
        tool = self._tools.get(tool_name)

        if tool is None:
            # Check if this is a skill name that should be redirected to use_skill
            use_skill_tool = self._tools.get("use_skill")
            if use_skill_tool is not None:
                # Check if it has a skill_manager with this skill
                skill_manager = getattr(use_skill_tool, "skill_manager", None)
                if skill_manager and skill_manager.is_skill_available(tool_name):
                    # Redirect to use_skill with the skill name
                    # Extract skill_input from args (could be 'message', 'input', etc.)
                    skill_input = args.get("skill_input") or args.get("message") or args.get("input") or ""
                    return await use_skill_tool.execute(
                        skill_name=tool_name,
                        skill_input=skill_input,
                    )

            return ToolResult(
                success=False,
                output="",
                error=f"Unknown tool: {tool_name}",
            )

        # Validate arguments
        valid, error = tool.validate_args(args)
        if not valid:
            return ToolResult(
                success=False,
                output="",
                error=error,
            )

        # Execute tool
        try:
            return await tool.execute(**args)
        except Exception as e:
            return ToolResult(
                success=False,
                output="",
                error=f"Tool execution failed: {e}",
            )
