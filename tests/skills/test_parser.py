"""Tests for SKILL.md parser."""

from pathlib import Path

import pytest

from rumi.skills.base import SkillSource
from rumi.skills.parser import (
    SkillParseError,
    SkillValidationError,
    parse_skill_content,
    parse_skill_file,
)

FIXTURES_DIR = Path(__file__).parent / "fixtures"


class TestParseSkillFile:
    """Tests for parse_skill_file function."""

    def test_valid_skill(self):
        """Parse a complete valid SKILL.md."""
        path = FIXTURES_DIR / "valid_skill.md"
        metadata, body = parse_skill_file(path)

        assert metadata.name == "summarize"
        assert metadata.description == "Summarize documents extracting key points"
        assert metadata.version == "1.0.0"
        assert metadata.tags == ["text", "productivity"]
        assert metadata.tools_required == ["bash"]
        assert metadata.enabled is True
        assert metadata.source == SkillSource.BUNDLED
        assert metadata.path == FIXTURES_DIR
        assert "# Summarize" in body
        assert "Executive summary" in body

    def test_minimal_skill(self):
        """Parse skill with only required fields."""
        path = FIXTURES_DIR / "minimal_skill.md"
        metadata, body = parse_skill_file(path)

        assert metadata.name == "simple"
        assert metadata.description == "A simple skill with minimal fields"
        assert metadata.version == "0.1.0"  # default
        assert metadata.tags == []
        assert metadata.tools_required == []
        assert metadata.enabled is True
        assert body == "Just do the thing."

    def test_file_not_found(self):
        """Raise SkillParseError for missing file."""
        path = FIXTURES_DIR / "nonexistent.md"
        with pytest.raises(SkillParseError, match="not found"):
            parse_skill_file(path)

    def test_directory_not_file(self, tmp_path):
        """Raise SkillParseError for directory."""
        with pytest.raises(SkillParseError, match="Not a file"):
            parse_skill_file(tmp_path)

    def test_missing_name(self):
        """Raise SkillValidationError when name missing."""
        path = FIXTURES_DIR / "missing_name.md"
        with pytest.raises(SkillValidationError, match="Missing required field: name"):
            parse_skill_file(path)

    def test_missing_description(self):
        """Raise SkillValidationError when description missing."""
        path = FIXTURES_DIR / "missing_description.md"
        with pytest.raises(
            SkillValidationError, match="Missing required field: description"
        ):
            parse_skill_file(path)

    def test_empty_name(self):
        """Raise SkillValidationError when name is empty."""
        path = FIXTURES_DIR / "empty_name.md"
        with pytest.raises(SkillValidationError, match="cannot be empty"):
            parse_skill_file(path)

    def test_string_tags_and_tools(self):
        """Handle comma-separated strings for tags and tools."""
        path = FIXTURES_DIR / "string_tags.md"
        metadata, _ = parse_skill_file(path)

        assert metadata.tags == ["text", "productivity", "ai"]
        assert metadata.tools_required == ["bash", "web_fetch"]

    def test_disabled_skill(self):
        """Parse skill with enabled=false."""
        path = FIXTURES_DIR / "disabled_skill.md"
        metadata, _ = parse_skill_file(path)

        assert metadata.enabled is False

    def test_no_frontmatter(self):
        """File without frontmatter fails validation."""
        path = FIXTURES_DIR / "no_frontmatter.md"
        with pytest.raises(SkillValidationError, match="Missing required field"):
            parse_skill_file(path)

    def test_dict_name(self):
        """Dict value for name raises SkillValidationError."""
        path = FIXTURES_DIR / "dict_name.md"
        with pytest.raises(SkillValidationError, match="must be a string"):
            parse_skill_file(path)

    def test_custom_source(self):
        """Pass custom SkillSource."""
        path = FIXTURES_DIR / "minimal_skill.md"
        metadata, _ = parse_skill_file(path, source=SkillSource.USER)

        assert metadata.source == SkillSource.USER


class TestParseSkillContent:
    """Tests for parse_skill_content function."""

    def test_basic_content(self):
        """Parse from string content."""
        content = """---
name: test_skill
description: A test skill
---

Instructions here.
"""
        metadata, body = parse_skill_content(content)

        assert metadata.name == "test_skill"
        assert metadata.description == "A test skill"
        assert metadata.path is None
        assert body == "Instructions here."

    def test_content_with_path(self):
        """Include path in metadata."""
        content = """---
name: test_skill
description: A test skill
---

Body text.
"""
        path = Path("/skills/test/SKILL.md")
        metadata, _ = parse_skill_content(content, path=path)

        assert metadata.path == Path("/skills/test")

    def test_content_with_source(self):
        """Include source in metadata."""
        content = """---
name: test_skill
description: A test skill
---

Body.
"""
        metadata, _ = parse_skill_content(content, source=SkillSource.WORKSPACE)

        assert metadata.source == SkillSource.WORKSPACE

    def test_whitespace_trimmed(self):
        """Body whitespace is trimmed."""
        content = """---
name: test
description: test


---


  Body with whitespace


"""
        _, body = parse_skill_content(content)

        assert body == "Body with whitespace"

    def test_enabled_string_true(self):
        """Parse enabled as 'true' string."""
        content = """---
name: test
description: test
enabled: "true"
---
Body.
"""
        metadata, _ = parse_skill_content(content)
        assert metadata.enabled is True

    def test_enabled_string_yes(self):
        """Parse enabled as 'yes' string."""
        content = """---
name: test
description: test
enabled: yes
---
Body.
"""
        metadata, _ = parse_skill_content(content)
        assert metadata.enabled is True

    def test_enabled_string_false(self):
        """Parse enabled as 'false' string."""
        content = """---
name: test
description: test
enabled: "false"
---
Body.
"""
        metadata, _ = parse_skill_content(content)
        assert metadata.enabled is False

    def test_enabled_string_no(self):
        """Parse enabled as 'no' string."""
        content = """---
name: test
description: test
enabled: no
---
Body.
"""
        metadata, _ = parse_skill_content(content)
        assert metadata.enabled is False

    def test_enabled_string_off(self):
        """Parse enabled as 'off' string."""
        content = """---
name: test
description: test
enabled: "off"
---
Body.
"""
        metadata, _ = parse_skill_content(content)
        assert metadata.enabled is False

    def test_enabled_string_zero(self):
        """Parse enabled as '0' string."""
        content = """---
name: test
description: test
enabled: "0"
---
Body.
"""
        metadata, _ = parse_skill_content(content)
        assert metadata.enabled is False

    def test_empty_tags_list(self):
        """Handle empty tags list."""
        content = """---
name: test
description: test
tags: []
---
Body.
"""
        metadata, _ = parse_skill_content(content)
        assert metadata.tags == []

    def test_invalid_tags_type(self):
        """Handle non-string/non-list tags gracefully."""
        content = """---
name: test
description: test
tags: 123
---
Body.
"""
        metadata, _ = parse_skill_content(content)
        assert metadata.tags == []

    def test_multiline_body(self):
        """Parse multiline body correctly."""
        content = """---
name: multi
description: Multiline body test
---

# Header

Paragraph one.

Paragraph two with **bold** text.

- Item 1
- Item 2
"""
        _, body = parse_skill_content(content)

        assert "# Header" in body
        assert "Paragraph one." in body
        assert "Paragraph two with **bold** text." in body
        assert "- Item 1" in body

    def test_empty_body(self):
        """Handle empty body."""
        content = """---
name: nobody
description: No body content
---
"""
        metadata, body = parse_skill_content(content)

        assert metadata.name == "nobody"
        assert body == ""

    def test_empty_description_after_strip(self):
        """Whitespace-only description fails validation."""
        content = """---
name: test
description: "   "
---
Body.
"""
        with pytest.raises(SkillValidationError, match="cannot be empty"):
            parse_skill_content(content)


class TestEdgeCases:
    """Edge cases and error handling."""

    def test_unicode_content(self):
        """Handle unicode in content."""
        content = """---
name: unicode_skill
description: Skill with unicode content
tags: [espa\u00f1ol, fran\u00e7ais]
---

\u00bfC\u00f3mo est\u00e1s?
\u4f60\u597d
\ud83d\ude80
"""
        metadata, body = parse_skill_content(content)

        assert metadata.name == "unicode_skill"
        assert "espa\u00f1ol" in metadata.tags
        assert "\u00bfC\u00f3mo est\u00e1s?" in body
        assert "\u4f60\u597d" in body
        assert "\ud83d\ude80" in body

    def test_yaml_special_characters(self):
        """Handle YAML special characters in values."""
        content = """---
name: special_chars
description: "Contains: colons, and [brackets]"
---
Body.
"""
        metadata, _ = parse_skill_content(content)

        assert metadata.name == "special_chars"
        assert "colons" in metadata.description
        assert "[brackets]" in metadata.description

    def test_numeric_version(self):
        """Handle numeric version (YAML parses as float)."""
        content = """---
name: test
description: test
version: 1.0
---
Body.
"""
        metadata, _ = parse_skill_content(content)
        assert metadata.version == "1.0"

    def test_integer_version(self):
        """Handle integer version."""
        content = """---
name: test
description: test
version: 2
---
Body.
"""
        metadata, _ = parse_skill_content(content)
        assert metadata.version == "2"

    def test_empty_version_fails(self):
        """Empty string version fails validation."""
        content = """---
name: test
description: test
version: "   "
---
Body.
"""
        with pytest.raises(SkillValidationError, match="version.*cannot be empty"):
            parse_skill_content(content)

    def test_list_name_fails(self):
        """List value for name fails validation."""
        content = """---
name: [item1, item2]
description: Name is a list
---
Body.
"""
        with pytest.raises(SkillValidationError, match="must be a string"):
            parse_skill_content(content)

    def test_dict_description_fails(self):
        """Dict value for description fails validation."""
        content = """---
name: test
description:
  nested: value
---
Body.
"""
        with pytest.raises(SkillValidationError, match="must be a string"):
            parse_skill_content(content)
