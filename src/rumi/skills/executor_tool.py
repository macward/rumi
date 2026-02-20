"""SkillExecutorTool: Bridge between ToolRegistry and SkillManager.

This tool allows the LLM to invoke skills via the standard tool calling mechanism.
It registers as a regular tool (use_skill) that delegates execution to SkillManager.
"""

from typing import TYPE_CHECKING, Any

from ..tools.base import Tool, ToolResult
from .base import LLMClient, SkillContext

if TYPE_CHECKING:
    from ..session.manager import SessionState
    from ..tools.registry import ToolRegistry
    from .manager import SkillManager


class SkillExecutorTool(Tool):
    """Tool that allows the LLM to invoke skills.

    When the LLM calls use_skill with a skill name, this tool:
    1. Looks up the skill in SkillManager
    2. Creates a SkillContext with the current session info
    3. Executes the skill and returns the result

    For PromptSkills, the result contains instructions that the LLM
    should follow in subsequent turns.

    Example:
        manager = SkillManager(config)
        manager.discover()

        executor = SkillExecutorTool(manager)
        registry.register(executor)

        # LLM can now call:
        # use_skill(skill_name="summarize", input="summarize this file")
    """

    def __init__(
        self,
        skill_manager: "SkillManager",
        tools: "ToolRegistry | None" = None,
        llm: LLMClient | None = None,
    ) -> None:
        """Initialize the SkillExecutorTool.

        Args:
            skill_manager: The SkillManager to delegate execution to.
            tools: Optional ToolRegistry for creating SkillContext.
            llm: Optional LLMClient for CodeSkills that need LLM access.
        """
        self._skill_manager = skill_manager
        self._tools = tools
        self._llm = llm

    @property
    def name(self) -> str:
        """Tool name for function calling."""
        return "use_skill"

    @property
    def description(self) -> str:
        """Tool description for LLM."""
        return (
            "Execute a skill by name. Check <available_skills> in the system prompt "
            "for available skills. Skills provide specialized instructions for "
            "completing complex tasks."
        )

    @property
    def parameters(self) -> dict[str, Any]:
        """JSON Schema for tool parameters."""
        return {
            "type": "object",
            "properties": {
                "skill_name": {
                    "type": "string",
                    "description": "Name of the skill to execute (from <available_skills>)",
                },
                "skill_input": {
                    "type": "string",
                    "description": "Additional input or context for the skill (optional)",
                },
            },
            "required": ["skill_name"],
        }

    async def execute(
        self,
        skill_name: str | None = None,
        skill_input: str = "",
        *,
        chat_id: str = "unknown",
        session: "SessionState | None" = None,
        **kwargs: Any,
    ) -> ToolResult:
        """Execute a skill by name.

        Args:
            skill_name: Name of the skill to execute.
            skill_input: Additional input or context for the skill.
            chat_id: Current chat/session ID.
            session: Current session state (if available).
            **kwargs: Additional arguments (ignored).

        Returns:
            ToolResult with skill output or error message.
        """
        if not skill_name:
            return ToolResult(
                success=False,
                output="",
                error="Missing required argument: skill_name. Check <available_skills> in the system prompt.",
            )

        # Create context for the skill
        # SkillContext requires a SessionState, so we create one if not provided
        from ..session.manager import SessionState
        from ..tools.registry import ToolRegistry

        ctx = SkillContext(
            tools=self._tools or ToolRegistry(),
            session=session or SessionState(chat_id=chat_id),
            chat_id=chat_id,
            user_message=skill_input,
            llm=self._llm,
        )

        # Execute through SkillManager
        result = await self._skill_manager.execute(skill_name, ctx)

        return ToolResult(
            success=result.success,
            output=result.output,
            error=result.error,
            metadata=result.metadata,
        )

    @property
    def skill_manager(self) -> "SkillManager":
        """Access to the underlying SkillManager."""
        return self._skill_manager
