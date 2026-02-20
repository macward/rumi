"""Parser for SKILL.md files with YAML frontmatter.

Reads skill definition files and extracts metadata (frontmatter) and
instructions (body). Uses python-frontmatter for robust parsing.
"""

from pathlib import Path
from typing import Any

import frontmatter

from .base import SkillMetadata, SkillSource


def _parse_string_or_list(value: Any) -> list[str]:
    """Parse a value that can be a comma-separated string or a list.

    Args:
        value: The raw value from frontmatter.

    Returns:
        List of non-empty strings.
    """
    if isinstance(value, str):
        return [t.strip() for t in value.split(",") if t.strip()]
    elif isinstance(value, list):
        return [str(t).strip() for t in value if str(t).strip()]
    return []


class SkillParseError(Exception):
    """Raised when a SKILL.md file cannot be parsed."""

    pass


class SkillValidationError(SkillParseError):
    """Raised when SKILL.md frontmatter fails validation."""

    pass


def parse_skill_file(
    path: Path,
    source: SkillSource = SkillSource.BUNDLED,
) -> tuple[SkillMetadata, str]:
    """Parse a SKILL.md file and extract metadata and body.

    Args:
        path: Path to the SKILL.md file.
        source: Where this skill comes from (affects priority).

    Returns:
        Tuple of (SkillMetadata, body_text).

    Raises:
        SkillParseError: If the file cannot be read or parsed.
        SkillValidationError: If required fields are missing.
    """
    if not path.exists():
        raise SkillParseError(f"Skill file not found: {path}")

    if not path.is_file():
        raise SkillParseError(f"Not a file: {path}")

    try:
        content = path.read_text(encoding="utf-8")
    except OSError as e:
        raise SkillParseError(f"Cannot read skill file {path}: {e}") from e

    return parse_skill_content(content, path=path, source=source)


def parse_skill_content(
    content: str,
    path: Path | None = None,
    source: SkillSource = SkillSource.BUNDLED,
) -> tuple[SkillMetadata, str]:
    """Parse SKILL.md content string and extract metadata and body.

    Args:
        content: The raw content of a SKILL.md file.
        path: Optional path for context (stored in metadata).
        source: Where this skill comes from (affects priority).

    Returns:
        Tuple of (SkillMetadata, body_text).

    Raises:
        SkillParseError: If the content cannot be parsed.
        SkillValidationError: If required fields are missing.
    """
    try:
        post = frontmatter.loads(content)
    except Exception as e:
        raise SkillParseError(f"Failed to parse frontmatter: {e}") from e

    meta = post.metadata
    body = post.content.strip()

    # Validate required fields
    if "name" not in meta:
        raise SkillValidationError("Missing required field: name")

    if "description" not in meta:
        raise SkillValidationError("Missing required field: description")

    # Validate and extract name
    raw_name = meta["name"]
    if not isinstance(raw_name, (str, int, float)):
        raise SkillValidationError(
            f"Field 'name' must be a string, got {type(raw_name).__name__}"
        )
    name = str(raw_name).strip()
    if not name:
        raise SkillValidationError("Field 'name' cannot be empty")

    # Validate and extract description
    raw_desc = meta["description"]
    if not isinstance(raw_desc, (str, int, float)):
        raise SkillValidationError(
            f"Field 'description' must be a string, got {type(raw_desc).__name__}"
        )
    description = str(raw_desc).strip()
    if not description:
        raise SkillValidationError("Field 'description' cannot be empty")

    # Version: defaults to "0.1.0", must be non-empty if provided
    raw_version = meta.get("version", "0.1.0")
    version = str(raw_version).strip()
    if not version:
        raise SkillValidationError("Field 'version' cannot be empty")

    # Tags: accept string or list
    tags = _parse_string_or_list(meta.get("tags", []))

    # Tools required: accept string or list
    tools_required = _parse_string_or_list(meta.get("tools_required", []))

    # Enabled: defaults to True, explicit handling of false-like strings
    enabled = meta.get("enabled", True)
    if isinstance(enabled, str):
        enabled_lower = enabled.lower().strip()
        if enabled_lower in ("false", "no", "0", "off"):
            enabled = False
        else:
            enabled = enabled_lower in ("true", "yes", "1", "on")
    elif not isinstance(enabled, bool):
        enabled = True  # Default for non-bool/non-string types

    # Determine path: use parent directory if file path provided
    skill_path = path.parent if path else None

    metadata = SkillMetadata(
        name=name,
        description=description,
        version=version,
        tags=tags,
        tools_required=tools_required,
        enabled=bool(enabled),
        source=source,
        path=skill_path,
    )

    return metadata, body
