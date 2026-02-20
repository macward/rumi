"""CodeSkill: Skills defined by Python code.

CodeSkills are more powerful than PromptSkills - they can execute arbitrary
Python logic, orchestrate multiple tools, and interact with the LLM directly.

A CodeSkill is defined by:
1. A SKILL.md file with metadata (same as PromptSkill)
2. A skill.py file with a class that extends CodeSkill

The loader uses importlib to dynamically load the CodeSkill class from skill.py.
This follows a trust-on-install model (ADR-017): the user trusts skills they install,
similar to pip packages.
"""

import importlib.util
import inspect
import logging
import sys
from abc import abstractmethod
from pathlib import Path
from typing import Type

from .base import Skill, SkillContext, SkillMetadata, SkillResult, SkillSource
from .parser import SkillParseError, parse_skill_file

logger = logging.getLogger(__name__)


class CodeSkill(Skill):
    """Abstract base class for Python-based skills.

    CodeSkills provide full programmatic control over skill execution.
    They can:
    - Execute complex logic with multiple steps
    - Orchestrate multiple tool calls via ctx.tools
    - Call the LLM directly via ctx.llm
    - Maintain state during execution

    Example skill.py:
        from rumi.skills import CodeSkill, SkillContext, SkillResult

        class MySkill(CodeSkill):
            async def execute(self, ctx: SkillContext) -> SkillResult:
                # Get files
                result = await ctx.tools.dispatch("bash", {"command": "ls"})

                # Call LLM for analysis
                analysis = await ctx.llm.complete(f"Analyze: {result.output}")

                return SkillResult(success=True, output=analysis)

    Subclasses must implement:
    - execute(ctx): The main skill logic

    Metadata is loaded from SKILL.md in the same directory.
    """

    def __init__(
        self,
        metadata: SkillMetadata,
        instructions: str = "",
    ) -> None:
        """Initialize a CodeSkill.

        Args:
            metadata: Skill metadata from SKILL.md or defined in code.
            instructions: Optional instructions from SKILL.md body.
        """
        self._metadata = metadata
        self._instructions = instructions

    @property
    def metadata(self) -> SkillMetadata:
        """Return the skill metadata."""
        return self._metadata

    @property
    def instructions(self) -> str:
        """Return instructions from SKILL.md (if any)."""
        return self._instructions

    @abstractmethod
    async def execute(self, ctx: SkillContext) -> SkillResult:
        """Execute the skill with the given context.

        This is the main entry point for skill logic. Implementations
        should use ctx.tools for tool calls and ctx.llm for LLM access.

        Args:
            ctx: Execution context with tools, session, llm, etc.

        Returns:
            SkillResult with the outcome of execution.
        """
        ...

    def __repr__(self) -> str:
        """Return string representation."""
        return f"CodeSkill(name={self.name!r}, source={self._metadata.source.value})"


class CodeSkillLoadError(Exception):
    """Error loading a CodeSkill from skill.py."""

    pass


def load_code_skill(
    skill_dir: Path,
    source: SkillSource = SkillSource.BUNDLED,
) -> CodeSkill:
    """Load a CodeSkill from a directory containing skill.py.

    The loader:
    1. Parses metadata from SKILL.md
    2. Loads skill.py as a Python module
    3. Finds the CodeSkill subclass
    4. Instantiates it with the parsed metadata

    Args:
        skill_dir: Directory containing skill.py and SKILL.md.
        source: Where this skill comes from (affects priority).

    Returns:
        Instantiated CodeSkill.

    Raises:
        CodeSkillLoadError: If skill.py cannot be loaded or is invalid.
        SkillParseError: If SKILL.md cannot be parsed.
    """
    skill_py = skill_dir / "skill.py"
    skill_md = skill_dir / "SKILL.md"

    if not skill_py.exists():
        raise CodeSkillLoadError(f"No skill.py found in {skill_dir}")

    # Parse metadata from SKILL.md
    if skill_md.exists():
        metadata, instructions = parse_skill_file(skill_md, source=source)
    else:
        # skill.py without SKILL.md - use directory name
        raise CodeSkillLoadError(
            f"CodeSkill requires SKILL.md for metadata in {skill_dir}"
        )

    # Load the Python module
    try:
        skill_class = _load_skill_class(skill_py)
    except Exception as e:
        raise CodeSkillLoadError(f"Failed to load skill.py from {skill_dir}: {e}")

    # Validate it's a CodeSkill subclass
    if not issubclass(skill_class, CodeSkill):
        raise CodeSkillLoadError(
            f"Class {skill_class.__name__} in {skill_py} must extend CodeSkill"
        )

    # Instantiate with metadata
    try:
        instance = skill_class(metadata=metadata, instructions=instructions)
    except TypeError as e:
        raise CodeSkillLoadError(
            f"Failed to instantiate {skill_class.__name__}: {e}. "
            "CodeSkill subclass must accept metadata and instructions parameters."
        )

    return instance


def _load_skill_class(skill_py: Path) -> Type[CodeSkill]:
    """Load and return the CodeSkill class from a skill.py file.

    Args:
        skill_py: Path to skill.py file.

    Returns:
        The CodeSkill subclass found in the module.

    Raises:
        CodeSkillLoadError: If no valid CodeSkill subclass is found.
    """
    # Create a unique module name to avoid conflicts
    module_name = f"rumi_skill_{skill_py.parent.name}_{id(skill_py)}"

    # Load the module using importlib
    spec = importlib.util.spec_from_file_location(module_name, skill_py)
    if spec is None or spec.loader is None:
        raise CodeSkillLoadError(f"Cannot create module spec for {skill_py}")

    module = importlib.util.module_from_spec(spec)
    sys.modules[module_name] = module

    try:
        spec.loader.exec_module(module)
    except Exception as e:
        # Clean up on failure
        sys.modules.pop(module_name, None)
        raise CodeSkillLoadError(f"Error executing {skill_py}: {e}")

    # Find CodeSkill subclass(es) in the module
    skill_classes: list[Type[CodeSkill]] = []

    for name, obj in inspect.getmembers(module, inspect.isclass):
        # Must be a subclass of CodeSkill, defined in this module
        if (
            issubclass(obj, CodeSkill)
            and obj is not CodeSkill
            and obj.__module__ == module_name
        ):
            skill_classes.append(obj)

    if not skill_classes:
        raise CodeSkillLoadError(
            f"No CodeSkill subclass found in {skill_py}. "
            "Define a class that extends CodeSkill."
        )

    if len(skill_classes) > 1:
        class_names = [c.__name__ for c in skill_classes]
        raise CodeSkillLoadError(
            f"Multiple CodeSkill subclasses found in {skill_py}: {class_names}. "
            "Each skill.py must define exactly one CodeSkill subclass."
        )

    return skill_classes[0]


def is_code_skill(skill_dir: Path) -> bool:
    """Check if a directory contains a CodeSkill (has skill.py).

    Args:
        skill_dir: Directory to check.

    Returns:
        True if skill.py exists, False otherwise.
    """
    return (skill_dir / "skill.py").exists()
