"""Skills module for MiniClaw extensibility.

Skills provide reusable knowledge and orchestration patterns that guide the LLM
in completing complex tasks. Unlike Tools (atomic capabilities), Skills represent
strategies and workflows.

Two types of skills:
- PromptSkill: Loaded from SKILL.md files, inject instructions into conversation
- CodeSkill: Python classes that orchestrate tools programmatically (Phase 2)
"""

from .base import (
    Skill,
    SkillContext,
    SkillMetadata,
    SkillResult,
    SkillSource,
)
from .parser import (
    SkillParseError,
    SkillValidationError,
    parse_skill_content,
    parse_skill_file,
)
from .prompt_skill import PromptSkill, load_prompt_skill

__all__ = [
    "Skill",
    "SkillContext",
    "SkillMetadata",
    "SkillResult",
    "SkillSource",
    "SkillParseError",
    "SkillValidationError",
    "parse_skill_content",
    "parse_skill_file",
    "PromptSkill",
    "load_prompt_skill",
]
