"""SkillManager: Central component for skill discovery and management.

The SkillManager handles:
- Discovery: Scanning directories to find skill definitions
- Registry: Storing and retrieving skills by name
- Prompt generation: Creating the <available_skills> block for LLM

Supports both PromptSkills (SKILL.md only) and CodeSkills (skill.py).
"""

import logging
from pathlib import Path
from typing import Any, Iterator

from .base import Skill, SkillContext, SkillMetadata, SkillResult, SkillSource
from .code_skill import CodeSkillLoadError, is_code_skill, load_code_skill
from .config import SkillsConfig, load_config, save_config
from .parser import SkillParseError
from .prompt_skill import PromptSkill

logger = logging.getLogger(__name__)


class SkillManager:
    """Central manager for skill discovery, registration, and execution.

    The SkillManager maintains a registry of available skills and provides:
    - Discovery of skills from configured directories
    - Registration and retrieval of skills by name
    - Precedence handling (user skills override bundled)
    - Prompt generation for LLM context

    Example:
        config = SkillsConfig(bundled_dir=Path("skills/bundled"))
        manager = SkillManager(config)
        manager.discover()

        # Generate prompt block
        prompt = manager.get_available_skills_prompt()

        # Execute a skill
        result = await manager.execute("summarize", ctx)
    """

    def __init__(self, config: SkillsConfig | None = None) -> None:
        """Initialize the SkillManager.

        Args:
            config: Configuration for skill discovery. Uses defaults if None.
        """
        self.config = config or SkillsConfig()
        self._registry: dict[str, Skill] = {}

    def discover(self) -> list[SkillMetadata]:
        """Discover skills from configured directories.

        Scans bundled_dir (if set) and user_dir for valid skill directories.
        Skills are loaded and registered, with user skills taking precedence
        over bundled skills of the same name.

        Returns:
            List of metadata for all discovered skills.
        """
        discovered: list[SkillMetadata] = []

        # Load bundled skills first (lowest priority)
        if self.config.bundled_dir and self.config.bundled_dir.exists():
            for skill_dir in self._scan_skill_dirs(self.config.bundled_dir):
                try:
                    skill = self.load_skill(skill_dir, source=SkillSource.BUNDLED)
                    self.register(skill)
                    discovered.append(skill.metadata)
                except (SkillParseError, CodeSkillLoadError) as e:
                    logger.warning("Failed to load skill from %s: %s", skill_dir, e)

        # Load user skills (higher priority, will override bundled)
        if self.config.user_dir and self.config.user_dir.exists():
            for skill_dir in self._scan_skill_dirs(self.config.user_dir):
                try:
                    skill = self.load_skill(skill_dir, source=SkillSource.USER)
                    self.register(skill)
                    discovered.append(skill.metadata)
                except (SkillParseError, CodeSkillLoadError) as e:
                    logger.warning("Failed to load skill from %s: %s", skill_dir, e)

        return discovered

    def _scan_skill_dirs(self, base_dir: Path) -> Iterator[Path]:
        """Scan a directory for skill subdirectories.

        A valid skill directory contains a SKILL.md file.

        Args:
            base_dir: Directory to scan.

        Yields:
            Paths to directories containing SKILL.md.
        """
        if not base_dir.is_dir():
            return

        for item in base_dir.iterdir():
            if item.is_dir() and (item / "SKILL.md").exists():
                yield item

    def load_skill(
        self,
        skill_dir: Path,
        source: SkillSource = SkillSource.BUNDLED,
    ) -> Skill:
        """Load a skill from its directory.

        Detection logic:
        - If skill.py exists → load as CodeSkill
        - If only SKILL.md exists → load as PromptSkill

        Args:
            skill_dir: Directory containing the skill.
            source: Where this skill comes from.

        Returns:
            Loaded Skill instance.

        Raises:
            SkillParseError: If skill cannot be loaded.
            CodeSkillLoadError: If CodeSkill cannot be loaded.
        """
        if is_code_skill(skill_dir):
            return load_code_skill(skill_dir, source=source)
        else:
            return PromptSkill(skill_dir, source=source)

    def register(self, skill: Skill) -> None:
        """Register a skill in the registry.

        If a skill with the same name already exists, the new skill
        takes precedence if it has a higher priority source.

        Args:
            skill: The skill to register.
        """
        name = skill.name
        existing = self._registry.get(name)

        if existing is None:
            self._registry[name] = skill
        else:
            # Higher priority source wins
            if skill.metadata.source.priority > existing.metadata.source.priority:
                self._registry[name] = skill

    def unregister(self, name: str) -> None:
        """Remove a skill from the registry.

        Args:
            name: Name of the skill to remove.
        """
        self._registry.pop(name, None)

    def get(self, name: str) -> Skill | None:
        """Get a skill by name.

        Args:
            name: The skill name.

        Returns:
            The skill if found, None otherwise.
        """
        return self._registry.get(name)

    def is_skill_available(self, name: str) -> bool:
        """Check if a skill is available for execution.

        A skill is available if:
        - It exists in the registry
        - It is enabled in its metadata
        - It is not in the disabled_skills config list

        Args:
            name: The skill name.

        Returns:
            True if the skill can be executed.
        """
        skill = self.get(name)
        if skill is None:
            return False
        if not skill.enabled:
            return False
        if name in self.config.disabled_skills:
            return False
        return True

    def enable(self, name: str) -> bool:
        """Enable a disabled skill.

        Removes the skill from the disabled_skills list if present.

        Args:
            name: Name of the skill to enable.

        Returns:
            True if the skill was enabled (was disabled), False otherwise.
        """
        if name in self.config.disabled_skills:
            self.config.disabled_skills.remove(name)
            return True
        return False

    def disable(self, name: str) -> bool:
        """Disable a skill.

        Adds the skill to the disabled_skills list if not already present.

        Args:
            name: Name of the skill to disable.

        Returns:
            True if the skill was disabled (wasn't already), False otherwise.
        """
        if name not in self.config.disabled_skills:
            self.config.disabled_skills.append(name)
            return True
        return False

    def get_skill_settings(self, name: str) -> dict[str, Any]:
        """Get settings for a specific skill.

        Args:
            name: Name of the skill.

        Returns:
            Settings dict for the skill, or empty dict if none.
        """
        return self.config.get_skill_settings(name)

    def list_skills(self, include_disabled: bool = False) -> list[SkillMetadata]:
        """List metadata for all registered skills.

        Args:
            include_disabled: Include disabled skills in the list.

        Returns:
            List of SkillMetadata for registered skills.
        """
        result = []
        for skill in self._registry.values():
            if include_disabled or self.is_skill_available(skill.name):
                result.append(skill.metadata)
        return result

    def get_available_skills_prompt(self) -> str:
        """Generate the <available_skills> XML block for the system prompt.

        Only includes enabled skills up to max_skills_in_prompt limit.
        Each skill shows only name and description (not full instructions).

        Returns:
            XML string with available skills, or empty string if none.
        """
        skills = self.list_skills(include_disabled=False)

        if not skills:
            return ""

        # Limit to configured maximum
        skills = skills[: self.config.max_skills_in_prompt]

        lines = ["<available_skills>"]
        for meta in skills:
            lines.append("<skill>")
            lines.append(f"  <name>{meta.name}</name>")
            lines.append(f"  <description>{meta.description}</description>")
            lines.append("</skill>")
        lines.append("</available_skills>")

        return "\n".join(lines)

    async def execute(self, name: str, ctx: SkillContext) -> SkillResult:
        """Execute a skill by name.

        Injects skill-specific settings into the context before execution.

        Args:
            name: Name of the skill to execute.
            ctx: Execution context with tools, session, etc.

        Returns:
            SkillResult from the skill execution.
        """
        skill = self.get(name)

        if skill is None:
            return SkillResult(
                success=False,
                output="",
                error=f"Skill not found: {name}",
            )

        if not self.is_skill_available(name):
            return SkillResult(
                success=False,
                output="",
                error=f"Skill is disabled: {name}",
            )

        # Inject skill-specific settings into context
        skill_settings = self.get_skill_settings(name)
        if skill_settings:
            # Merge with existing config, skill settings take precedence
            ctx.config = {**ctx.config, **skill_settings}

        return await skill.execute(ctx)

    def refresh(self) -> None:
        """Re-scan directories and update the registry.

        Clears the current registry and re-discovers all skills.
        """
        self._registry.clear()
        self.discover()

    @property
    def skill_count(self) -> int:
        """Return the number of registered skills."""
        return len(self._registry)
