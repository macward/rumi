"""Prompt builder for the agent."""

from typing import Any

SYSTEM_PROMPT_BASE = """You are MiniClaw, a helpful assistant that can execute commands safely in a sandboxed environment.

You have access to the following tools:
{tools_description}

When you need to use a tool, respond with a tool call. Always explain what you're doing before executing commands.

Important:
- Commands run in an isolated Docker container
- No network access from the container
- Files persist in /workspace during the session
- Be careful with destructive operations

If you cannot complete a task with the available tools, explain why."""

SKILLS_INSTRUCTIONS = """
{available_skills_block}

When a task matches a skill's description, use the `use_skill` tool to invoke it.
For simple tasks that only need a single tool, use the tool directly."""


def build_system_prompt(
    tools_schema: list[dict[str, Any]],
    available_skills_block: str = "",
    memory_block: str = "",
) -> str:
    """Build the system prompt with available tools, skills, and memory.

    Args:
        tools_schema: List of tool schemas for the LLM.
        available_skills_block: Optional XML block with available skills.
        memory_block: Optional XML block with user facts from memory.

    Returns:
        Complete system prompt string.
    """
    if not tools_schema:
        tools_desc = "No tools available."
    else:
        tools_desc = "\n".join(
            f"- {t['function']['name']}: {t['function']['description']}"
            for t in tools_schema
        )

    prompt = SYSTEM_PROMPT_BASE.format(tools_description=tools_desc)

    # Only add skills block if there are skills available
    if available_skills_block.strip():
        prompt += SKILLS_INSTRUCTIONS.format(
            available_skills_block=available_skills_block
        )

    # Add memory block if there are facts
    if memory_block.strip():
        prompt += "\n\n" + memory_block

    return prompt


def format_tool_result(tool_name: str, success: bool, output: str, error: str | None) -> str:
    """Format a tool result for the conversation."""
    if success:
        return f"[{tool_name}] Success:\n{output}"
    else:
        return f"[{tool_name}] Error: {error}"
