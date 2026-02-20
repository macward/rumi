"""PromptSkill: Skills defined by SKILL.md files.

PromptSkills are the simplest type of skill - they consist only of a SKILL.md
file with instructions. When executed, they return the markdown body as output,
which the LLM then follows as instructions.
"""

from pathlib import Path

from .base import Skill, SkillContext, SkillMetadata, SkillResult, SkillSource
from .parser import SkillParseError, parse_skill_file


class PromptSkill(Skill):
    """A skill loaded from a SKILL.md file.

    PromptSkills are defined entirely by their SKILL.md file. The file's
    frontmatter provides metadata, and the body provides instructions that
    the LLM should follow when the skill is invoked.

    Example SKILL.md:
        ---
        name: summarize
        description: Summarize documents extracting key points
        tags: [text, productivity]
        tools_required: [bash]
        ---

        When the user asks to summarize a file:
        1. Use `bash` to read the file with `cat`
        2. Extract key points
        3. Present a structured summary
    """

    def __init__(
        self,
        skill_dir: Path,
        source: SkillSource = SkillSource.BUNDLED,
    ) -> None:
        """Initialize a PromptSkill from a directory.

        Args:
            skill_dir: Directory containing SKILL.md file.
            source: Where this skill comes from (affects priority).

        Raises:
            SkillParseError: If SKILL.md cannot be found or parsed.
        """
        self._skill_dir = skill_dir
        self._source = source

        # Locate SKILL.md
        skill_file = skill_dir / "SKILL.md"
        if not skill_file.exists():
            raise SkillParseError(f"No SKILL.md found in {skill_dir}")

        # Parse and store
        self._metadata, self._instructions = parse_skill_file(skill_file, source=source)

    @property
    def metadata(self) -> SkillMetadata:
        """Return the parsed metadata from SKILL.md frontmatter."""
        return self._metadata

    @property
    def instructions(self) -> str:
        """Return the raw instructions from SKILL.md body."""
        return self._instructions

    @property
    def skill_dir(self) -> Path:
        """Return the directory containing this skill."""
        return self._skill_dir

    async def execute(self, ctx: SkillContext) -> SkillResult:
        """Execute the skill by returning instructions for the LLM.

        The instructions from SKILL.md are returned as the output.
        The LLM will receive these as a tool result and should follow them.

        Args:
            ctx: The execution context (not used for PromptSkills but
                 available for consistency with CodeSkills).

        Returns:
            SkillResult with instructions as output.
        """
        if not self._instructions:
            return SkillResult(
                success=True,
                output="(No instructions provided)",
                metadata={"skill_name": self.name, "type": "prompt_skill"},
            )

        return SkillResult(
            success=True,
            output=self._instructions,
            metadata={"skill_name": self.name, "type": "prompt_skill"},
        )

    def __repr__(self) -> str:
        """Return string representation."""
        return f"PromptSkill(name={self.name!r}, source={self._source.value})"


def load_prompt_skill(
    skill_dir: Path,
    source: SkillSource = SkillSource.BUNDLED,
) -> PromptSkill:
    """Load a PromptSkill from a directory.

    Convenience function that wraps PromptSkill constructor.

    Args:
        skill_dir: Directory containing SKILL.md file.
        source: Where this skill comes from.

    Returns:
        Loaded PromptSkill instance.

    Raises:
        SkillParseError: If SKILL.md cannot be found or parsed.
    """
    return PromptSkill(skill_dir, source=source)
