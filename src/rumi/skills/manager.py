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
    - Cache with mtime tracking for efficient refresh

    Example:
        config = SkillsConfig(bundled_dir=Path("skills/bundled"))
        manager = SkillManager(config)
        manager.discover()

        # Generate prompt block
        prompt = manager.get_available_skills_prompt()

        # Execute a skill
        result = await manager.execute("summarize", ctx)

        # Refresh only modified skills
        changed = manager.refresh_changed()
    """

    def __init__(self, config: SkillsConfig | None = None) -> None:
        """Initialize the SkillManager.

        Args:
            config: Configuration for skill discovery. Uses defaults if None.
        """
        self.config = config or SkillsConfig()
        self._registry: dict[str, Skill] = {}
        self._mtimes: dict[str, float] = {}  # skill_name -> mtime of SKILL.md
        self._skill_paths: dict[str, Path] = {}  # skill_name -> skill_dir path

    def discover(self) -> list[SkillMetadata]:
        """Discover skills from configured directories.

        Scans directories in order of precedence (lowest to highest):
        1. bundled_dir - Skills included with Rumi
        2. user_dir - User's personal skills (~/.rumi/skills)
        3. workspace_dir - Project-specific skills (optional)

        Skills are loaded and registered. If two skills have the same name,
        the one from the higher priority source wins.

        Returns:
            List of metadata for all discovered skills.
        """
        discovered: list[SkillMetadata] = []

        # Load bundled skills first (lowest priority)
        if self.config.bundled_dir and self.config.bundled_dir.exists():
            for skill_dir in self._scan_skill_dirs(self.config.bundled_dir):
                try:
                    skill = self.load_skill(skill_dir, source=SkillSource.BUNDLED)
                    self.register(skill, skill_dir=skill_dir)
                    discovered.append(skill.metadata)
                except (SkillParseError, CodeSkillLoadError) as e:
                    logger.warning("Failed to load skill from %s: %s", skill_dir, e)

        # Load user skills (medium priority, will override bundled)
        if self.config.user_dir and self.config.user_dir.exists():
            for skill_dir in self._scan_skill_dirs(self.config.user_dir):
                try:
                    skill = self.load_skill(skill_dir, source=SkillSource.USER)
                    self.register(skill, skill_dir=skill_dir)
                    discovered.append(skill.metadata)
                except (SkillParseError, CodeSkillLoadError) as e:
                    logger.warning("Failed to load skill from %s: %s", skill_dir, e)

        # Load workspace skills (highest priority, will override user and bundled)
        if self.config.workspace_dir and self.config.workspace_dir.exists():
            for skill_dir in self._scan_skill_dirs(self.config.workspace_dir):
                try:
                    skill = self.load_skill(skill_dir, source=SkillSource.WORKSPACE)
                    self.register(skill, skill_dir=skill_dir)
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

    def register(self, skill: Skill, skill_dir: Path | None = None) -> None:
        """Register a skill in the registry.

        If a skill with the same name already exists, the new skill
        takes precedence if it has a higher priority source.

        Args:
            skill: The skill to register.
            skill_dir: Directory the skill was loaded from (for mtime tracking).
        """
        name = skill.name
        existing = self._registry.get(name)

        should_register = existing is None or (
            skill.metadata.source.priority > existing.metadata.source.priority
        )

        if should_register:
            self._registry[name] = skill
            # Track mtime for cache invalidation
            if skill_dir is not None:
                self._skill_paths[name] = skill_dir
                skill_md = skill_dir / "SKILL.md"
                if skill_md.exists():
                    self._mtimes[name] = skill_md.stat().st_mtime

    def unregister(self, name: str) -> None:
        """Remove a skill from the registry and its cache entries.

        Args:
            name: Name of the skill to remove.
        """
        self._registry.pop(name, None)
        self._mtimes.pop(name, None)
        self._skill_paths.pop(name, None)

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

    def get_missing_tools(self, name: str, available_tools: list[str]) -> list[str]:
        """Check which required tools are missing for a skill.

        Args:
            name: Name of the skill.
            available_tools: List of available tool names from ToolRegistry.

        Returns:
            List of tool names that are required but not available.
        """
        skill = self.get(name)
        if skill is None:
            return []

        required = skill.metadata.tools_required
        return [tool for tool in required if tool not in available_tools]

    async def execute(self, name: str, ctx: SkillContext) -> SkillResult:
        """Execute a skill by name.

        Validates required tools and injects skill-specific settings
        into the context before execution.

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

        # Validate required tools are available
        available_tools = ctx.tools.list_tools()
        missing_tools = self.get_missing_tools(name, available_tools)
        if missing_tools:
            return SkillResult(
                success=False,
                output="",
                error=f"Skill '{name}' requires unavailable tools: {', '.join(missing_tools)}",
            )

        # Inject skill-specific settings into context
        skill_settings = self.get_skill_settings(name)
        if skill_settings:
            # Merge with existing config, skill settings take precedence
            ctx.config = {**ctx.config, **skill_settings}

        return await skill.execute(ctx)

    def match(
        self, query: str, threshold: float = 0.1
    ) -> list[tuple[Skill, float]]:
        """Find skills that can handle a query, scored by relevance.

        Calls can_handle() on all enabled skills and returns those
        scoring above the threshold, sorted by score descending.

        Args:
            query: The user query or task description.
            threshold: Minimum score to include (default 0.1).

        Returns:
            List of (skill, score) tuples, highest score first.
        """
        matches: list[tuple[Skill, float]] = []

        for skill in self._registry.values():
            if not self.is_skill_available(skill.name):
                continue

            score = skill.can_handle(query)
            if score >= threshold:
                matches.append((skill, score))

        # Sort by score descending
        matches.sort(key=lambda x: x[1], reverse=True)
        return matches

    def refresh(self) -> None:
        """Re-scan directories and update the registry.

        Clears the current registry and re-discovers all skills.
        This is a full refresh that reloads everything.
        """
        self.clear_cache()
        self.discover()

    def refresh_changed(self) -> list[str]:
        """Refresh only skills whose files have changed.

        Checks mtime of each skill's SKILL.md and reloads only those
        that have been modified since last load.

        Returns:
            List of skill names that were reloaded.
        """
        reloaded: list[str] = []

        for name, skill_dir in list(self._skill_paths.items()):
            skill_md = skill_dir / "SKILL.md"
            if not skill_md.exists():
                # Skill was deleted, remove from registry
                self.unregister(name)
                continue

            try:
                current_mtime = skill_md.stat().st_mtime
            except OSError as e:
                logger.warning("Cannot stat skill %s: %s", name, e)
                continue

            cached_mtime = self._mtimes.get(name, 0)

            if current_mtime > cached_mtime:
                # Skill has been modified, reload it
                skill = self._registry.get(name)
                if skill is None:
                    # Cache inconsistency - skill in paths but not registry
                    logger.warning("Cache inconsistency for skill %s, skipping", name)
                    continue

                try:
                    source = skill.metadata.source
                    new_skill = self.load_skill(skill_dir, source=source)
                    self._registry[name] = new_skill
                    self._mtimes[name] = current_mtime
                    reloaded.append(name)
                    logger.debug("Reloaded modified skill: %s", name)
                except (SkillParseError, CodeSkillLoadError) as e:
                    logger.warning("Failed to reload skill %s: %s", name, e)

        return reloaded

    def clear_cache(self) -> None:
        """Clear the skill cache completely.

        Removes all registered skills and their mtime tracking.
        Call discover() after this to reload skills.
        """
        self._registry.clear()
        self._mtimes.clear()
        self._skill_paths.clear()

    def get_skill_mtime(self, name: str) -> float | None:
        """Get the cached mtime for a skill.

        Args:
            name: Name of the skill.

        Returns:
            Unix timestamp of when the skill was last modified, or None.
        """
        return self._mtimes.get(name)

    @property
    def skill_count(self) -> int:
        """Return the number of registered skills."""
        return len(self._registry)
