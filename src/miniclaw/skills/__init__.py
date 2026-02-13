"""Skills module for MiniClaw extensibility.

Skills provide reusable knowledge and orchestration patterns that guide the LLM
in completing complex tasks. Unlike Tools (atomic capabilities), Skills represent
strategies and workflows.

Two types of skills:
- PromptSkill: Loaded from SKILL.md files, inject instructions into conversation
- CodeSkill: Python classes that orchestrate tools programmatically
"""

from .base import (
    LLMClient,
    Skill,
    SkillContext,
    SkillMetadata,
    SkillResult,
    SkillSource,
)
from .code_skill import (
    CodeSkill,
    CodeSkillLoadError,
    is_code_skill,
    load_code_skill,
)
from .llm_client import GroqLLMClient
from .parser import (
    SkillParseError,
    SkillValidationError,
    parse_skill_content,
    parse_skill_file,
)
from .prompt_skill import PromptSkill, load_prompt_skill
from .manager import SkillManager, SkillsConfig
from .executor_tool import SkillExecutorTool

__all__ = [
    "CodeSkill",
    "CodeSkillLoadError",
    "GroqLLMClient",
    "LLMClient",
    "Skill",
    "SkillContext",
    "SkillMetadata",
    "SkillResult",
    "SkillSource",
    "SkillParseError",
    "SkillValidationError",
    "is_code_skill",
    "load_code_skill",
    "parse_skill_content",
    "parse_skill_file",
    "PromptSkill",
    "load_prompt_skill",
    "SkillManager",
    "SkillsConfig",
    "SkillExecutorTool",
]
