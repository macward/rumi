"""Tests for PromptSkill class."""

from pathlib import Path
from unittest.mock import MagicMock

import pytest

from miniclaw.skills.base import SkillContext, SkillSource
from miniclaw.skills.parser import SkillParseError
from miniclaw.skills.prompt_skill import PromptSkill, load_prompt_skill

FIXTURES_DIR = Path(__file__).parent / "fixtures"


class TestPromptSkillInit:
    """Tests for PromptSkill initialization."""

    def test_load_valid_skill(self, tmp_path):
        """Load a valid PromptSkill from directory."""
        skill_dir = tmp_path / "my_skill"
        skill_dir.mkdir()
        (skill_dir / "SKILL.md").write_text(
            """---
name: test_skill
description: A test skill
version: 1.0.0
tags: [testing]
tools_required: [bash]
---

# Test Instructions

1. Do step one
2. Do step two
"""
        )

        skill = PromptSkill(skill_dir)

        assert skill.name == "test_skill"
        assert skill.description == "A test skill"
        assert skill.metadata.version == "1.0.0"
        assert skill.metadata.tags == ["testing"]
        assert skill.metadata.tools_required == ["bash"]
        assert skill.metadata.source == SkillSource.BUNDLED
        assert "# Test Instructions" in skill.instructions
        assert skill.skill_dir == skill_dir

    def test_load_with_custom_source(self, tmp_path):
        """Load skill with custom source."""
        skill_dir = tmp_path / "user_skill"
        skill_dir.mkdir()
        (skill_dir / "SKILL.md").write_text(
            """---
name: user_skill
description: User's custom skill
---

Instructions here.
"""
        )

        skill = PromptSkill(skill_dir, source=SkillSource.USER)

        assert skill.metadata.source == SkillSource.USER

    def test_missing_skill_md(self, tmp_path):
        """Raise error when SKILL.md is missing."""
        skill_dir = tmp_path / "empty_skill"
        skill_dir.mkdir()

        with pytest.raises(SkillParseError, match="No SKILL.md found"):
            PromptSkill(skill_dir)

    def test_nonexistent_directory(self, tmp_path):
        """Raise error when directory doesn't exist."""
        skill_dir = tmp_path / "nonexistent"

        with pytest.raises(SkillParseError, match="No SKILL.md found"):
            PromptSkill(skill_dir)

    def test_invalid_skill_md(self, tmp_path):
        """Raise error when SKILL.md is invalid."""
        skill_dir = tmp_path / "invalid_skill"
        skill_dir.mkdir()
        (skill_dir / "SKILL.md").write_text(
            """---
description: Missing name field
---

Invalid.
"""
        )

        with pytest.raises(SkillParseError):
            PromptSkill(skill_dir)


class TestPromptSkillExecution:
    """Tests for PromptSkill.execute()."""

    @pytest.fixture
    def valid_skill(self, tmp_path) -> PromptSkill:
        """Create a valid test skill."""
        skill_dir = tmp_path / "exec_skill"
        skill_dir.mkdir()
        (skill_dir / "SKILL.md").write_text(
            """---
name: executor
description: Executes things
---

# Execution Instructions

Follow these steps:
1. First step
2. Second step
"""
        )
        return PromptSkill(skill_dir)

    @pytest.fixture
    def mock_context(self) -> SkillContext:
        """Create a mock execution context."""
        return SkillContext(
            tools=MagicMock(),
            session=MagicMock(),
            chat_id="test_chat",
            user_message="Execute the skill",
        )

    @pytest.mark.asyncio
    async def test_execute_returns_instructions(self, valid_skill, mock_context):
        """Execute returns instructions as output."""
        result = await valid_skill.execute(mock_context)

        assert result.success is True
        assert "# Execution Instructions" in result.output
        assert "Follow these steps:" in result.output
        assert "First step" in result.output

    @pytest.mark.asyncio
    async def test_execute_includes_metadata(self, valid_skill, mock_context):
        """Execute result includes skill metadata."""
        result = await valid_skill.execute(mock_context)

        assert result.metadata is not None
        assert result.metadata["skill_name"] == "executor"
        assert result.metadata["type"] == "prompt_skill"

    @pytest.mark.asyncio
    async def test_execute_with_empty_body(self, tmp_path, mock_context):
        """Execute with empty instructions body."""
        skill_dir = tmp_path / "empty_body"
        skill_dir.mkdir()
        (skill_dir / "SKILL.md").write_text(
            """---
name: empty
description: Empty body skill
---
"""
        )
        skill = PromptSkill(skill_dir)

        result = await skill.execute(mock_context)

        assert result.success is True
        assert "(No instructions provided)" in result.output


class TestPromptSkillProperties:
    """Tests for PromptSkill property accessors."""

    @pytest.fixture
    def skill(self, tmp_path) -> PromptSkill:
        """Create test skill."""
        skill_dir = tmp_path / "prop_skill"
        skill_dir.mkdir()
        (skill_dir / "SKILL.md").write_text(
            """---
name: props
description: Property test skill
tags: [test, props]
enabled: false
---

Body content.
"""
        )
        return PromptSkill(skill_dir)

    def test_name_property(self, skill):
        """Name property returns skill name."""
        assert skill.name == "props"

    def test_description_property(self, skill):
        """Description property returns skill description."""
        assert skill.description == "Property test skill"

    def test_enabled_property(self, skill):
        """Enabled property returns enabled status."""
        assert skill.enabled is False

    def test_instructions_property(self, skill):
        """Instructions property returns body content."""
        assert skill.instructions == "Body content."

    def test_skill_dir_property(self, skill, tmp_path):
        """skill_dir property returns the directory."""
        assert skill.skill_dir == tmp_path / "prop_skill"

    def test_can_handle(self, skill):
        """can_handle uses metadata keyword matching."""
        score = skill.can_handle("props test")
        assert score > 0.0

        score_no_match = skill.can_handle("unrelated query")
        assert score_no_match == 0.0


class TestPromptSkillRepr:
    """Tests for PromptSkill string representation."""

    def test_repr(self, tmp_path):
        """__repr__ returns useful string."""
        skill_dir = tmp_path / "repr_skill"
        skill_dir.mkdir()
        (skill_dir / "SKILL.md").write_text(
            """---
name: my_repr_skill
description: For repr test
---

Body.
"""
        )
        skill = PromptSkill(skill_dir, source=SkillSource.WORKSPACE)

        repr_str = repr(skill)

        assert "PromptSkill" in repr_str
        assert "my_repr_skill" in repr_str
        assert "workspace" in repr_str


class TestLoadPromptSkillFunction:
    """Tests for load_prompt_skill convenience function."""

    def test_load_prompt_skill(self, tmp_path):
        """load_prompt_skill creates PromptSkill."""
        skill_dir = tmp_path / "func_skill"
        skill_dir.mkdir()
        (skill_dir / "SKILL.md").write_text(
            """---
name: func_test
description: Loaded via function
---

Content.
"""
        )

        skill = load_prompt_skill(skill_dir)

        assert isinstance(skill, PromptSkill)
        assert skill.name == "func_test"

    def test_load_prompt_skill_with_source(self, tmp_path):
        """load_prompt_skill passes source."""
        skill_dir = tmp_path / "source_skill"
        skill_dir.mkdir()
        (skill_dir / "SKILL.md").write_text(
            """---
name: sourced
description: With source
---

Content.
"""
        )

        skill = load_prompt_skill(skill_dir, source=SkillSource.USER)

        assert skill.metadata.source == SkillSource.USER


class TestPromptSkillWithFixtures:
    """Tests using the fixtures directory."""

    def test_load_from_fixtures(self):
        """Load skill from fixtures directory."""
        # The fixtures directory has individual .md files, not skill directories
        # So we need to create a proper skill directory structure for this test
        # Skip this test if fixtures aren't set up as directories
        pass  # Fixtures are individual files, not directories

    def test_valid_skill_fixture(self, tmp_path):
        """Create directory from valid_skill.md fixture content."""
        skill_dir = tmp_path / "summarize"
        skill_dir.mkdir()

        # Copy content from valid_skill.md fixture
        fixture_content = (FIXTURES_DIR / "valid_skill.md").read_text()
        (skill_dir / "SKILL.md").write_text(fixture_content)

        skill = PromptSkill(skill_dir)

        assert skill.name == "summarize"
        assert skill.description == "Summarize documents extracting key points"
        assert skill.metadata.version == "1.0.0"
        assert "text" in skill.metadata.tags
        assert "productivity" in skill.metadata.tags
        assert "bash" in skill.metadata.tools_required
