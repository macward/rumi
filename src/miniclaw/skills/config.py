"""Skills configuration loader.

Loads skills configuration from ~/.miniclaw/config.json and provides
utilities for managing skill settings at runtime.
"""

import json
import logging
from dataclasses import dataclass, field
from pathlib import Path
from typing import Any

logger = logging.getLogger(__name__)

DEFAULT_CONFIG_PATH = Path.home() / ".miniclaw" / "config.json"


@dataclass
class SkillsConfig:
    """Configuration for the skills system.

    Attributes:
        bundled_dir: Directory containing bundled skills (auto-detected if None).
        user_dir: User's personal skills directory (~/.miniclaw/skills).
        workspace_dir: Optional workspace-specific skills directory.
        max_skills_in_prompt: Maximum skills to include in available_skills block.
        disabled_skills: List of skill names to exclude.
        skill_settings: Per-skill configuration settings.
    """

    bundled_dir: Path | None = None
    user_dir: Path | None = None
    workspace_dir: Path | None = None
    max_skills_in_prompt: int = 20
    disabled_skills: list[str] = field(default_factory=list)
    skill_settings: dict[str, dict[str, Any]] = field(default_factory=dict)

    def __post_init__(self) -> None:
        """Validate config and set defaults."""
        if self.bundled_dir is None:
            # Default to the bundled skills in the package
            self.bundled_dir = Path(__file__).parent / "bundled"

        if self.user_dir is None:
            self.user_dir = Path.home() / ".miniclaw" / "skills"

        if self.max_skills_in_prompt < 1:
            raise ValueError("max_skills_in_prompt must be at least 1")

    def get_skill_settings(self, skill_name: str) -> dict[str, Any]:
        """Get settings for a specific skill.

        Args:
            skill_name: Name of the skill.

        Returns:
            Settings dict for the skill, or empty dict if none.
        """
        return self.skill_settings.get(skill_name, {})

    def is_skill_disabled(self, skill_name: str) -> bool:
        """Check if a skill is explicitly disabled.

        Args:
            skill_name: Name of the skill.

        Returns:
            True if skill is in disabled_skills list.
        """
        return skill_name in self.disabled_skills


def load_config(config_path: Path | None = None) -> SkillsConfig:
    """Load SkillsConfig from a JSON file.

    The config file should have this structure:
    ```json
    {
      "skills": {
        "dirs": ["~/.miniclaw/skills", "~/my-skills"],
        "disabled": ["git_review"],
        "max_in_prompt": 20,
        "settings": {
          "summarize": {
            "max_words": 300
          }
        }
      }
    }
    ```

    Args:
        config_path: Path to config file. Uses DEFAULT_CONFIG_PATH if None.

    Returns:
        SkillsConfig instance with loaded values.
    """
    path = config_path or DEFAULT_CONFIG_PATH

    if not path.exists():
        logger.debug("No config file at %s, using defaults", path)
        return SkillsConfig()

    try:
        with open(path, "r") as f:
            data = json.load(f)
    except json.JSONDecodeError as e:
        logger.warning("Invalid JSON in %s: %s. Using defaults.", path, e)
        return SkillsConfig()
    except OSError as e:
        logger.warning("Cannot read %s: %s. Using defaults.", path, e)
        return SkillsConfig()

    return _parse_config(data)


def _parse_config(data: dict[str, Any]) -> SkillsConfig:
    """Parse config dictionary into SkillsConfig.

    Args:
        data: Parsed JSON data.

    Returns:
        SkillsConfig instance.
    """
    skills_data = data.get("skills", {})

    # Parse directories
    user_dir: Path | None = None
    dirs = skills_data.get("dirs", [])
    if dirs and len(dirs) > 0:
        # First dir is the primary user skills directory
        first_dir = Path(dirs[0]).expanduser()
        if first_dir.is_absolute():
            user_dir = first_dir

    # Parse disabled skills
    disabled = skills_data.get("disabled", [])
    if not isinstance(disabled, list):
        disabled = []

    # Parse max_in_prompt
    max_in_prompt = skills_data.get("max_in_prompt", 20)
    if not isinstance(max_in_prompt, int) or max_in_prompt < 1:
        max_in_prompt = 20

    # Parse skill-specific settings
    settings = skills_data.get("settings", {})
    if not isinstance(settings, dict):
        settings = {}

    return SkillsConfig(
        user_dir=user_dir,
        max_skills_in_prompt=max_in_prompt,
        disabled_skills=disabled,
        skill_settings=settings,
    )


def save_config(config: SkillsConfig, config_path: Path | None = None) -> None:
    """Save SkillsConfig to a JSON file.

    Args:
        config: The config to save.
        config_path: Path to write to. Uses DEFAULT_CONFIG_PATH if None.
    """
    path = config_path or DEFAULT_CONFIG_PATH

    # Ensure parent directory exists
    path.parent.mkdir(parents=True, exist_ok=True)

    # Build the config structure
    data: dict[str, Any] = {}

    skills_data: dict[str, Any] = {}

    if config.user_dir:
        skills_data["dirs"] = [str(config.user_dir)]

    if config.disabled_skills:
        skills_data["disabled"] = config.disabled_skills

    if config.max_skills_in_prompt != 20:
        skills_data["max_in_prompt"] = config.max_skills_in_prompt

    if config.skill_settings:
        skills_data["settings"] = config.skill_settings

    if skills_data:
        data["skills"] = skills_data

    try:
        with open(path, "w") as f:
            json.dump(data, f, indent=2)
    except OSError as e:
        logger.error("Failed to save config to %s: %s", path, e)
        raise
