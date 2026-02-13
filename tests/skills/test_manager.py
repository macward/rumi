"""Tests for SkillManager class."""

from pathlib import Path
from unittest.mock import MagicMock

import pytest

from miniclaw.skills.base import SkillContext, SkillSource
from miniclaw.skills.manager import SkillManager, SkillsConfig


def create_skill_dir(base: Path, name: str, description: str, **kwargs) -> Path:
    """Helper to create a skill directory with SKILL.md."""
    skill_dir = base / name
    skill_dir.mkdir(parents=True)

    tags = kwargs.get("tags", [])
    enabled = kwargs.get("enabled", True)
    version = kwargs.get("version", "0.1.0")
    body = kwargs.get("body", f"Instructions for {name}")

    tags_str = ", ".join(tags) if tags else ""
    content = f"""---
name: {name}
description: {description}
version: {version}
tags: [{tags_str}]
enabled: {str(enabled).lower()}
---

{body}
"""
    (skill_dir / "SKILL.md").write_text(content)
    return skill_dir


class TestSkillsConfig:
    """Tests for SkillsConfig dataclass."""

    def test_defaults(self):
        """Default config uses home directory for user skills and package bundled dir."""
        config = SkillsConfig()

        assert config.bundled_dir is not None
        assert "bundled" in str(config.bundled_dir)
        assert config.user_dir == Path.home() / ".miniclaw" / "skills"
        assert config.max_skills_in_prompt == 20
        assert config.disabled_skills == []

    def test_custom_config(self, tmp_path):
        """Custom config values."""
        bundled = tmp_path / "bundled"
        user = tmp_path / "user"

        config = SkillsConfig(
            bundled_dir=bundled,
            user_dir=user,
            max_skills_in_prompt=10,
            disabled_skills=["skill_a"],
        )

        assert config.bundled_dir == bundled
        assert config.user_dir == user
        assert config.max_skills_in_prompt == 10
        assert config.disabled_skills == ["skill_a"]

    def test_invalid_max_skills_in_prompt(self):
        """Invalid max_skills_in_prompt raises ValueError."""
        with pytest.raises(ValueError, match="max_skills_in_prompt must be at least 1"):
            SkillsConfig(max_skills_in_prompt=0)

        with pytest.raises(ValueError, match="max_skills_in_prompt must be at least 1"):
            SkillsConfig(max_skills_in_prompt=-5)


class TestSkillManagerInit:
    """Tests for SkillManager initialization."""

    def test_default_config(self):
        """SkillManager uses default config if none provided."""
        manager = SkillManager()

        assert manager.config is not None
        assert manager.skill_count == 0

    def test_custom_config(self, tmp_path):
        """SkillManager accepts custom config."""
        config = SkillsConfig(bundled_dir=tmp_path)
        manager = SkillManager(config)

        assert manager.config == config


class TestSkillManagerDiscovery:
    """Tests for skill discovery."""

    def test_discover_bundled_skills(self, tmp_path):
        """Discover skills from bundled directory."""
        bundled = tmp_path / "bundled"
        bundled.mkdir()

        create_skill_dir(bundled, "summarize", "Summarize documents")
        create_skill_dir(bundled, "explain", "Explain concepts")

        config = SkillsConfig(bundled_dir=bundled)
        manager = SkillManager(config)

        discovered = manager.discover()

        assert len(discovered) == 2
        assert manager.skill_count == 2
        assert manager.get("summarize") is not None
        assert manager.get("explain") is not None

    def test_discover_user_skills(self, tmp_path):
        """Discover skills from user directory."""
        user = tmp_path / "user"
        bundled = tmp_path / "bundled"  # Empty bundled to isolate test
        user.mkdir()
        bundled.mkdir()

        create_skill_dir(user, "custom", "Custom user skill")

        config = SkillsConfig(bundled_dir=bundled, user_dir=user)
        manager = SkillManager(config)

        discovered = manager.discover()

        assert len(discovered) == 1
        skill = manager.get("custom")
        assert skill is not None
        assert skill.metadata.source == SkillSource.USER

    def test_user_overrides_bundled(self, tmp_path):
        """User skills override bundled skills with same name."""
        bundled = tmp_path / "bundled"
        user = tmp_path / "user"
        bundled.mkdir()
        user.mkdir()

        # Create bundled version
        create_skill_dir(bundled, "summarize", "Bundled summarize")
        # Create user version (should override)
        create_skill_dir(user, "summarize", "User summarize")

        config = SkillsConfig(bundled_dir=bundled, user_dir=user)
        manager = SkillManager(config)
        manager.discover()

        skill = manager.get("summarize")
        assert skill is not None
        assert skill.description == "User summarize"
        assert skill.metadata.source == SkillSource.USER

    def test_discover_skips_invalid(self, tmp_path):
        """Invalid skill directories are skipped."""
        bundled = tmp_path / "bundled"
        bundled.mkdir()

        # Valid skill
        create_skill_dir(bundled, "valid", "Valid skill")

        # Invalid skill (missing name in frontmatter)
        invalid_dir = bundled / "invalid"
        invalid_dir.mkdir()
        (invalid_dir / "SKILL.md").write_text("""---
description: Missing name
---
Body.
""")

        config = SkillsConfig(bundled_dir=bundled)
        manager = SkillManager(config)

        discovered = manager.discover()

        # Only valid skill should be registered
        assert len(discovered) == 1
        assert manager.get("valid") is not None
        assert manager.get("invalid") is None

    def test_discover_empty_directory(self, tmp_path):
        """Empty directory returns no skills."""
        bundled = tmp_path / "bundled"
        bundled.mkdir()

        config = SkillsConfig(bundled_dir=bundled)
        manager = SkillManager(config)

        discovered = manager.discover()

        assert discovered == []
        assert manager.skill_count == 0

    def test_discover_nonexistent_directory(self, tmp_path):
        """Nonexistent directory is handled gracefully."""
        config = SkillsConfig(bundled_dir=tmp_path / "nonexistent")
        manager = SkillManager(config)

        discovered = manager.discover()

        assert discovered == []


class TestSkillManagerRegistry:
    """Tests for skill registration and retrieval."""

    def test_register_and_get(self, tmp_path):
        """Register a skill and retrieve by name."""
        skill_dir = tmp_path / "myskill"
        skill_dir.mkdir()
        (skill_dir / "SKILL.md").write_text("""---
name: myskill
description: My skill
---
Body.
""")

        manager = SkillManager()
        skill = manager.load_skill(skill_dir)
        manager.register(skill)

        retrieved = manager.get("myskill")
        assert retrieved is skill

    def test_get_nonexistent(self):
        """Get returns None for unregistered skill."""
        manager = SkillManager()
        assert manager.get("nonexistent") is None

    def test_unregister(self, tmp_path):
        """Unregister removes skill from registry."""
        bundled = tmp_path / "bundled"
        bundled.mkdir()
        create_skill_dir(bundled, "remove_me", "To be removed")

        config = SkillsConfig(bundled_dir=bundled)
        manager = SkillManager(config)
        manager.discover()

        assert manager.get("remove_me") is not None

        manager.unregister("remove_me")

        assert manager.get("remove_me") is None

    def test_unregister_nonexistent(self):
        """Unregister nonexistent skill is no-op."""
        manager = SkillManager()
        manager.unregister("nonexistent")  # Should not raise


class TestSkillManagerListSkills:
    """Tests for list_skills method."""

    def test_list_skills(self, tmp_path):
        """List all enabled skills."""
        bundled = tmp_path / "bundled"
        bundled.mkdir()

        create_skill_dir(bundled, "skill_a", "Skill A")
        create_skill_dir(bundled, "skill_b", "Skill B")

        config = SkillsConfig(bundled_dir=bundled)
        manager = SkillManager(config)
        manager.discover()

        skills = manager.list_skills()

        assert len(skills) == 2
        names = [s.name for s in skills]
        assert "skill_a" in names
        assert "skill_b" in names

    def test_list_excludes_disabled(self, tmp_path):
        """Disabled skills are excluded from list."""
        bundled = tmp_path / "bundled"
        bundled.mkdir()

        create_skill_dir(bundled, "enabled", "Enabled skill")
        create_skill_dir(bundled, "disabled", "Disabled skill", enabled=False)

        config = SkillsConfig(bundled_dir=bundled)
        manager = SkillManager(config)
        manager.discover()

        skills = manager.list_skills(include_disabled=False)

        assert len(skills) == 1
        assert skills[0].name == "enabled"

    def test_list_includes_disabled(self, tmp_path):
        """Include disabled skills when requested."""
        bundled = tmp_path / "bundled"
        bundled.mkdir()

        create_skill_dir(bundled, "enabled", "Enabled skill")
        create_skill_dir(bundled, "disabled", "Disabled skill", enabled=False)

        config = SkillsConfig(bundled_dir=bundled)
        manager = SkillManager(config)
        manager.discover()

        skills = manager.list_skills(include_disabled=True)

        assert len(skills) == 2

    def test_list_excludes_config_disabled(self, tmp_path):
        """Skills in disabled_skills config are excluded."""
        bundled = tmp_path / "bundled"
        bundled.mkdir()

        create_skill_dir(bundled, "skill_a", "Skill A")
        create_skill_dir(bundled, "skill_b", "Skill B")

        config = SkillsConfig(bundled_dir=bundled, disabled_skills=["skill_a"])
        manager = SkillManager(config)
        manager.discover()

        skills = manager.list_skills()

        assert len(skills) == 1
        assert skills[0].name == "skill_b"


class TestSkillManagerPromptGeneration:
    """Tests for get_available_skills_prompt method."""

    def test_empty_when_no_skills(self):
        """Empty string when no skills registered."""
        manager = SkillManager()
        prompt = manager.get_available_skills_prompt()
        assert prompt == ""

    def test_generates_xml_block(self, tmp_path):
        """Generate proper XML structure."""
        bundled = tmp_path / "bundled"
        bundled.mkdir()

        create_skill_dir(bundled, "summarize", "Summarize documents")

        config = SkillsConfig(bundled_dir=bundled)
        manager = SkillManager(config)
        manager.discover()

        prompt = manager.get_available_skills_prompt()

        assert "<available_skills>" in prompt
        assert "</available_skills>" in prompt
        assert "<skill>" in prompt
        assert "<name>summarize</name>" in prompt
        assert "<description>Summarize documents</description>" in prompt

    def test_multiple_skills(self, tmp_path):
        """Multiple skills in prompt."""
        bundled = tmp_path / "bundled"
        bundled.mkdir()

        create_skill_dir(bundled, "summarize", "Summarize docs")
        create_skill_dir(bundled, "explain", "Explain concepts")

        config = SkillsConfig(bundled_dir=bundled)
        manager = SkillManager(config)
        manager.discover()

        prompt = manager.get_available_skills_prompt()

        assert prompt.count("<skill>") == 2
        assert "summarize" in prompt
        assert "explain" in prompt

    def test_respects_max_limit(self, tmp_path):
        """Respects max_skills_in_prompt limit."""
        bundled = tmp_path / "bundled"
        bundled.mkdir()

        # Create 5 skills
        for i in range(5):
            create_skill_dir(bundled, f"skill_{i}", f"Skill {i}")

        config = SkillsConfig(bundled_dir=bundled, max_skills_in_prompt=3)
        manager = SkillManager(config)
        manager.discover()

        prompt = manager.get_available_skills_prompt()

        # Only 3 skills should be included
        assert prompt.count("<skill>") == 3


class TestSkillManagerExecution:
    """Tests for skill execution."""

    @pytest.fixture
    def manager_with_skill(self, tmp_path) -> SkillManager:
        """Create manager with one skill."""
        bundled = tmp_path / "bundled"
        bundled.mkdir()
        create_skill_dir(
            bundled, "test_skill", "Test skill", body="Execute these instructions"
        )

        config = SkillsConfig(bundled_dir=bundled)
        manager = SkillManager(config)
        manager.discover()
        return manager

    @pytest.fixture
    def mock_context(self) -> SkillContext:
        """Create mock execution context."""
        return SkillContext(
            tools=MagicMock(),
            session=MagicMock(),
            chat_id="test_chat",
            user_message="Test message",
        )

    @pytest.mark.asyncio
    async def test_execute_success(self, manager_with_skill, mock_context):
        """Execute skill successfully."""
        result = await manager_with_skill.execute("test_skill", mock_context)

        assert result.success is True
        assert "Execute these instructions" in result.output

    @pytest.mark.asyncio
    async def test_execute_not_found(self, manager_with_skill, mock_context):
        """Execute returns error for unknown skill."""
        result = await manager_with_skill.execute("nonexistent", mock_context)

        assert result.success is False
        assert "not found" in result.error

    @pytest.mark.asyncio
    async def test_execute_disabled_skill(self, tmp_path, mock_context):
        """Execute returns error for disabled skill."""
        bundled = tmp_path / "bundled"
        bundled.mkdir()
        create_skill_dir(bundled, "disabled", "Disabled skill", enabled=False)

        config = SkillsConfig(bundled_dir=bundled)
        manager = SkillManager(config)
        manager.discover()

        result = await manager.execute("disabled", mock_context)

        assert result.success is False
        assert "disabled" in result.error.lower()

    @pytest.mark.asyncio
    async def test_execute_config_disabled(self, tmp_path, mock_context):
        """Execute returns error for config-disabled skill."""
        bundled = tmp_path / "bundled"
        bundled.mkdir()
        create_skill_dir(bundled, "blocked", "Blocked skill")

        config = SkillsConfig(bundled_dir=bundled, disabled_skills=["blocked"])
        manager = SkillManager(config)
        manager.discover()

        result = await manager.execute("blocked", mock_context)

        assert result.success is False
        assert "disabled" in result.error.lower()


class TestSkillManagerRefresh:
    """Tests for refresh method."""

    def test_refresh_clears_and_rediscovers(self, tmp_path):
        """Refresh clears registry and rediscovers."""
        bundled = tmp_path / "bundled"
        bundled.mkdir()
        create_skill_dir(bundled, "initial", "Initial skill")

        config = SkillsConfig(bundled_dir=bundled)
        manager = SkillManager(config)
        manager.discover()

        assert manager.skill_count == 1

        # Add another skill
        create_skill_dir(bundled, "new_skill", "New skill")

        manager.refresh()

        assert manager.skill_count == 2
        assert manager.get("new_skill") is not None
