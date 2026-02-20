"""Base interfaces for the skills system.

This module defines the core abstractions:
- SkillSource: Where a skill comes from (bundled, user, workspace)
- SkillMetadata: Descriptive information about a skill
- SkillResult: Outcome of skill execution
- SkillContext: Runtime context passed to skills
- Skill: Abstract base class for all skill implementations
"""

from abc import ABC, abstractmethod
from dataclasses import dataclass, field
from enum import Enum
from pathlib import Path
from typing import TYPE_CHECKING, Any, Protocol

if TYPE_CHECKING:
    from ..session.manager import SessionState
    from ..tools.registry import ToolRegistry


class SkillSource(Enum):
    """Origin of a skill, determines precedence.

    Precedence (highest to lowest):
    1. WORKSPACE - Project-specific skills
    2. USER - User's personal skills
    3. BUNDLED - Included with Rumi
    """

    BUNDLED = "bundled"
    USER = "user"
    WORKSPACE = "workspace"

    @property
    def priority(self) -> int:
        """Higher number = higher priority (overrides lower)."""
        priorities = {
            SkillSource.BUNDLED: 1,
            SkillSource.USER: 2,
            SkillSource.WORKSPACE: 3,
        }
        if self not in priorities:
            raise ValueError(f"No priority defined for {self}")
        return priorities[self]


@dataclass
class SkillMetadata:
    """Metadata describing a skill.

    Parsed from SKILL.md frontmatter or defined in code for CodeSkills.
    """

    name: str
    description: str
    version: str = "0.1.0"
    tags: list[str] = field(default_factory=list)
    tools_required: list[str] = field(default_factory=list)
    enabled: bool = True
    source: SkillSource = SkillSource.BUNDLED
    path: Path | None = None

    def matches_keywords(self, query: str) -> float:
        """Calculate relevance score based on keyword matching.

        Returns:
            Score from 0.0 to 1.0 indicating relevance.
        """
        query_lower = query.lower()
        score = 0.0

        # Check name match (strongest signal)
        if self.name.lower() in query_lower:
            score += 0.5

        # Check description
        desc_lower = self.description.lower()
        query_words = query_lower.split()
        matching_words = sum(1 for w in query_words if w in desc_lower)
        if query_words:
            score += 0.3 * (matching_words / len(query_words))

        # Check tags
        for tag in self.tags:
            if tag.lower() in query_lower:
                score += 0.2
                break

        return min(score, 1.0)


@dataclass
class SkillResult:
    """Result from executing a skill.

    Attributes:
        success: Whether the skill completed successfully.
        output: The primary output (instructions for PromptSkill, result for CodeSkill).
        error: Error message if success=False.
        metadata: Additional structured data about the execution.
        prompt_injection: Extra instructions to add to system prompt (CodeSkill only).
    """

    success: bool
    output: str
    error: str | None = None
    metadata: dict[str, Any] | None = None
    prompt_injection: str | None = None


class LLMClient(Protocol):
    """Protocol for LLM access in CodeSkills.

    Allows CodeSkills to call the LLM without depending on a specific provider.
    """

    async def complete(self, prompt: str, system: str | None = None) -> str:
        """Complete a prompt and return the text response."""
        ...


@dataclass
class SkillContext:
    """Runtime context injected into skills during execution.

    Provides access to tools, session state, and LLM for CodeSkills.

    Note: chat_id is assumed to be pre-validated by SessionManager before
    being used here. It must be alphanumeric with optional underscores/hyphens
    as it's used in container names and file paths.
    """

    tools: "ToolRegistry"
    session: "SessionState"
    chat_id: str
    user_message: str
    llm: LLMClient | None = None
    config: dict[str, Any] = field(default_factory=dict)

    def __post_init__(self) -> None:
        """Validate required fields."""
        if not self.chat_id or not self.chat_id.strip():
            raise ValueError("chat_id cannot be empty")


class Skill(ABC):
    """Abstract base class for all skills.

    Skills must implement:
    - metadata property: Returns SkillMetadata describing the skill
    - execute(): Performs the skill's action with given context
    """

    @property
    @abstractmethod
    def metadata(self) -> SkillMetadata:
        """Return metadata describing this skill."""
        ...

    @abstractmethod
    async def execute(self, ctx: SkillContext) -> SkillResult:
        """Execute the skill with the given context.

        For PromptSkills: Returns instructions as output.
        For CodeSkills: Orchestrates tools and returns result.
        """
        ...

    def can_handle(self, query: str) -> float:
        """Score indicating relevance for a query (0.0 to 1.0).

        Default implementation uses keyword matching against metadata.
        CodeSkills can override for more sophisticated matching.
        """
        return self.metadata.matches_keywords(query)

    @property
    def name(self) -> str:
        """Convenience accessor for skill name."""
        return self.metadata.name

    @property
    def description(self) -> str:
        """Convenience accessor for skill description."""
        return self.metadata.description

    @property
    def enabled(self) -> bool:
        """Check if skill is enabled."""
        return self.metadata.enabled
